"""GitHub Release assets and an atomic manifest in a separate data branch.

Public readers use token-free downloads. Published generations are immutable.
"""
from __future__ import annotations
import base64
import io
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import requests

TAG_PREFIX = "dashboard-data-"
POINTER_PATH = "dashboard/latest.json"
ASSET_LIMIT = 2 * 1024**3
PUBLIC_DATA_BRANCH = "dashboard-data"

class GitHubStoreError(RuntimeError):
    pass

def checked_repo(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("DASHBOARD_DATA_REPO must be OWNER/REPOSITORY")
    if any(part in (".", "..") for part in value.split("/")):
        raise ValueError("Invalid repository name")
    return value

def checked_branch(value):
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value)
            or ".." in value or any(part.startswith(".") or part.endswith((".", ".lock")) for part in value.split("/"))):
        raise ValueError("Invalid DASHBOARD_DATA_BRANCH")
    return value

def split_key(key):
    match = re.fullmatch(r"generations/([0-9]{8}T[0-9]{6}Z-[a-f0-9]{8})/(summary\.json\.gz|checkpoint\.sqlite3|manifest\.json|details/[0-9]{1,3}\.jsonl\.gz)", key)
    if not match:
        raise ValueError("Invalid snapshot object key")
    generation, name = match.groups()
    return TAG_PREFIX + generation, name.replace("/", "--")

class PublicGitHubStore:
    """Read-only public downloads, with no inherited credentials."""
    def __init__(self, config, session=None):
        self.repo = checked_repo(config["DASHBOARD_DATA_REPO"])
        self.branch = checked_branch(config.get("DASHBOARD_DATA_BRANCH") or PUBLIC_DATA_BRANCH)
        self.identity = f"github-public:{self.repo.casefold()}:{self.branch}"
        self.session = session or requests.Session()
        if hasattr(self.session, "trust_env"):
            self.session.trust_env = False

    def _response(self, key, optional=False):
        if key == "latest.json":
            url = f"https://raw.githubusercontent.com/{self.repo}/{quote(self.branch, safe='')}/{POINTER_PATH}"
        else:
            tag, name = split_key(key)
            url = f"https://github.com/{self.repo}/releases/download/{tag}/{name}"
        try:
            response = self.session.request("GET", url, headers={"Authorization": None,
                "User-Agent": "prepared-stock-dashboard", "Accept": "application/octet-stream"},
                timeout=(10, 120), stream=True)
        except requests.RequestException:
            raise GitHubStoreError("Public download failed; keeping previously saved data") from None
        if optional and response.status_code == 404:
            response.close()
            return None
        if not 200 <= response.status_code < 300:
            status = response.status_code
            response.close()
            raise GitHubStoreError(f"Public download HTTP {status}; check public repository, data branch and completed workflow")
        return response

    def read(self, key, optional=False):
        response = self._response(key, optional)
        if response is None:
            return None
        try:
            return response.content
        finally:
            response.close()

    def download(self, key, path):
        response = self._response(key)
        try:
            with Path(path).open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        finally:
            response.close()

    def write(self, *args, **kwargs):
        raise GitHubStoreError("Public reader cannot write; run the GitHub Actions collector")
    upload = write
    prune_generations = write

class GitHubReleaseStore:
    def __init__(self, config, session=None):
        self.repo = checked_repo(config["DASHBOARD_DATA_REPO"])
        self.token = config["DASHBOARD_GITHUB_TOKEN"]
        self.visibility = config.get("DASHBOARD_DATA_VISIBILITY", "public")
        if self.visibility not in ("public", "private"):
            raise ValueError("Invalid data visibility")
        requested = config.get("DASHBOARD_DATA_BRANCH") or (PUBLIC_DATA_BRANCH if self.visibility == "public" else "")
        self.requested_branch = checked_branch(requested) if requested else None
        self.identity = f"github-{self.visibility}:{self.repo.casefold()}:{requested}"
        if not self.token:
            raise ValueError("Missing GitHub token")
        self.session = session or requests.Session()
        self.base = "https://api.github.com/repos/" + self.repo
        self.verified = False
        self.branch = None
        self.default_branch = None
        self.branch_ready = False
        self.pointer_sha = None
        self.pointer_loaded = False
        self.releases = {}
        self.assets = {}
        self.last_mutation = 0.0

    def _pace_mutation(self):
        gap = 1.1 - (time.monotonic() - self.last_mutation)
        if gap > 0:
            time.sleep(gap)
        self.last_mutation = time.monotonic()

    def _request(self, method, path, *, missing=False, upload=False, **kwargs):
        if not path.startswith("/") or "://" in path or ".." in path:
            raise ValueError("Invalid GitHub API path")
        if method != "GET":
            self._pace_mutation()
        base = self.base.replace("api.github.com", "uploads.github.com") if upload else self.base
        # Repository metadata has no trailing slash; /repos/owner/repo/ returns 404.
        url = base if path == "/" else base + path
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "prepared-stock-dashboard"}
        headers.update(kwargs.pop("headers", {}))
        try:
            response = self.session.request(method, url, headers=headers, timeout=(10, 120), **kwargs)
        except requests.RequestException:
            raise GitHubStoreError("GitHub connection failed; saved data is unchanged") from None
        if missing and response.status_code == 404:
            response.close()
            return None
        if not 200 <= response.status_code < 300:
            status = response.status_code
            response.close()
            raise GitHubStoreError(f"GitHub HTTP {status} at {path}; check permissions and rate limits")
        return response

    def _json(self, method, path, **kwargs):
        response = self._request(method, path, **kwargs)
        if response is None:
            return None
        try:
            return response.json()
        finally:
            response.close()

    def _verify_repository(self):
        if self.verified:
            return
        repo = self._json("GET", "/")
        if repo.get("private") is not (self.visibility == "private"):
            raise GitHubStoreError(f"Data repository must be {self.visibility.title()}; check DASHBOARD_DATA_VISIBILITY")
        if not repo.get("default_branch"):
            raise GitHubStoreError("Initialize the repository with a README first")
        self.default_branch = repo["default_branch"]
        self.branch = self.requested_branch or self.default_branch
        self.verified = True

    def _ensure_data_branch(self):
        self._verify_repository()
        if self.branch_ready:
            return
        path = "/git/ref/heads/" + quote(self.branch, safe="")
        if self._json("GET", path, missing=True) is None:
            source = self._json("GET", "/git/ref/heads/" + quote(self.default_branch, safe=""))
            self._json("POST", "/git/refs", json={"ref": "refs/heads/" + self.branch,
                                                   "sha": source["object"]["sha"]})
        self.branch_ready = True

    def _release(self, tag, create=False):
        self._verify_repository()
        if tag not in self.releases:
            release = self._json("GET", "/releases/tags/" + quote(tag, safe=""), missing=True)
            if release is None and create:
                self._ensure_data_branch()
                release = self._json("POST", "/releases", json={
                    "tag_name": tag, "target_commitish": self.branch,
                    "name": tag, "body": f"Prepared dashboard data ({self.visibility}). Prices may be delayed; see per-symbol timestamps.",
                    "draft": True, "prerelease": False, "make_latest": "false"})
                self.assets[tag] = {}
            if release is None:
                raise GitHubStoreError("Saved data release is missing; keep the previous local data")
            self.releases[tag] = release
        return self.releases[tag]

    def _index(self, tag):
        release = self._release(tag)
        if tag not in self.assets:
            index, page = {}, 1
            while True:
                batch = self._json("GET", f"/releases/{int(release['id'])}/assets", params={"per_page": 100, "page": page})
                index.update({a["name"]: a for a in batch})
                if len(batch) < 100:
                    break
                page += 1
            self.assets[tag] = index
        return self.assets[tag]

    def _asset_response(self, key):
        tag, name = split_key(key)
        asset = self._index(tag).get(name)
        if asset is None or asset.get("state") != "uploaded":
            raise GitHubStoreError("A prepared data file is missing or incomplete")
        return self._request("GET", f"/releases/assets/{int(asset['id'])}", headers={"Accept": "application/octet-stream"}, stream=True)

    def read(self, key, optional=False):
        self._verify_repository()
        if key == "latest.json":
            item = self._json("GET", "/contents/" + POINTER_PATH, missing=optional, params={"ref": self.branch})
            self.pointer_loaded = True
            if item is None:
                self.pointer_sha = None
                return None
            if item.get("encoding") != "base64" or item.get("type") != "file":
                raise GitHubStoreError("Invalid latest.json pointer")
            self.pointer_sha = item["sha"]
            raw = base64.b64decode(item["content"])
            current = json.loads(raw).get("generation", "").split("/")[-1]
            tag = TAG_PREFIX + current
            self.releases = {k: v for k, v in self.releases.items() if k == tag}
            self.assets = {k: v for k, v in self.assets.items() if k == tag}
            return raw
        response = self._asset_response(key)
        try:
            return response.content
        finally:
            response.close()

    def download(self, key, path):
        response = self._asset_response(key)
        try:
            with Path(path).open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        finally:
            response.close()

    def read_watchlist_csv(self):
        self._verify_repository()
        response = self._request("GET", "/contents/daily_watchlist.csv", missing=True,
                                 headers={"Accept": "application/vnd.github.raw+json"}, params={"ref": self.default_branch})
        if response is None:
            return None
        try:
            return response.content
        finally:
            response.close()

    def _upload(self, key, body, size):
        if size >= ASSET_LIMIT:
            raise GitHubStoreError("Release file must be under 2 GiB; no paid storage fallback is enabled")
        tag, name = split_key(key)
        release = self._release(tag, create=True)
        if not release.get("draft"):
            raise GitHubStoreError("Published generations are immutable")
        if name in self._index(tag):
            raise GitHubStoreError("Duplicate asset; use a new snapshot generation")
        asset = self._json("POST", f"/releases/{int(release['id'])}/assets", upload=True,
                          params={"name": name}, data=body,
                          headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)})
        if asset.get("state") != "uploaded" or asset.get("size") != size:
            raise GitHubStoreError("GitHub did not confirm the full upload")
        self.assets[tag][name] = asset

    def upload(self, key, path):
        path = Path(path)
        with path.open("rb") as f:
            self._upload(key, f, path.stat().st_size)

    def write(self, key, raw):
        if key != "latest.json":
            self._upload(key, io.BytesIO(raw), len(raw))
            return
        self._verify_repository()
        if not self.pointer_loaded:
            raise GitHubStoreError("Read latest.json before publishing; refusing an unguarded pointer update")
        manifest = json.loads(raw)
        tag, _ = split_key(manifest["generation"] + "/manifest.json")
        release = self._release(tag)
        index = self._index(tag)
        expected = [manifest["summary"], manifest["checkpoint"], *manifest["details"].values()]
        if any(not item["key"].startswith(manifest["generation"] + "/") for item in expected):
            raise GitHubStoreError("Mixed snapshot generations are not publishable")
        required_names = {split_key(item["key"])[1] for item in expected} | {"manifest.json"}
        if not required_names.issubset(index):
            raise GitHubStoreError("Incomplete generation; latest.json is unchanged")
        if release.get("draft"):
            self.releases[tag] = self._json("PATCH", f"/releases/{int(release['id'])}", json={"draft": False, "make_latest": "false"})
        payload = {"message": "Update prepared market data", "content": base64.b64encode(raw).decode(), "branch": self.branch}
        if self.pointer_sha:
            payload["sha"] = self.pointer_sha
        result = self._json("PUT", "/contents/" + POINTER_PATH, json=payload)
        self.pointer_sha = result["content"]["sha"]

    def prune_generations(self, manifest, keep_days=3):
        self._verify_repository()
        actual = json.loads(self.read("latest.json"))
        if actual["generation"] != manifest["generation"]:
            return
        protected = {TAG_PREFIX + g.split("/")[-1] for g in (actual["generation"], actual.get("previous_generation")) if g}
        releases, page = [], 1
        while True:
            batch = self._json("GET", "/releases", params={"per_page": 100, "page": page})
            releases.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        for release in releases:
            tag = release["tag_name"]
            if not re.fullmatch(TAG_PREFIX + r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}", tag) or tag in protected:
                continue
            created = datetime.fromisoformat(release["created_at"].replace("Z", "+00:00")).timestamp()
            if created >= time.time() - keep_days * 86400:
                continue
            response = self._request("DELETE", f"/releases/{int(release['id'])}")
            response.close()
            response = self._request("DELETE", "/git/refs/tags/" + quote(tag, safe=""), missing=True)
            if response is not None:
                response.close()

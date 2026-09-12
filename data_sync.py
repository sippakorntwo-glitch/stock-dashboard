"""Prepared snapshots: public downloads, private GitHub Releases, or local disk."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import shutil
import tempfile
import threading
import time
from collections import OrderedDict, deque
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
SHARDS = 128
CONFIG_KEYS = ("DASHBOARD_DATA_REPO", "DASHBOARD_GITHUB_TOKEN",
               "DASHBOARD_DATA_VISIBILITY", "DASHBOARD_DATA_BRANCH")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def stamp_seconds(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def pack(value):
    return gzip.compress(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                    separators=(",", ":")).encode(), mtime=0)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def shard_number(ticker):
    return int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16) % SHARDS


def config_from(mapping=None):
    source = dict(mapping or {})
    if os.environ.get("DASHBOARD_LOCAL_ONLY") == "1":
        return {"backend": "local", "DASHBOARD_SNAPSHOT_DIR": os.environ.get("DASHBOARD_SNAPSHOT_DIR", "prepared_data")}
    local = str(source.get("DASHBOARD_SNAPSHOT_DIR") or os.environ.get("DASHBOARD_SNAPSHOT_DIR", "")).strip()
    result = {k: str(source.get(k) or os.environ.get(k, "")).strip() for k in CONFIG_KEYS}
    if local:
        if any(result.values()):
            raise ValueError("Choose local disk OR GitHub settings, not both")
        return {"backend": "local", "DASHBOARD_SNAPSHOT_DIR": local}
    if not any(result.values()):
        return None
    visibility = result["DASHBOARD_DATA_VISIBILITY"] or "public"
    if visibility not in ("public", "private"):
        raise ValueError("DASHBOARD_DATA_VISIBILITY must be public or private")
    required = ["DASHBOARD_DATA_REPO"]
    if visibility == "private":
        required.append("DASHBOARD_GITHUB_TOKEN")
    missing = [k for k in required if not result[k]]
    if missing:
        raise ValueError("Missing settings: " + ", ".join(missing))
    result["DASHBOARD_DATA_VISIBILITY"] = visibility
    result["DASHBOARD_DATA_BRANCH"] = result["DASHBOARD_DATA_BRANCH"] or ("dashboard-data" if visibility == "public" else "")
    return {"backend": "github", **result}


class DirectoryStore:
    """Atomic local files. No hosting account, payment method or storage API."""
    def __init__(self, path):
        self.root = Path(path).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.identity = "local:" + str(self.root)

    def _path(self, key):
        path = (self.root / key).resolve()
        if path == self.root or self.root not in path.parents:
            raise ValueError("Invalid snapshot path")
        return path

    def read(self, key, optional=False):
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            if optional:
                return None
            raise

    def _replace(self, key, write):
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
                name = f.name
                write(f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, target)
        finally:
            if name:
                Path(name).unlink(missing_ok=True)

    def write(self, key, raw):
        self._replace(key, lambda f: f.write(raw))

    def upload(self, key, path):
        with Path(path).open("rb") as source:
            self._replace(key, lambda f: shutil.copyfileobj(source, f))

    def download(self, key, path):
        shutil.copyfile(self._path(key), path)

    def list(self, prefix):
        for path in self._path(prefix).rglob("*"):
            if path.is_file():
                yield path.relative_to(self.root).as_posix(), path.stat().st_mtime

    def delete(self, keys):
        for key in keys:
            self._path(key).unlink(missing_ok=True)


def ObjectStore(config, writable=False):
    if config["backend"] == "local":
        return DirectoryStore(config["DASHBOARD_SNAPSHOT_DIR"])
    if config["backend"] == "github":
        from github_store import GitHubReleaseStore, PublicGitHubStore
        if config.get("DASHBOARD_DATA_VISIBILITY", "public") == "public" and not writable:
            return PublicGitHubStore(config)
        return GitHubReleaseStore(config)
    raise ValueError("No paid storage backend is supported")


def read_manifest(store):
    raw = store.read("latest.json", optional=True)
    if raw is None:
        return None
    value = json.loads(raw)
    if value.get("schema") != SCHEMA or not str(value.get("generation", "")).startswith("generations/"):
        raise ValueError("Snapshot schema ไม่ตรงกับรุ่นแอป")
    return value


def read_checked(store, item):
    raw = store.read(item["key"])
    if digest(raw) != item["sha256"]:
        raise ValueError("Snapshot checksum ไม่ตรง: ใช้ข้อมูลเดิมต่อ")
    return raw


def apply_summary(cache, summary):
    import pandas as pd
    if summary.get("schema") != SCHEMA:
        raise ValueError("Unsupported summary schema")
    cache.put("remote:watchlist", summary.get("watchlist_csv"), {"fetched_at": utc_now()})
    cache.put("remote:universe", summary.get("universe", []), {"fetched_at": utc_now()})
    cache.put("remote:quality", summary.get("quality", {}), {"fetched_at": utc_now()})
    cache.put("remote:screener", summary.get("screener", {}), {"fetched_at": utc_now()})
    rows = summary.get("quotes", {})
    if rows:
        known_quotes = cache.quotes()
        eligible = [r for t, r in rows.items()
                    if stamp_seconds(r.get("Data_Time")) >= stamp_seconds(known_quotes.get(t, {}).get("Data_Time"))]
        if eligible:
            cache.save_quotes(pd.DataFrame(eligible))
    with cache._lock:
        known = cache.classifications()
        incoming = []
        for ticker, value in summary.get("classifications", {}).items():
            if stamp_seconds(value.get("Industry_Time")) >= stamp_seconds(known.get(ticker, {}).get("Industry_Time")):
                incoming.append((ticker, json.dumps(value, ensure_ascii=False, allow_nan=False)))
        if cache.error:
            cache._fallback_classifications.update({t: json.loads(v) for t, v in incoming})
        elif incoming:
            with cache.connect() as db:
                db.executemany("INSERT INTO classifications VALUES (?,?) ON CONFLICT(ticker) DO UPDATE SET body=excluded.body", incoming)


class SnapshotReader:
    """Async small summary + selected-symbol shard; never downloads the database."""
    def __init__(self, store, cache, refresh_seconds=300):
        self.store, self.cache, self.refresh_seconds = store, cache, refresh_seconds
        self.lock = threading.RLock()
        saved, metadata = cache.get("remote:manifest")
        self.source_id = getattr(store, "identity", store.__class__.__name__)
        if metadata.get("source") != self.source_id:
            saved = None
        self.manifest = saved
        self.message = "กำลังตรวจข้อมูลที่เตรียมไว้"
        self.error = ""
        self.next_check = 0.0
        self.thread = None
        self.queue, self.pending = deque(), set()
        self.attempted = {}
        self.shards = OrderedDict()
        self.revision = 0
        self.available = bool(saved)

    def status(self):
        with self.lock:
            return {"busy": bool(self.thread and self.thread.is_alive()), "revision": self.revision,
                    "manifest": self.manifest or {}, "message": self.message, "error": self.error}

    def refresh(self, force=False):
        with self.lock:
            if force:
                self.next_check = 0
            if time.time() >= self.next_check or self.queue:
                self._start()

    def request(self, ticker):
        with self.lock:
            generation = (self.manifest or {}).get("generation")
            marker = (generation, ticker)
            if not generation or ticker in self.pending or self.attempted.get(marker, 0) > time.time():
                return
            self.queue.append(ticker)
            self.pending.add(ticker)
            self._start()

    def _start(self):
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, name="prepared-market-data", daemon=True)
            self.thread.start()

    def _sync(self):
        incoming = read_manifest(self.store)
        if incoming is None:
            self.message = "ยังไม่มีชุดข้อมูลที่เตรียมไว้ — เริ่มงานอัปเดตครั้งแรกตามคู่มือ"
            return
        if not self.manifest or incoming["generation"] != self.manifest["generation"]:
            summary = json.loads(gzip.decompress(read_checked(self.store, incoming["summary"])))
            # Apply before changing the pointer. Interrupted downloads keep the prior generation.
            apply_summary(self.cache, summary)
            self.cache.put("remote:manifest", incoming, {"fetched_at": utc_now(), "source": self.source_id})
            with self.lock:
                self.manifest = incoming
                self.available = True
                self.shards.clear()
                self.attempted.clear()
                self.revision += 1
        self.message = "อ่านชุดข้อมูลที่เตรียมไว้ — ไม่ต้องสแกนทั้งทะเบียนบนหน้าเว็บ"
        self.error = ""

    def _details(self, ticker):
        manifest = self.manifest
        marker = (manifest["generation"], ticker)
        slot = str(shard_number(ticker))
        if slot not in manifest["details"]:
            self.attempted[marker] = float("inf")
            return
        if slot not in self.shards:
            raw = read_checked(self.store, manifest["details"][slot])
            records = {}
            for line in gzip.decompress(raw).splitlines():
                t, key, value, meta = json.loads(line)
                records.setdefault(t, []).append((key, value, meta))
            self.shards[slot] = records
            while len(self.shards) > 4:
                self.shards.popitem(last=False)
        else:
            self.shards.move_to_end(slot)
        changed = False
        for key, value, meta in self.shards[slot].get(ticker, []):
            # Bypass the reader hook when comparing local data to remote data.
            with self.cache._lock:
                old, oldmeta = self.cache.get(key, request_remote=False)
                if old is None or stamp_seconds(meta.get("fetched_at")) > stamp_seconds(oldmeta.get("fetched_at")):
                    self.cache.put(key, value, meta)
                    changed = True
        self.attempted[marker] = float("inf")
        if changed:
            self.revision += 1

    def _run(self):
        try:
            if time.time() >= self.next_check:
                self.next_check = time.time() + self.refresh_seconds
                try:
                    self._sync()
                except Exception as exc:
                    self.error = f"อ่านข้อมูลที่เตรียมไว้ไม่ได้ ({type(exc).__name__}) — ใช้ข้อมูลเดิมต่อ ตรวจ GitHub/Secrets หรืองานอัปเดตบนคอม"
                    self.revision += 1
            while True:
                with self.lock:
                    if not self.queue:
                        # Mark idle under the same lock as request() to avoid a lost final request.
                        self.thread = None
                        return
                    ticker = self.queue.popleft()
                try:
                    self._details(ticker)
                except Exception as exc:
                    self.attempted[((self.manifest or {}).get("generation"), ticker)] = time.time() + 300
                    self.error = f"โหลดข้อมูลที่เตรียมไว้ของ {ticker} ไม่สำเร็จ ({type(exc).__name__}) — ข้อมูลเดิมยังอยู่"
                    self.revision += 1
                finally:
                    with self.lock:
                        self.pending.discard(ticker)
        finally:
            # Normal exit already cleared it under lock. Do not clear a newer worker.
            with self.lock:
                if self.thread is threading.current_thread():
                    self.thread = None


def restore_checkpoint(store, manifest, destination):
    """Fail closed if a saved checkpoint is unavailable; never rebuild over it."""
    if not manifest:
        return
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".download")
    store.download(manifest["checkpoint"]["key"], partial)
    sha = hashlib.sha256()
    with partial.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    if sha.hexdigest() != manifest["checkpoint"]["sha256"]:
        partial.unlink(missing_ok=True)
        raise ValueError("Checkpoint checksum mismatch; will not overwrite remote data")
    with closing(sqlite3.connect(str(partial))) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Checkpoint integrity failure")
    # The collector opens the destination database only after this replacement.
    for suffix in ("-wal", "-shm"):
        Path(str(destination) + suffix).unlink(missing_ok=True)
    os.replace(partial, destination)

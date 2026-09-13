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
import zlib
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


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _validate_summary(summary):
    from data_quality import checked_universe
    if not isinstance(summary, dict) or summary.get("schema") != SCHEMA:
        raise ValueError("Unsupported summary schema")
    universe = set(checked_universe(summary))
    for section in ("quotes", "classifications"):
        rows = summary.get(section, {})
        if not isinstance(rows, dict):
            raise ValueError("Invalid summary records")
        for ticker, row in rows.items():
            if ticker not in universe or not isinstance(row, dict):
                raise ValueError("Summary record outside its universe")
            if section == "quotes" and row.get("Ticker") != ticker:
                raise ValueError("Summary quote symbol mismatch")
    _json(summary)  # Reject invalid values before touching any cache table.


def _apply_snapshot(cache, *, summary=None, records=(), manifest=None,
                    generation=None, source=None, tickers=()):
    """Publish one validated view in a single transaction, including its pointer.

    Cache.put/save_quotes each commit separately and can silently use fallback
    storage after an error, so they cannot implement a snapshot transaction.
    This path uses the same serialized tables and quote merge policy directly.
    A failed transaction leaves the last successful cache and pointer intact.
    """
    import pandas as pd
    from dashboard_core import remember_quotes
    if summary is not None:
        _validate_summary(summary)
    generation = generation or (manifest or {}).get("generation")
    metadata = {"fetched_at": (manifest or {}).get("published_at") or utc_now()}
    if generation:
        metadata.update(snapshot_generation=generation, source=source)
    objects = {}
    if summary is not None:
        for key, value in (("watchlist", summary.get("watchlist_csv")),
                           ("universe", summary["universe"]),
                           ("quality", summary.get("quality", {})),
                           ("screener", summary.get("screener", {}))):
            objects["remote:" + key] = (value, dict(metadata))
    if manifest is not None:
        objects["remote:manifest"] = (manifest, dict(metadata))
    tickers = set(tickers)
    incoming_records = {key: (value, dict(meta, snapshot_generation=generation,
                                         snapshot_source=source)) for key, value, meta in records}
    for value, meta in (*objects.values(), *incoming_records.values()):
        _json(value), _json(meta)

    def stage(known_objects, known_quotes, known_classifications):
        updates = dict(objects)
        # A new publication must not silently drop a selected symbol's earlier
        # prepared inputs while claiming that its details are from the new view.
        if tickers and generation:
            for key, (_, oldmeta) in known_objects.items():
                if (key.rsplit(":", 1)[-1] in tickers and not key.startswith("remote:")
                        and oldmeta.get("snapshot_generation")
                        and key not in incoming_records):
                    raise ValueError("Selected snapshot inputs are incomplete")
        retained = {ticker: {} for ticker in tickers}
        for key, (value, meta) in incoming_records.items():
            old, oldmeta = known_objects.get(key, (None, {}))
            if old is None or stamp_seconds(meta.get("fetched_at")) >= stamp_seconds(oldmeta.get("fetched_at")):
                updates[key] = (value, meta)
            elif oldmeta.get("snapshot_generation"):
                if oldmeta.get("snapshot_source") != source:
                    raise ValueError("Newer detail belongs to another prepared source")
                raise ValueError("Prepared detail timestamp moved backwards")
            else:
                # This marker confirms which shard was reconciled. A genuinely
                # newer independent local observation retains its own metadata;
                # do not relabel it as originating in the incoming snapshot.
                owner = key.rsplit(":", 1)[-1]
                if owner in retained:
                    retained[owner][key] = dict(oldmeta)
        for ticker in tickers:
            updates["remote:detail:" + ticker] = ({"generation": generation,
                         "retained_newer_local": retained[ticker]}, dict(metadata))
        quotes, classifications = {}, {}
        if summary is not None:
            eligible = [row for t, row in summary.get("quotes", {}).items()
                        if stamp_seconds(row.get("Data_Time")) >= stamp_seconds(known_quotes.get(t, {}).get("Data_Time"))]
            if eligible:
                merged = remember_quotes(known_quotes, pd.DataFrame(eligible))
                clean = json.loads(pd.DataFrame([merged[r["Ticker"]] for r in eligible]).to_json(orient="records", double_precision=15))
                quotes = {r["Ticker"]: r for r in clean}
            classifications = {t: v for t, v in summary.get("classifications", {}).items()
                               if stamp_seconds(v.get("Industry_Time")) >= stamp_seconds(known_classifications.get(t, {}).get("Industry_Time"))}
        encoded = [(key, zlib.compress(_json(value).encode()), _json(meta)) for key, (value, meta) in updates.items()]
        quote_rows = [(t, _json(v)) for t, v in quotes.items()]
        classification_rows = [(t, _json(v)) for t, v in classifications.items()]
        return updates, quotes, classifications, encoded, quote_rows, classification_rows

    with cache._lock:
        if cache.error:
            updates, quotes, classifications, *_ = stage(cache._fallback, cache._fallback_quotes, cache._fallback_classifications)
            cache._fallback = {**cache._fallback, **updates}
            cache._fallback_quotes = {**cache._fallback_quotes, **quotes}
            cache._fallback_classifications = {**cache._fallback_classifications, **classifications}
        else:
            with closing(cache.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                keys = set(incoming_records)
                for ticker in tickers:
                    keys.update(row[0] for row in db.execute("SELECT key FROM objects WHERE key LIKE ?", ("%:" + ticker,)))
                known_objects = {}
                for key in keys:
                    row = db.execute("SELECT body,metadata FROM objects WHERE key=?", (key,)).fetchone()
                    if row:
                        known_objects[key] = (json.loads(zlib.decompress(row[0])), json.loads(row[1]))
                known_quotes = {t: json.loads(body) for t, body in db.execute("SELECT ticker,body FROM quotes")} if summary is not None else {}
                known_classifications = {t: json.loads(body) for t, body in db.execute("SELECT ticker,body FROM classifications")} if summary is not None else {}
                _, _, _, encoded, quote_rows, classification_rows = stage(known_objects, known_quotes, known_classifications)
                db.executemany("INSERT INTO objects VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body,metadata=excluded.metadata", encoded)
                db.executemany("INSERT INTO quotes VALUES (?,?) ON CONFLICT(ticker) DO UPDATE SET body=excluded.body", quote_rows)
                db.executemany("INSERT INTO classifications VALUES (?,?) ON CONFLICT(ticker) DO UPDATE SET body=excluded.body", classification_rows)


def apply_summary(cache, summary):
    _apply_snapshot(cache, summary=summary)


class SnapshotReader:
    """Async small summary + selected-symbol shard; never downloads the database."""
    def __init__(self, store, cache, refresh_seconds=60):
        self.store, self.cache, self.refresh_seconds = store, cache, refresh_seconds
        self.lock = threading.RLock()
        saved, metadata = cache.get("remote:manifest")
        self.source_id = getattr(store, "identity", store.__class__.__name__)
        if metadata.get("source") != self.source_id:
            saved = None
        self.manifest = saved
        self.message = "กำลังตรวจข้อมูลที่เตรียมไว้"
        self.error = ""
        self.summary_error = ""
        self.detail_errors = {}
        self.next_check = 0.0
        self.thread = None
        self.queue, self.pending = deque(), set()
        self.attempted = {}
        self.shards = OrderedDict()
        self.revision = 0
        self.summary_revision = 0
        self.detail_revisions = {}
        self.available = bool(saved)
        self.active_tickers = OrderedDict()
        self.active_ttl_seconds = 300
        self.active_limit = 16
        self.detail_generations = {}
        self.checked_at = None

    def status(self, ticker=None):
        with self.lock:
            error = self.error if ticker is None else self.summary_error or self.detail_errors.get(ticker, "")
            return {"busy": bool(self.thread and self.thread.is_alive()), "revision": self.revision,
                    "manifest": self.manifest or {}, "message": self.message, "error": error,
                    "detail_generation": self.detail_generations.get(ticker),
                    "view_revision": (self.summary_revision, self.detail_revisions.get(ticker, 0)),
                    "active_tickers": list(self.active_tickers),
                    "checked_at": self.checked_at, "next_check": self.next_check}

    def _update_error(self):
        self.error = self.summary_error or next(iter(self.detail_errors.values()), "")

    def select(self, ticker):
        """Lease one session's visible ticker; ordinary cache requests do not lease.

        The reader is shared between sessions. Bounded, expiring leases avoid a
        global selection and coalesce sessions viewing the same ticker.
        """
        ticker = str(ticker).strip().upper() if ticker else None
        if not ticker:
            return
        with self.lock:
            self._active()
            self.active_tickers[ticker] = time.monotonic()
            self.active_tickers.move_to_end(ticker)
            while len(self.active_tickers) > self.active_limit:
                self.active_tickers.popitem(last=False)
        self.request(ticker)

    def _active(self):
        expired = time.monotonic() - self.active_ttl_seconds
        for ticker, touched in list(self.active_tickers.items()):
            if touched < expired:
                self.active_tickers.pop(ticker, None)
        return tuple(self.active_tickers)

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
        with self.lock:
            current, active = self.manifest, self._active()
        if current and incoming["generation"] != current["generation"]:
            if stamp_seconds(incoming.get("published_at")) <= stamp_seconds(current.get("published_at")):
                raise ValueError("Snapshot publication moved backwards")
        if not current or incoming["generation"] != current["generation"]:
            self._validate_reference(incoming, incoming["summary"])
            summary = json.loads(gzip.decompress(read_checked(self.store, incoming["summary"])))
            _validate_summary(summary)
            # Download and validate visible inputs before publishing the new
            # summary. Slow or failed detail downloads keep the complete old view.
            staged_shards, records = {}, []
            for ticker in active:
                slot = str(shard_number(ticker))
                if slot not in staged_shards:
                    staged_shards[slot] = self._read_shard(incoming, ticker)
                records.extend(staged_shards[slot].get(ticker, []))
            # UI rendering may hold cache._lock and call status()/request().
            # Always take the cache lock first; never wait for it with lock held.
            with self.cache._lock, self.lock:
                if set(self._active()) - set(active):
                    self.next_check = time.time() + 5
                    raise ValueError("Active tickers changed while staging snapshot")
                _apply_snapshot(self.cache, summary=summary, records=records, manifest=incoming,
                                source=self.source_id, tickers=active)
                self.manifest = incoming
                self.available = True
                self.shards.clear()
                self.attempted.clear()
                self.detail_generations.clear()
                self.detail_revisions.clear()
                self.shards.update(staged_shards)
                while len(self.shards) > 4:
                    self.shards.popitem(last=False)
                for ticker in active:
                    self.attempted[(incoming["generation"], ticker)] = float("inf")
                    self.detail_generations[ticker] = incoming["generation"]
                    self.detail_errors.pop(ticker, None)
                self.revision += 1
                self.summary_revision += 1
        with self.lock:
            self.checked_at = utc_now()
            self.message = "อ่านชุดข้อมูลที่เตรียมไว้ — ไม่ต้องสแกนทั้งทะเบียนบนหน้าเว็บ"
            self.summary_error = ""
            self._update_error()

    @staticmethod
    def _validate_reference(manifest, reference):
        if not str(reference.get("key", "")).startswith(manifest["generation"] + "/"):
            raise ValueError("Snapshot reference belongs to another generation")

    def _read_shard(self, manifest, ticker):
        slot = str(shard_number(ticker))
        reference = manifest["details"].get(slot)
        if reference is None:
            return {}
        self._validate_reference(manifest, reference)
        raw = read_checked(self.store, reference)
        records, seen = {}, set()
        for line in gzip.decompress(raw).splitlines():
            t, key, value, meta = json.loads(line)
            if (not isinstance(t, str) or not isinstance(key, str) or not isinstance(meta, dict)
                    or str(shard_number(t)) != slot
                    or key not in {prefix + t for prefix in ("history:1d:", "info:", "dividends:", "reference:", "financials:")}
                    or key in seen):
                raise ValueError("Invalid or mismatched snapshot detail record")
            _json(value), _json(meta)
            seen.add(key)
            records.setdefault(t, []).append((key, value, meta))
        return records

    def _details(self, ticker):
        with self.lock:
            manifest = self.manifest
        if not manifest:
            return
        marker = (manifest["generation"], ticker)
        slot = str(shard_number(ticker))
        if slot not in self.shards:
            records = self._read_shard(manifest, ticker)
        else:
            records = self.shards[slot]
        with self.cache._lock, self.lock:
            if manifest is not self.manifest:
                raise ValueError("Snapshot changed while staging details")
            _apply_snapshot(self.cache, records=records.get(ticker, []),
                            generation=manifest["generation"], source=self.source_id, tickers=(ticker,))
            self.shards[slot] = records
            self.shards.move_to_end(slot)
            while len(self.shards) > 4:
                self.shards.popitem(last=False)
            changed = self.detail_generations.get(ticker) != manifest["generation"]
            self.detail_generations[ticker] = manifest["generation"]
            self.detail_errors.pop(ticker, None)
            self._update_error()
            self.attempted[marker] = float("inf")
            if changed:
                self.revision += 1
                self.detail_revisions[ticker] = self.detail_revisions.get(ticker, 0) + 1

    def _run(self):
        try:
            if time.time() >= self.next_check:
                self.next_check = time.time() + self.refresh_seconds
                try:
                    self._sync()
                except Exception as exc:
                    with self.lock:
                        self.summary_error = f"อ่านข้อมูลที่เตรียมไว้ไม่ได้ ({type(exc).__name__}) — ใช้ข้อมูลเดิมต่อ ตรวจ GitHub/Secrets หรืองานอัปเดตบนคอม"
                        self._update_error()
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
                    with self.lock:
                        self.attempted[((self.manifest or {}).get("generation"), ticker)] = time.time() + 300
                        self.detail_errors[ticker] = f"โหลดข้อมูลที่เตรียมไว้ของ {ticker} ไม่สำเร็จ ({type(exc).__name__}) — ข้อมูลเดิมยังอยู่"
                        self._update_error()
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

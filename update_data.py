"""Run on GitHub Actions: durable history, incremental prices, resumable metadata."""
from __future__ import annotations

import argparse
import atexit
import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import uuid
import zlib
from contextlib import ExitStack, closing
from pathlib import Path

import pandas as pd

import dashboard_runtime as app
from data_sync import (SCHEMA, SHARDS, ObjectStore, config_from, digest, pack,
                       read_manifest, restore_checkpoint, shard_number, stamp_seconds, utc_now)


def object_metadata(cache):
    with cache.connect() as db:
        return {key: json.loads(meta) for key, meta in db.execute("SELECT key, metadata FROM objects")}


def history_missing(row):
    return ((app.number(row.get("History_Years_Loaded")) or 0) < app.HISTORY_YEARS
            or app.number(row.get("Return_Calc_Version")) != app.RETURN_CALC_VERSION
            or app.number(row.get("Close")) is None
            or app.number(row.get("Metric_Calc_Version")) != app.METRIC_VERSION)


def retry_due(metadata, kind, ticker):
    return stamp_seconds(metadata.get(f"attempt:{kind}:{ticker}", {}).get("retry_after"))


def record_attempt(cache, kind, ticker, success):
    now = time.time()
    retry = pd.Timestamp(now + (0 if success else 86400), unit="s", tz="UTC").isoformat()
    meta = {"fetched_at": utc_now(), "retry_after": retry, "success": success}
    cache.put(f"attempt:{kind}:{ticker}", {"success": success}, meta)


def pending_bootstrap(universe, quotes, metadata):
    pending, due = set(), []
    for ticker in universe:
        missing = []
        if history_missing(quotes.get(ticker, {})):
            missing.append("history")
        for kind in ("info", "dividends"):
            if f"{kind}:{ticker}" not in metadata:
                missing.append(kind)
            elif kind == "info" and metadata[f"info:{ticker}"].get("classification_available") is False:
                missing.append(kind)
        if missing:
            pending.add(ticker)
            due.extend(max(retry_due(metadata, kind, ticker),
                stamp_seconds(metadata.get(f"info:{ticker}", {}).get("fetched_at")) + 86400
                if kind == "info" and metadata.get(f"info:{ticker}", {}).get("classification_available") is False else 0) for kind in missing)
    return len(pending), min(due) if due else None


def publish_snapshot(store, cache, universe, report, previous=None, watchlist_csv=None):
    """Upload an immutable generation, then atomically replace its small pointer."""
    if cache.error:
        raise RuntimeError("Local cache could not be persisted; refusing to publish")
    from data_quality import prepare_cached_metadata, make_quality
    prepare_cached_metadata(cache, universe, app.ETF_NAMES)
    quality = make_quality(cache, universe, etfs=app.ETF_NAMES)
    generation = "generations/" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix="snapshot-") as folder:
        folder = Path(folder)
        checkpoint = folder / "checkpoint.sqlite3"
        with closing(cache.connect()) as source, closing(sqlite3.connect(str(checkpoint))) as destination:
            source.backup(destination)
            destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            destination.execute("PRAGMA journal_mode=DELETE")
        with closing(sqlite3.connect(str(checkpoint))) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Invalid local checkpoint")
            all_quotes = {t: json.loads(body) for t, body in db.execute("SELECT ticker, body FROM quotes")}
            quotes = {t: all_quotes[t] for t in universe if t in all_quotes}
            classifications = {t: json.loads(body) for t, body in db.execute("SELECT ticker, body FROM classifications") if t in universe}
            metadata = {k: json.loads(m) for k, m in db.execute("SELECT key, metadata FROM objects")}
            # Stream each record into one of 128 bounded shards; never hold all histories in RAM.
            handles = {}
            with ExitStack() as stack:
                for key, compressed, meta in db.execute("SELECT key, body, metadata FROM objects"):
                    if not key.startswith(("history:1d:", "info:", "dividends:")):
                        continue
                    ticker = key.rsplit(":", 1)[-1]
                    if ticker not in universe:
                        continue
                    slot = shard_number(ticker)
                    if slot not in handles:
                        handles[slot] = stack.enter_context(gzip.open(folder / f"{slot}.jsonl.gz", "wt", encoding="utf-8"))
                    handles[slot].write(json.dumps([ticker, key, json.loads(zlib.decompress(compressed)), json.loads(meta)],
                                                  ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        pending, next_due = pending_bootstrap(universe, quotes, metadata)
        coverage = {
            "universe": len(universe),
            "prices": sum(app.number(r.get("Close")) is not None for r in quotes.values()),
            "checked_today": sum(app.summary_is_current(r) for r in quotes.values()),
            "industry": sum(bool(app.clean_industry(r.get("Industry"))) for r in classifications.values()),
            "info": sum(f"info:{t}" in metadata for t in universe),
            "dividends": sum(f"dividends:{t}" in metadata for t in universe),
            "return_1y": sum(app.number(r.get("Historical_Return")) is not None for r in quotes.values()),
            "return_2y": sum(app.number(r.get("Return_2Y")) is not None for r in quotes.values()),
            "return_3y": sum(app.number(r.get("Return_3Y")) is not None for r in quotes.values()),
        }
        from return_periods import RETURN_FIELDS
        coverage["return_periods"] = {field: sum(app.number(r.get(field)) is not None for r in quotes.values()) for field in RETURN_FIELDS}
        summary = {"schema": SCHEMA, "quotes": quotes, "classifications": classifications,
                   "universe": list(universe), "watchlist_csv": watchlist_csv, "quality": quality}
        raw = pack(summary)
        summary_ref = {"key": generation + "/summary.json.gz", "sha256": digest(raw)}
        store.write(summary_ref["key"], raw)
        details = {}
        for slot in sorted(handles):
            path = folder / f"{slot}.jsonl.gz"
            key = generation + f"/details/{slot}.jsonl.gz"
            store.upload(key, path)
            details[str(slot)] = {"key": key, "sha256": digest(path.read_bytes())}
        sha = hashlib.sha256()
        with checkpoint.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(block)
        checkpoint_ref = {"key": generation + "/checkpoint.sqlite3", "sha256": sha.hexdigest()}
        store.upload(checkpoint_ref["key"], checkpoint)
        manifest = {"schema": SCHEMA, "generation": generation, "published_at": utc_now(),
                    "previous_generation": (previous or {}).get("generation"),
                    "summary": summary_ref, "details": details, "checkpoint": checkpoint_ref,
                    "coverage": coverage, "quality_counts": quality["counts"], "report": report,
                    "bootstrap_pending": pending, "bootstrap_next_due": next_due,
                    "catalog_as_of": app.CATALOG_AS_OF, "app_version": app.APP_VERSION}
        manifest_raw = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()
        store.write(generation + "/manifest.json", manifest_raw)
        # A single object PUT becomes visible only after complete upload. No partial generation exposed.
        store.write("latest.json", manifest_raw)
        print("Published:", json.dumps(coverage), "bootstrap pending:", pending, flush=True)
        return manifest


def prune_old_generations(store, manifest, keep_days=7):
    if hasattr(store, "prune_generations"):
        store.prune_generations(manifest, keep_days=3)
        return
    # Always retain current + previous even if the workflow is inactive for months.
    protected = {manifest["generation"], manifest.get("previous_generation")}
    cutoff = time.time() - keep_days * 86400
    groups = {}
    for key, modified in store.list("generations/"):
        parts = key.split("/")
        if len(parts) < 3:
            continue
        generation = "/".join(parts[:2])
        group = groups.setdefault(generation, {"newest": 0, "keys": []})
        group["newest"] = max(group["newest"], modified)
        group["keys"].append(key)
    for generation, group in groups.items():
        if generation not in protected and group["newest"] < cutoff:
            store.delete(group["keys"])


def collect(cache, universe, mode, price_minutes=35, metadata_minutes=20, metadata_limit=1000,
            first_publish=None):
    report = {"started_at": utc_now(), "mode": mode, "price_attempted": 0,
              "price_success": 0, "price_failed": 0, "metadata_success": 0, "metadata_failed": 0,
              "rate_limited": False, "errors": []}
    quotes, metadata = cache.quotes(), object_metadata(cache)
    now = time.time()
    prices = [t for t in universe if (history_missing(quotes.get(t, {})) if mode == "bootstrap" else
                                    not app.summary_is_current(quotes.get(t, {})))
              and retry_due(metadata, "history", t) <= now]
    # Resume missing symbols first, then oldest successful prices. Stable order prevents starvation.
    order = {t: i for i, t in enumerate(universe)}
    prices.sort(key=lambda t: (not history_missing(quotes.get(t, {})),
                               stamp_seconds(quotes.get(t, {}).get("Data_Time")), order[t]))
    deadline = time.monotonic() + price_minutes * 60
    initial_published = False
    for offset in range(0, len(prices), app.SCAN_BATCH_SIZE):
        if time.monotonic() >= deadline:
            break
        batch = prices[offset:offset + app.SCAN_BATCH_SIZE]
        rows, errors, stats = app.fetch_daily_batch(batch, cache, years=app.HISTORY_YEARS)
        successes = set(rows.loc[rows.Data_Status.eq("โหลดสำเร็จ"), "Ticker"])
        for ticker in batch:
            record_attempt(cache, "history", ticker, ticker in successes)
        report["price_attempted"] += len(batch)
        report["price_success"] += len(successes)
        report["price_failed"] += len(batch) - len(successes)
        report["errors"] = (report["errors"] + errors)[-20:]
        print(f"Prices: {report['price_attempted']}/{len(prices)}; success {report['price_success']}", flush=True)
        if first_publish and not initial_published and report["price_success"] >= 100:
            first_publish(report.copy())
            initial_published = True
        if len(successes) < len(batch) / 2:
            # No aggressive retries or parallel evasion of provider limits.
            report["rate_limited"] = True
            break
        time.sleep(app.SCAN_INTERVAL_SECONDS)
    from metadata_repair import collect_metadata
    collect_metadata(cache, universe, mode, metadata_minutes, metadata_limit, report,
                     app=app, get_metadata=object_metadata, record_attempt=record_attempt)
    report["finished_at"] = utc_now()
    return report


def local_collector_lock(path):
    """One scheduled/manual local collector at a time; released on process exit."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    atexit.register(handle.close)
    return handle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("daily", "bootstrap"), default="daily")
    parser.add_argument("--price-minutes", type=float, default=35)
    parser.add_argument("--metadata-minutes", type=float, default=20)
    parser.add_argument("--metadata-limit", type=int, default=1000)
    args = parser.parse_args()
    if min(args.price_minutes, args.metadata_minutes, args.metadata_limit) < 0:
        parser.error("Budgets and metadata limit must be non-negative")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # The job-level public-repository condition is the primary pre-allocation gate.
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        if event.get("repository", {}).get("private") is not False:
            parser.error("This workflow only runs in a Public code repository; no private-runner fallback")
    config = config_from()
    if not config:
        parser.error("Configure the GitHub Actions workflow, or DASHBOARD_SNAPSHOT_DIR for local storage")
    if config["backend"] == "github":
        if not config.get("DASHBOARD_GITHUB_TOKEN"):
            parser.error("Collector needs the Actions GITHUB_TOKEN; the public website does not need a token")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            if (config["DASHBOARD_DATA_REPO"].casefold() != os.environ.get("GITHUB_REPOSITORY", "").casefold()
                    or config["DASHBOARD_DATA_VISIBILITY"] != "public"):
                parser.error("Public workflow writes only to its own repository")
    path = Path(os.environ.get("DASHBOARD_CACHE_FILE", "work/dashboard_cache.sqlite3"))
    if config["backend"] == "local":
        lock = local_collector_lock(path.parent / "collector.lock")
        if lock is None:
            print("A local update is already running; no second collector started.")
            return
    store = ObjectStore(config, writable=True)
    previous = read_manifest(store)
    if args.mode == "bootstrap" and previous:
        due = previous.get("bootstrap_next_due")
        if not previous.get("bootstrap_pending") or (due is not None and due > time.time()):
            print("No bootstrap work due. Daily update remains scheduled.")
            return
    # Deliberately fail before any publication on authentication/download/checksum failure.
    restore_checkpoint(store, previous, path)
    cache = app.DashboardCache(path)
    if cache.error:
        raise RuntimeError("Cannot persist checkpoint: " + cache.error)
    csv_bytes = app.WATCHLIST_FILE.read_bytes() if app.WATCHLIST_FILE.exists() else None
    if csv_bytes is None and hasattr(store, "read_watchlist_csv"):
        csv_bytes = store.read_watchlist_csv()
    csv_frame = app.parse_watchlist(csv_bytes) if csv_bytes else pd.DataFrame(columns=["Ticker"])
    csv_text = csv_bytes.decode("utf-8-sig") if csv_bytes else None
    if not previous and not csv_frame.empty:
        cache.save_quotes(csv_frame)
    universe = app.select_universe(csv_frame)
    def first_publish(report):
        nonlocal previous
        previous = publish_snapshot(store, cache, universe, report, previous, watchlist_csv=csv_text)
    # A first partial snapshot becomes usable after 100 successful symbols.
    try:
        report = collect(cache, universe, args.mode, args.price_minutes, args.metadata_minutes,
                         args.metadata_limit, first_publish=first_publish if not previous else None)
    except Exception as exc:
        # Save successful work on an ordinary failure. A hard runner kill still leaves
        # the last fully published remote generation intact.
        partial = {"mode": args.mode, "finished_at": utc_now(), "interrupted": True,
                   "errors": [type(exc).__name__]}
        publish_snapshot(store, cache, universe, partial, previous, watchlist_csv=csv_text)
        raise
    manifest = publish_snapshot(store, cache, universe, report, previous, watchlist_csv=csv_text)
    try:
        prune_old_generations(store, manifest)
    except Exception as exc:
        print("::warning::Old snapshot cleanup failed:", type(exc).__name__)
    counts = manifest["coverage"]
    text = (f"### Prepared market data\n\nPublished (UTC): {manifest['published_at']}\n\n"
            f"Prices available: {counts['prices']}/{len(universe)}; checked today: {counts['checked_today']}\n\n"
            f"Industry: {counts['industry']}; dividends checked: {counts['dividends']}\n\n"
            f"Bootstrap symbols remaining: {manifest['bootstrap_pending']}\n\n"
            "A successful workflow means the available progress was saved, not that all symbols are current.\n")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(text)
    print(text)
    if report["rate_limited"] or report["price_failed"] or report["metadata_failed"]:
        print("::warning::Provider returned incomplete data; prior values retained. See coverage and per-symbol timestamps.")


if __name__ == "__main__":
    main()

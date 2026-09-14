"""Unattended refresh across reporting periods; explicit fixtures, no live data."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

import company_financials_job as job
from financial_completeness import COLLECTION_REVISION, preserve_refresh
from financial_statements import FLOW_FIELDS, observations, statement_records


def bundle(ticker="TEST", end="2030-06-30", revenue=100):
    value = {
        "schema": 1, "collection_revision": COLLECTION_REVISION,
        "ticker": ticker, "currency": "USD", "errors": [],
        "fetched_at": "2030-08-15T00:00:00Z",
        "annual": {"income": [{"end": end, "values": {"revenue": revenue}}]},
        "quarterly": {},
    }
    value["observations"] = observations(value)
    return value


def test_future_year_and_non_calendar_fiscal_year_are_accepted_when_reported():
    previous = bundle()
    new = bundle(end="2031-06-30", revenue=125)
    new["fetched_at"] = "2031-08-15T00:00:00Z"
    frame = pd.DataFrame(
        {"2031-06-30": [125], "2030-06-30": [100], "2032-06-30": [999]},
        index=["Total Revenue"],
    )
    new["annual"]["income"] = statement_records(frame, FLOW_FIELDS, today=date(2031, 8, 15))
    merged = preserve_refresh(previous, new)
    assert [r["end"] for r in merged["annual"]["income"]] == ["2031-06-30", "2030-06-30"]
    assert merged["observations"]["revenue"]["end"] == "2031-06-30"
    assert merged["observations"]["revenueGrowthFY"]["value"] == pytest.approx(.25)


def test_new_quarter_rotates_ttm_and_retains_prior_reported_history():
    previous = bundle()
    previous["quarterly"]["income"] = [
        {"end": end, "values": {"revenue": 10}}
        for end in ("2030-12-31", "2030-09-30", "2030-06-30", "2030-03-31")
    ]
    new = deepcopy(previous)
    new["fetched_at"] = "2031-05-15T00:00:00Z"
    new["quarterly"]["income"] = [{"end": "2031-03-31", "values": {"revenue": 20}}]
    merged = preserve_refresh(previous, new)
    revenue = merged["observations"]["revenue"]
    assert revenue["value"] == 50
    assert revenue["basis"] == "TTM (4 reported quarters)"
    assert revenue["end"] == "2031-03-31"
    assert revenue["period_ends"] == ["2031-03-31", "2030-12-31", "2030-09-30", "2030-06-30"]
    assert merged["quarterly"]["income"][-1]["end"] == "2030-03-31"


def test_calendar_flip_without_new_filing_does_not_invent_a_reporting_period():
    previous = bundle(end="2030-09-30")
    refreshed = deepcopy(previous)
    refreshed["fetched_at"] = "2031-01-02T00:00:00Z"
    merged = preserve_refresh(previous, refreshed)
    assert merged["annual"]["income"][0]["end"] == "2030-09-30"
    assert merged["observations"]["revenue"]["value"] == 100
    assert merged["observations"]["revenue"]["end"] == "2030-09-30"
    assert merged["quarterly"]["income"] == []


def test_due_queue_prioritizes_never_checked_then_oldest_attempt_not_popularity():
    names = ("AAPL", "FAILED", "NEW", "OLDER", "PAUSED")
    profiles = {"info:"+t: ({"financialCurrency": "USD"}, {}) for t in names}
    statements = {"financials:"+t: (bundle(t), {"fetched_at": stamp, "available": True})
                  for t, stamp in (("AAPL", "2030-08-10T00:00:00Z"), ("OLDER", "2030-08-01T00:00:00Z"))}
    for value, meta in statements.values():
        value["fetched_at"] = meta["fetched_at"]
    attempts = {
        "attempt:financials:FAILED": ({}, {"fetched_at": "2030-08-13T00:00:00Z", "success": False,
                                             "retry_after": "2030-08-13T06:00:00Z"}),
        "attempt:financials:PAUSED": ({}, {"fetched_at": "2030-08-01T00:00:00Z", "success": False,
                                             "retry_after": "2030-08-16T06:00:00Z"}),
    }
    now = datetime(2030, 8, 15, tzinfo=timezone.utc).timestamp()
    assert job.due_symbols(names, profiles, statements, attempts, set(), now=now) == ["NEW", "OLDER", "AAPL", "FAILED"]


def test_repeated_failures_do_not_starve_full_catalog_rollover_sweep():
    # All 4,200 companies need a fresh check. A 400-company six-hour batch must
    # eventually visit the last one even when each attempt fails and is due again.
    names = tuple(f"TEST{i:04}" for i in range(4200))
    profiles = {"info:"+t: ({"financialCurrency": "USD"}, {}) for t in names}
    attempts, visited = {}, set()
    start = datetime(2031, 1, 1, tzinfo=timezone.utc)
    for batch in range(11):
        clock = start + timedelta(hours=6*batch)
        due = job.due_symbols(names, profiles, {}, attempts, set(), now=clock.timestamp())[:400]
        visited.update(due)
        for ticker in due:
            attempts["attempt:financials:"+ticker] = ({}, {
                "fetched_at": clock.isoformat(), "success": False,
                "retry_after": (clock+timedelta(hours=6)).isoformat(),
            })
    assert visited == set(names)


def test_successful_statement_refresh_is_due_after_two_days_and_persists_retry(tmp_path, monkeypatch):
    from dashboard_runtime import DashboardCache
    from data_quality import timestamp

    now = datetime.now(timezone.utc)
    stamp = (now-timedelta(days=2, seconds=1)).isoformat()
    previous = bundle()
    previous["fetched_at"] = stamp
    profiles = {"info:TEST": ({"financialCurrency": "USD"}, {})}
    statements = {"financials:TEST": (previous, {"fetched_at": stamp, "available": True})}
    assert job.due_symbols(("TEST",), profiles, statements, {}, set(), now=now.timestamp()) == ["TEST"]
    assert job.due_symbols(("TEST",), profiles, statements, {}, set(), now=(now-timedelta(seconds=2)).timestamp()) == []

    cache = DashboardCache(tmp_path/"financials.sqlite3")
    cache.put("info:TEST", profiles["info:TEST"][0], {})
    cache.put("financials:TEST", previous, statements["financials:TEST"][1])
    monkeypatch.setattr(job, "collect", lambda *args: deepcopy(previous))
    monkeypatch.setattr(job.time, "sleep", lambda _: None)
    report = job.collect_batch(cache, ("TEST",), set())
    assert report["attempted"] == 1 and report["updated"] == 0
    attempt = cache.get("attempt:financials:TEST", request_remote=False)[1]
    retry_seconds = timestamp(attempt["retry_after"])-timestamp(attempt["fetched_at"])
    assert 2*86400-2 <= retry_seconds <= 2*86400+2


@pytest.mark.parametrize("success,expected", [(True, ["TEST"]), (False, []), (None, [])])
def test_previous_seven_day_success_retry_migrates_but_failure_cooldown_does_not(success, expected):
    now = datetime(2030, 8, 20, tzinfo=timezone.utc)
    value = bundle()
    statements = {"financials:TEST": (value, {"fetched_at": value["fetched_at"], "available": True})}
    attempts = {"attempt:financials:TEST": ({}, {
        "fetched_at": "2030-08-15T00:00:00Z", "retry_after": "2030-08-22T00:00:00Z", "success": success,
    })}
    profiles = {"info:TEST": ({"financialCurrency": "USD"}, {})}
    assert job.due_symbols(("TEST",), profiles, statements, attempts, set(), now=now.timestamp()) == expected
    if success is True:
        attempts["attempt:financials:TEST"][1].pop("fetched_at")
        assert job.due_symbols(("TEST",), profiles, statements, attempts, set(), now=now.timestamp()) == []


def test_sec_metadata_refresh_does_not_postpone_new_quarter_provider_poll():
    now = datetime(2030, 8, 20, tzinfo=timezone.utc)
    value = bundle()
    value["sec_reconciliation"] = {"checked_at": now.isoformat()}
    statements = {"financials:TEST": (value, {"fetched_at": now.isoformat(), "available": True})}
    profiles = {"info:TEST": ({"financialCurrency": "USD"}, {})}
    assert job.due_symbols(("TEST",), profiles, statements, {}, set(), now=now.timestamp()) == ["TEST"]
    # Old snapshots with no provider timestamp still use their available metadata.
    value.pop("fetched_at")
    assert job.due_symbols(("TEST",), profiles, statements, {}, set(), now=now.timestamp()) == []

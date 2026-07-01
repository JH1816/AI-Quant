"""Tests for the pure calendar engine (no fixtures / no network)."""

from datetime import date, datetime

import pandas as pd

from core.calendar_engine import (
    normalize_ticker_events, build_calendar, DEFAULT_WINDOW_DAYS,
)

TODAY = date(2026, 7, 1)


# ── normalize_ticker_events ───────────────────────────────────────────────────

def test_dict_calendar_with_earnings_range_is_estimate():
    cal = {
        "Earnings Date": [date(2026, 7, 30), date(2026, 8, 3)],
        "Ex-Dividend Date": date(2026, 8, 20),
        "Dividend Date": date(2026, 9, 10),
    }
    events = normalize_ticker_events("AAPL", cal)
    by_type = {e["type"]: e for e in events}

    assert by_type["earnings"]["date"] == "2026-07-30"   # earliest of the range
    assert by_type["earnings"]["estimate"] is True
    assert by_type["ex_dividend"]["date"] == "2026-08-20"
    assert by_type["ex_dividend"]["estimate"] is False
    assert by_type["dividend_payment"]["date"] == "2026-09-10"


def test_single_earnings_date_is_not_estimate():
    events = normalize_ticker_events("AAPL", {"Earnings Date": [date(2026, 7, 30)]})
    assert events == [{"ticker": "AAPL", "type": "earnings",
                       "date": "2026-07-30", "estimate": False}]


def test_legacy_dataframe_calendar():
    df = pd.DataFrame(
        {0: [datetime(2026, 7, 30), datetime(2026, 8, 20)]},
        index=["Earnings Date", "Ex-Dividend Date"],
    )
    events = normalize_ticker_events("MSFT", df)
    by_type = {e["type"]: e["date"] for e in events}
    assert by_type == {"earnings": "2026-07-30", "ex_dividend": "2026-08-20"}


def test_info_epoch_fallback_when_calendar_empty():
    info = {
        "earningsTimestamp": 1785369600,   # 2026-07-30 UTC
        "exDividendDate": 1787184000,      # 2026-08-20 UTC
    }
    events = normalize_ticker_events("AAPL", None, info)
    by_type = {e["type"]: e["date"] for e in events}
    assert by_type["earnings"] == "2026-07-30"
    assert by_type["ex_dividend"] == "2026-08-20"


def test_calendar_takes_precedence_over_info():
    cal = {"Ex-Dividend Date": date(2026, 8, 20)}
    info = {"exDividendDate": 1600000000}  # stale epoch — must be ignored
    events = normalize_ticker_events("AAPL", cal, info)
    assert [e for e in events if e["type"] == "ex_dividend"] == [
        {"ticker": "AAPL", "type": "ex_dividend", "date": "2026-08-20", "estimate": False}
    ]


def test_unparseable_dates_dropped():
    events = normalize_ticker_events("AAPL", {"Earnings Date": ["not-a-date"]})
    assert events == []


def test_none_and_empty_calendar_without_info():
    assert normalize_ticker_events("VOO", None) == []
    assert normalize_ticker_events("VOO", {}) == []


# ── build_calendar ────────────────────────────────────────────────────────────

def _event(ticker, type_, iso, estimate=False):
    return {"ticker": ticker, "type": type_, "date": iso, "estimate": estimate}


def test_events_filtered_to_window_and_sorted():
    events_by_ticker = {
        "AAPL": [
            _event("AAPL", "earnings", "2026-07-30"),
            _event("AAPL", "ex_dividend", "2026-06-15"),  # past → dropped
            _event("AAPL", "dividend_payment", "2027-01-01"),  # beyond window → dropped
        ],
        "MSFT": [_event("MSFT", "earnings", "2026-07-25")],
    }
    res = build_calendar(events_by_ticker, TODAY)
    assert [(e["ticker"], e["date"]) for e in res["events"]] == [
        ("MSFT", "2026-07-25"), ("AAPL", "2026-07-30"),
    ]
    assert res["as_of"] == "2026-07-01"
    assert res["window_days"] == DEFAULT_WINDOW_DAYS


def test_window_boundaries_inclusive():
    events_by_ticker = {
        "AAA": [_event("AAA", "earnings", "2026-07-01"),           # today → kept
                _event("AAA", "ex_dividend", "2026-09-29")],        # day 90 → kept
    }
    res = build_calendar(events_by_ticker, TODAY, window_days=90)
    assert len(res["events"]) == 2
    assert res["events"][0]["days_until"] == 0
    assert res["events"][1]["days_until"] == 90


def test_duplicate_events_deduped():
    events_by_ticker = {
        "AAPL": [_event("AAPL", "ex_dividend", "2026-08-20"),
                 _event("AAPL", "ex_dividend", "2026-08-20")],
    }
    res = build_calendar(events_by_ticker, TODAY)
    assert len(res["events"]) == 1


def test_same_date_sorted_by_ticker():
    events_by_ticker = {
        "ZZZ": [_event("ZZZ", "earnings", "2026-07-30")],
        "AAA": [_event("AAA", "earnings", "2026-07-30")],
    }
    res = build_calendar(events_by_ticker, TODAY)
    assert [e["ticker"] for e in res["events"]] == ["AAA", "ZZZ"]


def test_labels_and_estimate_flag_carried():
    events_by_ticker = {
        "AAPL": [_event("AAPL", "earnings", "2026-07-30", estimate=True)],
    }
    ev = build_calendar(events_by_ticker, TODAY)["events"][0]
    assert ev["label"] == "Earnings"
    assert ev["estimate"] is True


def test_failed_and_empty_tickers_reported_as_no_data():
    events_by_ticker = {
        "AAPL": [_event("AAPL", "earnings", "2026-07-30")],
        "VOO": [],     # nothing published
        "FAIL": None,  # fetch failed
    }
    res = build_calendar(events_by_ticker, TODAY)
    assert res["tickers_checked"] == ["AAPL", "FAIL", "VOO"]
    assert sorted(res["tickers_with_no_data"]) == ["FAIL", "VOO"]
    assert len(res["events"]) == 1


def test_malformed_rows_skipped():
    events_by_ticker = {
        "AAPL": [{"ticker": "AAPL", "type": "earnings"},        # no date
                 {"ticker": "AAPL", "type": "earnings", "date": "bogus"},
                 _event("AAPL", "earnings", "2026-07-30")],
    }
    res = build_calendar(events_by_ticker, TODAY)
    assert len(res["events"]) == 1

"""Upcoming dividend & earnings events for a set of tickers.

Pure transforms only: ``normalize_ticker_events`` coerces the unstable
yfinance ``.calendar`` payload (a dict in current versions, a DataFrame in
older ones, ``{}``/None for ETFs or non-Yahoo providers) plus ``.info`` epoch
fields into flat event rows, and ``build_calendar`` merges per-ticker rows
into one sorted upcoming-events feed. The network side (fetching and the 1h
cache) lives in ``main.py``, so everything here is unit testable offline.
"""

from datetime import date, timedelta

import pandas as pd

from core.fundamentals_engine import _epoch_to_date

DEFAULT_WINDOW_DAYS = 90

EVENT_LABELS = {
    "earnings": "Earnings",
    "ex_dividend": "Ex-dividend",
    "dividend_payment": "Dividend payment",
}

# yfinance .calendar keys → event type.
_CAL_KEYS = {
    "Earnings Date": "earnings",
    "Ex-Dividend Date": "ex_dividend",
    "Dividend Date": "dividend_payment",
}

# .info epoch-second fields → event type (fallback when .calendar lacks them).
_INFO_KEYS = (
    ("earningsTimestamp", "earnings"),
    ("earningsTimestampStart", "earnings"),
    ("exDividendDate", "ex_dividend"),
    ("dividendDate", "dividend_payment"),
)


def _to_iso(value) -> str | None:
    """Coerce a date/datetime/Timestamp/string to 'YYYY-MM-DD', or None."""
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def normalize_ticker_events(ticker: str, calendar, info: dict | None = None) -> list[dict]:
    """Flatten one ticker's calendar payload into event rows.

    ``calendar`` may be a dict (current yfinance), a DataFrame (legacy), or
    None/{} (ETFs, rate-limited, non-Yahoo providers). Earnings dates given as
    a 2-item range are reported as the first date with ``estimate: True``.
    ``info`` epoch fields only fill event types the calendar didn't supply.
    """
    entries: dict = {}
    if isinstance(calendar, pd.DataFrame) and not calendar.empty:
        # Legacy shape: row labels × one column per upcoming event.
        entries = {str(idx): list(row.dropna()) for idx, row in calendar.iterrows()}
    elif isinstance(calendar, dict):
        entries = calendar

    events: list[dict] = []
    seen_types: set[str] = set()

    for key, event_type in _CAL_KEYS.items():
        raw = entries.get(key)
        if raw is None:
            continue
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        iso_dates = sorted({d for d in (_to_iso(v) for v in values) if d})
        if not iso_dates:
            continue
        events.append({
            "ticker": ticker,
            "type": event_type,
            "date": iso_dates[0],
            "estimate": event_type == "earnings" and len(iso_dates) > 1,
        })
        seen_types.add(event_type)

    for key, event_type in _INFO_KEYS:
        if event_type in seen_types or not info:
            continue
        iso = _epoch_to_date(info.get(key))
        if iso:
            events.append({"ticker": ticker, "type": event_type,
                           "date": iso, "estimate": False})
            seen_types.add(event_type)

    return events


def build_calendar(events_by_ticker: dict[str, list[dict] | None],
                   today: date,
                   window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Merge per-ticker event rows into one sorted upcoming-events feed.

    ``today`` is a parameter (not ``date.today()``) so tests are deterministic.
    A ticker mapping to None (fetch failed) or [] (nothing published) is
    reported in ``tickers_with_no_data`` rather than dropped silently.
    """
    horizon = today + timedelta(days=window_days)
    seen: set[tuple] = set()
    events: list[dict] = []
    no_data: list[str] = []

    for ticker in sorted(events_by_ticker):
        rows = events_by_ticker[ticker]
        if not rows:
            no_data.append(ticker)
            continue
        for row in rows:
            try:
                d = date.fromisoformat(row["date"])
            except (KeyError, TypeError, ValueError):
                continue
            key = (row.get("ticker", ticker), row.get("type"), row["date"])
            if key in seen or not today <= d <= horizon:
                continue
            seen.add(key)
            events.append({
                "ticker": row.get("ticker", ticker),
                "type": row.get("type"),
                "label": EVENT_LABELS.get(row.get("type"), row.get("type")),
                "date": row["date"],
                "days_until": (d - today).days,
                "estimate": bool(row.get("estimate")),
            })

    events.sort(key=lambda e: (e["date"], e["ticker"]))
    return {
        "as_of": today.isoformat(),
        "window_days": window_days,
        "events": events,
        "tickers_checked": sorted(events_by_ticker),
        "tickers_with_no_data": no_data,
    }

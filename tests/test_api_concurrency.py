"""
Tests for the parallelised per-ticker endpoints.

Goals:
  1. Response shape & ordering preserved after the serial→concurrent refactor.
  2. One failing ticker still returns a None/error fallback while others succeed.
  3. Calls actually run concurrently: wall-clock for 5 slow tickers < serial sum.
"""

import time
import pytest
from fastapi.testclient import TestClient


# ── fixtures ──────────────────────────────────────────────────────────────────

POSITIONS = [
    {"id": 1, "ticker": "AAPL", "shares": 10.0, "average_buy_price": 150.0, "date_added": "2024-01-01"},
    {"id": 2, "ticker": "MSFT", "shares": 5.0,  "average_buy_price": 300.0, "date_added": "2024-01-02"},
    {"id": 3, "ticker": "NVDA", "shares": 2.0,  "average_buy_price": 500.0, "date_added": "2024-01-03"},
]

WATCHLIST_ROWS = [
    {"ticker": "GOOGL", "date_added": "2024-02-01"},
    {"ticker": "AMZN",  "date_added": "2024-02-02"},
    {"ticker": "TSLA",  "date_added": "2024-02-03"},
]

FAKE_INDICATORS = {
    "latest_close": 200.0,
    "sma50": 195.0,
}

FAKE_FUNDAMENTALS = {
    "profile": {"name": "Fake Corp", "sector": "Technology"},
    "price": {"current": 200.0},
    "valuation": {
        "trailing_pe": 25.0,
        "fair_value": {"estimate": 210.0, "upside_pct": 5.0, "verdict": "Fairly valued"},
    },
    "dividends": {"yield_pct": 1.5},
}


@pytest.fixture()
def client(monkeypatch, tmp_db):
    """TestClient with DB and external calls monkeypatched."""
    monkeypatch.setattr("core.db_manager.get_all_positions", lambda: POSITIONS)
    monkeypatch.setattr("core.db_manager.get_watchlist",     lambda: WATCHLIST_ROWS)
    monkeypatch.setattr(
        "core.quant_engine.extract_quant_indicators",
        lambda ticker: FAKE_INDICATORS,
    )
    monkeypatch.setattr(
        "core.fundamentals_engine.extract_fundamentals",
        lambda ticker: FAKE_FUNDAMENTALS,
    )
    # Also patch the names imported directly into main
    import main as app_module
    monkeypatch.setattr(app_module, "get_all_positions",        lambda: POSITIONS)
    monkeypatch.setattr(app_module, "get_watchlist",            lambda: WATCHLIST_ROWS)
    monkeypatch.setattr(app_module, "extract_quant_indicators", lambda ticker: FAKE_INDICATORS)
    monkeypatch.setattr(app_module, "extract_fundamentals",     lambda ticker: FAKE_FUNDAMENTALS)

    from main import app
    return TestClient(app)


# ── shape & ordering ──────────────────────────────────────────────────────────

def test_enriched_returns_all_positions_in_order(client):
    resp = client.get("/api/portfolio/enriched")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    assert [r["ticker"] for r in rows] == ["AAPL", "MSFT", "NVDA"]


def test_enriched_row_keys(client):
    row = client.get("/api/portfolio/enriched").json()[0]
    for key in ("ticker", "shares", "average_buy_price", "current_price",
                "current_value", "unrealised_pnl", "return_pct"):
        assert key in row


def test_enriched_computes_pnl_correctly(client):
    rows = client.get("/api/portfolio/enriched").json()
    aapl = rows[0]
    assert aapl["current_price"] == 200.0
    assert aapl["current_value"] == round(200.0 * 10.0, 2)
    assert aapl["unrealised_pnl"] == round((200.0 - 150.0) * 10.0, 2)
    assert aapl["return_pct"] == round((200.0 / 150.0 - 1) * 100, 2)


def test_watchlist_enriched_returns_all_rows_in_order(client):
    resp = client.get("/api/watchlist/enriched")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    assert [r["ticker"] for r in rows] == ["GOOGL", "AMZN", "TSLA"]


def test_watchlist_enriched_row_keys(client):
    row = client.get("/api/watchlist/enriched").json()[0]
    for key in ("ticker", "name", "sector", "price", "trailing_pe",
                "dividend_yield_pct", "fair_value", "upside_pct", "verdict", "date_added"):
        assert key in row


def test_portfolio_insights_returns_dict(client):
    resp = client.get("/api/portfolio/insights")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# ── graceful degradation ──────────────────────────────────────────────────────

def test_enriched_one_bad_ticker_returns_none_fallback(client, monkeypatch):
    """If one ticker fails, its row is all-None; the others still succeed."""
    call_count = {"n": 0}

    def flaky_indicators(ticker):
        call_count["n"] += 1
        if ticker == "MSFT":
            raise ValueError("no data")
        return FAKE_INDICATORS

    import main as app_module
    monkeypatch.setattr(app_module, "extract_quant_indicators", flaky_indicators)

    rows = client.get("/api/portfolio/enriched").json()

    assert rows[0]["current_price"] == 200.0  # AAPL ok
    assert rows[1]["current_price"] is None    # MSFT failed → None
    assert rows[2]["current_price"] == 200.0  # NVDA ok
    assert call_count["n"] == 3               # all three were attempted


def test_watchlist_enriched_one_bad_ticker_returns_none_fallback(client, monkeypatch):
    def flaky_fundamentals(ticker):
        if ticker == "AMZN":
            raise ValueError("no data")
        return FAKE_FUNDAMENTALS

    import main as app_module
    monkeypatch.setattr(app_module, "extract_fundamentals", flaky_fundamentals)

    rows = client.get("/api/watchlist/enriched").json()

    assert rows[0]["price"] == 200.0  # GOOGL ok
    assert rows[1]["price"] is None   # AMZN failed → None
    assert rows[2]["price"] == 200.0  # TSLA ok


# ── concurrency proof ─────────────────────────────────────────────────────────

def test_enriched_runs_concurrently(client, monkeypatch):
    """5 tickers each sleeping 0.3 s should finish well under 1.5 s serial sum."""
    slow_positions = [
        {"id": i, "ticker": t, "shares": 1.0, "average_buy_price": 100.0, "date_added": "2024-01-01"}
        for i, t in enumerate(["A", "B", "C", "D", "E"], start=1)
    ]

    def slow_indicators(ticker):
        time.sleep(0.3)
        return FAKE_INDICATORS

    import main as app_module
    monkeypatch.setattr(app_module, "get_all_positions",        lambda: slow_positions)
    monkeypatch.setattr(app_module, "extract_quant_indicators", slow_indicators)

    t0 = time.monotonic()
    resp = client.get("/api/portfolio/enriched")
    elapsed = time.monotonic() - t0

    assert resp.status_code == 200
    assert len(resp.json()) == 5
    # Serial would be 5 × 0.3 = 1.5 s; concurrent should be ~0.3–0.5 s.
    assert elapsed < 1.0, f"Expected concurrent execution but took {elapsed:.2f}s"

"""
Tests for the parallelised per-ticker endpoints.

Goals:
  1. Response shape & ordering preserved after the serial→concurrent refactor.
  2. One failing ticker still returns a None/error fallback while others succeed.
  3. Calls actually run concurrently: wall-clock for 5 slow tickers < serial sum.
"""

import time
import pandas as pd
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


# ── /api/compare ──────────────────────────────────────────────────────────────

def test_compare_returns_metric_rows(client):
    resp = client.get("/api/compare?tickers=AAPL,MSFT")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tickers"] == ["AAPL", "MSFT"]
    keys = {m["key"] for m in data["metrics"]}
    assert {"price", "trailing_pe", "dividend_yield_pct", "verdict"} <= keys
    price_row = next(m for m in data["metrics"] if m["key"] == "price")
    assert price_row["values"] == {"AAPL": 200.0, "MSFT": 200.0}


def test_compare_dedupes_and_uppercases(client):
    resp = client.get("/api/compare?tickers=aapl, AAPL , msft")
    assert resp.status_code == 200
    assert resp.json()["tickers"] == ["AAPL", "MSFT"]


def test_compare_rejects_single_ok_but_too_many_fails(client):
    resp = client.get("/api/compare?tickers=A,B,C,D,E")
    assert resp.status_code == 400


def test_compare_empty_is_rejected(client):
    resp = client.get("/api/compare?tickers=%20%2C%20")  # " , "
    assert resp.status_code == 400


# ── /api/portfolio/risk ───────────────────────────────────────────────────────

def _synthetic_close(_ticker, _period="1y"):
    idx = pd.bdate_range(start="2023-01-02", periods=120)
    # Deterministic gentle uptrend with oscillation, never flat.
    prices = [100 * (1 + 0.001 * i + 0.01 * ((-1) ** i)) for i in range(len(idx))]
    return pd.Series(prices, index=idx)


def test_portfolio_risk_route(client, monkeypatch):
    import main as app_module
    monkeypatch.setattr(app_module, "_close_series", _synthetic_close)

    resp = client.get("/api/portfolio/risk")
    assert resp.status_code == 200
    data = resp.json()
    assert data["benchmark"] == "SPY"
    assert {p["ticker"] for p in data["positions"]} == {"AAPL", "MSFT", "NVDA"}
    for key in ("annual_volatility_pct", "sharpe_ratio", "max_drawdown_pct", "beta"):
        assert key in data
    assert len(data["correlation"]["matrix"]) == 3


def test_portfolio_risk_empty_portfolio(client, monkeypatch):
    import main as app_module
    monkeypatch.setattr(app_module, "get_all_positions", lambda: [])
    resp = client.get("/api/portfolio/risk")
    assert resp.status_code == 200
    assert resp.json()["positions"] == []


# ── /api/portfolio/montecarlo ────────────────────────────────────────────────

def test_montecarlo_route(client, monkeypatch):
    import main as app_module
    monkeypatch.setattr(app_module, "_close_series", _synthetic_close)

    resp = client.get("/api/portfolio/montecarlo?years=2&simulations=100&contribution=50")
    assert resp.status_code == 200
    data = resp.json()
    assert data["years"] == 2
    assert data["simulations"] == 100
    assert data["monthly_contribution"] == 50.0
    assert set(data["bands"]) == {"p5", "p25", "p50", "p75", "p95"}
    assert len(data["dates"]) == len(data["bands"]["p50"]) > 0
    assert data["summary"]["median_terminal_value"] is not None


def test_montecarlo_params_clamped(client):
    assert client.get("/api/portfolio/montecarlo?simulations=999999").status_code == 400
    assert client.get("/api/portfolio/montecarlo?years=0").status_code == 400
    assert client.get("/api/portfolio/montecarlo?contribution=-1").status_code == 400


def test_montecarlo_empty_portfolio(client, monkeypatch):
    import main as app_module
    monkeypatch.setattr(app_module, "get_all_positions", lambda: [])
    resp = client.get("/api/portfolio/montecarlo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dates"] == []
    assert data["summary"]["median_terminal_value"] is None


# ── /api/portfolio/targets + /api/portfolio/rebalance ───────────────────────

def test_put_and_get_targets_roundtrip(client):
    resp = client.put("/api/portfolio/targets", json={
        "targets": [{"ticker": "aapl", "target_pct": 60.0},
                    {"ticker": "MSFT", "target_pct": 40.0}],
    })
    assert resp.status_code == 200
    saved = client.get("/api/portfolio/targets").json()
    assert [(r["ticker"], r["target_pct"]) for r in saved] == [("AAPL", 60.0), ("MSFT", 40.0)]


def test_put_targets_bad_sum_rejected(client):
    resp = client.put("/api/portfolio/targets", json={
        "targets": [{"ticker": "AAPL", "target_pct": 50.0},
                    {"ticker": "MSFT", "target_pct": 30.0}],
    })
    assert resp.status_code == 422


def test_put_targets_duplicate_ticker_rejected(client):
    resp = client.put("/api/portfolio/targets", json={
        "targets": [{"ticker": "AAPL", "target_pct": 50.0},
                    {"ticker": "aapl", "target_pct": 50.0}],
    })
    assert resp.status_code == 422


def test_put_targets_empty_list_clears(client):
    client.put("/api/portfolio/targets", json={
        "targets": [{"ticker": "AAPL", "target_pct": 100.0}],
    })
    resp = client.put("/api/portfolio/targets", json={"targets": []})
    assert resp.status_code == 200
    assert client.get("/api/portfolio/targets").json() == []


def test_rebalance_route(client, monkeypatch):
    import main as app_module
    monkeypatch.setattr(app_module, "_latest_price", lambda t: 200.0)

    client.put("/api/portfolio/targets", json={
        "targets": [{"ticker": "AAPL", "target_pct": 50.0},
                    {"ticker": "MSFT", "target_pct": 50.0}],
    })
    resp = client.get("/api/portfolio/rebalance?cash=1000")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cash"] == 1000.0
    tickers = {r["ticker"] for r in data["rows"]}
    # Union of held (AAPL/MSFT/NVDA fixtures) and targeted tickers.
    assert tickers == {"AAPL", "MSFT", "NVDA"}
    nvda = next(r for r in data["rows"] if r["ticker"] == "NVDA")
    assert nvda["target_pct"] == 0.0
    assert nvda["action"] == "SELL"
    for key in ("current_pct", "drift_pct", "shares_delta", "value_delta"):
        assert key in data["rows"][0]


def test_rebalance_no_targets_returns_empty_plan(client):
    resp = client.get("/api/portfolio/rebalance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rows"] == []
    assert data["warnings"] == ["No target allocations set."]


def test_rebalance_negative_cash_rejected(client):
    resp = client.get("/api/portfolio/rebalance?cash=-5")
    assert resp.status_code == 400


# ── /api/calendar ─────────────────────────────────────────────────────────────

def test_calendar_route_unions_portfolio_and_watchlist(client, monkeypatch):
    from datetime import date, timedelta
    import main as app_module
    monkeypatch.setattr(app_module, "_CAL_CACHE", {})

    soon = (date.today() + timedelta(days=10)).isoformat()

    def fake_events(ticker):
        if ticker == "TSLA":
            return None  # simulate a failed fetch
        return [{"ticker": ticker, "type": "earnings", "date": soon, "estimate": False}]

    monkeypatch.setattr(app_module, "_safe_calendar_events", fake_events)

    resp = client.get("/api/calendar")
    assert resp.status_code == 200
    data = resp.json()
    # Union of POSITIONS (AAPL/MSFT/NVDA) and WATCHLIST_ROWS (GOOGL/AMZN/TSLA).
    assert data["tickers_checked"] == ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA", "TSLA"]
    assert data["tickers_with_no_data"] == ["TSLA"]
    assert len(data["events"]) == 5
    assert all(e["days_until"] == 10 for e in data["events"])
    assert data["events"] == sorted(data["events"], key=lambda e: (e["date"], e["ticker"]))


def test_calendar_route_empty_universe(client, monkeypatch):
    import main as app_module
    monkeypatch.setattr(app_module, "get_all_positions", lambda: [])
    monkeypatch.setattr(app_module, "get_watchlist", lambda: [])
    resp = client.get("/api/calendar")
    assert resp.status_code == 200
    data = resp.json()
    assert data["events"] == []
    assert data["tickers_checked"] == []


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

# ── ticker normalization ──────────────────────────────────────────────────────

def test_post_transaction_lowercase_ticker(tmp_db):
    """POST /api/transactions with a lowercase ticker stores it uppercased."""
    import main as app_module
    from fastapi.testclient import TestClient
    client = TestClient(app_module.app)
    resp = client.post("/api/transactions", json={
        "ticker": "aapl", "side": "BUY", "shares": 1.0, "price": 150.0,
    })
    assert resp.status_code == 201
    txs = client.get("/api/transactions?ticker=AAPL").json()
    assert len(txs) == 1
    assert txs[0]["ticker"] == "AAPL"


def test_get_transactions_lowercase_filter(tmp_db):
    """GET /api/transactions?ticker=googl (lowercase) returns the same rows as GOOGL."""
    import main as app_module
    from fastapi.testclient import TestClient
    client = TestClient(app_module.app)
    client.post("/api/transactions", json={
        "ticker": "GOOGL", "side": "BUY", "shares": 2.0, "price": 180.0,
    })
    resp = client.get("/api/transactions?ticker=googl")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


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


# ── input validation (transaction & position write paths) ─────────────────────

def test_transaction_nan_shares_rejected():
    """NaN slips past a plain ``<= 0`` check — the schema validator must reject it.

    Tested at the model layer: JSON has no NaN literal, so a non-standard client
    is the only way NaN reaches the field, and FastAPI can't echo NaN back into a
    422 body — but the validator logic is what guards the DB, so assert it directly.
    """
    from pydantic import ValidationError
    from main import TransactionIn

    with pytest.raises(ValidationError):
        TransactionIn(ticker="AAPL", side="BUY", shares=float("nan"), price=100.0)


def test_transaction_negative_shares_rejected(client):
    resp = client.post(
        "/api/transactions",
        json={"ticker": "AAPL", "side": "BUY", "shares": -5.0, "price": 100.0},
    )
    assert resp.status_code == 422


def test_transaction_zero_price_rejected(client):
    resp = client.post(
        "/api/transactions",
        json={"ticker": "AAPL", "side": "BUY", "shares": 5.0, "price": 0.0},
    )
    assert resp.status_code == 422


def test_transaction_negative_fee_rejected(client):
    resp = client.post(
        "/api/transactions",
        json={"ticker": "AAPL", "side": "BUY", "shares": 5.0, "price": 100.0, "fee": -1.0},
    )
    assert resp.status_code == 422


def test_transaction_future_date_rejected(client):
    resp = client.post(
        "/api/transactions",
        json={"ticker": "AAPL", "side": "BUY", "shares": 5.0, "price": 100.0, "trade_date": "2999-01-01"},
    )
    assert resp.status_code == 422


def test_valid_transaction_accepted(client):
    """Regression guard: a clean BUY still records (201)."""
    resp = client.post(
        "/api/transactions",
        json={"ticker": "AAPL", "side": "BUY", "shares": 5.0, "price": 100.0},
    )
    assert resp.status_code == 201


def test_position_infinite_shares_rejected():
    """Inf must be rejected by the PositionIn schema (asserted at the model layer)."""
    from pydantic import ValidationError
    from main import PositionIn

    with pytest.raises(ValidationError):
        PositionIn(ticker="AAPL", shares=float("inf"), average_buy_price=100.0)


def test_position_negative_price_rejected(client):
    resp = client.post(
        "/api/portfolio",
        json={"ticker": "AAPL", "shares": 5.0, "average_buy_price": -100.0},
    )
    assert resp.status_code == 422

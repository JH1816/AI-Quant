"""Tests for the pure portfolio risk engine."""

import numpy as np
import pandas as pd
import pytest

from core.risk_engine import compute_portfolio_risk, _empty_result


def _price_series(start, daily_returns, start_date="2023-01-02"):
    """Build a close-price Series from a list of daily simple returns."""
    idx = pd.bdate_range(start=start_date, periods=len(daily_returns) + 1)
    prices = [start]
    for r in daily_returns:
        prices.append(prices[-1] * (1 + r))
    return pd.Series(prices, index=idx)


@pytest.fixture()
def two_asset_portfolio():
    rng = np.random.default_rng(42)
    n = 252
    a = _price_series(100.0, rng.normal(0.0005, 0.01, n))
    b = _price_series(200.0, rng.normal(0.0003, 0.015, n))
    bench = _price_series(400.0, rng.normal(0.0004, 0.009, n))
    positions = [
        {"ticker": "AAA", "shares": 10.0},
        {"ticker": "BBB", "shares": 5.0},
    ]
    close_by_ticker = {"AAA": a, "BBB": b}
    return positions, close_by_ticker, bench


def test_empty_positions_returns_empty_shape():
    res = compute_portfolio_risk([], {}, None, "SPY")
    assert res == _empty_result("SPY")
    assert res["positions"] == []
    assert res["correlation"]["matrix"] == []


def test_basic_metrics_present_and_typed(two_asset_portfolio):
    positions, close_by_ticker, bench = two_asset_portfolio
    res = compute_portfolio_risk(positions, close_by_ticker, bench, "SPY")

    for key in ("annual_return_pct", "annual_volatility_pct", "sharpe_ratio",
                "sortino_ratio", "max_drawdown_pct", "beta"):
        assert res[key] is not None
        assert isinstance(res[key], (int, float))

    assert res["benchmark"] == "SPY"
    assert res["observations"] > 200
    assert res["annual_volatility_pct"] > 0
    # Drawdown is a peak-to-trough decline → non-positive.
    assert res["max_drawdown_pct"] <= 0


def test_weights_sum_to_100(two_asset_portfolio):
    positions, close_by_ticker, bench = two_asset_portfolio
    res = compute_portfolio_risk(positions, close_by_ticker, bench, "SPY")
    total_weight = sum(p["weight_pct"] for p in res["positions"])
    assert total_weight == pytest.approx(100.0, abs=0.1)


def test_correlation_matrix_is_square_with_unit_diagonal(two_asset_portfolio):
    positions, close_by_ticker, bench = two_asset_portfolio
    res = compute_portfolio_risk(positions, close_by_ticker, bench, "SPY")
    tickers = res["correlation"]["tickers"]
    matrix = res["correlation"]["matrix"]
    assert len(matrix) == len(tickers)
    for i, row in enumerate(matrix):
        assert len(row) == len(tickers)
        assert row[i] == pytest.approx(1.0, abs=1e-6)


def test_self_correlation_of_one_asset_is_one():
    s = _price_series(100.0, [0.01, -0.02, 0.03, -0.01, 0.005] * 20)
    res = compute_portfolio_risk(
        [{"ticker": "AAA", "shares": 1.0}], {"AAA": s}, None, "SPY"
    )
    assert res["correlation"]["matrix"] == [[1.0]]
    # No benchmark supplied → beta is None.
    assert res["beta"] is None


def test_beta_against_self_is_one():
    """A single-asset portfolio benchmarked against itself has beta ≈ 1."""
    s = _price_series(100.0, [0.01, -0.02, 0.03, -0.01, 0.005] * 20)
    res = compute_portfolio_risk(
        [{"ticker": "AAA", "shares": 1.0}], {"AAA": s}, s, "AAA"
    )
    assert res["beta"] == pytest.approx(1.0, abs=1e-6)


def test_ticker_without_price_data_is_excluded():
    s = _price_series(100.0, [0.01, -0.01] * 60)
    positions = [
        {"ticker": "AAA", "shares": 1.0},
        {"ticker": "ZZZ", "shares": 1.0},  # no series
    ]
    res = compute_portfolio_risk(positions, {"AAA": s}, None, "SPY")
    tickers = [p["ticker"] for p in res["positions"]]
    assert tickers == ["AAA"]

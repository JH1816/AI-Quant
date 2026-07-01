"""Tests for the pure Monte Carlo projection engine."""

import numpy as np
import pandas as pd
import pytest

from core.monte_carlo import (
    simulate_portfolio, portfolio_daily_returns, _empty_result,
    MIN_OBSERVATIONS, MAX_CHART_POINTS, PERCENTILES,
)


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
    positions = [
        {"ticker": "AAA", "shares": 10.0},
        {"ticker": "BBB", "shares": 5.0},
    ]
    return positions, {"AAA": a, "BBB": b}


def _run(two_asset_portfolio, **kwargs):
    positions, close_by_ticker = two_asset_portfolio
    defaults = dict(years=5, simulations=200, seed=7, start_date="2026-07-01")
    defaults.update(kwargs)
    return simulate_portfolio(positions, close_by_ticker, **defaults)


def test_same_seed_is_deterministic(two_asset_portfolio):
    assert _run(two_asset_portfolio) == _run(two_asset_portfolio)


def test_different_seed_changes_paths(two_asset_portfolio):
    a = _run(two_asset_portfolio, seed=1)
    b = _run(two_asset_portfolio, seed=2)
    assert a["bands"]["p50"] != b["bands"]["p50"]


def test_bands_ordered_at_every_point(two_asset_portfolio):
    res = _run(two_asset_portfolio)
    b = res["bands"]
    for i in range(len(res["dates"])):
        assert b["p5"][i] <= b["p25"][i] <= b["p50"][i] <= b["p75"][i] <= b["p95"][i]


def test_dates_and_bands_aligned_and_ascending(two_asset_portfolio):
    res = _run(two_asset_portfolio)
    assert len(res["dates"]) >= 2
    for key in res["bands"]:
        assert len(res["bands"][key]) == len(res["dates"])
    assert res["dates"] == sorted(res["dates"])
    assert len(set(res["dates"])) == len(res["dates"])
    assert res["dates"][0] == "2026-07-01"


def test_long_horizon_downsampled_for_chart(two_asset_portfolio):
    res = _run(two_asset_portfolio, years=40)  # 481 monthly points raw
    assert len(res["dates"]) <= MAX_CHART_POINTS
    # The terminal point is always kept.
    assert res["dates"][-1] == "2066-07-01"


def test_all_paths_start_at_portfolio_value(two_asset_portfolio):
    positions, close_by_ticker = two_asset_portfolio
    start_value, _ = portfolio_daily_returns(positions, close_by_ticker)
    res = _run(two_asset_portfolio)
    for p in PERCENTILES:
        assert res["bands"][f"p{p}"][0] == pytest.approx(start_value, rel=1e-6)


def test_contribution_increases_terminal_and_invested(two_asset_portfolio):
    base = _run(two_asset_portfolio, monthly_contribution=0.0)
    plus = _run(two_asset_portfolio, monthly_contribution=500.0)
    assert plus["summary"]["total_invested"] > base["summary"]["total_invested"]
    assert plus["summary"]["median_terminal_value"] > base["summary"]["median_terminal_value"]
    assert plus["summary"]["total_invested"] == pytest.approx(
        base["summary"]["total_invested"] + 500.0 * 5 * 12
    )


def test_summary_percentiles_consistent(two_asset_portfolio):
    s = _run(two_asset_portfolio)["summary"]
    assert s["p5_terminal_value"] <= s["median_terminal_value"] <= s["p95_terminal_value"]
    assert 0.0 <= s["prob_loss_pct"] <= 100.0
    assert s["median_cagr_pct"] is not None


def test_empty_positions_return_empty_shape():
    res = simulate_portfolio([], {}, years=10, simulations=200)
    assert res == _empty_result(10, 200)
    assert res["dates"] == []
    assert res["summary"]["median_terminal_value"] is None


def test_ticker_without_series_is_ignored():
    s = _price_series(100.0, [0.01, -0.01] * 60)
    positions = [
        {"ticker": "AAA", "shares": 1.0},
        {"ticker": "ZZZ", "shares": 1.0},  # no series
    ]
    res = simulate_portfolio(positions, {"AAA": s}, years=2, simulations=100, seed=1)
    assert res["start_value"] == pytest.approx(float(s.iloc[-1]), abs=0.01)


def test_too_few_observations_returns_empty_shape():
    s = _price_series(100.0, [0.01] * (MIN_OBSERVATIONS - 2))
    res = simulate_portfolio([{"ticker": "AAA", "shares": 1.0}], {"AAA": s},
                             years=5, simulations=100)
    assert res["observations"] == 0
    assert res["bands"]["p50"] == []


def test_zero_volatility_series_has_no_nans():
    """A flat price history keeps every path exactly at start value (+ contributions)."""
    s = _price_series(100.0, [0.0] * 100)
    res = simulate_portfolio([{"ticker": "AAA", "shares": 2.0}], {"AAA": s},
                             years=3, simulations=100, seed=1,
                             monthly_contribution=10.0, start_date="2026-07-01")
    for key, series in res["bands"].items():
        assert all(v is not None for v in series), key
    assert res["bands"]["p50"][-1] == pytest.approx(200.0 + 10.0 * 36, rel=1e-9)
    # Every simulation ends exactly at invested value → "loss" is never strict.
    assert res["summary"]["prob_loss_pct"] == 0.0

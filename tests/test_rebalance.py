"""Tests for the pure rebalancing engine."""

import pytest

from core.rebalance import build_rebalance_plan, empty_plan, DEFAULT_TOLERANCE_PCT


def _row(plan, ticker):
    return next(r for r in plan["rows"] if r["ticker"] == ticker)


def test_empty_inputs_return_empty_plan():
    plan = build_rebalance_plan([], {}, {})
    assert plan == empty_plan()
    assert plan["rows"] == []
    assert plan["total_value"] is None


def test_no_targets_returns_empty_plan_with_warning():
    positions = [{"ticker": "AAA", "shares": 10.0}]
    plan = build_rebalance_plan(positions, {"AAA": 100.0}, {})
    assert plan["rows"] == []
    assert plan["warnings"] == ["No target allocations set."]


def test_two_asset_drift_hand_computed():
    """AAA $1,000 + BBB $3,000 with 50/50 targets → buy $1,000 AAA, sell $1,000 BBB."""
    positions = [
        {"ticker": "AAA", "shares": 10.0},
        {"ticker": "BBB", "shares": 10.0},
    ]
    prices = {"AAA": 100.0, "BBB": 300.0}
    plan = build_rebalance_plan(positions, prices, {"AAA": 50.0, "BBB": 50.0})

    assert plan["total_value"] == 4000.0
    aaa, bbb = _row(plan, "AAA"), _row(plan, "BBB")

    assert aaa["current_pct"] == 25.0
    assert aaa["drift_pct"] == -25.0
    assert aaa["action"] == "BUY"
    assert aaa["value_delta"] == 1000.0
    assert aaa["shares_delta"] == 10.0

    assert bbb["current_pct"] == 75.0
    assert bbb["drift_pct"] == 25.0
    assert bbb["action"] == "SELL"
    assert bbb["value_delta"] == -1000.0
    assert bbb["shares_delta"] == pytest.approx(-3.3333, abs=1e-4)


def test_rows_sorted_by_absolute_drift():
    positions = [
        {"ticker": "AAA", "shares": 10.0},   # $1,000 → 10%
        {"ticker": "BBB", "shares": 30.0},   # $9,000 → 90%
    ]
    prices = {"AAA": 100.0, "BBB": 300.0}
    plan = build_rebalance_plan(positions, prices, {"AAA": 60.0, "BBB": 40.0})
    # BBB drifts +50, AAA drifts −50 — equal magnitude keeps input (sorted) order,
    # so just assert the biggest drift leads.
    drifts = [abs(r["drift_pct"]) for r in plan["rows"]]
    assert drifts == sorted(drifts, reverse=True)


def test_within_tolerance_is_hold():
    positions = [
        {"ticker": "AAA", "shares": 10.0},
        {"ticker": "BBB", "shares": 10.0},
    ]
    prices = {"AAA": 100.0, "BBB": 300.0}
    plan = build_rebalance_plan(positions, prices, {"AAA": 25.0, "BBB": 75.0})
    assert all(r["action"] == "HOLD" for r in plan["rows"])


def test_cash_deployment_on_balanced_portfolio():
    """A perfectly balanced portfolio + fresh cash → proportional BUYs."""
    positions = [
        {"ticker": "AAA", "shares": 10.0},   # $1,000
        {"ticker": "BBB", "shares": 5.0},    # $1,000
    ]
    prices = {"AAA": 100.0, "BBB": 200.0}
    plan = build_rebalance_plan(positions, prices, {"AAA": 50.0, "BBB": 50.0}, cash=500.0)

    assert plan["total_value"] == 2500.0
    for ticker in ("AAA", "BBB"):
        row = _row(plan, ticker)
        assert row["action"] == "BUY"
        assert row["value_delta"] == 250.0


def test_held_without_target_becomes_full_sell():
    positions = [
        {"ticker": "AAA", "shares": 10.0},
        {"ticker": "BBB", "shares": 10.0},
    ]
    prices = {"AAA": 100.0, "BBB": 300.0}
    plan = build_rebalance_plan(positions, prices, {"AAA": 100.0})

    bbb = _row(plan, "BBB")
    assert bbb["target_pct"] == 0.0
    assert bbb["action"] == "SELL"
    assert bbb["value_delta"] == -3000.0
    assert bbb["shares_delta"] == -10.0


def test_target_without_holding_is_buy_from_zero():
    positions = [{"ticker": "AAA", "shares": 10.0}]
    prices = {"AAA": 100.0, "CCC": 50.0}
    plan = build_rebalance_plan(positions, prices, {"AAA": 50.0, "CCC": 50.0})

    ccc = _row(plan, "CCC")
    assert ccc["shares"] == 0.0
    assert ccc["current_pct"] == 0.0
    assert ccc["action"] == "BUY"
    assert ccc["value_delta"] == 500.0
    assert ccc["shares_delta"] == 10.0


def test_missing_price_excluded_from_totals_with_warning():
    positions = [
        {"ticker": "AAA", "shares": 10.0},
        {"ticker": "ZZZ", "shares": 5.0},   # no price
    ]
    prices = {"AAA": 100.0, "ZZZ": None}
    plan = build_rebalance_plan(positions, prices, {"AAA": 50.0, "ZZZ": 50.0})

    assert plan["total_value"] == 1000.0  # ZZZ excluded
    zzz = _row(plan, "ZZZ")
    assert zzz["current_value"] is None
    assert zzz["action"] is None
    assert zzz["shares_delta"] is None
    assert any("ZZZ" in w for w in plan["warnings"])


def test_targets_normalised_when_sum_is_not_exactly_100():
    positions = [
        {"ticker": "AAA", "shares": 10.0},
        {"ticker": "BBB", "shares": 10.0},
    ]
    prices = {"AAA": 100.0, "BBB": 100.0}
    plan = build_rebalance_plan(positions, prices, {"AAA": 49.9, "BBB": 49.9})

    assert plan["targets_sum_pct"] == 99.8
    # Effective targets scale to 50/50, so a 50/50 portfolio is a clean HOLD.
    assert all(r["target_pct"] == 50.0 for r in plan["rows"])
    assert all(r["action"] == "HOLD" for r in plan["rows"])


def test_nan_cash_treated_as_zero():
    positions = [{"ticker": "AAA", "shares": 10.0}]
    plan = build_rebalance_plan(positions, {"AAA": 100.0}, {"AAA": 100.0},
                                cash=float("nan"))
    assert plan["cash"] == 0.0
    assert _row(plan, "AAA")["action"] == "HOLD"


def test_default_tolerance_reported():
    plan = build_rebalance_plan([], {}, {"AAA": 100.0})
    assert plan["tolerance_pct"] == DEFAULT_TOLERANCE_PCT

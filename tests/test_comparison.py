"""Tests for the pure multi-ticker comparison builder."""

from core.comparison import build_comparison


def _fund(name, **over):
    """Minimal fundamentals dict with overridable leaf values."""
    base = {
        "profile": {"name": name},
        "price": {"current": 100.0, "market_cap": 1e12, "beta": 1.1},
        "valuation": {
            "trailing_pe": 25.0, "forward_pe": 20.0, "peg_ratio": 1.5,
            "price_to_sales": 5.0, "price_to_book": 8.0, "ev_to_ebitda": 18.0,
            "fair_value": {"upside_pct": 5.0, "verdict": "Fairly valued"},
        },
        "profitability": {"profit_margin_pct": 20.0, "roe_pct": 30.0},
        "growth": {"revenue_growth_pct": 10.0},
        "dividends": {"yield_pct": 1.0},
    }
    for path, val in over.items():
        section, leaf = path.split(".")
        base[section][leaf] = val
    return base


def test_tickers_and_names_preserved_in_order():
    data = {"AAPL": _fund("Apple Inc."), "MSFT": _fund("Microsoft")}
    res = build_comparison(["AAPL", "MSFT"], data)
    assert res["tickers"] == ["AAPL", "MSFT"]
    assert res["names"] == {"AAPL": "Apple Inc.", "MSFT": "Microsoft"}


def test_best_low_metric_picks_smallest():
    data = {
        "AAPL": _fund("Apple", **{"valuation.trailing_pe": 30.0}),
        "MSFT": _fund("Microsoft", **{"valuation.trailing_pe": 20.0}),
    }
    res = build_comparison(["AAPL", "MSFT"], data)
    pe = next(m for m in res["metrics"] if m["key"] == "trailing_pe")
    assert pe["better"] == "low"
    assert pe["best"] == "MSFT"


def test_best_high_metric_picks_largest():
    data = {
        "AAPL": _fund("Apple", **{"profitability.roe_pct": 50.0}),
        "MSFT": _fund("Microsoft", **{"profitability.roe_pct": 30.0}),
    }
    res = build_comparison(["AAPL", "MSFT"], data)
    roe = next(m for m in res["metrics"] if m["key"] == "roe_pct")
    assert roe["best"] == "AAPL"


def test_missing_fundamentals_yields_none_values_and_no_best():
    data = {"AAPL": _fund("Apple"), "BAD": None}
    res = build_comparison(["AAPL", "BAD"], data)
    pe = next(m for m in res["metrics"] if m["key"] == "trailing_pe")
    assert pe["values"]["BAD"] is None
    assert pe["values"]["AAPL"] == 25.0
    assert pe["best"] == "AAPL"  # only AAPL is numeric
    assert res["names"]["BAD"] is None


def test_verdict_is_passed_through_as_text():
    data = {
        "AAPL": _fund("Apple"),
        "MSFT": _fund("Microsoft", **{"valuation.fair_value": {"verdict": "Undervalued", "upside_pct": 12.0}}),
    }
    res = build_comparison(["AAPL", "MSFT"], data)
    verdict = next(m for m in res["metrics"] if m["key"] == "verdict")
    assert verdict["format"] == "text"
    assert verdict["values"]["MSFT"] == "Undervalued"
    assert verdict["best"] is None  # text rows have no winner

from core.portfolio_insights import build_portfolio_insights


def _fund(price, sector, rate):
    return {
        "price": {"current": price},
        "profile": {"sector": sector},
        "dividends": {"rate": rate},
    }


POSITIONS = [
    {"ticker": "AAA", "shares": 10},   # $100 -> $1000, $2/sh div -> $20
    {"ticker": "BBB", "shares": 5},    # $200 -> $1000, no dividend
    {"ticker": "CCC", "shares": 20},   # $50  -> $1000, $1/sh div -> $20
]
DATA = {
    "AAA": _fund(100.0, "Technology", 2.0),
    "BBB": _fund(200.0, "Technology", None),
    "CCC": _fund(50.0, "Energy", 1.0),
}


def test_total_value():
    r = build_portfolio_insights(POSITIONS, DATA)
    assert r["total_value"] == 3000.0


def test_annual_and_monthly_income():
    r = build_portfolio_insights(POSITIONS, DATA)
    assert r["annual_dividend_income"] == 40.0
    assert r["monthly_dividend_income"] == round(40.0 / 12, 2)


def test_portfolio_yield():
    r = build_portfolio_insights(POSITIONS, DATA)
    # 40 / 3000 = 1.33%
    assert r["portfolio_yield_pct"] == 1.33


def test_sector_allocation_grouped_and_sorted():
    r = build_portfolio_insights(POSITIONS, DATA)
    alloc = r["sector_allocation"]
    assert alloc[0]["sector"] == "Technology"  # largest first
    assert alloc[0]["value"] == 2000.0
    assert alloc[0]["pct"] == round(2000 / 3000 * 100, 2)
    energy = next(a for a in alloc if a["sector"] == "Energy")
    assert energy["value"] == 1000.0


def test_income_by_ticker_excludes_zero_and_sorted():
    r = build_portfolio_insights(POSITIONS, DATA)
    tickers = [i["ticker"] for i in r["income_by_ticker"]]
    assert "BBB" not in tickers           # no dividend
    assert set(tickers) == {"AAA", "CCC"}


def test_missing_fundamentals_marked_unknown():
    positions = [{"ticker": "ZZZ", "shares": 3}]
    r = build_portfolio_insights(positions, {"ZZZ": None})
    assert r["total_value"] == 0.0
    assert r["portfolio_yield_pct"] is None
    assert r["positions"][0]["current_value"] is None
    assert r["positions"][0]["sector"] is None


def test_unknown_sector_bucket():
    positions = [{"ticker": "QQQ", "shares": 1}]
    data = {"QQQ": _fund(100.0, None, None)}
    r = build_portfolio_insights(positions, data)
    assert r["sector_allocation"][0]["sector"] == "Unknown"


def test_etf_without_sector_bucketed_as_fund():
    """An ETF (no GICS sector) should label as 'ETF / Fund', not 'Unknown'."""
    positions = [{"ticker": "VWRA", "shares": 1}]
    data = {"VWRA": {
        "price": {"current": 100.0},
        "profile": {"sector": None, "quote_type": "ETF"},
        "dividends": {"rate": None},
    }}
    r = build_portfolio_insights(positions, data)
    assert r["sector_allocation"][0]["sector"] == "ETF / Fund"


def test_equity_without_sector_still_unknown():
    """A throttled equity (no sector, quoteType EQUITY) stays 'Unknown'."""
    positions = [{"ticker": "MSFT", "shares": 1}]
    data = {"MSFT": {
        "price": {"current": 100.0},
        "profile": {"sector": None, "quote_type": "EQUITY"},
        "dividends": {"rate": None},
    }}
    r = build_portfolio_insights(positions, data)
    assert r["sector_allocation"][0]["sector"] == "Unknown"


def test_empty_portfolio():
    r = build_portfolio_insights([], {})
    assert r["total_value"] == 0.0
    assert r["annual_dividend_income"] == 0.0
    assert r["portfolio_yield_pct"] is None
    assert r["sector_allocation"] == []

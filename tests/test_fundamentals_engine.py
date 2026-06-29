import pandas as pd
import pytest
from unittest.mock import patch

from core import fundamentals_engine as fe
from core.fundamentals_engine import (
    extract_fundamentals, _cagr, _pct, _series_by_year, _fair_value,
)


# ── Fakes ──────────────────────────────────────────────────────────────────────

def _stmt_df(rows: dict) -> pd.DataFrame:
    """Build a yfinance-style statement DataFrame (rows = line items,
    columns = most-recent-first reporting dates)."""
    cols = [pd.Timestamp("2023-12-31"), pd.Timestamp("2022-12-31"), pd.Timestamp("2021-12-31")]
    return pd.DataFrame(rows, index=cols).T


class FakeTicker:
    def __init__(self, *_args, **_kwargs):
        self.info = {
            "longName": "Acme Corp",
            "sector": "Technology",
            "industry": "Software",
            "currentPrice": 100.0,
            "marketCap": 1_000_000_000,
            "trailingPE": 25.0,
            "forwardPE": 20.0,
            "priceToBook": 8.0,
            "grossMargins": 0.55,
            "operatingMargins": 0.30,
            "profitMargins": 0.22,
            "returnOnEquity": 0.40,
            "revenueGrowth": 0.18,
            "dividendYield": 1.5,
            "dividendRate": 1.2,
            "payoutRatio": 0.25,
            "totalCash": 500_000_000,
            "totalDebt": 100_000_000,
            "debtToEquity": 40.0,
            "targetMeanPrice": 120.0,
            "recommendationKey": "buy",
            "numberOfAnalystOpinions": 30,
            "exDividendDate": 1_700_000_000,
            "trailingEps": 5.0,
            "earningsGrowth": 0.20,
            "fiveYearAvgDividendYield": 1.5,
        }
        self.income_stmt = _stmt_df({
            "Total Revenue": [300, 250, 200],
            "Net Income": [60, 45, 30],
            "Gross Profit": [165, 140, 110],
            "Operating Income": [90, 70, 50],
            "Diluted EPS": [6.0, 4.5, 3.0],
        })
        self.balance_sheet = _stmt_df({"Total Assets": [1000, 900, 800]})
        self.cashflow = _stmt_df({
            "Operating Cash Flow": [80, 65, 50],
            "Capital Expenditure": [-20, -15, -10],
        })
        self.dividends = pd.Series(
            [0.3, 0.3, 0.3, 0.3, 0.25, 0.25, 0.25, 0.25],
            index=pd.to_datetime([
                "2023-03-01", "2023-06-01", "2023-09-01", "2023-12-01",
                "2022-03-01", "2022-06-01", "2022-09-01", "2022-12-01",
            ]),
        )


@pytest.fixture()
def result():
    with patch.object(fe, "_get_ticker", return_value=FakeTicker()):
        return extract_fundamentals("acme")


# ── helper unit tests ───────────────────────────────────────────────────────────

def test_pct_converts_fraction():
    assert _pct(0.55) == 55.0
    assert _pct(None) is None


def test_cagr_basic():
    # 100 -> 200 -> 400 across 2 periods = doubling each year = 100% CAGR
    series = [{"year": "2021", "value": 100}, {"year": "2022", "value": 200},
              {"year": "2023", "value": 400}]
    assert _cagr(series) == 100.0


def test_cagr_needs_two_points():
    assert _cagr([{"year": "2023", "value": 100}]) is None


def test_series_by_year_sorted_oldest_first():
    df = _stmt_df({"Total Revenue": [300, 250, 200]})
    series = _series_by_year(df.loc["Total Revenue"])
    years = [p["year"] for p in series]
    assert years == sorted(years)
    assert series[0]["value"] == 200  # 2021 oldest


# ── extract_fundamentals ────────────────────────────────────────────────────────

def test_ticker_uppercased(result):
    assert result["ticker"] == "ACME"


def test_top_level_sections(result):
    for key in ("profile", "price", "valuation", "profitability", "growth",
                "health", "dividends", "analyst", "financials"):
        assert key in result


def test_profile_name(result):
    assert result["profile"]["name"] == "Acme Corp"


def test_margins_are_percentages(result):
    assert result["profitability"]["gross_margin_pct"] == 55.0
    assert result["profitability"]["profit_margin_pct"] == 22.0


def test_financial_series_oldest_first(result):
    rev = result["financials"]["revenue"]
    assert [p["value"] for p in rev] == [200, 250, 300]


def test_free_cash_flow_derived_from_capex(result):
    # FCF = OCF + capex (capex negative): 50-10, 65-15, 80-20
    fcf = {p["year"]: p["value"] for p in result["financials"]["free_cash_flow"]}
    assert fcf["2021"] == 40
    assert fcf["2023"] == 60


def test_net_margin_series(result):
    nm = {p["year"]: p["value"] for p in result["financials"]["net_margin"]}
    assert nm["2023"] == 20.0  # 60/300


def test_dividend_yield_pct_stored_as_is(result):
    # FakeTicker.dividendYield = 1.5 (already a percent from yfinance).
    # Must be stored as 1.5, NOT multiplied by 100 to 150.
    assert result["dividends"]["yield_pct"] == 1.5


def test_dividend_yield_pct_low_yield():
    """A sub-1% yield (e.g. AAPL ~0.36%) must not be multiplied by 100."""
    class LowYieldTicker(FakeTicker):
        def __init__(self):
            super().__init__()
            self.info = {**self.info, "dividendYield": 0.36}

    with patch.object(fe, "_get_ticker", return_value=LowYieldTicker()):
        r = extract_fundamentals("LOW")
    assert r["dividends"]["yield_pct"] == pytest.approx(0.36)


def test_dividend_history_aggregated_by_year(result):
    hist = {p["year"]: p["value"] for p in result["dividends"]["history"]}
    assert hist["2023"] == pytest.approx(1.2)
    assert hist["2022"] == pytest.approx(1.0)


def test_revenue_cagr_present(result):
    assert result["growth"]["revenue_cagr_pct"] is not None


# ── fair value ──────────────────────────────────────────────────────────────────

def test_fair_value_blends_three_methods(result):
    fv = result["valuation"]["fair_value"]
    assert fv is not None
    names = {m["name"] for m in fv["methods"]}
    assert names == {"Analyst target", "Growth (PEG=1)", "Dividend yield theory"}
    # (120 + 5*20 + 1.2/0.015) / 3 = (120 + 100 + 80) / 3 = 100
    assert fv["estimate"] == 100.0
    assert fv["upside_pct"] == 0.0
    assert fv["verdict"] == "Fairly valued"


def test_fair_value_undervalued_verdict():
    info = {"trailingEps": None}
    fv = _fair_value(info, price=80.0, dividends={}, analyst={"target_mean": 100.0},
                     growth_pct=None)
    assert fv["verdict"] == "Undervalued"
    assert fv["upside_pct"] == 25.0


def test_fair_value_overvalued_verdict():
    fv = _fair_value({"trailingEps": None}, price=200.0, dividends={},
                     analyst={"target_mean": 100.0}, growth_pct=None)
    assert fv["verdict"] == "Overvalued"


def test_fair_value_none_when_no_inputs():
    fv = _fair_value({"trailingEps": None}, price=100.0, dividends={},
                     analyst={}, growth_pct=None)
    assert fv is None


def test_fair_value_growth_pe_clamped():
    # 200% growth must be clamped to a 35 P/E, not used literally.
    fv = _fair_value({"trailingEps": 10.0}, price=100.0, dividends={},
                     analyst={}, growth_pct=200.0)
    assert fv["methods"][0]["value"] == 350.0  # 10 * 35 (clamp), not 10 * 200


def test_missing_info_raises():
    class Empty:
        info = {}
    with patch.object(fe, "_get_ticker", return_value=Empty()):
        with pytest.raises(ValueError, match="No fundamental data"):
            extract_fundamentals("FAKE")


# ── caching behaviour ────────────────────────────────────────────────────────────

class _MinimalTicker:
    """Name + price present, plus whatever extra info is passed in."""
    income_stmt = balance_sheet = cashflow = None
    dividends = None

    def __init__(self, **extra):
        self.info = {"longName": "Foo Inc", "currentPrice": 50.0, **extra}


def test_normal_equity_is_cached():
    fe._FUND_CACHE.clear()
    tk = _MinimalTicker(sector="Technology", quoteType="EQUITY")
    with patch.object(fe, "_get_ticker", return_value=tk):
        r = extract_fundamentals("CACHEME")
    assert r["profile"]["sector"] == "Technology"
    assert "CACHEME" in fe._FUND_CACHE


def test_partial_equity_not_cached():
    """A throttled response (name+price, no sector, EQUITY) must not poison the cache."""
    fe._FUND_CACHE.clear()
    tk = _MinimalTicker(quoteType="EQUITY")  # no sector
    with patch.object(fe, "_get_ticker", return_value=tk):
        r = extract_fundamentals("PARTIAL")
    assert r["profile"]["sector"] is None
    assert "PARTIAL" not in fe._FUND_CACHE


def test_etf_cached_and_quote_type_exposed():
    """ETFs legitimately have no sector — still cache them and expose quote_type."""
    fe._FUND_CACHE.clear()
    tk = _MinimalTicker(quoteType="ETF")  # no sector, but a fund
    with patch.object(fe, "_get_ticker", return_value=tk):
        r = extract_fundamentals("VWRA")
    assert r["profile"]["sector"] is None
    assert r["profile"]["quote_type"] == "ETF"
    assert "VWRA" in fe._FUND_CACHE

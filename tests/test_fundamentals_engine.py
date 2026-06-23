import pandas as pd
import pytest
from unittest.mock import patch

from core import fundamentals_engine as fe
from core.fundamentals_engine import extract_fundamentals, _cagr, _pct, _series_by_year


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


def test_dividend_history_aggregated_by_year(result):
    hist = {p["year"]: p["value"] for p in result["dividends"]["history"]}
    assert hist["2023"] == pytest.approx(1.2)
    assert hist["2022"] == pytest.approx(1.0)


def test_revenue_cagr_present(result):
    assert result["growth"]["revenue_cagr_pct"] is not None


def test_missing_info_raises():
    class Empty:
        info = {}
    with patch.object(fe, "_get_ticker", return_value=Empty()):
        with pytest.raises(ValueError, match="No fundamental data"):
            extract_fundamentals("FAKE")

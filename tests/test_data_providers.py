"""Tests for the pluggable market-data provider layer.

Everything here is offline: parsers are fed sample CSV/JSON text, and the
orchestration (provider selection + fallback chain) is exercised by patching the
provider registries, so no network or API key is required.
"""

import pandas as pd
import pytest

from core import data_providers as dp


# ── normalisation & period slicing ──────────────────────────────────────────

def test_normalize_flattens_multiindex_and_sorts():
    idx = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"])
    df = pd.DataFrame(
        {("Close", "AAPL"): [3.0, 1.0, 2.0], ("Open", "AAPL"): [3.0, 1.0, 2.0]},
        index=idx,
    )
    out = dp._normalize_ohlcv(df)
    assert list(out.columns) == ["Open", "Close"] or set(out.columns) == {"Open", "Close"}
    assert out.index.is_monotonic_increasing
    assert out["Close"].tolist() == [1.0, 2.0, 3.0]


def test_normalize_empty_without_close():
    df = pd.DataFrame({"Open": [1.0]}, index=pd.to_datetime(["2024-01-01"]))
    assert dp._normalize_ohlcv(df).empty


def test_normalize_none_returns_empty():
    assert dp._normalize_ohlcv(None).empty
    assert dp._normalize_ohlcv(pd.DataFrame()).empty


def test_slice_period_trims_to_window():
    idx = pd.date_range("2022-01-01", periods=800, freq="D")
    df = pd.DataFrame({"Close": range(800)}, index=idx)
    sliced = dp._slice_period(df, "1mo")
    span = (sliced.index.max() - sliced.index.min()).days
    assert span <= 31
    assert not sliced.empty


# ── Stooq ───────────────────────────────────────────────────────────────────

def test_stooq_symbol_appends_us():
    assert dp._stooq_symbol("AAPL") == "aapl.us"
    assert dp._stooq_symbol("BMW.DE") == "bmw.de"  # dotted symbols pass through


def test_parse_stooq_csv_ok():
    csv = (
        "Date,Open,High,Low,Close,Volume\n"
        "2024-01-02,10,12,9,11,1000\n"
        "2024-01-03,11,13,10,12,2000\n"
    )
    df = dp._parse_stooq_csv(csv)
    out = dp._normalize_ohlcv(df)
    assert out["Close"].tolist() == [11.0, 12.0]
    assert isinstance(out.index, pd.DatetimeIndex)


def test_parse_stooq_csv_no_data():
    assert dp._parse_stooq_csv("No data").empty
    assert dp._parse_stooq_csv("").empty


# ── Alpha Vantage parsing & mapping ─────────────────────────────────────────

def test_parse_av_daily():
    payload = {
        "Time Series (Daily)": {
            "2024-01-03": {"1. open": "11", "2. high": "13", "3. low": "10", "4. close": "12", "5. volume": "2000"},
            "2024-01-02": {"1. open": "10", "2. high": "12", "3. low": "9", "4. close": "11", "5. volume": "1000"},
        }
    }
    out = dp._normalize_ohlcv(dp._parse_av_daily(payload))
    assert out["Close"].tolist() == [11.0, 12.0]
    assert out["Volume"].tolist() == [1000.0, 2000.0]


def test_parse_av_daily_empty():
    assert dp._parse_av_daily({}).empty


def test_coerce_treats_placeholders_as_missing():
    assert dp._coerce("None", float) is None
    assert dp._coerce("-", float) is None
    assert dp._coerce("", float) is None
    assert dp._coerce("12.5", float) == 12.5


def test_av_overview_to_info_maps_and_scales_yield():
    overview = {
        "Name": "Apple Inc",
        "Sector": "Technology",
        "PERatio": "28.5",
        "ProfitMargin": "0.25",
        "DividendYield": "0.0055",  # decimal → engine wants already-percent
        "MarketCapitalization": "3000000000000",
    }
    info = dp._av_overview_to_info(overview)
    assert info["longName"] == "Apple Inc"
    assert info["shortName"] == "Apple Inc"
    assert info["sector"] == "Technology"
    assert info["trailingPE"] == 28.5
    assert info["profitMargins"] == 0.25            # decimal kept (engine *100 later)
    assert info["dividendYield"] == pytest.approx(0.55)  # 0.0055 * 100
    assert info["quoteType"] == "EQUITY"


def test_av_statement_df_signs_and_labels():
    reports = [
        {"fiscalDateEnding": "2023-12-31", "operatingCashflow": "1000", "capitalExpenditures": "200"},
        {"fiscalDateEnding": "2022-12-31", "operatingCashflow": "800", "capitalExpenditures": "150"},
    ]
    df = dp._av_statement_df(reports, dp._AV_CASHFLOW_MAP)
    assert "Operating Cash Flow" in df.index
    assert "Capital Expenditure" in df.index
    # capex is negated to match yfinance's negative-capex convention
    latest = df.columns.max()
    assert df.loc["Capital Expenditure", latest] == -200.0
    assert df.loc["Operating Cash Flow", latest] == 1000.0


# ── provider selection & fallback chain ─────────────────────────────────────

def test_provider_chain_from_env(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "stooq")
    monkeypatch.setenv("DATA_PROVIDER_FALLBACKS", "yahoo, stooq")  # stooq de-duped
    assert dp._provider_chain() == ["stooq", "yahoo"]


def test_provider_chain_defaults(monkeypatch):
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.delenv("DATA_PROVIDER_FALLBACKS", raising=False)
    assert dp._provider_chain() == ["yahoo", "stooq"]


def test_get_ohlcv_falls_back_when_primary_empty(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "yahoo")
    monkeypatch.setenv("DATA_PROVIDER_FALLBACKS", "stooq")
    good = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2024-01-01"]))
    monkeypatch.setitem(dp._OHLCV_PROVIDERS, "yahoo", lambda t, p: pd.DataFrame())
    monkeypatch.setitem(dp._OHLCV_PROVIDERS, "stooq", lambda t, p: good)
    out = dp.get_ohlcv("AAPL", "1y")
    assert out["Close"].tolist() == [1.0]


def test_get_ohlcv_falls_back_when_primary_raises(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "yahoo")
    monkeypatch.setenv("DATA_PROVIDER_FALLBACKS", "stooq")
    good = pd.DataFrame({"Close": [2.0]}, index=pd.to_datetime(["2024-01-01"]))

    def boom(t, p):
        raise dp.ProviderError("primary down")

    monkeypatch.setitem(dp._OHLCV_PROVIDERS, "yahoo", boom)
    monkeypatch.setitem(dp._OHLCV_PROVIDERS, "stooq", lambda t, p: good)
    assert dp.get_ohlcv("AAPL", "1y")["Close"].tolist() == [2.0]


def test_get_ohlcv_empty_when_all_fail(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "yahoo")
    monkeypatch.setenv("DATA_PROVIDER_FALLBACKS", "stooq")
    monkeypatch.setitem(dp._OHLCV_PROVIDERS, "yahoo", lambda t, p: pd.DataFrame())
    monkeypatch.setitem(dp._OHLCV_PROVIDERS, "stooq", lambda t, p: pd.DataFrame())
    assert dp.get_ohlcv("AAPL", "1y").empty


def test_alphavantage_ohlcv_unsupported_without_key(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(dp.ProviderUnsupported):
        dp._av_fetch({"function": "TIME_SERIES_DAILY", "symbol": "AAPL"})


def test_get_fundamentals_source_falls_back_to_yahoo(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "alphavantage")
    monkeypatch.setenv("DATA_PROVIDER_FALLBACKS", "yahoo")
    sentinel = object()

    def av_unsupported(t):
        raise dp.ProviderUnsupported("no key")

    monkeypatch.setitem(dp._FUNDAMENTALS_PROVIDERS, "alphavantage", av_unsupported)
    monkeypatch.setitem(dp._FUNDAMENTALS_PROVIDERS, "yahoo", lambda t: sentinel)
    assert dp.get_fundamentals_source("AAPL") is sentinel

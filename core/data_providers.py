"""Pluggable market-data provider layer.

Centralises every outbound price / fundamentals call so the rest of the codebase
stays source-agnostic. The indicator, risk, chart and portfolio maths all consume
the normalised shapes produced here and never touch a vendor SDK directly.

Selection is driven by environment variables (read lazily, so tests can patch):

    DATA_PROVIDER            primary provider name              (default "yahoo")
    DATA_PROVIDER_FALLBACKS  comma-separated providers tried,    (default "stooq")
                             in order, when the primary yields nothing
    ALPHAVANTAGE_API_KEY     required only when "alphavantage" is selected

Two capabilities are exposed:

    get_ohlcv(ticker, period)        -> normalised OHLCV DataFrame (may be empty)
    get_fundamentals_source(ticker)  -> object exposing .info / .income_stmt /
                                        .balance_sheet / .cashflow / .dividends
                                        (the yfinance.Ticker duck-type the
                                        fundamentals engine already consumes)

Not every provider supports every capability (Stooq is price-only). A provider
that cannot serve a request raises ``ProviderUnsupported`` (or ``ProviderError``)
so the orchestrator falls through to the next provider in the chain.
"""

from __future__ import annotations

import io
import os
import json
import urllib.request

import pandas as pd

# ── Provider names ──────────────────────────────────────────────────────────
YAHOO = "yahoo"
STOOQ = "stooq"
ALPHAVANTAGE = "alphavantage"

# Generous look-back buffers (calendar days) for providers that return full
# history and must be sliced down to the requested window.
_PERIOD_DAYS = {"1mo": 31, "3mo": 93, "6mo": 186, "1y": 372, "2y": 744}

_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class ProviderError(RuntimeError):
    """A provider was asked for data it normally serves but the call failed."""


class ProviderUnsupported(ProviderError):
    """A provider does not implement the requested capability at all."""


# ── Config (read lazily so tests / .env reloads take effect) ────────────────

def _primary() -> str:
    return (os.getenv("DATA_PROVIDER") or YAHOO).strip().lower()


def _fallbacks() -> list[str]:
    raw = os.getenv("DATA_PROVIDER_FALLBACKS")
    if raw is None:
        raw = STOOQ
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _provider_chain() -> list[str]:
    """Primary provider followed by fallbacks, de-duplicated, order preserved."""
    return list(dict.fromkeys([_primary(), *_fallbacks()]))


def _av_key() -> str | None:
    key = os.getenv("ALPHAVANTAGE_API_KEY")
    return key.strip() if key and key.strip() else None


# ── Shared helpers ──────────────────────────────────────────────────────────

def _http_get(url: str, timeout: float = 15.0) -> str:
    """GET a URL and return the body text. Honours the environment's proxy."""
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Quant/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted hosts)
        return resp.read().decode("utf-8", errors="replace")


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce any provider frame to OHLCV columns on a sorted DatetimeIndex."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()].sort_index()
    keep = [c for c in _OHLCV_COLUMNS if c in df.columns]
    if "Close" not in keep:
        return pd.DataFrame()
    return df[keep].dropna(how="all")


def _slice_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Trim a full-history frame to the requested period window."""
    if df.empty:
        return df
    days = _PERIOD_DAYS.get(period, 372)
    cutoff = df.index.max() - pd.Timedelta(days=days)
    return df[df.index >= cutoff]


# ── Yahoo (yfinance) ────────────────────────────────────────────────────────
# Imported lazily inside the helpers so a missing/extra SDK never breaks import,
# and so test patches target this module's ``yf`` symbol.
import yfinance as yf  # noqa: E402


def _yahoo_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    return _normalize_ohlcv(df)


def _yahoo_fundamentals_source(ticker: str):
    return yf.Ticker(ticker)


# ── Stooq (keyless, price-only) ─────────────────────────────────────────────

def _stooq_symbol(ticker: str) -> str:
    """Stooq expects a market suffix; default plain US tickers to ``.us``."""
    t = ticker.strip().lower()
    return t if "." in t else f"{t}.us"


def _parse_stooq_csv(text: str) -> pd.DataFrame:
    """Parse a Stooq daily CSV body into an OHLCV frame (empty on 'No data')."""
    if not text:
        return pd.DataFrame()
    first = text.splitlines()[0] if text.splitlines() else ""
    if "Date" not in first:  # Stooq returns the literal "No data" on a miss
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(text))
    if "Date" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df.set_index("Date")


def _stooq_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    url = f"https://stooq.com/q/d/l/?s={_stooq_symbol(ticker)}&i=d"
    try:
        text = _http_get(url)
    except Exception as exc:  # network/HTTP failure → let the chain continue
        raise ProviderError(f"Stooq fetch failed for {ticker}: {exc}") from exc
    return _slice_period(_normalize_ohlcv(_parse_stooq_csv(text)), period)


# ── Alpha Vantage (keyed; prices + fundamentals) ────────────────────────────

_AV_BASE = "https://www.alphavantage.co/query"


def _av_fetch(params: dict) -> dict:
    key = _av_key()
    if not key:
        raise ProviderUnsupported("ALPHAVANTAGE_API_KEY is not set")
    query = "&".join(f"{k}={v}" for k, v in {**params, "apikey": key}.items())
    try:
        body = _http_get(f"{_AV_BASE}?{query}")
        data = json.loads(body)
    except Exception as exc:
        raise ProviderError(f"Alpha Vantage fetch failed: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("Alpha Vantage returned an unexpected payload")
    # Rate-limit / error envelopes come back 200-OK with a Note/Information key.
    if "Note" in data or "Information" in data or "Error Message" in data:
        raise ProviderError(data.get("Note") or data.get("Information") or data.get("Error Message"))
    return data


def _parse_av_daily(data: dict) -> pd.DataFrame:
    """Parse an Alpha Vantage TIME_SERIES_DAILY payload into an OHLCV frame."""
    series = data.get("Time Series (Daily)")
    if not isinstance(series, dict) or not series:
        return pd.DataFrame()
    rows = {
        pd.Timestamp(day): {
            "Open": float(v["1. open"]),
            "High": float(v["2. high"]),
            "Low": float(v["3. low"]),
            "Close": float(v["4. close"]),
            "Volume": float(v["5. volume"]),
        }
        for day, v in series.items()
    }
    return pd.DataFrame.from_dict(rows, orient="index")


def _alphavantage_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    outputsize = "full" if period in ("1y", "2y") else "compact"
    data = _av_fetch({"function": "TIME_SERIES_DAILY", "symbol": ticker, "outputsize": outputsize})
    return _slice_period(_normalize_ohlcv(_parse_av_daily(data)), period)


# Alpha Vantage OVERVIEW field → yfinance ``.info`` key the engine reads.
# Margins/ratios arrive as decimals (e.g. 0.21), matching yfinance's fraction
# convention so the engine's ``_pct`` helper works unchanged. DividendYield is
# the exception: it is mapped to the engine's already-percent convention below.
_AV_OVERVIEW_MAP = {
    "Name": ("longName", str),
    "Sector": ("sector", str),
    "Industry": ("industry", str),
    "Country": ("country", str),
    "Currency": ("currency", str),
    "Exchange": ("exchange", str),
    "Description": ("longBusinessSummary", str),
    "MarketCapitalization": ("marketCap", float),
    "EBITDA": ("ebitda", float),
    "PERatio": ("trailingPE", float),
    "ForwardPE": ("forwardPE", float),
    "PEGRatio": ("trailingPegRatio", float),
    "PriceToBookRatio": ("priceToBook", float),
    "PriceToSalesRatioTTM": ("priceToSalesTrailing12Months", float),
    "EVToEBITDA": ("enterpriseToEbitda", float),
    "EVToRevenue": ("enterpriseToRevenue", float),
    "EPS": ("trailingEps", float),
    "ProfitMargin": ("profitMargins", float),
    "OperatingMarginTTM": ("operatingMargins", float),
    "ReturnOnEquityTTM": ("returnOnEquity", float),
    "ReturnOnAssetsTTM": ("returnOnAssets", float),
    "RevenueTTM": ("totalRevenue", float),
    "DividendPerShare": ("dividendRate", float),
    "PayoutRatio": ("payoutRatio", float),
    "Beta": ("beta", float),
    "52WeekHigh": ("fiftyTwoWeekHigh", float),
    "52WeekLow": ("fiftyTwoWeekLow", float),
    "AnalystTargetPrice": ("targetMeanPrice", float),
}

# Alpha Vantage statement field → (engine row label, sign). yfinance reports
# capex negative; Alpha Vantage reports it positive, hence the -1.
_AV_INCOME_MAP = {
    "totalRevenue": ("Total Revenue", 1),
    "netIncome": ("Net Income", 1),
    "grossProfit": ("Gross Profit", 1),
    "operatingIncome": ("Operating Income", 1),
}
_AV_CASHFLOW_MAP = {
    "operatingCashflow": ("Operating Cash Flow", 1),
    "capitalExpenditures": ("Capital Expenditure", -1),
}


def _coerce(value, caster):
    """Cast an Alpha Vantage string field, treating 'None'/'-'/'' as missing."""
    if value in (None, "None", "-", ""):
        return None
    try:
        return caster(value)
    except (TypeError, ValueError):
        return None


def _av_overview_to_info(overview: dict) -> dict:
    info: dict = {}
    for av_key, (info_key, caster) in _AV_OVERVIEW_MAP.items():
        val = _coerce(overview.get(av_key), caster)
        if val is not None:
            info[info_key] = val
    info.setdefault("shortName", info.get("longName"))
    info["quoteType"] = "EQUITY"
    # DividendYield arrives as a decimal fraction; the engine expects an already
    # percent value for ``dividendYield``.
    dy = _coerce(overview.get("DividendYield"), float)
    if dy is not None:
        info["dividendYield"] = round(dy * 100, 4)
    return info


def _av_statement_df(reports: list[dict], field_map: dict) -> pd.DataFrame:
    """Build a yfinance-style statement frame (rows=line items, cols=periods)."""
    if not reports:
        return pd.DataFrame()
    cols: dict = {}
    for rpt in reports:
        ts = pd.Timestamp(rpt.get("fiscalDateEnding")) if rpt.get("fiscalDateEnding") else None
        if ts is None:
            continue
        col: dict = {}
        for av_field, (label, sign) in field_map.items():
            val = _coerce(rpt.get(av_field), float)
            if val is not None:
                col[label] = val * sign
        cols[ts] = col
    if not cols:
        return pd.DataFrame()
    # Columns most-recent first, like yfinance.
    return pd.DataFrame(cols).sort_index(axis=1, ascending=False)


class _AVFundamentalsSource:
    """Adapter exposing the yfinance.Ticker duck-type over Alpha Vantage.

    ``info`` is fetched eagerly so an empty/invalid symbol raises ``ProviderError``
    and the orchestrator can fall back to another provider. Statements are fetched
    lazily (the engine only touches them when it builds the multi-year series).
    """

    def __init__(self, ticker: str):
        overview = _av_fetch({"function": "OVERVIEW", "symbol": ticker})
        if not overview or not overview.get("Name"):
            raise ProviderError(f"Alpha Vantage has no fundamentals for {ticker}")
        self._ticker = ticker
        self.info = _av_overview_to_info(overview)

    @property
    def income_stmt(self) -> pd.DataFrame:
        data = _av_fetch({"function": "INCOME_STATEMENT", "symbol": self._ticker})
        return _av_statement_df(data.get("annualReports", []), _AV_INCOME_MAP)

    @property
    def balance_sheet(self) -> pd.DataFrame:
        return pd.DataFrame()  # health metrics come from OVERVIEW, not the statement

    @property
    def cashflow(self) -> pd.DataFrame:
        data = _av_fetch({"function": "CASH_FLOW", "symbol": self._ticker})
        return _av_statement_df(data.get("annualReports", []), _AV_CASHFLOW_MAP)

    @property
    def dividends(self) -> pd.Series:
        return pd.Series(dtype=float)  # Alpha Vantage has no free dividend history


def _alphavantage_fundamentals_source(ticker: str):
    return _AVFundamentalsSource(ticker)


# ── Registries & orchestration ──────────────────────────────────────────────

_OHLCV_PROVIDERS = {
    YAHOO: _yahoo_ohlcv,
    STOOQ: _stooq_ohlcv,
    ALPHAVANTAGE: _alphavantage_ohlcv,
}

_FUNDAMENTALS_PROVIDERS = {
    YAHOO: _yahoo_fundamentals_source,
    ALPHAVANTAGE: _alphavantage_fundamentals_source,
    # Stooq is price-only — intentionally absent.
}


def get_ohlcv(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Normalised OHLCV for ``ticker`` over ``period`` via the provider chain.

    Tries the configured primary provider, then each fallback, returning the first
    non-empty frame. Returns an empty DataFrame if every provider fails or has no
    data (callers already treat an empty frame as "no data").
    """
    for name in _provider_chain():
        fn = _OHLCV_PROVIDERS.get(name)
        if fn is None:
            continue
        try:
            df = fn(ticker, period)
        except ProviderError:
            continue
        except Exception:
            continue
        if df is not None and not df.empty:
            return df
    return pd.DataFrame()


def get_fundamentals_source(ticker: str):
    """A yfinance.Ticker-shaped source for ``ticker`` via the provider chain.

    A provider that can't serve fundamentals (e.g. Stooq, or Alpha Vantage with no
    API key / unknown symbol) raises and the chain falls through. Yahoo is lazy and
    never pre-validates, so it is the dependable last resort when listed.
    """
    last_exc: Exception | None = None
    for name in _provider_chain():
        fn = _FUNDAMENTALS_PROVIDERS.get(name)
        if fn is None:
            continue
        try:
            return fn(ticker)
        except Exception as exc:  # ProviderUnsupported / ProviderError / network
            last_exc = exc
            continue
    # Nothing in the chain could serve fundamentals — fall back to Yahoo so the
    # engine's own "no data" handling produces a clean error.
    if YAHOO not in _provider_chain():
        return _yahoo_fundamentals_source(ticker)
    if last_exc is not None:
        raise last_exc
    raise ProviderError(f"No fundamentals provider available for {ticker}")

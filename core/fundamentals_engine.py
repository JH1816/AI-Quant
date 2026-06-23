"""Fundamental-analysis data layer (Qualtrim-style).

Pulls company profile, valuation, profitability, dividend, balance-sheet and
multi-year financial-statement data from yfinance and normalises it into a flat,
JSON-serialisable dict for the frontend.

All maths/normalisation lives here so ``main.py`` stays thin. The numeric
sanitiser ``_safe`` is reused from ``quant_engine`` to avoid duplication.
"""

import time

import pandas as pd
import yfinance as yf

from core.quant_engine import _safe

# Fundamentals change slowly — cache for an hour, keyed by ticker.
_FUND_CACHE: dict = {}
_CACHE_TTL = 3600  # seconds


def _get_ticker(symbol: str) -> yf.Ticker:
    return yf.Ticker(symbol)


def _pick(info: dict, *keys):
    """Return the first present, non-None value among ``keys`` from ``info``."""
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return None


def _row(df: pd.DataFrame, *candidates) -> pd.Series | None:
    """Return the first matching row (by label) from a statement DataFrame.

    yfinance statement DataFrames are indexed by line-item name with one column
    per reporting period (most-recent first). Row labels vary, so we try several
    candidate names.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def _series_by_year(row: pd.Series | None) -> list[dict]:
    """Convert a statement row (Timestamp-indexed) into ``[{year, value}]``.

    Returned oldest→newest so the frontend can render left-to-right bar charts.
    """
    if row is None:
        return []
    out = []
    for ts, val in row.items():
        year = getattr(ts, "year", None)
        if year is None:
            try:
                year = pd.Timestamp(ts).year
            except Exception:
                continue
        v = _safe(val)
        if v is not None:
            out.append({"year": str(year), "value": v})
    out.sort(key=lambda d: d["year"])
    return out


def _pct(val):
    """yfinance margins/yields arrive as fractions; expose as percentages."""
    v = _safe(val)
    return round(v * 100, 2) if v is not None else None


def _cagr(series: list[dict]):
    """Compound annual growth rate (%) across a year series, or None."""
    pts = [p for p in series if p["value"] and p["value"] > 0]
    if len(pts) < 2:
        return None
    first, last = pts[0]["value"], pts[-1]["value"]
    periods = len(pts) - 1
    try:
        return round(((last / first) ** (1 / periods) - 1) * 100, 2)
    except (ValueError, ZeroDivisionError):
        return None


def _fair_value(info: dict, price, dividends: dict, analyst: dict, growth_pct):
    """Estimate fair value by blending several simple, transparent methods.

    Each method is only used when its inputs are present, so a non-dividend or
    loss-making company still gets an estimate from whatever applies. Returns a
    dict with the blended estimate, per-method breakdown and an over/under-valued
    verdict, or ``None`` when nothing can be computed.
    """
    methods: list[dict] = []

    eps_ttm = _safe(info.get("trailingEps"))

    # 1. Analyst consensus target.
    target = _safe(analyst.get("target_mean"))
    if target and target > 0:
        methods.append({"name": "Analyst target", "value": round(target, 2)})

    # 2. Growth-justified P/E (Peter Lynch / PEG≈1): fair P/E ≈ growth rate,
    #    clamped to a sane 8–35 band to avoid absurd outputs.
    if eps_ttm and eps_ttm > 0 and growth_pct and growth_pct > 0:
        fair_pe = min(max(growth_pct, 8), 35)
        methods.append({
            "name": "Growth (PEG=1)",
            "value": round(eps_ttm * fair_pe, 2),
        })

    # 3. Dividend yield theory: fair price = annual dividend ÷ 5y-average yield.
    rate = _safe(dividends.get("rate"))
    avg_yield = _safe(dividends.get("five_year_avg_yield_pct"))
    if rate and rate > 0 and avg_yield and avg_yield > 0:
        methods.append({
            "name": "Dividend yield theory",
            "value": round(rate / (avg_yield / 100), 2),
        })

    if not methods:
        return None

    estimate = round(sum(m["value"] for m in methods) / len(methods), 2)

    verdict, upside = None, None
    if price and price > 0:
        upside = round((estimate / price - 1) * 100, 1)
        if upside > 10:
            verdict = "Undervalued"
        elif upside < -10:
            verdict = "Overvalued"
        else:
            verdict = "Fairly valued"

    return {
        "estimate": estimate,
        "upside_pct": upside,
        "verdict": verdict,
        "methods": methods,
    }



def extract_fundamentals(ticker_symbol: str) -> dict:
    """Return a normalised fundamentals dict for ``ticker_symbol``."""
    ticker_symbol = ticker_symbol.upper()

    now = time.time()
    cached = _FUND_CACHE.get(ticker_symbol)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    tk = _get_ticker(ticker_symbol)

    info = {}
    try:
        info = tk.info or {}
    except Exception:
        info = {}

    if not info or _pick(info, "longName", "shortName") is None:
        raise ValueError(f"No fundamental data available for '{ticker_symbol}'")

    income = getattr(tk, "income_stmt", None)
    balance = getattr(tk, "balance_sheet", None)
    cashflow = getattr(tk, "cashflow", None)

    # ── Multi-year financial series ──────────────────────────────────────────
    revenue = _series_by_year(_row(income, "Total Revenue", "TotalRevenue"))
    net_income = _series_by_year(
        _row(income, "Net Income", "NetIncome", "Net Income Common Stockholders")
    )
    gross_profit = _series_by_year(_row(income, "Gross Profit", "GrossProfit"))
    operating_income = _series_by_year(
        _row(income, "Operating Income", "OperatingIncome")
    )
    eps = _series_by_year(_row(income, "Diluted EPS", "Basic EPS"))

    op_cf = _row(cashflow, "Operating Cash Flow", "Total Cash From Operating Activities")
    capex = _row(cashflow, "Capital Expenditure", "Capital Expenditures")
    fcf_row = _row(cashflow, "Free Cash Flow")
    if fcf_row is not None:
        free_cash_flow = _series_by_year(fcf_row)
    elif op_cf is not None and capex is not None:
        # FCF = operating cash flow + capex (capex is reported negative)
        free_cash_flow = _series_by_year(op_cf.add(capex, fill_value=0))
    else:
        free_cash_flow = _series_by_year(op_cf)

    # Net-margin series derived from revenue & net income (same years only)
    rev_by_year = {p["year"]: p["value"] for p in revenue}
    net_margin_series = [
        {"year": p["year"], "value": round(p["value"] / rev_by_year[p["year"]] * 100, 2)}
        for p in net_income
        if p["year"] in rev_by_year and rev_by_year[p["year"]]
    ]

    # ── Dividends ────────────────────────────────────────────────────────────
    div_history = []
    try:
        divs = tk.dividends
        if divs is not None and not divs.empty:
            by_year: dict[str, float] = {}
            for ts, amt in divs.items():
                yr = str(getattr(ts, "year", pd.Timestamp(ts).year))
                by_year[yr] = by_year.get(yr, 0.0) + float(amt)
            div_history = [
                {"year": y, "value": round(v, 4)} for y, v in sorted(by_year.items())
            ]
    except Exception:
        div_history = []

    div_yield = _pick(info, "dividendYield", "trailingAnnualDividendYield")
    # yfinance is inconsistent: dividendYield is sometimes already a percent.
    if div_yield is not None and div_yield > 1:
        div_yield = round(_safe(div_yield), 2)
    else:
        div_yield = _pct(div_yield)

    dividends = {
        "yield_pct": div_yield,
        "rate": _safe(_pick(info, "dividendRate", "trailingAnnualDividendRate")),
        "payout_ratio_pct": _pct(info.get("payoutRatio")),
        "five_year_avg_yield_pct": _safe(info.get("fiveYearAvgDividendYield")),
        "ex_dividend_date": _epoch_to_date(info.get("exDividendDate")),
        "history": div_history,
        "growth_5y_cagr_pct": _cagr(div_history[-6:]) if len(div_history) >= 2 else None,
    }

    # ── Fair value estimate ──────────────────────────────────────────────────
    current_price = _safe(_pick(info, "currentPrice", "regularMarketPrice"))
    analyst = {
        "target_mean": _safe(info.get("targetMeanPrice")),
        "target_high": _safe(info.get("targetHighPrice")),
        "target_low": _safe(info.get("targetLowPrice")),
        "recommendation": info.get("recommendationKey"),
        "num_analysts": info.get("numberOfAnalystOpinions"),
    }
    earnings_growth_pct = _pct(info.get("earningsGrowth"))
    fair_value = _fair_value(
        info, current_price, dividends, analyst,
        earnings_growth_pct if earnings_growth_pct else _cagr(net_income),
    )

    # ── Assemble ─────────────────────────────────────────────────────────────
    result = {
        "ticker": ticker_symbol,
        "profile": {
            "name": _pick(info, "longName", "shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "website": info.get("website"),
            "employees": info.get("fullTimeEmployees"),
            "summary": info.get("longBusinessSummary"),
            "currency": _pick(info, "financialCurrency", "currency"),
            "exchange": info.get("exchange"),
        },
        "price": {
            "current": current_price,
            "market_cap": _safe(info.get("marketCap")),
            "enterprise_value": _safe(info.get("enterpriseValue")),
            "beta": _safe(info.get("beta")),
            "week52_high": _safe(info.get("fiftyTwoWeekHigh")),
            "week52_low": _safe(info.get("fiftyTwoWeekLow")),
        },
        "valuation": {
            "trailing_pe": _safe(info.get("trailingPE")),
            "forward_pe": _safe(info.get("forwardPE")),
            "peg_ratio": _safe(_pick(info, "trailingPegRatio", "pegRatio")),
            "price_to_sales": _safe(info.get("priceToSalesTrailing12Months")),
            "price_to_book": _safe(info.get("priceToBook")),
            "ev_to_ebitda": _safe(info.get("enterpriseToEbitda")),
            "ev_to_revenue": _safe(info.get("enterpriseToRevenue")),
            "trailing_eps": _safe(info.get("trailingEps")),
            "fair_value": fair_value,
        },
        "profitability": {
            "gross_margin_pct": _pct(info.get("grossMargins")),
            "operating_margin_pct": _pct(info.get("operatingMargins")),
            "profit_margin_pct": _pct(info.get("profitMargins")),
            "roe_pct": _pct(info.get("returnOnEquity")),
            "roa_pct": _pct(info.get("returnOnAssets")),
        },
        "growth": {
            "revenue_growth_pct": _pct(info.get("revenueGrowth")),
            "earnings_growth_pct": earnings_growth_pct,
            "revenue_cagr_pct": _cagr(revenue),
            "net_income_cagr_pct": _cagr(net_income),
        },
        "health": {
            "total_cash": _safe(info.get("totalCash")),
            "total_debt": _safe(info.get("totalDebt")),
            "debt_to_equity": _safe(info.get("debtToEquity")),
            "current_ratio": _safe(info.get("currentRatio")),
            "quick_ratio": _safe(info.get("quickRatio")),
            "free_cash_flow": _safe(info.get("freeCashflow")),
        },
        "dividends": dividends,
        "analyst": analyst,
        "financials": {
            "revenue": revenue,
            "net_income": net_income,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "free_cash_flow": free_cash_flow,
            "eps": eps,
            "net_margin": net_margin_series,
        },
    }

    _FUND_CACHE[ticker_symbol] = (now, result)
    return result


def _epoch_to_date(epoch):
    """Convert a unix-epoch (seconds) field to an ISO date string, or None."""
    v = _safe(epoch)
    if v is None:
        return None
    try:
        return pd.Timestamp(int(v), unit="s").strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return None

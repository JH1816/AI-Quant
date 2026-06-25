"""Side-by-side multi-ticker comparison.

Pure, I/O-free transformation of per-ticker ``extract_fundamentals`` dicts into a
metric-row table (rows = metrics, columns = tickers) ready for the frontend. Each
row carries a ``better`` hint (``"high"``/``"low"``/``None``) and the ticker
holding the best value so the UI can highlight winners. Network lookups happen in
``main.py``; everything here is unit testable.
"""

from core.quant_engine import _safe


def _g(data, *path):
    """Safely walk a nested dict by ``path``, returning None if anything is missing."""
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


# (key, label, format, better-direction, getter)
#   format ∈ {money, compact, ratio, pct, text}
#   better ∈ {"high", "low", None}
_METRICS = [
    ("price",              "Price",            "money",   None,   lambda f: _g(f, "price", "current")),
    ("market_cap",         "Market Cap",       "compact", None,   lambda f: _g(f, "price", "market_cap")),
    ("trailing_pe",        "P/E (TTM)",        "ratio",   "low",  lambda f: _g(f, "valuation", "trailing_pe")),
    ("forward_pe",         "Forward P/E",      "ratio",   "low",  lambda f: _g(f, "valuation", "forward_pe")),
    ("peg_ratio",          "PEG",              "ratio",   "low",  lambda f: _g(f, "valuation", "peg_ratio")),
    ("price_to_sales",     "P/S",              "ratio",   "low",  lambda f: _g(f, "valuation", "price_to_sales")),
    ("price_to_book",      "P/B",              "ratio",   "low",  lambda f: _g(f, "valuation", "price_to_book")),
    ("ev_to_ebitda",       "EV/EBITDA",        "ratio",   "low",  lambda f: _g(f, "valuation", "ev_to_ebitda")),
    ("profit_margin_pct",  "Profit Margin",    "pct",     "high", lambda f: _g(f, "profitability", "profit_margin_pct")),
    ("roe_pct",            "ROE",              "pct",     "high", lambda f: _g(f, "profitability", "roe_pct")),
    ("revenue_growth_pct", "Revenue Growth",   "pct",     "high", lambda f: _g(f, "growth", "revenue_growth_pct")),
    ("dividend_yield_pct", "Dividend Yield",   "pct",     "high", lambda f: _g(f, "dividends", "yield_pct")),
    ("beta",               "Beta",             "ratio",   None,   lambda f: _g(f, "price", "beta")),
    ("fv_upside_pct",      "Fair-Value Upside","pct",     "high", lambda f: _g(f, "valuation", "fair_value", "upside_pct")),
    ("verdict",            "Verdict",          "text",    None,   lambda f: _g(f, "valuation", "fair_value", "verdict")),
]


def build_comparison(tickers: list[str], data_by_ticker: dict) -> dict:
    """Build a comparison table from ``ticker -> fundamentals`` (or None).

    ``tickers`` fixes the column order. Returns ``{tickers, names, metrics}``
    where each metric is ``{key, label, format, better, values, best}``.
    """
    names = {t: _g(data_by_ticker.get(t), "profile", "name") for t in tickers}

    metrics = []
    for key, label, fmt, better, getter in _METRICS:
        values: dict = {}
        for t in tickers:
            f = data_by_ticker.get(t)
            raw = getter(f) if f else None
            values[t] = raw if fmt == "text" else _safe(raw)

        best = None
        if better in ("high", "low"):
            numeric = {t: v for t, v in values.items() if isinstance(v, (int, float))}
            if numeric:
                best = (max if better == "high" else min)(numeric, key=numeric.get)

        metrics.append({
            "key": key,
            "label": label,
            "format": fmt,
            "better": better,
            "values": values,
            "best": best,
        })

    return {"tickers": tickers, "names": names, "metrics": metrics}

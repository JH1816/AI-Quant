"""Portfolio-level insight aggregation (Qualtrim-style).

Pure functions that turn per-position holdings plus per-ticker fundamentals into
portfolio roll-ups: total value, projected dividend income and sector allocation.
Kept free of I/O so it can be unit-tested without network access.
"""


def _num(val):
    """Return a finite float or None."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def build_portfolio_insights(positions: list[dict], data_by_ticker: dict) -> dict:
    """Aggregate holdings + fundamentals into portfolio insights.

    ``positions``      — rows from the DB (``ticker``, ``shares`` …).
    ``data_by_ticker`` — ``ticker -> extract_fundamentals(...) dict`` (or ``None``
                         when the lookup failed).
    """
    rows = []
    sector_values: dict[str, float] = {}
    total_value = 0.0
    annual_income = 0.0

    for pos in positions:
        ticker = pos["ticker"]
        shares = _num(pos.get("shares")) or 0.0
        f = data_by_ticker.get(ticker)

        price = sector = rate = None
        if f:
            price = _num(f.get("price", {}).get("current"))
            sector = f.get("profile", {}).get("sector")
            rate = _num(f.get("dividends", {}).get("rate"))

        value = round(price * shares, 2) if price is not None else None
        annual_div = round(rate * shares, 2) if rate is not None else 0.0
        yield_pct = (
            round(annual_div / value * 100, 2)
            if value and annual_div else (0.0 if value else None)
        )

        if value is not None:
            total_value += value
            bucket = sector or "Unknown"
            sector_values[bucket] = sector_values.get(bucket, 0.0) + value
        annual_income += annual_div

        rows.append({
            "ticker": ticker,
            "shares": shares,
            "sector": sector,
            "current_value": value,
            "annual_dividend": annual_div,
            "yield_pct": yield_pct,
        })

    total_value = round(total_value, 2)
    annual_income = round(annual_income, 2)

    sector_allocation = [
        {
            "sector": sector,
            "value": round(value, 2),
            "pct": round(value / total_value * 100, 2) if total_value else 0.0,
        }
        for sector, value in sector_values.items()
    ]
    sector_allocation.sort(key=lambda d: d["value"], reverse=True)

    income_by_ticker = sorted(
        [{"ticker": r["ticker"], "annual_dividend": r["annual_dividend"]}
         for r in rows if r["annual_dividend"]],
        key=lambda d: d["annual_dividend"], reverse=True,
    )

    return {
        "total_value": total_value,
        "annual_dividend_income": annual_income,
        "monthly_dividend_income": round(annual_income / 12, 2),
        "portfolio_yield_pct": round(annual_income / total_value * 100, 2) if total_value else None,
        "sector_allocation": sector_allocation,
        "income_by_ticker": income_by_ticker,
        "positions": rows,
    }

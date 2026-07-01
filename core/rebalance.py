"""Target-allocation drift and rebalancing suggestions.

Pure, I/O-free: takes stored positions, latest prices and target weights and
returns per-ticker drift plus the concrete BUY/SELL quantities that would
restore the target allocation (optionally deploying new cash). The
network/yfinance side lives in ``main.py``, so everything here is unit
testable with plain dicts.
"""

from core.quant_engine import _safe

DEFAULT_TOLERANCE_PCT = 1.0


def _round(val, ndigits: int = 2):
    """``round`` that first sanitises NaN/Inf to None (so it never raises)."""
    f = _safe(val)
    return round(f, ndigits) if f is not None else None


def empty_plan(cash: float = 0.0, warnings: list[str] | None = None) -> dict:
    """The response shape with nothing to compute (no targets / no holdings)."""
    return {
        "total_value": None,
        "cash": _round(cash),
        "tolerance_pct": DEFAULT_TOLERANCE_PCT,
        "targets_sum_pct": None,
        "rows": [],
        "warnings": warnings or [],
    }


def build_rebalance_plan(
    positions: list[dict],
    price_by_ticker: dict[str, float | None],
    targets: dict[str, float],
    cash: float = 0.0,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> dict:
    """Compute per-ticker drift vs target weights and the trades to fix it.

    ``positions``        — rows from the DB (``ticker``, ``shares`` …).
    ``price_by_ticker``  — ticker -> latest price (None when unavailable).
    ``targets``          — ticker -> target weight in percent.
    ``cash``             — new money to deploy; counted into the total so the
                           suggested BUYs absorb it proportionally.

    The universe is the union of held and targeted tickers: a holding without
    a target gets ``target_pct = 0`` (an explicit full-SELL suggestion) and a
    target without a holding is a BUY from zero. Targets are normalised to sum
    to exactly 100 so small rounding in user input doesn't skew the math.
    Holdings without a price are excluded from totals and flagged in
    ``warnings`` rather than silently mispricing the plan.
    """
    cash = _safe(cash) or 0.0
    warnings: list[str] = []

    shares_by_ticker = {p["ticker"]: _safe(p.get("shares")) or 0.0 for p in positions}
    raw_targets = {t: _safe(pct) or 0.0 for t, pct in targets.items()}
    targets_sum = sum(raw_targets.values())

    tickers = sorted(set(shares_by_ticker) | set(raw_targets))
    if not tickers or targets_sum <= 0:
        return empty_plan(cash, ["No target allocations set."] if tickers else None)

    scale = 100.0 / targets_sum
    eff_targets = {t: raw_targets.get(t, 0.0) * scale for t in tickers}

    # Current values; unpriced holdings can't be valued and are left out of totals.
    current_values: dict[str, float | None] = {}
    prices: dict[str, float | None] = {}
    for t in tickers:
        shares = shares_by_ticker.get(t, 0.0)
        price = _safe(price_by_ticker.get(t))
        price = price if price is not None and price > 0 else None
        prices[t] = price
        if shares > 0 and price is None:
            current_values[t] = None
            warnings.append(f"No price for {t}; excluded from totals.")
        else:
            current_values[t] = shares * price if price is not None else 0.0

    total_value = sum(v for v in current_values.values() if v is not None) + cash

    rows = []
    for t in tickers:
        shares = shares_by_ticker.get(t, 0.0)
        price = prices[t]
        cv = current_values[t]
        target_pct = eff_targets[t]

        if cv is None or total_value <= 0:
            rows.append({
                "ticker": t,
                "shares": _round(shares, 4),
                "price": None,
                "current_value": None,
                "current_pct": None,
                "target_pct": _round(target_pct),
                "drift_pct": None,
                "action": None,
                "shares_delta": None,
                "value_delta": None,
            })
            continue

        current_pct = cv / total_value * 100
        drift_pct = current_pct - target_pct
        value_delta = target_pct / 100 * total_value - cv
        shares_delta = _round(value_delta / price, 4) if price is not None else None
        if price is None and abs(drift_pct) > tolerance_pct:
            warnings.append(f"No price for {t}; cannot size the trade in shares.")

        if abs(drift_pct) <= tolerance_pct:
            action = "HOLD"
        else:
            action = "BUY" if value_delta > 0 else "SELL"

        rows.append({
            "ticker": t,
            "shares": _round(shares, 4),
            "price": _round(price),
            "current_value": _round(cv),
            "current_pct": _round(current_pct),
            "target_pct": _round(target_pct),
            "drift_pct": _round(drift_pct),
            "action": action,
            "shares_delta": shares_delta,
            "value_delta": _round(value_delta),
        })

    # Biggest imbalances first; unpriced rows sink to the bottom.
    rows.sort(key=lambda r: abs(r["drift_pct"]) if r["drift_pct"] is not None else -1,
              reverse=True)

    return {
        "total_value": _round(total_value),
        "cash": _round(cash),
        "tolerance_pct": tolerance_pct,
        "targets_sum_pct": _round(targets_sum),
        "rows": rows,
        "warnings": warnings,
    }

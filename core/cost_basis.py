"""Average-cost accounting engine (I/O-free, unit-tested).

Folds a chronological trade log into net holdings and realized P&L.
All maths lives here so db_manager stays thin and this can be tested
without a database.
"""


def compute_holding(trades: list[dict]) -> dict:
    """Fold BUY/SELL trades (oldest first) into a holding snapshot.

    Uses the average-cost method: a SELL realizes (sell_price − avg_cost) × qty
    and leaves the average cost of remaining shares unchanged.

    Returns:
        shares          — net open shares (0.0 if fully closed)
        average_buy_price — weighted average cost per share, or None if no open shares
        realized_pnl    — cumulative realized gain/loss (after fees)
    """
    qty = 0.0
    cost = 0.0
    realized = 0.0

    for t in trades:
        q = float(t["shares"])
        p = float(t["price"])
        fee = float(t.get("fee") or 0.0)
        if t["side"] == "BUY":
            qty += q
            cost += q * p + fee
        else:  # SELL
            avg = cost / qty if qty > 1e-9 else 0.0
            realized += (p - avg) * q - fee
            cost -= avg * q
            qty -= q

    avg_cost = round(cost / qty, 4) if qty > 1e-9 else None
    return {
        "shares": round(qty, 6),
        "average_buy_price": avg_cost,
        "realized_pnl": round(realized, 2),
    }


def derive_positions(trades_by_ticker: dict[str, list[dict]]) -> list[dict]:
    """Turn a per-ticker trade log into open holdings.

    ``trades_by_ticker`` maps ticker → list of trade dicts, oldest first.

    Returns one dict per ticker that still has open shares, with keys:
        ticker, shares, average_buy_price, realized_pnl, date_added
    Fully-closed tickers (shares ≈ 0) are excluded from the returned list.
    """
    positions = []
    for ticker, trades in trades_by_ticker.items():
        if not trades:
            continue
        holding = compute_holding(trades)
        if holding["shares"] < 1e-9:
            continue
        positions.append({
            "ticker": ticker,
            "shares": holding["shares"],
            "average_buy_price": holding["average_buy_price"],
            "realized_pnl": holding["realized_pnl"],
            "date_added": trades[0].get("trade_date", ""),
        })
    return positions

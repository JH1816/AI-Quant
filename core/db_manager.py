import sqlite3
import os
from datetime import datetime, timezone

from core.cost_basis import compute_holding

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.db")


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker            TEXT NOT NULL UNIQUE,
                shares            REAL NOT NULL,
                average_buy_price REAL NOT NULL,
                date_added        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL UNIQUE,
                date_added  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL,
                side        TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
                shares      REAL NOT NULL,
                price       REAL NOT NULL,
                fee         REAL NOT NULL DEFAULT 0,
                trade_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS target_allocations (
                ticker      TEXT PRIMARY KEY,
                target_pct  REAL NOT NULL CHECK (target_pct > 0 AND target_pct <= 100),
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # One-time migration: seed legacy portfolio rows as opening BUYs.
        tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        legacy = conn.execute(
            "SELECT ticker, shares, average_buy_price, date_added FROM portfolio"
        ).fetchall()
        if tx_count == 0 and legacy:
            conn.executemany(
                "INSERT INTO transactions (ticker, side, shares, price, fee, trade_date) "
                "VALUES (?, 'BUY', ?, ?, 0, ?)",
                [(r[0], r[1], r[2], r[3]) for r in legacy],
            )
            conn.commit()


# ── Transactions ─────────────────────────────────────────────────────────────

def add_transaction(ticker: str, side: str, shares: float, price: float,
                    fee: float = 0.0, trade_date: str | None = None) -> int:
    ticker = ticker.upper()
    side = side.upper()
    ts = trade_date or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO transactions (ticker, side, shares, price, fee, trade_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker, side, shares, price, fee, ts),
        )
        conn.commit()
        return cur.lastrowid


def get_transactions(ticker: str | None = None) -> list[dict]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        if ticker:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE ticker = ? ORDER BY trade_date DESC",
                (ticker.upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY trade_date DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def delete_transaction(tx_id: int):
    with _connect() as conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()


# ── Portfolio (derived from trade log) ───────────────────────────────────────

def get_all_positions() -> list[dict]:
    """Derive open holdings from the transaction log (average-cost method).

    Returns the same shape as before — ticker, shares, average_buy_price,
    date_added — plus realized_pnl, so downstream code is unchanged.
    """
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY ticker, trade_date ASC"
        ).fetchall()

    trades_by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        t = dict(r)
        trades_by_ticker.setdefault(t["ticker"], []).append(t)

    positions = []
    for ticker, trades in sorted(trades_by_ticker.items()):
        holding = compute_holding(trades)
        if holding["shares"] < 1e-9:
            continue
        positions.append({
            "id": hash(ticker) & 0x7FFFFFFF,
            "ticker": ticker,
            "shares": holding["shares"],
            "average_buy_price": holding["average_buy_price"],
            "realized_pnl": holding["realized_pnl"],
            "date_added": trades[0]["trade_date"],
        })

    return positions


def add_position(ticker: str, shares: float, price: float):
    """Thin wrapper — records a single BUY trade. Kept for backward compat."""
    add_transaction(ticker, "BUY", shares, price)


def remove_position(ticker: str):
    """Delete all trades for a ticker (closes and forgets the position)."""
    ticker = ticker.upper()
    with _connect() as conn:
        conn.execute("DELETE FROM transactions WHERE ticker = ?", (ticker,))
        conn.commit()


# ── Target allocations ────────────────────────────────────────────────────────

def get_target_allocations() -> list[dict]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, target_pct, updated_at FROM target_allocations ORDER BY ticker"
        ).fetchall()
    return [dict(r) for r in rows]


def set_target_allocations(targets: list[tuple[str, float]]):
    """Replace the full target set in one transaction (PUT semantics).

    Omitting a ticker deletes its target; an empty list clears all targets.
    """
    with _connect() as conn:
        conn.execute("DELETE FROM target_allocations")
        conn.executemany(
            "INSERT INTO target_allocations (ticker, target_pct) VALUES (?, ?)",
            [(t.upper(), pct) for t, pct in targets],
        )
        conn.commit()


# ── Watchlist ─────────────────────────────────────────────────────────────────

def add_to_watchlist(ticker: str):
    ticker = ticker.upper()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO watchlist (ticker) VALUES (?) ON CONFLICT(ticker) DO NOTHING",
            (ticker,),
        )
        conn.commit()


def remove_from_watchlist(ticker: str):
    ticker = ticker.upper()
    with _connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))
        conn.commit()


def get_watchlist() -> list[dict]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, ticker, date_added FROM watchlist ORDER BY date_added DESC"
        ).fetchall()
    return [dict(r) for r in rows]

import sqlite3
import os
from datetime import datetime

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
        conn.commit()


def add_position(ticker: str, shares: float, price: float):
    ticker = ticker.upper()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO portfolio (ticker, shares, average_buy_price)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                shares            = excluded.shares,
                average_buy_price = excluded.average_buy_price
        """, (ticker, shares, price))
        conn.commit()


def remove_position(ticker: str):
    ticker = ticker.upper()
    with _connect() as conn:
        conn.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker,))
        conn.commit()


def get_all_positions() -> list[dict]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, ticker, shares, average_buy_price, date_added FROM portfolio ORDER BY date_added DESC"
        ).fetchall()
    return [dict(r) for r in rows]

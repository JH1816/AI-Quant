import sqlite3
import pytest
import core.db_manager as dbm


def test_init_db_creates_table(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio'"
        ).fetchall()
    assert len(tables) == 1


def test_add_and_get_position(tmp_db):
    dbm.add_position("AAPL", 10.0, 175.50)
    positions = dbm.get_all_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"
    assert positions[0]["shares"] == 10.0
    assert positions[0]["average_buy_price"] == 175.50


def test_add_position_upserts(tmp_db):
    dbm.add_position("TSLA", 5.0, 200.0)
    dbm.add_position("TSLA", 8.0, 210.0)
    positions = dbm.get_all_positions()
    assert len(positions) == 1
    assert positions[0]["shares"] == 8.0
    assert positions[0]["average_buy_price"] == 210.0


def test_remove_position(tmp_db):
    dbm.add_position("MSFT", 3.0, 400.0)
    dbm.remove_position("MSFT")
    assert dbm.get_all_positions() == []


def test_remove_nonexistent_is_noop(tmp_db):
    dbm.remove_position("NONEXISTENT")  # should not raise


def test_ticker_is_uppercased(tmp_db):
    dbm.add_position("aapl", 1.0, 100.0)
    positions = dbm.get_all_positions()
    assert positions[0]["ticker"] == "AAPL"


def test_multiple_positions_returned(tmp_db):
    dbm.add_position("AAPL", 10.0, 175.0)
    dbm.add_position("GOOGL", 2.0, 180.0)
    positions = dbm.get_all_positions()
    tickers = {p["ticker"] for p in positions}
    assert tickers == {"AAPL", "GOOGL"}


# ── Watchlist ───────────────────────────────────────────────────────────────

def test_init_db_creates_watchlist_table(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='watchlist'"
        ).fetchall()
    assert len(tables) == 1


def test_add_and_get_watchlist(tmp_db):
    dbm.add_to_watchlist("nvda")
    items = dbm.get_watchlist()
    assert len(items) == 1
    assert items[0]["ticker"] == "NVDA"


def test_watchlist_add_is_idempotent(tmp_db):
    dbm.add_to_watchlist("AAPL")
    dbm.add_to_watchlist("AAPL")
    assert len(dbm.get_watchlist()) == 1


def test_remove_from_watchlist(tmp_db):
    dbm.add_to_watchlist("TSLA")
    dbm.remove_from_watchlist("tsla")
    assert dbm.get_watchlist() == []


def test_remove_nonexistent_watchlist_is_noop(tmp_db):
    dbm.remove_from_watchlist("NOPE")  # should not raise

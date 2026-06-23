import sqlite3
import pytest
import core.db_manager as dbm


# ── portfolio (derive-on-read) ─────────────────────────────────────────────────

def test_init_db_creates_tables(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert "portfolio" in tables
    assert "transactions" in tables
    assert "watchlist" in tables


def test_add_and_get_position(tmp_db):
    dbm.add_position("AAPL", 10.0, 175.50)
    positions = dbm.get_all_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"
    assert positions[0]["shares"] == pytest.approx(10.0)
    assert positions[0]["average_buy_price"] == pytest.approx(175.50)


def test_add_position_twice_accumulates_avg_cost(tmp_db):
    # Two BUYs → shares add up, avg cost blends (no overwrite).
    dbm.add_position("TSLA", 5.0, 200.0)
    dbm.add_position("TSLA", 5.0, 220.0)
    positions = dbm.get_all_positions()
    assert len(positions) == 1
    assert positions[0]["shares"] == pytest.approx(10.0)
    assert positions[0]["average_buy_price"] == pytest.approx(210.0)


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


def test_positions_include_realized_pnl(tmp_db):
    dbm.add_transaction("NVDA", "BUY", 10, 400.0)
    dbm.add_transaction("NVDA", "SELL", 5, 500.0)
    positions = dbm.get_all_positions()
    assert len(positions) == 1
    assert positions[0]["realized_pnl"] == pytest.approx(500.0)


def test_fully_closed_position_excluded(tmp_db):
    dbm.add_transaction("AMD", "BUY", 10, 100.0)
    dbm.add_transaction("AMD", "SELL", 10, 120.0)
    assert dbm.get_all_positions() == []


# ── transactions CRUD ──────────────────────────────────────────────────────────

def test_add_transaction_returns_id(tmp_db):
    tx_id = dbm.add_transaction("AAPL", "BUY", 5, 150.0)
    assert isinstance(tx_id, int) and tx_id > 0


def test_get_transactions_all(tmp_db):
    dbm.add_transaction("AAPL", "BUY", 10, 150.0)
    dbm.add_transaction("MSFT", "BUY", 5, 300.0)
    txs = dbm.get_transactions()
    assert len(txs) == 2


def test_get_transactions_filtered_by_ticker(tmp_db):
    dbm.add_transaction("AAPL", "BUY", 10, 150.0)
    dbm.add_transaction("MSFT", "BUY", 5, 300.0)
    txs = dbm.get_transactions("AAPL")
    assert len(txs) == 1
    assert txs[0]["ticker"] == "AAPL"


def test_delete_transaction(tmp_db):
    tx_id = dbm.add_transaction("GOOGL", "BUY", 3, 180.0)
    dbm.delete_transaction(tx_id)
    assert dbm.get_transactions("GOOGL") == []


def test_delete_transaction_recomputes_holding(tmp_db):
    dbm.add_transaction("KO", "BUY", 20, 60.0)
    tx_id = dbm.add_transaction("KO", "SELL", 20, 70.0)
    # After the SELL, position is fully closed
    assert dbm.get_all_positions() == []
    # Delete the SELL → position reopens
    dbm.delete_transaction(tx_id)
    positions = dbm.get_all_positions()
    assert len(positions) == 1
    assert positions[0]["shares"] == pytest.approx(20.0)


# ── migration ──────────────────────────────────────────────────────────────────

def test_legacy_portfolio_migrated_on_init(tmp_db):
    """Existing portfolio rows are seeded as BUY transactions on first init_db."""
    # Seed a legacy portfolio row directly (bypassing add_position)
    with sqlite3.connect(tmp_db) as conn:
        conn.execute(
            "INSERT INTO portfolio (ticker, shares, average_buy_price, date_added) "
            "VALUES ('LEGACY', 7.0, 55.0, '2023-01-01 00:00:00')"
        )
        conn.commit()

    # Re-run init_db — should migrate the row
    dbm.init_db()
    txs = dbm.get_transactions("LEGACY")
    assert len(txs) == 1
    assert txs[0]["side"] == "BUY"
    assert txs[0]["shares"] == pytest.approx(7.0)

    positions = dbm.get_all_positions()
    assert any(p["ticker"] == "LEGACY" for p in positions)


# ── Watchlist ─────────────────────────────────────────────────────────────────

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

import pytest
from core.cost_basis import compute_holding, derive_positions


def _trade(side, shares, price, fee=0.0, date="2024-01-01"):
    return {"side": side, "shares": shares, "price": price, "fee": fee, "trade_date": date}


# ── compute_holding ────────────────────────────────────────────────────────────

def test_single_buy():
    h = compute_holding([_trade("BUY", 10, 100)])
    assert h["shares"] == 10.0
    assert h["average_buy_price"] == pytest.approx(100.0)
    assert h["realized_pnl"] == 0.0


def test_two_buys_blends_average():
    trades = [_trade("BUY", 10, 100), _trade("BUY", 10, 120)]
    h = compute_holding(trades)
    assert h["shares"] == 20.0
    assert h["average_buy_price"] == pytest.approx(110.0)
    assert h["realized_pnl"] == 0.0


def test_partial_sell_realizes_gain():
    trades = [
        _trade("BUY", 10, 100),
        _trade("BUY", 10, 120),
        _trade("SELL", 5, 150),
    ]
    h = compute_holding(trades)
    assert h["shares"] == 15.0
    # avg cost stays 110 after the sell
    assert h["average_buy_price"] == pytest.approx(110.0)
    # (150 - 110) * 5 = 200
    assert h["realized_pnl"] == pytest.approx(200.0)


def test_sell_at_loss_realizes_negative():
    trades = [_trade("BUY", 10, 100), _trade("SELL", 10, 80)]
    h = compute_holding(trades)
    assert h["shares"] == pytest.approx(0.0, abs=1e-9)
    assert h["average_buy_price"] is None
    assert h["realized_pnl"] == pytest.approx(-200.0)


def test_fee_on_buy_increases_avg_cost():
    # BUY 10 @ 100 + $10 fee → cost basis = 1010, avg = 101
    h = compute_holding([_trade("BUY", 10, 100, fee=10)])
    assert h["average_buy_price"] == pytest.approx(101.0)


def test_fee_on_sell_reduces_realized():
    trades = [_trade("BUY", 10, 100), _trade("SELL", 10, 120, fee=5)]
    h = compute_holding(trades)
    # (120 - 100) * 10 - 5 = 195
    assert h["realized_pnl"] == pytest.approx(195.0)


def test_full_close_avg_cost_is_none():
    trades = [_trade("BUY", 5, 200), _trade("SELL", 5, 250)]
    h = compute_holding(trades)
    assert h["shares"] < 1e-9
    assert h["average_buy_price"] is None


def test_multiple_sells_cumulate_realized():
    trades = [
        _trade("BUY", 20, 50),
        _trade("SELL", 10, 60),   # realizes (60-50)*10 = 100
        _trade("SELL", 10, 70),   # realizes (70-50)*10 = 200
    ]
    h = compute_holding(trades)
    assert h["realized_pnl"] == pytest.approx(300.0)


def test_empty_trades():
    h = compute_holding([])
    assert h["shares"] == 0.0
    assert h["average_buy_price"] is None
    assert h["realized_pnl"] == 0.0


# ── derive_positions ───────────────────────────────────────────────────────────

def test_derive_positions_open_only():
    trades_by_ticker = {
        "AAPL": [_trade("BUY", 10, 100)],
        "MSFT": [_trade("BUY", 5, 200), _trade("SELL", 5, 220)],  # fully closed
    }
    positions = derive_positions(trades_by_ticker)
    tickers = [p["ticker"] for p in positions]
    assert "AAPL" in tickers
    assert "MSFT" not in tickers


def test_derive_positions_includes_realized_pnl():
    trades_by_ticker = {
        "KO": [_trade("BUY", 10, 50), _trade("SELL", 5, 70)],
    }
    positions = derive_positions(trades_by_ticker)
    assert len(positions) == 1
    assert positions[0]["realized_pnl"] == pytest.approx(100.0)


def test_derive_positions_date_added_is_first_trade():
    trades_by_ticker = {
        "T": [
            _trade("BUY", 5, 30, date="2023-06-01"),
            _trade("BUY", 5, 32, date="2024-01-15"),
        ],
    }
    pos = derive_positions(trades_by_ticker)[0]
    assert pos["date_added"] == "2023-06-01"

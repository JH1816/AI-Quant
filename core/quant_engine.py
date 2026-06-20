import math
import yfinance as yf
import pandas as pd
import pandas_ta as ta


def _safe(val):
    """Convert a scalar to float/int, returning None for NaN/Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def extract_quant_indicators(ticker_symbol: str) -> dict:
    ticker_symbol = ticker_symbol.upper()
    df = yf.download(ticker_symbol, period="1y", interval="1d", progress=False, auto_adjust=True)

    if df.empty:
        raise ValueError(f"No data returned for ticker '{ticker_symbol}'")

    # Flatten MultiIndex columns produced when auto_adjust=True
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    vol   = df["Volume"]

    # --- SMAs ---
    sma50  = ta.sma(close, length=50)
    sma100 = ta.sma(close, length=100)
    sma200 = ta.sma(close, length=200)

    # --- RSI ---
    rsi = ta.rsi(close, length=14)

    # --- MACD ---
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)

    # --- Bollinger Bands ---
    bb_df = ta.bbands(close, length=5, std=2.0)

    # --- Fibonacci Levels ---
    week52_high = _safe(high.max())
    week52_low  = _safe(low.min())
    diff = (week52_high or 0) - (week52_low or 0)
    fib_levels = {
        "0.0":   _safe(week52_low),
        "0.236": _safe((week52_low or 0) + 0.236 * diff),
        "0.382": _safe((week52_low or 0) + 0.382 * diff),
        "0.500": _safe((week52_low or 0) + 0.500 * diff),
        "0.618": _safe((week52_low or 0) + 0.618 * diff),
        "1.0":   _safe(week52_high),
    }

    # --- Volume vs 20-day MA ---
    vol_ma20   = _safe(vol.rolling(20).mean().iloc[-1])
    latest_vol = _safe(vol.iloc[-1])
    vol_ratio  = _safe(latest_vol / vol_ma20) if vol_ma20 else None

    # --- MACD component extraction ---
    macd_val    = None
    macd_signal = None
    macd_hist   = None
    if macd_df is not None and not macd_df.empty:
        cols = macd_df.columns.tolist()
        macd_col    = next((c for c in cols if c.startswith("MACD_") and "s" not in c.lower() and "h" not in c.lower()), None)
        signal_col  = next((c for c in cols if "MACDs" in c), None)
        hist_col    = next((c for c in cols if "MACDh" in c), None)
        macd_val    = _safe(macd_df[macd_col].iloc[-1])    if macd_col    else None
        macd_signal = _safe(macd_df[signal_col].iloc[-1])  if signal_col  else None
        macd_hist   = _safe(macd_df[hist_col].iloc[-1])    if hist_col    else None

    # --- BB component extraction ---
    bb_upper  = None
    bb_middle = None
    bb_lower  = None
    if bb_df is not None and not bb_df.empty:
        cols = bb_df.columns.tolist()
        upper_col  = next((c for c in cols if c.startswith("BBU")), None)
        mid_col    = next((c for c in cols if c.startswith("BBM")), None)
        lower_col  = next((c for c in cols if c.startswith("BBL")), None)
        bb_upper  = _safe(bb_df[upper_col].iloc[-1])  if upper_col  else None
        bb_middle = _safe(bb_df[mid_col].iloc[-1])    if mid_col    else None
        bb_lower  = _safe(bb_df[lower_col].iloc[-1])  if lower_col  else None

    latest_close = _safe(close.iloc[-1])

    return {
        "ticker":         ticker_symbol,
        "latest_close":   latest_close,
        "sma_50":         _safe(sma50.iloc[-1])  if sma50  is not None else None,
        "sma_100":        _safe(sma100.iloc[-1]) if sma100 is not None else None,
        "sma_200":        _safe(sma200.iloc[-1]) if sma200 is not None else None,
        "rsi_14":         _safe(rsi.iloc[-1])    if rsi    is not None else None,
        "macd": {
            "macd":   macd_val,
            "signal": macd_signal,
            "hist":   macd_hist,
        },
        "bollinger_bands": {
            "upper":  bb_upper,
            "middle": bb_middle,
            "lower":  bb_lower,
        },
        "fibonacci_levels": fib_levels,
        "volume": {
            "latest":       latest_vol,
            "ma_20":        vol_ma20,
            "ratio_vs_ma":  vol_ratio,
        },
        "52_week_high": week52_high,
        "52_week_low":  week52_low,
    }

import math
import time
import yfinance as yf
import pandas as pd

_DOWNLOAD_CACHE: dict = {}
_CACHE_TTL = 300  # seconds; re-fetch after 5 minutes


def _fetch_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    """Download OHLCV data with a 5-minute in-process cache."""
    key = (ticker, period)
    now = time.time()
    cached = _DOWNLOAD_CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1].copy()
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    _DOWNLOAD_CACHE[key] = (now, df)
    return df.copy()


def _safe(val):
    """Convert a scalar to float, returning None for NaN/Inf/non-numeric."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=length - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=length - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bbands(series: pd.Series, length: int = 20, std: float = 2.0):
    mid = series.rolling(window=length).mean()
    dev = series.rolling(window=length).std()
    return mid + std * dev, mid, mid - std * dev


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range: max of (h-l, |h-prev_close|, |l-prev_close|)."""
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's Average True Range (Wilder smoothing via ewm alpha=1/length)."""
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3):
    """Stochastic oscillator. %K = 100*(close-LL)/(HH-LL); %D = SMA(%K, d)."""
    lowest = low.rolling(window=k).min()
    highest = high.rolling(window=k).max()
    rng = highest - lowest
    percent_k = 100 * (close - lowest) / rng
    percent_d = percent_k.rolling(window=d).mean()
    return percent_k, percent_d


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
    """Average Directional Index with +DI / -DI (Wilder smoothing). Returns (adx, +DI, -DI)."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = _true_range(high, low, close)
    atr = tr.ewm(alpha=1 / length, adjust=False).mean()

    plus_di = 100 * plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / length, adjust=False).mean()
    return adx, plus_di, minus_di


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume: cumulative volume signed by the day's close direction."""
    direction = close.diff().apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    return (direction * volume).cumsum()


def extract_quant_indicators(ticker_symbol: str) -> dict:
    ticker_symbol = ticker_symbol.upper()
    df = _fetch_ohlcv(ticker_symbol, "1y")

    if df.empty:
        raise ValueError(f"No data returned for ticker '{ticker_symbol}'")

    if len(df) < 60:
        raise ValueError(
            f"Insufficient data for '{ticker_symbol}': only {len(df)} trading days available (minimum 60 required)."
        )

    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    vol   = df["Volume"]

    # --- SMAs ---
    sma50  = _sma(close, 50)
    sma100 = _sma(close, 100)
    sma200 = _sma(close, 200)

    # --- RSI ---
    rsi = _rsi(close, 14)

    # --- MACD ---
    macd_line, signal_line, histogram = _macd(close, 12, 26, 9)

    # --- Bollinger Bands (standard 20-period) ---
    bb_upper, bb_middle, bb_lower = _bbands(close, 20, 2.0)

    # --- ATR / Stochastic / ADX / OBV ---
    atr = _atr(high, low, close, 14)
    stoch_k, stoch_d = _stochastic(high, low, close, 14, 3)
    adx, plus_di, minus_di = _adx(high, low, close, 14)
    obv = _obv(close, vol)

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

    latest_close = _safe(close.iloc[-1])
    rsi_val      = _safe(rsi.iloc[-1])

    # --- Optimum Entry Price ---
    _sma50_val  = _safe(sma50.iloc[-1])
    _sma100_val = _safe(sma100.iloc[-1])
    _sma200_val = _safe(sma200.iloc[-1])
    _bb_lower   = _safe(bb_lower.iloc[-1])

    supports = []
    for fib_key in ["0.236", "0.382", "0.500"]:
        v = fib_levels.get(fib_key)
        if v and latest_close and v < latest_close:
            supports.append((f"Fib {fib_key}", v))
    if _bb_lower and latest_close and _bb_lower < latest_close:
        supports.append(("BB Lower", _bb_lower))
    for lbl, val in [
        ("SMA 50",  _sma50_val),
        ("SMA 100", _sma100_val),
        ("SMA 200", _sma200_val),
    ]:
        if val and latest_close and val < latest_close:
            supports.append((lbl, val))
    supports.sort(key=lambda x: x[1], reverse=True)

    if not supports or not latest_close:
        optimum_entry = {
            "price": round(latest_close * 0.99, 2) if latest_close else None,
            "signal": "OVERSOLD",
            "basis": "Price below all supports — deeply oversold",
            "support_levels": [],
        }
    else:
        nearest_lbl, nearest_price = supports[0]
        r = rsi_val or 50
        if r < 35:
            ep = round(latest_close * 0.999, 2)
            sig, basis = "BUY NOW", f"RSI oversold ({r:.1f}) — enter near market"
        elif r < 50:
            ep = round(nearest_price * 1.005, 2)
            sig, basis = "ACCUMULATE", f"Near {nearest_lbl} support (${nearest_price:.2f})"
        else:
            ep = round(nearest_price * 0.995, 2)
            sig, basis = "WAIT", f"Pullback to {nearest_lbl} (${nearest_price:.2f})"
        optimum_entry = {
            "price": ep,
            "signal": sig,
            "basis": basis,
            "support_levels": [{"label": l, "price": round(p, 2)} for l, p in supports[:3]],
        }

    return {
        "ticker":         ticker_symbol,
        "latest_close":   latest_close,
        "sma_50":         _safe(sma50.iloc[-1]),
        "sma_100":        _safe(sma100.iloc[-1]),
        "sma_200":        _safe(sma200.iloc[-1]),
        "rsi_14":         rsi_val,
        "optimum_entry":  optimum_entry,
        "macd": {
            "macd":   _safe(macd_line.iloc[-1]),
            "signal": _safe(signal_line.iloc[-1]),
            "hist":   _safe(histogram.iloc[-1]),
        },
        "bollinger_bands": {
            "upper":  _safe(bb_upper.iloc[-1]),
            "middle": _safe(bb_middle.iloc[-1]),
            "lower":  _safe(bb_lower.iloc[-1]),
        },
        "fibonacci_levels": fib_levels,
        "atr_14": _safe(atr.iloc[-1]),
        "stochastic": {
            "k": _safe(stoch_k.iloc[-1]),
            "d": _safe(stoch_d.iloc[-1]),
        },
        "adx": {
            "adx":      _safe(adx.iloc[-1]),
            "plus_di":  _safe(plus_di.iloc[-1]),
            "minus_di": _safe(minus_di.iloc[-1]),
        },
        "obv": _safe(obv.iloc[-1]),
        "volume": {
            "latest":      latest_vol,
            "ma_20":       vol_ma20,
            "ratio_vs_ma": vol_ratio,
        },
        "52_week_high": week52_high,
        "52_week_low":  week52_low,
    }

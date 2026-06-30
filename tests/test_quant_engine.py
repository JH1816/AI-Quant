import math
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from core.quant_engine import extract_quant_indicators, _safe, _obv


# ── _safe() helper ────────────────────────────────────────────────────────────

def test_safe_handles_nan():
    assert _safe(float("nan")) is None


def test_safe_handles_inf():
    assert _safe(float("inf")) is None
    assert _safe(float("-inf")) is None


def test_safe_handles_none():
    assert _safe(None) is None


def test_safe_returns_python_float():
    result = _safe(np.float64(1.5))
    assert isinstance(result, float)
    assert result == 1.5


def test_safe_returns_int_as_float():
    result = _safe(np.int64(42))
    assert isinstance(result, float)


# ── extract_quant_indicators() ────────────────────────────────────────────────

REQUIRED_KEYS = {
    "ticker", "latest_close", "sma_50", "sma_100", "sma_200",
    "rsi_14", "macd", "bollinger_bands", "fibonacci_levels",
    "atr_14", "stochastic", "adx", "obv",
    "volume", "52_week_high", "52_week_low",
}


@pytest.fixture()
def result(mock_ohlcv_df):
    with patch("core.data_providers.yf.download", return_value=mock_ohlcv_df):
        return extract_quant_indicators("AAPL")


def test_returns_required_keys(result):
    assert REQUIRED_KEYS.issubset(result.keys())


def test_ticker_uppercased(mock_ohlcv_df):
    with patch("core.data_providers.yf.download", return_value=mock_ohlcv_df):
        r = extract_quant_indicators("aapl")
    assert r["ticker"] == "AAPL"


def test_latest_close_is_float(result):
    assert isinstance(result["latest_close"], float)


def test_sma_values_are_float_or_none(result):
    for key in ("sma_50", "sma_100", "sma_200"):
        val = result[key]
        assert val is None or isinstance(val, float), f"{key} has unexpected type {type(val)}"


def test_rsi_in_valid_range(result):
    rsi = result["rsi_14"]
    assert rsi is not None
    assert 0.0 <= rsi <= 100.0


def test_macd_keys_present(result):
    assert set(result["macd"].keys()) == {"macd", "signal", "hist"}


def test_macd_values_are_float_or_none(result):
    for key, val in result["macd"].items():
        assert val is None or isinstance(val, float), f"macd.{key} has unexpected type"


def test_bollinger_bands_order(result):
    bb = result["bollinger_bands"]
    upper, middle, lower = bb["upper"], bb["middle"], bb["lower"]
    assert upper is not None and middle is not None and lower is not None
    assert upper > middle > lower


def test_fibonacci_levels_ordered(result):
    fib = result["fibonacci_levels"]
    values = [fib[k] for k in ("0.0", "0.236", "0.382", "0.500", "0.618", "1.0")]
    assert all(v is not None for v in values)
    assert values == sorted(values), "Fibonacci levels should be in ascending order"


def test_volume_ratio_is_positive(result):
    ratio = result["volume"]["ratio_vs_ma"]
    assert ratio is not None and ratio > 0


def test_52_week_high_above_low(result):
    assert result["52_week_high"] > result["52_week_low"]


# ── advanced indicators (ATR / Stochastic / ADX / OBV) ────────────────────────

def test_atr_is_positive_float(result):
    atr = result["atr_14"]
    assert isinstance(atr, float)
    assert atr > 0


def test_stochastic_in_range(result):
    stoch = result["stochastic"]
    assert set(stoch.keys()) == {"k", "d"}
    for key, val in stoch.items():
        assert val is None or (0.0 <= val <= 100.0), f"stochastic.{key}={val} out of range"


def test_adx_block_in_range(result):
    adx = result["adx"]
    assert set(adx.keys()) == {"adx", "plus_di", "minus_di"}
    for key, val in adx.items():
        assert val is None or (0.0 <= val <= 100.0), f"adx.{key}={val} out of range"


def test_obv_is_float(result):
    assert isinstance(result["obv"], float)


def test_obv_rises_with_monotonic_closes():
    """Strictly rising closes → every day adds +volume, so OBV is strictly increasing."""
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    volume = pd.Series([100.0, 200.0, 150.0, 300.0, 250.0])
    obv = _obv(close, volume)
    # First diff is NaN → direction 0; subsequent up-days accumulate volume.
    assert obv.tolist() == [0.0, 200.0, 350.0, 650.0, 900.0]
    assert obv.is_monotonic_increasing


# ── error cases ───────────────────────────────────────────────────────────────

def test_empty_data_raises():
    empty_df = pd.DataFrame()
    with patch("core.data_providers.yf.download", return_value=empty_df):
        with pytest.raises(ValueError, match="No data returned"):
            extract_quant_indicators("FAKE")


def test_insufficient_data_raises():
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    small_df = pd.DataFrame(
        {
            "Close": rng.uniform(100, 200, 30),
            "High":  rng.uniform(200, 210, 30),
            "Low":   rng.uniform(90, 100, 30),
            "Volume": rng.integers(1_000_000, 5_000_000, 30).astype(float),
        },
        index=dates,
    )
    with patch("core.data_providers.yf.download", return_value=small_df):
        with pytest.raises(ValueError, match="Insufficient data"):
            extract_quant_indicators("NEW")

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temporary file for each test."""
    db_file = str(tmp_path / "test_portfolio.db")
    monkeypatch.setattr("core.db_manager.DB_PATH", db_file)
    import core.db_manager as dbm
    dbm.init_db()
    yield db_file


@pytest.fixture()
def mock_ohlcv_df():
    """252-row OHLCV DataFrame with synthetic but realistic values."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    close = 150.0 + np.cumsum(rng.normal(0, 1.5, 252))
    high  = close + rng.uniform(0.5, 3.0, 252)
    low   = close - rng.uniform(0.5, 3.0, 252)
    vol   = rng.integers(5_000_000, 30_000_000, 252).astype(float)

    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Volume": vol},
        index=dates,
    )

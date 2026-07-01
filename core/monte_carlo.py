"""Monte Carlo portfolio projection via bootstrap resampling of daily returns.

Pure, I/O-free: takes stored positions plus per-ticker close-price history and
simulates future portfolio value paths by resampling the portfolio's own
historical daily returns (IID bootstrap). No normality assumption — the
empirical fat tails and skew carry through, consistent with the historical
VaR/CVaR in ``risk_engine``. Known limitation: IID resampling ignores return
autocorrelation and volatility regimes.

The network/yfinance side lives in ``main.py``, so everything here is unit
testable with synthetic ``pandas`` Series and a seeded RNG.
"""

import numpy as np
import pandas as pd

from core.quant_engine import _safe

TRADING_DAYS = 252
STEPS_PER_MONTH = 21     # contribution cadence and path-recording interval
MAX_CHART_POINTS = 121   # downsample long horizons for the fan chart
MIN_OBSERVATIONS = 60    # need a meaningful sample to bootstrap from
PERCENTILES = (5, 25, 50, 75, 95)


def _round(val, ndigits: int = 2):
    """``round`` that first sanitises NaN/Inf to None (so it never raises)."""
    f = _safe(val)
    return round(f, ndigits) if f is not None else None


def _empty_result(years: int, simulations: int, monthly_contribution: float = 0.0) -> dict:
    return {
        "method": "bootstrap",
        "years": years,
        "simulations": simulations,
        "monthly_contribution": _round(monthly_contribution),
        "start_value": None,
        "observations": 0,
        "dates": [],
        "bands": {f"p{p}": [] for p in PERCENTILES},
        "summary": {
            "median_terminal_value": None,
            "p5_terminal_value": None,
            "p95_terminal_value": None,
            "total_invested": None,
            "prob_loss_pct": None,
            "median_cagr_pct": None,
        },
    }


def portfolio_daily_returns(
    positions: list[dict],
    close_by_ticker: dict[str, pd.Series],
) -> tuple[float, pd.Series]:
    """(current portfolio value, value-weighted daily return Series).

    Weights are value-based (latest price × shares) held constant — the same
    transparent approximation as ``risk_engine``. Returns ``(0.0, empty)``
    when nothing is computable.
    """
    weights: dict[str, float] = {}
    for pos in positions:
        ticker = pos["ticker"]
        shares = _safe(pos.get("shares")) or 0.0
        series = close_by_ticker.get(ticker)
        if shares <= 0 or series is None or series.empty:
            continue
        last = _safe(series.iloc[-1])
        if last is None or last <= 0:
            continue
        weights[ticker] = shares * last

    total = sum(weights.values())
    if not weights or total <= 0:
        return 0.0, pd.Series(dtype=float)

    tickers = list(weights.keys())
    closes = pd.DataFrame({t: close_by_ticker[t] for t in tickers}).sort_index()
    returns = closes.pct_change().dropna(how="any")
    if returns.empty:
        return total, pd.Series(dtype=float)

    w = pd.Series({t: v / total for t, v in weights.items()})[returns.columns]
    return total, returns.dot(w)


def simulate_portfolio(
    positions: list[dict],
    close_by_ticker: dict[str, pd.Series],
    *,
    years: int = 10,
    simulations: int = 500,
    monthly_contribution: float = 0.0,
    start_date: str | None = None,
    seed: int | None = None,
) -> dict:
    """Simulate future portfolio value paths and return percentile bands.

    Each path compounds ``years × 12`` month blocks of 21 bootstrap-resampled
    daily returns, adding ``monthly_contribution`` at the end of every month.
    ``start_date`` (ISO) anchors the projected dates — defaults to today and is
    a parameter so tests are deterministic. ``seed`` fixes the RNG in tests;
    the endpoint leaves it None.
    """
    monthly_contribution = _safe(monthly_contribution) or 0.0
    start_value, daily = portfolio_daily_returns(positions, close_by_ticker)
    if start_value <= 0 or len(daily) < MIN_OBSERVATIONS:
        return _empty_result(years, simulations, monthly_contribution)

    rng = np.random.default_rng(seed)
    rets = daily.to_numpy()
    months = years * 12

    # (simulations, months): each cell is one month's compounded growth factor.
    idx = rng.integers(0, len(rets), size=(simulations, months * STEPS_PER_MONTH))
    monthly_growth = (1.0 + rets[idx]).reshape(simulations, months, STEPS_PER_MONTH).prod(axis=2)

    path = np.empty((simulations, months + 1))
    path[:, 0] = start_value
    values = np.full(simulations, float(start_value))
    for m in range(months):
        values = values * monthly_growth[:, m] + monthly_contribution
        path[:, m + 1] = values

    # Downsample recorded months evenly for the chart, always keeping the ends.
    if months + 1 > MAX_CHART_POINTS:
        keep = np.unique(np.linspace(0, months, MAX_CHART_POINTS).round().astype(int))
    else:
        keep = np.arange(months + 1)

    start = pd.Timestamp(start_date) if start_date else pd.Timestamp.today().normalize()
    dates = [(start + pd.DateOffset(months=int(m))).strftime("%Y-%m-%d") for m in keep]

    bands_matrix = np.percentile(path[:, keep], PERCENTILES, axis=0)
    bands = {
        f"p{p}": [_round(v) for v in row]
        for p, row in zip(PERCENTILES, bands_matrix)
    }

    terminal = path[:, -1]
    total_invested = start_value + monthly_contribution * months
    median_terminal = float(np.median(terminal))
    # With contributions this is an approximation (money-weighted timing is
    # ignored); exact when monthly_contribution is 0.
    median_cagr = ((median_terminal / total_invested) ** (1.0 / years) - 1.0) * 100 \
        if total_invested > 0 and median_terminal > 0 else None

    return {
        "method": "bootstrap",
        "years": years,
        "simulations": simulations,
        "monthly_contribution": _round(monthly_contribution),
        "start_value": _round(start_value),
        "observations": int(len(daily)),
        "dates": dates,
        "bands": bands,
        "summary": {
            "median_terminal_value": _round(median_terminal),
            "p5_terminal_value": _round(float(np.percentile(terminal, 5))),
            "p95_terminal_value": _round(float(np.percentile(terminal, 95))),
            "total_invested": _round(total_invested),
            "prob_loss_pct": _round(float((terminal < total_invested).mean() * 100)),
            "median_cagr_pct": _round(median_cagr),
        },
    }

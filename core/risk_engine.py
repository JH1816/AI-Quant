"""Portfolio risk & correlation metrics.

Pure, I/O-free functions that turn per-position holdings plus per-ticker price
history into portfolio-level risk statistics: annualised return/volatility,
Sharpe and Sortino ratios, maximum drawdown, beta versus a benchmark, a
pairwise correlation matrix and per-position risk contributions.

The network/yfinance side lives in ``main.py`` (it fetches close-price Series
concurrently and passes them in here), so everything in this module is unit
testable with synthetic ``pandas`` Series.
"""

import pandas as pd

from core.quant_engine import _safe

TRADING_DAYS = 252
DEFAULT_BENCHMARK = "SPY"


def _round(val, ndigits: int = 2):
    """``round`` that first sanitises NaN/Inf to None (so it never raises)."""
    f = _safe(val)
    return round(f, ndigits) if f is not None else None


def _annualised_return(daily: pd.Series) -> float:
    return float(daily.mean()) * TRADING_DAYS


def _annualised_vol(daily: pd.Series) -> float:
    return float(daily.std()) * (TRADING_DAYS ** 0.5)


def _beta(asset_returns: pd.Series, bench_returns: pd.Series):
    """OLS beta of ``asset_returns`` against ``bench_returns`` on shared dates."""
    if bench_returns is None or bench_returns.empty:
        return None
    common = asset_returns.index.intersection(bench_returns.index)
    if len(common) < 2:
        return None
    a = asset_returns.loc[common]
    b = bench_returns.loc[common]
    var = float(b.var())
    if not var:
        return None
    return float(a.cov(b)) / var


def _historical_var(returns: pd.Series, confidence: float = 0.95):
    """Historical (non-parametric) Value-at-Risk as a positive daily-loss fraction.

    The empirical ``(1 - confidence)`` quantile of daily returns; a left-tail
    loss is reported as a positive magnitude (e.g. 0.021 → a 2.1% daily VaR).
    """
    if returns is None or returns.empty:
        return None
    q = returns.quantile(1 - confidence)
    return float(-q)


def _cvar(returns: pd.Series, confidence: float = 0.95):
    """Conditional VaR (expected shortfall): mean loss in the worst tail."""
    if returns is None or returns.empty:
        return None
    threshold = returns.quantile(1 - confidence)
    tail = returns[returns <= threshold]
    if tail.empty:
        return None
    return float(-tail.mean())


def _empty_result(benchmark: str) -> dict:
    return {
        "benchmark": benchmark,
        "observations": 0,
        "annual_return_pct": None,
        "annual_volatility_pct": None,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "max_drawdown_pct": None,
        "beta": None,
        "var_95_pct": None,
        "var_99_pct": None,
        "cvar_95_pct": None,
        "correlation": {"tickers": [], "matrix": []},
        "positions": [],
    }


def compute_portfolio_risk(
    positions: list[dict],
    close_by_ticker: dict[str, pd.Series],
    benchmark_close: pd.Series | None = None,
    benchmark_symbol: str = DEFAULT_BENCHMARK,
    risk_free_rate: float = 0.0,
) -> dict:
    """Roll holdings + price history into portfolio risk metrics.

    ``positions``        — rows from the DB (``ticker``, ``shares`` …).
    ``close_by_ticker``  — ``ticker -> close-price Series`` (DatetimeIndex).
    ``benchmark_close``  — close-price Series for the benchmark (optional).
    ``risk_free_rate``   — annualised, as a decimal (e.g. 0.04 for 4%).

    Weights are value-based (latest price × shares). Portfolio returns use those
    current weights held constant — a standard, transparent approximation.
    """
    # ── Value weights ────────────────────────────────────────────────────────
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
        return _empty_result(benchmark_symbol)
    weights = {t: v / total for t, v in weights.items()}
    tickers = list(weights.keys())

    # ── Aligned daily returns ────────────────────────────────────────────────
    closes = pd.DataFrame({t: close_by_ticker[t] for t in tickers}).sort_index()
    returns = closes.pct_change().dropna(how="any")
    if returns.empty or len(returns) < 2:
        return _empty_result(benchmark_symbol)

    w = pd.Series(weights)[returns.columns]
    port_ret = returns.dot(w)

    ann_ret = _annualised_return(port_ret)
    ann_vol = _annualised_vol(port_ret)
    sharpe = (ann_ret - risk_free_rate) / ann_vol if ann_vol else None

    downside = port_ret[port_ret < 0]
    dd_dev = float(downside.std()) * (TRADING_DAYS ** 0.5) if len(downside) > 1 else None
    sortino = (ann_ret - risk_free_rate) / dd_dev if dd_dev else None

    # ── Maximum drawdown ─────────────────────────────────────────────────────
    cum = (1 + port_ret).cumprod()
    drawdown = cum / cum.cummax() - 1
    max_dd = float(drawdown.min())

    # ── Benchmark beta ───────────────────────────────────────────────────────
    bench_ret = None
    if benchmark_close is not None and not benchmark_close.empty:
        bench_ret = benchmark_close.sort_index().pct_change().dropna()
    portfolio_beta = _beta(port_ret, bench_ret) if bench_ret is not None else None

    # ── Correlation matrix ───────────────────────────────────────────────────
    corr = returns.corr()
    corr_tickers = list(corr.columns)
    matrix = [[_round(corr.loc[a, b]) for b in corr_tickers] for a in corr_tickers]

    # ── Per-position contributions ───────────────────────────────────────────
    per_position = []
    for ticker in tickers:
        r = returns[ticker]
        per_position.append({
            "ticker": ticker,
            "weight_pct": _round(weights[ticker] * 100),
            "annual_return_pct": _round(_annualised_return(r) * 100),
            "annual_volatility_pct": _round(_annualised_vol(r) * 100),
            "beta": _round(_beta(r, bench_ret)),
        })
    per_position.sort(key=lambda d: d["weight_pct"] or 0.0, reverse=True)

    return {
        "benchmark": benchmark_symbol,
        "observations": int(len(port_ret)),
        "annual_return_pct": _round(ann_ret * 100),
        "annual_volatility_pct": _round(ann_vol * 100),
        "sharpe_ratio": _round(sharpe),
        "sortino_ratio": _round(sortino),
        "max_drawdown_pct": _round(max_dd * 100),
        "beta": _round(portfolio_beta),
        "var_95_pct": _round(_historical_var(port_ret, 0.95) * 100),
        "var_99_pct": _round(_historical_var(port_ret, 0.99) * 100),
        "cvar_95_pct": _round(_cvar(port_ret, 0.95) * 100),
        "correlation": {"tickers": corr_tickers, "matrix": matrix},
        "positions": per_position,
    }

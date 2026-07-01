# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run the app
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run all tests
pytest -q

# Run a single test file
pytest tests/test_quant_engine.py -q

# Run a single test by name
pytest tests/test_quant_engine.py::test_bollinger_bands_order -q
```

`GOOGLE_API_KEY` must be set in `.env` for LLM endpoints (`/api/analyze`, `/api/report/*`). The dashboard, portfolio CRUD, indicators, and chart endpoints work without it.

## Architecture

**Entry point:** `main.py` — FastAPI app, all API routes, and APScheduler setup. Mounts the `static/` SPA last so API routes take precedence.

**Data flow for a ticker lookup:**
1. `GET /api/indicators/{ticker}` → `core/quant_engine.extract_quant_indicators()` — downloads 1y OHLCV via the provider layer (`core/data_providers.get_ohlcv`, cached 5 min in `_fetch_ohlcv`), computes all indicators natively, returns a flat dict.
2. `GET /api/analyze/{ticker}` — calls the above, then passes the dict to `agents/quant_agent.analyze_ticker()` → Gemini → Markdown.
3. `GET /api/chart/{ticker}?period=6mo` — uses the same `_fetch_ohlcv` cache, then builds candle/volume/SMA series for the frontend chart.

**Market-data providers** (`core/data_providers.py`) — a pluggable layer that centralises every outbound price/fundamentals call so the rest of the codebase is source-agnostic. `get_ohlcv(ticker, period)` returns a normalised OHLCV DataFrame; `get_fundamentals_source(ticker)` returns a `yfinance.Ticker`-shaped object (`.info`/`.income_stmt`/`.balance_sheet`/`.cashflow`/`.dividends`). Both walk a provider chain (`DATA_PROVIDER` primary + `DATA_PROVIDER_FALLBACKS`, default `yahoo` then `stooq`), returning the first non-empty/usable result. Providers: **yahoo** (yfinance, prices+fundamentals), **stooq** (keyless CSV, prices only), **alphavantage** (keyed via `ALPHAVANTAGE_API_KEY`, prices+fundamentals; `_AV_OVERVIEW_MAP`/`_AV_INCOME_MAP`/`_AV_CASHFLOW_MAP` adapt its payloads to the yfinance shape). The two seams `quant_engine._fetch_ohlcv` (keeps the 5-min cache) and `fundamentals_engine._get_ticker` delegate here — patch those (or `core.data_providers.yf.download`) in tests. Parsers (`_parse_stooq_csv`, `_parse_av_daily`, `_av_overview_to_info`, `_av_statement_df`) are pure and unit-tested offline.

**Indicator math** lives entirely in `core/quant_engine.py` — no `pandas-ta`. Key private helpers: `_sma`, `_rsi`, `_macd`, `_bbands` (20-period), `_atr`/`_true_range` (Wilder ATR), `_stochastic` (%K/%D), `_adx` (ADX + ±DI), `_obv` (on-balance volume), `_safe` (NaN/Inf → None). `extract_quant_indicators()` returns these as `atr_14`, `stochastic`, `adx`, and `obv` alongside the classic indicators. The SMA/Bollinger helpers are imported directly by `main.py` to avoid duplication in the chart endpoint.

**Fundamentals** (`core/fundamentals_engine.py`) — `extract_fundamentals(ticker)` returns a Qualtrim-style dict: company profile, valuation (P/E, P/S, P/B, PEG, EV/EBITDA), profitability/margins, dividends (yield, payout, history, CAGR), balance-sheet health, analyst targets, and multi-year financial-statement series (revenue/net income/FCF/EPS/net-margin) from yfinance's `.info`, `.income_stmt`, `.balance_sheet`, `.cashflow`, `.dividends`. Reuses `_safe` from `quant_engine`; cached 1h per ticker in `_FUND_CACHE`. Exposed at `GET /api/fundamentals/{ticker}`. `_fair_value()` blends up to three transparent methods (analyst target, growth-justified P/E with PEG≈1, dividend yield theory) into `valuation.fair_value` with an Undervalued/Fairly valued/Overvalued verdict (±10% bands).

**Agents** (`agents/quant_agent.py`, `agents/reporter_agent.py`) use the `google-genai` SDK (package: `google-genai>=2.0.0` — **not** the deprecated `google-generativeai`). They lazy-init a `genai.Client` on first call via `_get_client()` and call `client.models.generate_content(model=MODEL_NAME, contents=..., config=GenerateContentConfig(system_instruction=...))`. The shared model name lives in `agents/config.py` as `MODEL_NAME` (currently `gemini-3.5-flash`). Both agents handle quota (429) and blocked-response errors explicitly. Google AI Studio keys with the `AQ.` prefix are valid for this SDK.

**Portfolio insights** (`core/portfolio_insights.py`) — `build_portfolio_insights(positions, data_by_ticker)` is a pure (I/O-free, unit-tested) aggregator that rolls holdings + per-ticker fundamentals into total value, projected annual/monthly dividend income, portfolio yield, sector allocation (grouped + sorted, `None`→"Unknown"), and top income contributors. Exposed at `GET /api/portfolio/insights` (which fetches fundamentals per holding) and rendered as dividend-income + sector-allocation cards under the Portfolio table.

**Portfolio enriched** — `GET /api/portfolio/enriched` augments each stored position with live `current_price`, `current_value`, `unrealised_pnl`, and `return_pct` by calling `extract_quant_indicators()` per ticker (benefits from the 5-min OHLCV cache). This is the endpoint the Portfolio tab's P&L table actually reads.

**Portfolio equity curve** — `GET /api/portfolio/chart` reconstructs a historical value vs. cost-basis series from the transaction log. It fetches 2y OHLCV for every holding concurrently via `asyncio.gather`, then iterates each business day since the first trade, calling `compute_holding(trades_to_date)` per ticker to derive shares × close = market value. Returns parallel `dates`, `portfolio_values`, and `cost_basis` arrays; rendered as a line chart in the Portfolio tab.

**Risk metrics** (`core/risk_engine.py`) — `compute_portfolio_risk(positions, close_by_ticker, benchmark_close, benchmark_symbol, risk_free_rate)` is a pure (I/O-free, unit-tested) aggregator. From value-weighted holdings (latest price × shares) and per-ticker close-price Series it computes annualised return/volatility, Sharpe & Sortino ratios, max drawdown, portfolio beta vs a benchmark (default `SPY`), historical Value-at-Risk (`var_95_pct`, `var_99_pct` via `_historical_var`) and Conditional VaR / expected shortfall (`cvar_95_pct` via `_cvar`) as positive loss percentages, a pairwise correlation matrix, and per-holding weight/volatility/beta. Reuses `_safe` from `quant_engine`; returns a `None`-filled empty shape (`_empty_result`) when there's nothing to compute. Exposed at `GET /api/portfolio/risk` (which fans out the module-level `_close_series` helper for every holding plus the benchmark in one `asyncio.gather`) and rendered as the "Risk & Correlation" card under the Portfolio table (stat grid + per-holding table + correlation heatmap).

**Monte Carlo projection** (`core/monte_carlo.py`) — `simulate_portfolio(positions, close_by_ticker, *, years, simulations, monthly_contribution, start_date, seed)` is a pure, unit-tested IID **bootstrap** of the portfolio's historical daily returns (no GBM/normality assumption, consistent with the historical VaR/CVaR in `risk_engine`). It compounds `years × 12` month blocks of 21 resampled daily returns (vectorised numpy), adds the contribution each month, and returns monthly percentile bands (`bands.p5/p25/p50/p75/p95`, downsampled to ≤121 chart points) plus a `summary` (median/p5/p95 terminal value, total invested, `prob_loss_pct`, approximate `median_cagr_pct`). `seed` fixes the RNG in tests; `start_date` anchors the projected dates. Exposed at `GET /api/portfolio/montecarlo?years=&simulations=&contribution=` (params clamped to 1–40y / 100–2000 sims to stop a hostile query pinning the CPU; the fan-out uses 2y `_close_series` history and the sim itself runs in `asyncio.to_thread`). Rendered as the "Monte Carlo Projection" card in the Portfolio tab (fan chart + stat grid, re-runs via its inputs).

**Rebalancing advisor** (`core/rebalance.py`) — `build_rebalance_plan(positions, price_by_ticker, targets, cash, tolerance_pct)` is a pure, unit-tested transform: universe = held ∪ targeted tickers (held-without-target → explicit full-SELL row, targeted-unheld → BUY from zero), targets normalised to sum to exactly 100, per-row `current_pct`/`drift_pct`/`action` (HOLD inside ±1% tolerance) and concrete `shares_delta`/`value_delta`; `cash` is added to the total so BUYs absorb it. Holdings without a price are excluded from totals and reported in `warnings`. Targets live in the `target_allocations` DB table (`get_target_allocations`/`set_target_allocations` — replace-all PUT semantics). Endpoints: `GET/PUT /api/portfolio/targets` (`TargetsIn` validates no duplicates and sum ∈ [99.5, 100.5]; empty list clears) and `GET /api/portfolio/rebalance?cash=` (fans out the `_latest_price` helper over the ticker union). Rendered as the "Target Allocation & Rebalancing" card (editable target inputs + suggested-trades table).

**Dividend & earnings calendar** (`core/calendar_engine.py`) — `normalize_ticker_events(ticker, calendar, info)` defensively coerces yfinance's unstable `.calendar` payload (dict in current versions, DataFrame in legacy ones, `{}`/None for ETFs or non-Yahoo providers — the Alpha Vantage adapter and Stooq have no calendar at all) plus `.info` epoch fields (`exDividendDate`, `dividendDate`, `earningsTimestamp(Start)`, only for types the calendar didn't supply) into flat event rows; a 2-date earnings range becomes the first date with `estimate: true`. `build_calendar(events_by_ticker, today, window_days=90)` merges/dedupes/sorts them into upcoming events with `days_until`, reporting failed or empty tickers in `tickers_with_no_data` (never a 500). `today` is a parameter for test determinism. Exposed at `GET /api/calendar` over the union of holdings + watchlist via the `_safe_calendar_events` helper in `main.py`, which caches **normalized rows** for 1h in `_CAL_CACHE` (mirrors `_FUND_CACHE`; successes only). Rendered as the "Dividend & Earnings Calendar" card — loaded from init, not `loadPortfolio()`, so it works with an empty portfolio + populated watchlist.

**Comparison** (`core/comparison.py`) — `build_comparison(tickers, data_by_ticker)` is a pure, unit-tested transform of per-ticker `extract_fundamentals` dicts into a metric-row table (rows = valuation/profitability/growth metrics, columns = tickers). Each metric carries a `better` hint (`"high"`/`"low"`/`None`) and the `best` ticker so the UI can highlight winners. Exposed at `GET /api/compare?tickers=AAPL,MSFT,NVDA` (2–4 tickers, deduped/uppercased; fetches fundamentals concurrently via `_safe_fundamentals`) and rendered as the Compare tab.

**Concurrency pattern** — `extract_quant_indicators()` and `extract_fundamentals()` are synchronous blocking yfinance calls. All multi-ticker endpoints (`/api/portfolio/enriched`, `/api/portfolio/insights`, `/api/portfolio/risk`, `/api/portfolio/montecarlo`, `/api/portfolio/rebalance`, `/api/compare`, `/api/watchlist/enriched`, `/api/calendar`) and `run_daily_report()` fan them out concurrently via `asyncio.gather(asyncio.to_thread(...))` using module-level sync helpers (`_enrich_position`, `_safe_fundamentals`, `_enrich_watchlist_row`, `_safe_indicators`, `_close_series`, `_latest_price`, `_safe_calendar_events`) defined in `main.py`. Total latency is ≈ the slowest ticker rather than the sum. Each helper owns its own try/except so per-ticker failures still return `None`-filled fallback rows. Do not revert to serial `for` loops — that blocks the event loop.

**Database** (`core/db_manager.py`) — SQLite with four tables created in `init_db()`. `DB_PATH` is monkeypatched in tests via `conftest.py`.
- `transactions(id, ticker, side CHECK IN ('BUY','SELL'), shares, price, fee, trade_date)` — the source of truth for all holdings. Every buy and sell is appended here; the portfolio is **never directly mutated**.
- `portfolio(id, ticker, shares, average_buy_price, date_added)` — legacy table kept only for the one-time migration: if `transactions` is empty on startup and `portfolio` has rows, each row is seeded as an opening BUY transaction.
- `watchlist(id, ticker, date_added)` (insert-or-ignore).
- `target_allocations(ticker PRIMARY KEY, target_pct CHECK (0 < target_pct <= 100), updated_at)` — rebalancing targets; always replaced wholesale via `set_target_allocations` (PUT semantics).

**Cost-basis engine** (`core/cost_basis.py`) — pure, I/O-free. `compute_holding(trades)` folds a chronological list of BUY/SELL dicts into `{shares, average_buy_price, realized_pnl}` using the **average-cost** method: a SELL realizes `(sell_price − avg_cost) × qty − fee`; remaining shares keep the same average cost. `derive_positions(trades_by_ticker)` returns only open holdings (shares > 0). `get_all_positions()` calls this and returns the same shape as before — `id, ticker, shares, average_buy_price, date_added` — plus `realized_pnl`, so all downstream code is unchanged.

**Transaction API** — `POST /api/transactions` records a trade (validates side ∈ {BUY,SELL}, rejects SELL > current holdings; Pydantic `field_validator`s on `TransactionIn`/`PositionIn` reject non-finite (NaN/Inf) or non-positive `shares`/`price`, negative/non-finite `fee`, and future/unparseable `trade_date` via the shared `_positive_finite` helper — NaN slips past a plain `<= 0` check, so this guards the DB); `GET /api/transactions?ticker=` lists trades; `DELETE /api/transactions/{id}` removes one trade (holdings recompute automatically). The Portfolio tab's "History" button opens a per-ticker trade log with per-row delete.

**Watchlist** — `GET/POST/DELETE /api/watchlist` plus `GET /api/watchlist/enriched`, which fetches fundamentals per ticker and returns price, P/E, dividend yield, and the `fair_value` estimate/upside/verdict for an at-a-glance valuation read. Rendered as the Watchlist tab; ticker rows link into the Fundamentals tab.

**Frontend** (`static/index.html` + `static/app.js`) is a vanilla-JS SPA with six sections (Portfolio, Research, Fundamentals, Watchlist, Compare, Reports). Uses Tailwind CSS, lightweight-charts (candlestick chart), and marked.js (Markdown rendering) all from CDN. The Fundamentals tab renders metric grids + year-by-year bar charts via a dependency-free `barChart()` helper in `app.js`; the Portfolio tab adds dividend-income + sector-allocation cards plus the "Risk & Correlation" card (`loadPortfolioRisk()` → `/api/portfolio/risk`), the "Monte Carlo Projection" card (`loadMonteCarlo()` → `/api/portfolio/montecarlo`), the "Target Allocation & Rebalancing" card (`loadRebalance()`/`saveTargets()` → `/api/portfolio/rebalance` + `/api/portfolio/targets`), and the "Dividend & Earnings Calendar" card (`loadCalendar()` → `/api/calendar`, wired from the `DOMContentLoaded` init — not `loadPortfolio()` — so it renders from the watchlist even with an empty portfolio); the Compare tab (`runCompare()` → `/api/compare`) renders a side-by-side metric table. Tooltip system is CSS-only via `.tip` / `data-tip` attribute.

**Scheduled report** — an APScheduler cron job (`run_daily_report`) registered in the `lifespan` context manager that writes `.md` files to `data/reports/` (gitignored). **The automatic schedule is currently commented out in `lifespan` to conserve LLM tokens** — re-enable by uncommenting the `scheduler.add_job(...)` block. `POST /api/report/trigger` still fires the same report on demand; `GET /api/report/latest` returns the most recent report file's content.

## Testing

`conftest.py` provides two shared fixtures:
- `tmp_db` — redirects `DB_PATH` to a `tmp_path` file and calls `init_db()`, so DB tests are fully isolated.
- `mock_ohlcv_df` — a 252-row synthetic OHLCV `DataFrame` (seeded RNG, realistic price walk). Monkeypatch `_fetch_ohlcv` to return this when writing new indicator tests without hitting yfinance.

`tests/test_api_concurrency.py` uses `fastapi.testclient.TestClient` with a `client` fixture that monkeypatches `get_all_positions`, `get_watchlist`, `extract_quant_indicators`, and `extract_fundamentals` in `main`. **Always add route tests to this fixture** rather than constructing a bare `TestClient(app)` inside test functions — the APScheduler singleton in `main.py` will fail on a closed event loop if the lifespan is started more than once per session.

## Key constraints

- The `data/` directory (SQLite DB + reports) is gitignored and auto-created at startup.
- yfinance requires `>=1.4.1`; older versions return empty DataFrames against Yahoo's current API.
- The in-process download cache (`core/quant_engine._DOWNLOAD_CACHE`) has a 5-minute TTL and is keyed by `(ticker, period)`. It resets on server restart.
- Fibonacci levels and 52-week high/low are derived from the 1y download window, not a true calendar year.
- The LLM SDK is `google-genai` (v2+). Do **not** use or re-add `google-generativeai` — it is deprecated, no longer receives updates, and is incompatible with newer `AQ.`-prefixed Google AI Studio keys.
- `gemini-3.5-flash` errors with `503 UNAVAILABLE` under high demand (expected for newly released models); retry after a short wait. `429 RESOURCE_EXHAUSTED` means per-minute quota hit on the free tier.

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
1. `GET /api/indicators/{ticker}` → `core/quant_engine.extract_quant_indicators()` — downloads 1y OHLCV via yfinance (cached 5 min in `_fetch_ohlcv`), computes all indicators natively, returns a flat dict.
2. `GET /api/analyze/{ticker}` — calls the above, then passes the dict to `agents/quant_agent.analyze_ticker()` → Gemini → Markdown.
3. `GET /api/chart/{ticker}?period=6mo` — uses the same `_fetch_ohlcv` cache, then builds candle/volume/SMA series for the frontend chart.

**Indicator math** lives entirely in `core/quant_engine.py` — no `pandas-ta`. Key private helpers: `_sma`, `_rsi`, `_macd`, `_bbands` (20-period), `_safe` (NaN/Inf → None). These are imported directly by `main.py` to avoid duplication in the chart endpoint.

**Fundamentals** (`core/fundamentals_engine.py`) — `extract_fundamentals(ticker)` returns a Qualtrim-style dict: company profile, valuation (P/E, P/S, P/B, PEG, EV/EBITDA), profitability/margins, dividends (yield, payout, history, CAGR), balance-sheet health, analyst targets, and multi-year financial-statement series (revenue/net income/FCF/EPS/net-margin) from yfinance's `.info`, `.income_stmt`, `.balance_sheet`, `.cashflow`, `.dividends`. Reuses `_safe` from `quant_engine`; cached 1h per ticker in `_FUND_CACHE`. Exposed at `GET /api/fundamentals/{ticker}`. `_fair_value()` blends up to three transparent methods (analyst target, growth-justified P/E with PEG≈1, dividend yield theory) into `valuation.fair_value` with an Undervalued/Fairly valued/Overvalued verdict (±10% bands).

**Agents** (`agents/quant_agent.py`, `agents/reporter_agent.py`) lazy-init the Gemini model on first call. The shared model name lives in `agents/config.py` as `MODEL_NAME`. Both agents handle quota (429) and blocked-response errors explicitly.

**Portfolio insights** (`core/portfolio_insights.py`) — `build_portfolio_insights(positions, data_by_ticker)` is a pure (I/O-free, unit-tested) aggregator that rolls holdings + per-ticker fundamentals into total value, projected annual/monthly dividend income, portfolio yield, sector allocation (grouped + sorted, `None`→"Unknown"), and top income contributors. Exposed at `GET /api/portfolio/insights` (which fetches fundamentals per holding) and rendered as dividend-income + sector-allocation cards under the Portfolio table.

**Portfolio enriched** — `GET /api/portfolio/enriched` augments each stored position with live `current_price`, `current_value`, `unrealised_pnl`, and `return_pct` by calling `extract_quant_indicators()` per ticker (benefits from the 5-min OHLCV cache). This is the endpoint the Portfolio tab's P&L table actually reads.

**Concurrency pattern** — `extract_quant_indicators()` and `extract_fundamentals()` are synchronous blocking yfinance calls. All multi-ticker endpoints (`/api/portfolio/enriched`, `/api/portfolio/insights`, `/api/watchlist/enriched`) and `run_daily_report()` fan them out concurrently via `asyncio.gather(asyncio.to_thread(...))` using module-level sync helpers (`_enrich_position`, `_safe_fundamentals`, `_enrich_watchlist_row`, `_safe_indicators`) defined in `main.py`. Total latency is ≈ the slowest ticker rather than the sum. Each helper owns its own try/except so per-ticker failures still return `None`-filled fallback rows. Do not revert to serial `for` loops — that blocks the event loop.

**Database** (`core/db_manager.py`) — SQLite with three tables created in `init_db()`. `DB_PATH` is monkeypatched in tests via `conftest.py`.
- `transactions(id, ticker, side CHECK IN ('BUY','SELL'), shares, price, fee, trade_date)` — the source of truth for all holdings. Every buy and sell is appended here; the portfolio is **never directly mutated**.
- `portfolio(id, ticker, shares, average_buy_price, date_added)` — legacy table kept only for the one-time migration: if `transactions` is empty on startup and `portfolio` has rows, each row is seeded as an opening BUY transaction.
- `watchlist(id, ticker, date_added)` (insert-or-ignore).

**Cost-basis engine** (`core/cost_basis.py`) — pure, I/O-free. `compute_holding(trades)` folds a chronological list of BUY/SELL dicts into `{shares, average_buy_price, realized_pnl}` using the **average-cost** method: a SELL realizes `(sell_price − avg_cost) × qty − fee`; remaining shares keep the same average cost. `derive_positions(trades_by_ticker)` returns only open holdings (shares > 0). `get_all_positions()` calls this and returns the same shape as before — `id, ticker, shares, average_buy_price, date_added` — plus `realized_pnl`, so all downstream code is unchanged.

**Transaction API** — `POST /api/transactions` records a trade (validates side ∈ {BUY,SELL}, rejects SELL > current holdings); `GET /api/transactions?ticker=` lists trades; `DELETE /api/transactions/{id}` removes one trade (holdings recompute automatically). The Portfolio tab's "History" button opens a per-ticker trade log with per-row delete.

**Watchlist** — `GET/POST/DELETE /api/watchlist` plus `GET /api/watchlist/enriched`, which fetches fundamentals per ticker and returns price, P/E, dividend yield, and the `fair_value` estimate/upside/verdict for an at-a-glance valuation read. Rendered as the Watchlist tab; ticker rows link into the Fundamentals tab.

**Frontend** (`static/index.html` + `static/app.js`) is a vanilla-JS SPA with five sections (Portfolio, Research, Fundamentals, Watchlist, Reports). Uses Tailwind CSS, lightweight-charts (candlestick chart), and marked.js (Markdown rendering) all from CDN. The Fundamentals tab renders metric grids + year-by-year bar charts via a dependency-free `barChart()` helper in `app.js`; the Portfolio tab adds dividend-income + sector-allocation cards. Tooltip system is CSS-only via `.tip` / `data-tip` attribute.

**Scheduled report** fires Mon–Fri 16:15 ET via APScheduler cron job registered in the `lifespan` context manager. Reports are written as `.md` files to `data/reports/` (gitignored). `POST /api/report/trigger` manually fires the same job; `GET /api/report/latest` returns the most recent report file's content.

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

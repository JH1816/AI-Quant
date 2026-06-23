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

**Database** (`core/db_manager.py`) is a thin SQLite wrapper — one table `portfolio(id, ticker, shares, average_buy_price, date_added)` with upsert-on-conflict. `DB_PATH` is monkeypatched in tests via `conftest.py`.

**Frontend** (`static/index.html` + `static/app.js`) is a vanilla-JS SPA with four sections (Portfolio, Research, Fundamentals, Reports). Uses Tailwind CSS, lightweight-charts (candlestick chart), and marked.js (Markdown rendering) all from CDN. The Fundamentals tab renders metric grids + year-by-year bar charts via a dependency-free `barChart()` helper in `app.js`. Tooltip system is CSS-only via `.tip` / `data-tip` attribute.

**Scheduled report** fires Mon–Fri 16:15 ET via APScheduler cron job registered in the `lifespan` context manager. Reports are written as `.md` files to `data/reports/` (gitignored).

## Key constraints

- The `data/` directory (SQLite DB + reports) is gitignored and auto-created at startup.
- yfinance requires `>=1.4.1`; older versions return empty DataFrames against Yahoo's current API.
- The in-process download cache (`core/quant_engine._DOWNLOAD_CACHE`) has a 5-minute TTL and is keyed by `(ticker, period)`. It resets on server restart.
- Fibonacci levels and 52-week high/low are derived from the 1y download window, not a true calendar year.

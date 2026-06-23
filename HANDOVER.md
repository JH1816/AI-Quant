# AI Quant Portfolio Tracker — Session Handover

**Date:** 2026-06-23
**Branch:** `claude/project-qualtrim-improvement-fjml7j` (open as PR #8 against `main`)
**Theme of this work:** make the app more like [Qualtrim](https://qualtrim.com) by adding a fundamentals/valuation/dividend dimension alongside the existing technical analysis.

---

## What This App Does

A FastAPI + vanilla JS single-page app that blends **technical** and **fundamental** analysis:

**Technical analysis**
1. Tracks a stock portfolio (SQLite) with add/remove positions and live P&L
2. Fetches live market data via yfinance and computes quant indicators natively (SMA, RSI, MACD, Bollinger, Fibonacci, volume) plus an Optimum Entry signal — shown in a Technical Metrics Dashboard with plain-English tooltips
3. Runs those indicators through Google Gemini to produce a Markdown trade-analysis report
4. Generates a daily portfolio health report on a schedule (Mon–Fri 16:15 ET)

**Fundamental analysis (Qualtrim-style)**
5. **Fundamentals tab** — company profile, valuation (P/E, PEG, P/S, P/B, EV/EBITDA), profitability/margins, financial health, analyst targets, dividends, and year-by-year financial-statement bar charts (revenue/net income/FCF/EPS/margins)
6. **Fair-value estimate** — blends analyst target, growth-justified P/E (PEG≈1), and dividend yield theory into an Undervalued/Fairly valued/Overvalued verdict
7. **Portfolio insights** — projected dividend income, portfolio yield, and sector allocation
8. **Watchlist** — persisted tickers with an at-a-glance fair-value verdict per row

---

## Project Layout

```
AI-Quant/
├── main.py                  # FastAPI app, all API routes, APScheduler setup
├── requirements.txt         # Runtime deps (see below)
├── requirements-dev.txt     # Dev/test deps
├── .env                     # NOT in git — contains GOOGLE_API_KEY
├── .env.example             # Template: GOOGLE_API_KEY=your_google_api_key_here
├── agents/
│   ├── quant_agent.py       # analyze_ticker(dict) → Markdown report via Gemini
│   └── reporter_agent.py    # generate_portfolio_report(list, dict) → Markdown via Gemini
├── core/
│   ├── quant_engine.py      # extract_quant_indicators(ticker) → dict (TA maths)
│   ├── fundamentals_engine.py # extract_fundamentals(ticker) + _fair_value() (fundamentals/valuation)
│   ├── portfolio_insights.py  # build_portfolio_insights() — dividend income + sector allocation (pure)
│   └── db_manager.py        # SQLite CRUD: portfolio + watchlist tables
├── static/
│   ├── index.html           # SPA shell (5 tabs), Tailwind CSS, tooltip CSS (.tip / data-tip)
│   └── app.js               # All frontend logic: portfolio, research, fundamentals, watchlist, reports
├── data/
│   ├── portfolio.db         # SQLite DB (gitignored, auto-created on first run)
│   └── reports/             # Generated .md reports (gitignored)
└── tests/                   # Unit test suite (pytest)
```

---

## Setup & Running

### Prerequisites
- **Python 3.10+** required
- Virtual env at `.venv/` (not committed)

### First-time setup
```bash
cd "AI-Quant"
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY
```

### Start the server
```bash
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

App is at `http://localhost:8000`

---

## Environment Variables

Only one required variable:

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Google AI Studio API key (get from aistudio.google.com) |

The key format starts with `AQ.` — this is correct for newer Google AI Studio keys.
The `.env` file is gitignored; never commit it.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/portfolio` | List all positions |
| `GET` | `/api/portfolio/enriched` | Positions with live price, P&L, return % |
| `GET` | `/api/portfolio/insights` | Dividend income, portfolio yield, sector allocation |
| `POST` | `/api/portfolio` | Add/update position `{ticker, shares, average_buy_price}` |
| `DELETE` | `/api/portfolio/{ticker}` | Remove position |
| `GET` | `/api/watchlist` | List watchlist tickers |
| `GET` | `/api/watchlist/enriched` | Watchlist with price, P/E, yield, fair-value verdict |
| `POST` | `/api/watchlist` | Add ticker `{ticker}` |
| `DELETE` | `/api/watchlist/{ticker}` | Remove from watchlist |
| `GET` | `/api/indicators/{ticker}` | Raw quant indicators (fast, no LLM call) |
| `GET` | `/api/fundamentals/{ticker}` | Fundamentals, valuation, dividends + fair value (no LLM call) |
| `GET` | `/api/chart/{ticker}?period=6mo` | OHLCV candles + SMA series |
| `GET` | `/api/analyze/{ticker}` | Full AI analysis via Gemini (costs API quota) |
| `POST` | `/api/report/trigger` | Manually trigger daily portfolio health report |
| `GET` | `/api/report/latest` | Fetch the most recently generated report |

Only `/api/analyze` and `/api/report/*` require `GOOGLE_API_KEY`; everything else (fundamentals, valuation, insights, watchlist) is quota-free.

---

## Key Technical Decisions

### No pandas-ta
The `pandas-ta` library's GitHub repo was deleted. All technical indicators are implemented natively in `core/quant_engine.py`:
- `_sma(series, length)` — simple rolling mean
- `_rsi(series, length=14)` — EWM-based Wilder RSI
- `_macd(series, fast=12, slow=26, signal=9)` — returns (macd_line, signal_line, histogram)
- `_bbands(series, length=20, std=2.0)` — returns (upper, middle, lower)

### Optimum Entry Price Logic (`quant_engine.py` lines 103–149)
Collects all support levels below current price (Fib 0.236/0.382/0.500, BB Lower, SMA 50/100/200), sorts descending (nearest support first), then:
- RSI < 35 → **BUY NOW** — enter near market price
- RSI 35–50 → **ACCUMULATE** — target nearest support + 0.5%
- RSI > 50 → **WAIT** — target nearest support − 0.5% (better entry on pullback)

### Tooltip System (index.html)
CSS-only, no JS library. Uses `::before` pseudo-element on `.tip` class with `data-tip` attribute for the tooltip text. Hover the `ⓘ` icon to see the explanation.

### Gemini Model
Both agents use `gemini-3.5-flash` (defined in `agents/config.py` as `MODEL_NAME`). Model is lazy-initialised on first LLM call. To change the model, update `MODEL_NAME` in `agents/config.py`.

### yfinance
Requires `>=1.4.1` — older versions (0.2.x) are broken against Yahoo Finance's current API and return empty DataFrames or JSONDecodeErrors.

---

## Known Limitations / Possible Next Features

- **All data depends on yfinance** — fundamentals (`.info`, statements, dividends) and prices come from Yahoo. Some hosting/CI environments block Yahoo egress; in that case fundamentals endpoints return 404 and the logic is only exercised by the mocked tests.
- **Fair value is a heuristic** — it blends analyst targets, growth-justified P/E (PEG≈1, clamped to an 8–35 band), and dividend yield theory. It's an educational guide, not a DCF; treat the verdict accordingly.
- **`/api/portfolio/insights` and `/api/watchlist/enriched` fetch fundamentals per ticker** — first load for many tickers can be slow until the 1h cache warms.
- **No authentication** — the API is fully open. Fine for local use, needs auth before any deployment.
- **Reports are stored as flat .md files** — no UI to browse past reports, only `/api/report/latest` is exposed.
- **Daily report scheduler** runs at 16:15 ET Mon–Fri but only if the server is running at that time.
- **Free-tier Gemini quota** is low — expect 429 errors under heavy use. The fundamentals/indicators endpoints are quota-free and should be preferred for dashboard-only use.
- **Next ideas:** valuation history bands (P/E over time), CSV import/export, earnings/ex-dividend calendar, and feeding fundamentals into the Gemini agents for a richer report.

---

## Dependencies (requirements.txt)

```
fastapi>=0.110.0
uvicorn>=0.28.0
yfinance>=1.4.1
pandas>=2.0.0
google-generativeai>=0.8.0
APScheduler==3.10.4
python-dotenv==1.0.1
pytz>=2024.1
```

> Note: `requirements.txt` may show `google-genai>=1.0.0` as an alternative package name — both `google-generativeai` and `google-genai` refer to the same SDK. If you see import errors, check which is installed with `pip show google-generativeai`.

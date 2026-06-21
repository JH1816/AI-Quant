# AI Quant Portfolio Tracker — Session Handover

**Date:** 2026-06-21
**Branch:** `main` (clean, pushed to `github.com/JH1816/AI-Quant`)
**Last commit:** `7e4e3aa` — feat: migrate to Google Gemini API and add Technical Metrics Dashboard

---

## What This App Does

A FastAPI + vanilla JS single-page app that:
1. Tracks a stock portfolio (SQLite) with add/remove positions
2. Fetches live market data via yfinance and computes quant indicators natively
3. Runs those indicators through Google Gemini (gemini-2.0-flash) to produce a Markdown trade analysis report
4. Generates a daily portfolio health report on a schedule (Mon–Fri 16:15 ET)
5. Shows a **Technical Metrics Dashboard** with RSI, MACD, Bollinger Bands, Fibonacci levels, volume profile, and an Optimum Entry price signal — all with plain-English tooltip explanations for non-quant users

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
│   ├── quant_engine.py      # extract_quant_indicators(ticker) → dict (all maths live here)
│   └── db_manager.py        # SQLite CRUD: init_db, add_position, remove_position, get_all_positions
├── static/
│   ├── index.html           # SPA shell, Tailwind CSS, tooltip CSS (.tip / data-tip)
│   └── app.js               # All frontend logic: portfolio table, metrics dashboard, AI analysis
├── data/
│   ├── portfolio.db         # SQLite DB (gitignored, auto-created on first run)
│   └── reports/             # Generated .md reports (gitignored)
└── tests/                   # Unit test suite (pytest)
```

---

## Setup & Running

### Prerequisites
- **Python 3.12+** required (google-generativeai does not support Python 3.8)
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
| `POST` | `/api/portfolio` | Add/update position `{ticker, shares, average_buy_price}` |
| `DELETE` | `/api/portfolio/{ticker}` | Remove position |
| `GET` | `/api/indicators/{ticker}` | Raw quant indicators (fast, no LLM call) |
| `GET` | `/api/analyze/{ticker}` | Full AI analysis via Gemini (costs API quota) |
| `POST` | `/api/report/trigger` | Manually trigger daily portfolio health report |
| `GET` | `/api/report/latest` | Fetch the most recently generated report |

---

## Key Technical Decisions

### No pandas-ta
The `pandas-ta` library's GitHub repo was deleted. All technical indicators are implemented natively in `core/quant_engine.py`:
- `_sma(series, length)` — simple rolling mean
- `_rsi(series, length=14)` — EWM-based Wilder RSI
- `_macd(series, fast=12, slow=26, signal=9)` — returns (macd_line, signal_line, histogram)
- `_bbands(series, length=5, std=2.0)` — returns (upper, middle, lower)

### Optimum Entry Price Logic (`quant_engine.py` lines 103–149)
Collects all support levels below current price (Fib 0.236/0.382/0.500, BB Lower, SMA 50/100/200), sorts descending (nearest support first), then:
- RSI < 35 → **BUY NOW** — enter near market price
- RSI 35–50 → **ACCUMULATE** — target nearest support + 0.5%
- RSI > 50 → **WAIT** — target nearest support − 0.5% (better entry on pullback)

### Tooltip System (index.html)
CSS-only, no JS library. Uses `::before` pseudo-element on `.tip` class with `data-tip` attribute for the tooltip text. Hover the `ⓘ` icon to see the explanation.

### Gemini Model
Both agents use `gemini-2.0-flash`. Model is initialised once at module load with a `system_instruction`. If you want to upgrade to a newer model, change `model_name` in both `agents/quant_agent.py` and `agents/reporter_agent.py`.

### yfinance
Requires `>=1.4.1` — older versions (0.2.x) are broken against Yahoo Finance's current API and return empty DataFrames or JSONDecodeErrors.

---

## Known Limitations / Possible Next Features

- **Bollinger Band window is 5 days** (short-term, more reactive). Standard is 20 days — consider making this configurable.
- **No authentication** — the API is fully open. Fine for local use, needs auth before any deployment.
- **No price-paid P&L** — the portfolio table shows positions but doesn't compute unrealised P&L vs. average buy price.
- **Reports are stored as flat .md files** — no UI to browse past reports, only `/api/report/latest` is exposed.
- **Daily report scheduler** runs at 16:15 ET Mon–Fri but only if the server is running at that time.
- **Free-tier Gemini quota** is low — expect 429 errors under heavy use. The `/api/indicators/{ticker}` endpoint is quota-free and should be preferred for dashboard-only use.

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

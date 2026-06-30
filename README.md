# AI Quant

A personal quantitative research and portfolio management dashboard powered by FastAPI, yfinance, and Google Gemini.

## Features

- **Research tab** — candlestick chart, technical indicators (RSI, MACD, Bollinger Bands, Fibonacci, SMA 50/100/200), and AI-generated analysis via Gemini
- **Fundamentals tab** — valuation multiples, profitability metrics, dividend history, fair-value estimate, and multi-year financial charts
- **Portfolio tab** — transaction log (BUY/SELL), live P&L, equity curve vs cost-basis, dividend income, sector allocation, and risk metrics (Sharpe, Sortino, beta, correlation heatmap)
- **Watchlist tab** — at-a-glance valuation with fair-value verdict per ticker
- **Compare tab** — side-by-side fundamental comparison for 2–4 tickers
- **Reports tab** — on-demand or scheduled AI portfolio health report

## Setup

```bash
# Clone and create a virtual environment
git clone <repo-url>
cd AI-Quant
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Create .env with your Google AI Studio API key
echo "GOOGLE_API_KEY=your_key_here" > .env

# Run the app
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser.

## API Key

Get a free key at **aistudio.google.com** → Get API key. Keys with the `AQ.` prefix (the current Google AI Studio format) are supported.

The key is only required for the AI Analysis (`/api/analyze`) and Report (`/api/report/*`) endpoints. All other tabs work without it.

## Market-data sources

Price and fundamentals data flows through a pluggable provider layer
(`core/data_providers.py`). By default Yahoo (yfinance) is the primary source with
**Stooq** (keyless) as an automatic fallback when Yahoo rate-limits or returns no
data. Configure via `.env`:

```bash
DATA_PROVIDER=yahoo                 # primary: yahoo | stooq | alphavantage
DATA_PROVIDER_FALLBACKS=stooq       # comma-separated, tried in order
ALPHAVANTAGE_API_KEY=your_key_here  # only needed if alphavantage is used
```

Stooq serves prices only; Alpha Vantage serves both prices and fundamentals (free
key at alphavantage.co). Fundamentals automatically fall back to Yahoo when the
selected provider can't serve them. The indicator, risk and charting code is
source-agnostic — it consumes the normalised shapes the provider layer returns.

## Tech Stack

| Layer | Library |
|---|---|
| Backend | FastAPI + Uvicorn |
| Market data | Pluggable: yfinance (Yahoo) / Stooq / Alpha Vantage |
| LLM | Google Gemini via `google-genai` SDK |
| Database | SQLite (`core/db_manager.py`) |
| Scheduler | APScheduler |
| Frontend | Vanilla JS SPA + Tailwind CSS (CDN) |

## Running Tests

```bash
pytest -q
```

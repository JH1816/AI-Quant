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

## Tech Stack

| Layer | Library |
|---|---|
| Backend | FastAPI + Uvicorn |
| Market data | yfinance |
| LLM | Google Gemini via `google-genai` SDK |
| Database | SQLite (`core/db_manager.py`) |
| Scheduler | APScheduler |
| Frontend | Vanilla JS SPA + Tailwind CSS (CDN) |

## Running Tests

```bash
pytest -q
```

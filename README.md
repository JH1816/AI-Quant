# AI Quant Portfolio Tracker

An AI-driven portfolio research web application that blends **technical** and **fundamental** analysis in one clean single-page dashboard. It combines real-time market data, technical indicators, Qualtrim-style fundamentals (financial statements, valuation, dividends, fair value), and the Google Gemini API for per-ticker trade analysis and daily portfolio health reports.

---

## Features

### Technical analysis
- **Interactive Price Chart** — Candlestick chart with SMA 50/100/200 overlays and a color-coded volume histogram. Switch between 1M, 3M, 6M, 1Y, and 2Y views instantly.
- **Quantitative Engine** — Fetches daily price data via yfinance and computes SMA (50/100/200), RSI-14, MACD, Bollinger Bands, Fibonacci retracement levels, volume vs. 20-day MA, and an optimum entry price signal.
- **AI Stock Analysis** — Sends computed indicators to Gemini acting as a Senior Quant Trader, returning a structured Markdown report with entry points, stop-losses, targets, and risk-reward ratios.

### Fundamental analysis (Qualtrim-style)
- **Company Fundamentals** — Profile, valuation (P/E, forward P/E, PEG, P/S, P/B, EV/EBITDA), profitability/margins (gross/operating/net, ROE, ROA), financial health (cash, debt, current ratio, FCF), and analyst targets.
- **Financial Statements** — Year-by-year bar charts for revenue, net income, gross/operating income, free cash flow, EPS, and net margin.
- **Fair-Value Estimate** — Blends analyst targets, growth-justified P/E (PEG≈1), and dividend yield theory into a single estimate with an **Undervalued / Fairly valued / Overvalued** verdict and % upside.
- **Dividends** — Yield, annual rate, payout ratio, 5-year growth (CAGR), and per-share payout history.

### Portfolio & watchlist
- **Portfolio Management** — Record buys and sells as transactions (average-cost accounting); live unrealised P&L, return %, and realized P&L on every load.
- **Portfolio Equity Curve** — Historical line chart showing total portfolio value vs. cost basis, reconstructed day-by-day from the transaction log.
- **Portfolio Insights** — Projected annual/monthly **dividend income**, portfolio yield, top income contributors, and a **sector-allocation** breakdown.
- **Watchlist** — Track tickers with an at-a-glance fair-value verdict, price, P/E, and yield per row.
- **Daily Portfolio Reports** — Holistic health summary across all holdings, scheduled Mon–Fri at 16:15 ET and available on demand.

### Platform
- **Web Dashboard** — Responsive light/dark-theme SPA built with Tailwind CSS and vanilla JavaScript; renders AI Markdown output via marked.js and financial charts via a dependency-free bar-chart helper.

---

## Screenshots

> Load a ticker in the Technical Metrics Dashboard to see the candlestick chart, SMA overlays, volume pane, and full indicator breakdown.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Data | yfinance, pandas |
| LLM | Google Gemini API (`google-generativeai`) |
| Database | SQLite3 |
| Scheduler | APScheduler |
| Frontend | Tailwind CSS (CDN), lightweight-charts (CDN), marked.js (CDN), Vanilla JS |

---

## Project Structure

```
AI-Quant/
├── data/
│   ├── portfolio.db          # SQLite database (auto-created)
│   └── reports/              # Generated Markdown reports
├── core/
│   ├── db_manager.py         # Database CRUD (portfolio + watchlist)
│   ├── quant_engine.py       # Technical indicator calculations
│   ├── fundamentals_engine.py# Fundamentals + fair-value estimate
│   └── portfolio_insights.py # Dividend income + sector allocation
├── agents/
│   ├── quant_agent.py        # Per-ticker LLM analysis
│   └── reporter_agent.py     # Portfolio-wide LLM report
├── static/
│   ├── index.html            # Single-page application
│   └── app.js                # Frontend logic and API calls
├── main.py                   # FastAPI app + API routes + scheduler
├── requirements.txt
└── .env                      # API keys (not committed)
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- A [Google AI Studio API key](https://aistudio.google.com/app/apikey)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/JH1816/AI-Quant.git
cd AI-Quant

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set your GOOGLE_API_KEY
```

### Running

```bash
uvicorn main:app --reload
```

Open `http://localhost:8000` in your browser.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/portfolio` | List all active positions |
| `GET` | `/api/portfolio/enriched` | Positions with live price, P&L, and return % |
| `GET` | `/api/portfolio/insights` | Dividend income, portfolio yield, and sector allocation |
| `GET` | `/api/portfolio/chart` | Historical equity curve (portfolio value vs. cost basis) |
| `POST` | `/api/portfolio` | Add or update a position |
| `DELETE` | `/api/portfolio/{ticker}` | Remove a position |
| `GET` | `/api/transactions` | List all transactions (optional `?ticker=` filter) |
| `POST` | `/api/transactions` | Record a BUY or SELL trade |
| `DELETE` | `/api/transactions/{id}` | Delete a transaction (holdings recompute automatically) |
| `GET` | `/api/watchlist` | List watchlist tickers |
| `GET` | `/api/watchlist/enriched` | Watchlist with price, P/E, yield, and fair-value verdict |
| `POST` | `/api/watchlist` | Add a ticker to the watchlist |
| `DELETE` | `/api/watchlist/{ticker}` | Remove a ticker from the watchlist |
| `GET` | `/api/indicators/{ticker}` | Full technical indicator snapshot |
| `GET` | `/api/fundamentals/{ticker}` | Fundamentals, valuation, dividends + fair-value estimate |
| `GET` | `/api/chart/{ticker}?period=6mo` | OHLCV candles + SMA series for charting |
| `GET` | `/api/analyze/{ticker}` | Run AI analysis on a ticker |
| `POST` | `/api/report/trigger` | Generate a portfolio report now |
| `GET` | `/api/report/latest` | Fetch the most recent report |

**Chart period options:** `1mo`, `3mo`, `6mo`, `1y`, `2y`

> Fundamentals, valuation, dividends, portfolio insights, and the watchlist all work **without** a Gemini key — only `/api/analyze` and `/api/report/*` require `GOOGLE_API_KEY`.

### Example — Add a Position

```bash
curl -X POST http://localhost:8000/api/portfolio \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "shares": 10, "average_buy_price": 175.50}'
```

### Example — Fetch Chart Data

```bash
curl "http://localhost:8000/api/chart/AAPL?period=6mo"
```

---

## Scheduled Reports

The scheduler fires automatically at **16:15 EST, Monday through Friday**. Reports are written as Markdown files to `data/reports/` and are accessible via the dashboard. Trigger a report manually at any time from the UI or via:

```bash
curl -X POST http://localhost:8000/api/report/trigger
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Your Google AI Studio API key |

---

## License

MIT

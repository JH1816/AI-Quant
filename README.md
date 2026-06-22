# AI Quant Portfolio Tracker

An AI-driven quantitative portfolio monitoring web application. It combines real-time market data, technical analysis indicators, and the Google Gemini API to deliver per-ticker trade analysis, interactive price charts, and daily portfolio health reports — all from a clean single-page dashboard.

---

## Features

- **Portfolio Management** — Add, update, and remove stock positions stored in a local SQLite database, with live P&L and return % calculated on every load.
- **Interactive Price Chart** — Candlestick chart with SMA 50/100/200 overlays and a color-coded volume histogram. Switch between 1M, 3M, 6M, 1Y, and 2Y views instantly.
- **Quantitative Engine** — Fetches daily price data via yfinance and computes SMA (50/100/200), RSI-14, MACD, Bollinger Bands, Fibonacci retracement levels, volume vs. 20-day MA, and an optimum entry price signal.
- **AI Stock Analysis** — Sends computed indicators to Gemini acting as a Senior Quant Trader, returning a structured Markdown report with entry points, stop-losses, targets, and risk-reward ratios.
- **Daily Portfolio Reports** — Holistic portfolio health summary across all active holdings, automatically scheduled Mon–Fri at 16:15 EST and available on demand from the dashboard.
- **Web Dashboard** — Responsive dark-mode SPA built with Tailwind CSS and vanilla JavaScript; renders AI Markdown output via marked.js.

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
│   ├── db_manager.py         # Database CRUD operations
│   └── quant_engine.py       # Technical indicator calculations
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

- Python 3.11+
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
| `POST` | `/api/portfolio` | Add or update a position |
| `DELETE` | `/api/portfolio/{ticker}` | Remove a position |
| `GET` | `/api/indicators/{ticker}` | Full technical indicator snapshot |
| `GET` | `/api/chart/{ticker}?period=6mo` | OHLCV candles + SMA series for charting |
| `GET` | `/api/analyze/{ticker}` | Run AI analysis on a ticker |
| `POST` | `/api/report/trigger` | Generate a portfolio report now |
| `GET` | `/api/report/latest` | Fetch the most recent report |

**Chart period options:** `1mo`, `3mo`, `6mo`, `1y`, `2y`

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

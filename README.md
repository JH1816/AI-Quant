# AI Quant Portfolio Tracker

An AI-driven quantitative portfolio monitoring web application. It combines real-time market data, technical analysis indicators, and the Anthropic Claude API to deliver per-ticker trade analysis and daily portfolio health reports — all from a clean single-page dashboard.

---

## Features

- **Portfolio Management** — Add, update, and remove stock positions stored in a local SQLite database.
- **Quantitative Engine** — Automatically fetches 1 year of daily price data via yfinance and computes SMA (50/100/200), RSI-14, MACD, Bollinger Bands, Fibonacci retracement levels, and volume vs. 20-day MA.
- **AI Stock Analysis** — Sends computed indicators to Claude (`claude-3-5-sonnet-20240620`) acting as a Senior Quant Trader, returning a structured Markdown report with entry points, stop-losses, and risk-reward ratios.
- **Daily Portfolio Reports** — Generates a holistic portfolio health summary across all active holdings, automatically scheduled Mon–Fri at 16:15 EST and available on demand.
- **Web Dashboard** — Responsive dark-mode SPA built with Tailwind CSS and vanilla JavaScript; renders AI Markdown output via marked.js.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Data | yfinance, pandas, pandas-ta |
| LLM | Anthropic SDK (direct, no framework) |
| Database | SQLite3 |
| Scheduler | APScheduler |
| Frontend | Tailwind CSS (CDN), marked.js (CDN), Vanilla JS |

---

## Project Structure

```
ai-quant-portfolio/
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
├── main.py                   # FastAPI app + scheduler
├── requirements.txt
└── .env                      # API key (not committed)
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/JH1816/AI-Quan.git
cd AI-Quan

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set your ANTHROPIC_API_KEY
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
| `POST` | `/api/portfolio` | Add or update a position |
| `DELETE` | `/api/portfolio/{ticker}` | Remove a position |
| `GET` | `/api/analyze/{ticker}` | Run AI analysis on a ticker |
| `POST` | `/api/report/trigger` | Generate a portfolio report now |
| `GET` | `/api/report/latest` | Fetch the most recent report |

### Example — Add a Position

```bash
curl -X POST http://localhost:8000/api/portfolio \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "shares": 10, "average_buy_price": 175.50}'
```

---

## Scheduled Reports

The scheduler fires automatically at **16:15 EST, Monday through Friday**. Reports are written as Markdown files to `data/reports/` and are also accessible via the dashboard. You can trigger a report manually at any time from the UI or via `POST /api/report/trigger`.

---

## Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

---

## License

MIT

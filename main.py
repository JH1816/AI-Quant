import os
import json
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from core.db_manager import (
    init_db, add_position, remove_position, get_all_positions,
    add_to_watchlist, remove_from_watchlist, get_watchlist,
    add_transaction, get_transactions, delete_transaction,
)
from core.quant_engine import extract_quant_indicators, _safe, _sma, _fetch_ohlcv
from core.fundamentals_engine import extract_fundamentals
from core.portfolio_insights import build_portfolio_insights
from agents.quant_agent import analyze_ticker
from agents.reporter_agent import generate_portfolio_report

load_dotenv()

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "data", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

scheduler = AsyncIOScheduler()


async def run_daily_report():
    """Fetch quant data for every holding and write the report to disk."""
    positions = get_all_positions()
    if not positions:
        return

    results = await asyncio.gather(
        *(asyncio.to_thread(_safe_indicators, pos["ticker"]) for pos in positions)
    )
    market_data = {pos["ticker"]: res for pos, res in zip(positions, results)}

    report_md = generate_portfolio_report(positions, market_data)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORTS_DIR, f"report_{ts}.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report_md)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Run Monday–Friday at 16:15 Eastern (handles EST/EDT automatically)
    scheduler.add_job(
        run_daily_report,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=15, timezone="America/New_York"),
        id="daily_report",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="AI Quant Portfolio Tracker", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PositionIn(BaseModel):
    ticker: str
    shares: float
    average_buy_price: float


class TickerIn(BaseModel):
    ticker: str


class TransactionIn(BaseModel):
    ticker: str
    side: str
    shares: float
    price: float
    fee: float = 0.0
    trade_date: str | None = None


# ─── Concurrency helpers ──────────────────────────────────────────────────────
# The per-ticker data functions (extract_quant_indicators / extract_fundamentals)
# are synchronous, blocking yfinance calls. Fanning them out across the default
# thread pool keeps the event loop free and makes total latency ≈ the slowest
# ticker rather than the sum. gather preserves input order.

async def _gather_blocking(func, items):
    """Run blocking func(item) for each item concurrently in threads, order preserved."""
    return await asyncio.gather(*(asyncio.to_thread(func, item) for item in items))


def _enrich_position(pos: dict) -> dict:
    """Augment a stored position with live price/value/PnL, or None fields on failure."""
    try:
        ind = extract_quant_indicators(pos["ticker"])
        cp  = ind["latest_close"]
        return {
            **pos,
            "current_price":  round(cp, 2),
            "current_value":  round(cp * pos["shares"], 2),
            "unrealised_pnl": round((cp - pos["average_buy_price"]) * pos["shares"], 2),
            "return_pct":     round((cp / pos["average_buy_price"] - 1) * 100, 2),
            "realized_pnl":   pos.get("realized_pnl", 0.0),
        }
    except Exception:
        return {
            **pos,
            "current_price":  None,
            "current_value":  None,
            "unrealised_pnl": None,
            "return_pct":     None,
            "realized_pnl":   pos.get("realized_pnl", 0.0),
        }


def _safe_fundamentals(ticker: str):
    """extract_fundamentals(ticker) or None on failure."""
    try:
        return extract_fundamentals(ticker)
    except Exception:
        return None


def _safe_indicators(ticker: str) -> dict:
    """extract_quant_indicators(ticker) or an {"error": ...} marker on failure."""
    try:
        return extract_quant_indicators(ticker)
    except Exception as exc:
        return {"error": str(exc)}


def _enrich_watchlist_row(row: dict) -> dict:
    """Build the at-a-glance watchlist row, or a None-filled fallback on failure."""
    ticker = row["ticker"]
    try:
        f = extract_fundamentals(ticker)
        fv = f["valuation"].get("fair_value") or {}
        return {
            "ticker": ticker,
            "name": f["profile"].get("name"),
            "sector": f["profile"].get("sector"),
            "price": f["price"].get("current"),
            "trailing_pe": f["valuation"].get("trailing_pe"),
            "dividend_yield_pct": f["dividends"].get("yield_pct"),
            "fair_value": fv.get("estimate"),
            "upside_pct": fv.get("upside_pct"),
            "verdict": fv.get("verdict"),
            "date_added": row["date_added"],
        }
    except Exception:
        return {
            "ticker": ticker, "name": None, "sector": None, "price": None,
            "trailing_pe": None, "dividend_yield_pct": None, "fair_value": None,
            "upside_pct": None, "verdict": None, "date_added": row["date_added"],
        }


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/portfolio")
async def get_portfolio():
    return get_all_positions()


@app.get("/api/portfolio/enriched")
async def get_portfolio_enriched():
    return await _gather_blocking(_enrich_position, get_all_positions())


@app.get("/api/portfolio/insights")
async def portfolio_insights():
    positions = get_all_positions()
    results = await _gather_blocking(lambda p: _safe_fundamentals(p["ticker"]), positions)
    data_by_ticker = {pos["ticker"]: res for pos, res in zip(positions, results)}
    return build_portfolio_insights(positions, data_by_ticker)


@app.post("/api/portfolio", status_code=201)
async def create_position(body: PositionIn):
    try:
        add_position(body.ticker, body.shares, body.average_buy_price)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": f"Position {body.ticker.upper()} saved."}


@app.delete("/api/portfolio/{ticker}")
async def delete_position(ticker: str):
    remove_position(ticker)
    return {"message": f"Position {ticker.upper()} removed."}


# ─── Transaction routes ───────────────────────────────────────────────────────

@app.post("/api/transactions", status_code=201)
async def create_transaction(body: TransactionIn):
    side = body.side.upper()
    if side not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL.")
    if body.shares <= 0 or body.price <= 0:
        raise HTTPException(status_code=400, detail="shares and price must be positive.")
    if body.fee < 0:
        raise HTTPException(status_code=400, detail="fee cannot be negative.")

    if side == "SELL":
        holdings = {p["ticker"]: p["shares"] for p in get_all_positions()}
        available = holdings.get(body.ticker.upper(), 0.0)
        if body.shares > available + 1e-9:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot sell {body.shares} shares — only {available} held.",
            )

    try:
        tx_id = add_transaction(
            body.ticker, side, body.shares, body.price,
            body.fee, body.trade_date,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": f"{side} {body.shares} {body.ticker.upper()} recorded.", "id": tx_id}


@app.get("/api/transactions")
async def list_transactions(ticker: str | None = None):
    return get_transactions(ticker)


@app.delete("/api/transactions/{tx_id}")
async def remove_transaction(tx_id: int):
    delete_transaction(tx_id)
    return {"message": f"Transaction {tx_id} deleted."}


@app.get("/api/watchlist")
async def list_watchlist():
    return get_watchlist()


@app.get("/api/watchlist/enriched")
async def list_watchlist_enriched():
    return await _gather_blocking(_enrich_watchlist_row, get_watchlist())


@app.post("/api/watchlist", status_code=201)
async def create_watchlist_item(body: TickerIn):
    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required.")
    add_to_watchlist(ticker)
    return {"message": f"{ticker} added to watchlist."}


@app.delete("/api/watchlist/{ticker}")
async def delete_watchlist_item(ticker: str):
    remove_from_watchlist(ticker)
    return {"message": f"{ticker.upper()} removed from watchlist."}


@app.get("/api/chart/{ticker}")
async def get_chart(ticker: str, period: str = "6mo"):
    ALLOWED_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y"}
    if period not in ALLOWED_PERIODS:
        period = "6mo"

    ticker = ticker.upper()
    df = _fetch_ohlcv(ticker, period)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for '{ticker}'")

    def _r(v):
        f = _safe(v)
        return round(f, 4) if f is not None else None

    close = df["Close"]
    sma50  = _sma(close, 50)
    sma100 = _sma(close, 100)
    sma200 = _sma(close, 200)

    candles, vol_series = [], []
    sma50_series, sma100_series, sma200_series = [], [], []

    for ts, row in df.iterrows():
        date_str = ts.strftime("%Y-%m-%d")
        o, h, l, c = _r(row["Open"]), _r(row["High"]), _r(row["Low"]), _r(row["Close"])
        v = _r(row["Volume"])
        if None not in (o, h, l, c):
            candles.append({"time": date_str, "open": o, "high": h, "low": l, "close": c})
        if v is not None:
            color = "#26a69a" if (c or 0) >= (o or 0) else "#ef5350"
            vol_series.append({"time": date_str, "value": v, "color": color})

    for ts, val in sma50.items():
        v = _r(val)
        if v is not None:
            sma50_series.append({"time": ts.strftime("%Y-%m-%d"), "value": v})
    for ts, val in sma100.items():
        v = _r(val)
        if v is not None:
            sma100_series.append({"time": ts.strftime("%Y-%m-%d"), "value": v})
    for ts, val in sma200.items():
        v = _r(val)
        if v is not None:
            sma200_series.append({"time": ts.strftime("%Y-%m-%d"), "value": v})

    return {
        "ticker": ticker,
        "period": period,
        "candles": candles,
        "volume": vol_series,
        "sma50": sma50_series,
        "sma100": sma100_series,
        "sma200": sma200_series,
    }


@app.get("/api/indicators/{ticker}")
async def get_indicators(ticker: str):
    try:
        return extract_quant_indicators(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Data fetch error: {exc}")


@app.get("/api/fundamentals/{ticker}")
async def get_fundamentals(ticker: str):
    try:
        return extract_fundamentals(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Data fetch error: {exc}")


@app.get("/api/analyze/{ticker}")
async def analyze(ticker: str):
    try:
        indicators = extract_quant_indicators(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Data fetch error: {exc}")

    try:
        report_md = analyze_ticker(indicators)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM error: {exc}")

    return {"ticker": ticker.upper(), "report": report_md}


@app.post("/api/report/trigger")
async def trigger_report():
    positions = get_all_positions()
    if not positions:
        raise HTTPException(status_code=400, detail="No positions in portfolio.")

    market_data = {}
    for pos in positions:
        try:
            market_data[pos["ticker"]] = extract_quant_indicators(pos["ticker"])
        except Exception as exc:
            market_data[pos["ticker"]] = {"error": str(exc)}

    try:
        report_md = generate_portfolio_report(positions, market_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM error: {exc}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORTS_DIR, f"report_{ts}.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report_md)

    return {"message": "Report generated.", "file": os.path.basename(report_path), "report": report_md}


@app.get("/api/report/latest")
async def latest_report():
    files = sorted(
        [f for f in os.listdir(REPORTS_DIR) if f.endswith(".md")],
        reverse=True,
    )
    if not files:
        return {"report": None}
    with open(os.path.join(REPORTS_DIR, files[0]), encoding="utf-8") as fh:
        return {"file": files[0], "report": fh.read()}


# ─── Static SPA (must be mounted last) ───────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")

import os
import json
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

from core.db_manager import init_db, add_position, remove_position, get_all_positions
from core.quant_engine import extract_quant_indicators
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

    market_data = {}
    for pos in positions:
        try:
            market_data[pos["ticker"]] = extract_quant_indicators(pos["ticker"])
        except Exception as exc:
            market_data[pos["ticker"]] = {"error": str(exc)}

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


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/portfolio")
async def get_portfolio():
    return get_all_positions()


@app.get("/api/portfolio/enriched")
async def get_portfolio_enriched():
    positions = get_all_positions()
    enriched = []
    for pos in positions:
        try:
            ind = extract_quant_indicators(pos["ticker"])
            cp  = ind["latest_close"]
            enriched.append({
                **pos,
                "current_price":  round(cp, 2),
                "current_value":  round(cp * pos["shares"], 2),
                "unrealised_pnl": round((cp - pos["average_buy_price"]) * pos["shares"], 2),
                "return_pct":     round((cp / pos["average_buy_price"] - 1) * 100, 2),
            })
        except Exception:
            enriched.append({
                **pos,
                "current_price":  None,
                "current_value":  None,
                "unrealised_pnl": None,
                "return_pct":     None,
            })
    return enriched


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


@app.get("/api/indicators/{ticker}")
async def get_indicators(ticker: str):
    try:
        return extract_quant_indicators(ticker)
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

import json
import os

import google.generativeai as genai
from dotenv import load_dotenv

from agents.config import MODEL_NAME

load_dotenv()

_SYSTEM_PROMPT = """You are a Chief Portfolio Risk Officer responsible for daily end-of-day portfolio health summaries.

Given a list of active holdings with their latest quant indicators, produce a holistic **Daily Portfolio Health Report** in Markdown with the following structure:

1. **Executive Summary** – One paragraph overview of today's portfolio posture.
2. **Holdings Breakdown** – For each ticker: current price, day-over-day context, key signal (BULLISH/BEARISH/NEUTRAL).
3. **Risk Assessment**
   - Portfolio concentration risks
   - Positions showing RSI extremes (>70 overbought, <30 oversold)
   - Positions trading below SMA 200 (structural downtrend risk)
4. **Recommended Actions** – Prioritised list of positions to review, trim, or hold.
5. **Market Breadth Notes** – Cross-portfolio volume trends and overall momentum sentiment.
6. **Conclusion** – Overall portfolio health score (1–10) with a one-sentence justification.

Be precise, reference actual numbers, and keep the report actionable."""

_model = None


def _get_model():
    global _model
    if _model is None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set — required for portfolio reports. "
                "Add it to your .env file."
            )
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=_SYSTEM_PROMPT,
        )
    return _model


def generate_portfolio_report(portfolio_data: list, market_data: dict) -> str:
    model = _get_model()
    content = (
        "Please generate today's Daily Portfolio Health Report based on the following data.\n\n"
        f"**Active Holdings (database positions):**\n```json\n{json.dumps(portfolio_data, indent=2)}\n```\n\n"
        f"**Live Market & Quant Indicators:**\n```json\n{json.dumps(market_data, indent=2)}\n```"
    )
    try:
        response = model.generate_content(content)
    except Exception as exc:
        msg = str(exc)
        if "429" in msg or "quota" in msg.lower() or "resource exhausted" in msg.lower():
            raise RuntimeError("Gemini API quota exceeded — try again later.") from exc
        raise RuntimeError(f"Gemini API error: {msg}") from exc

    if not getattr(response, "candidates", None):
        raise RuntimeError(
            "Gemini returned an empty or blocked response — safety filters may have triggered."
        )
    return response.text

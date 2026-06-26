import json
import os

from google import genai
from google.genai import types
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

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set — required for portfolio reports. "
                "Add it to your .env file."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def generate_portfolio_report(portfolio_data: list, market_data: dict) -> str:
    client = _get_client()
    content = (
        "Please generate today's Daily Portfolio Health Report based on the following data.\n\n"
        f"**Active Holdings (database positions):**\n```json\n{json.dumps(portfolio_data, indent=2)}\n```\n\n"
        f"**Live Market & Quant Indicators:**\n```json\n{json.dumps(market_data, indent=2)}\n```"
    )
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
            ),
        )
    except Exception as exc:
        msg = str(exc)
        if "429" in msg or "quota" in msg.lower() or "resource exhausted" in msg.lower():
            raise RuntimeError("Gemini API quota exceeded — try again later.") from exc
        raise RuntimeError(f"Gemini API error: {msg}") from exc

    if not response.text:
        raise RuntimeError(
            "Gemini returned an empty or blocked response — safety filters may have triggered."
        )
    return response.text

import json
import os

import google.generativeai as genai
from dotenv import load_dotenv

from agents.config import MODEL_NAME

load_dotenv()

_SYSTEM_PROMPT = """You are a Senior Quantitative Trader with 20+ years of experience at top-tier hedge funds.
You specialise in technical analysis, risk management, and systematic trading strategies.

When given a quantitative data dictionary for a stock you will produce a structured Markdown report covering:

1. **Market Context** – Brief interpretation of price vs. moving averages (SMA 50/100/200).
2. **Momentum Analysis** – RSI reading, MACD crossover signal, and histogram direction.
3. **Volatility & Band Analysis** – Bollinger Band position, squeeze potential.
4. **Key Price Levels** – Fibonacci support/resistance levels relevant right now.
5. **Volume Profile** – Whether recent volume confirms or diverges from price action.
6. **Trade Setup**
   - Entry point(s) with rationale
   - Stop-loss level with rationale
   - Target(s) and risk-reward ratio
7. **Overall Signal** – BULLISH / BEARISH / NEUTRAL with confidence (High/Medium/Low).

Be concise, precise, and data-driven. Always reference the actual numbers from the data provided."""

_model = None


def _get_model():
    global _model
    if _model is None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set — required for AI analysis. "
                "Add it to your .env file."
            )
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=_SYSTEM_PROMPT,
        )
    return _model


def analyze_ticker(indicator_dict: dict) -> str:
    model = _get_model()
    try:
        response = model.generate_content(
            "Please analyse the following quantitative data and produce your full report:\n\n"
            f"```json\n{json.dumps(indicator_dict, indent=2)}\n```"
        )
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

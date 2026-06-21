import json
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

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

_model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=_SYSTEM_PROMPT,
)


def generate_portfolio_report(portfolio_data: list, market_data: dict) -> str:
    content = (
        "Please generate today's Daily Portfolio Health Report based on the following data.\n\n"
        f"**Active Holdings (database positions):**\n```json\n{json.dumps(portfolio_data, indent=2)}\n```\n\n"
        f"**Live Market & Quant Indicators:**\n```json\n{json.dumps(market_data, indent=2)}\n```"
    )
    response = _model.generate_content(content)
    return response.text

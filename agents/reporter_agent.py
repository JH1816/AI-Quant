import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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


def generate_portfolio_report(portfolio_data: list, market_data: dict) -> str:
    content = (
        "Please generate today's Daily Portfolio Health Report based on the following data.\n\n"
        f"**Active Holdings (database positions):**\n```json\n{portfolio_data}\n```\n\n"
        f"**Live Market & Quant Indicators:**\n```json\n{market_data}\n```"
    )

    message = _client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=3000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text

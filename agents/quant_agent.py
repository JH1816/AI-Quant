import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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


def analyze_ticker(indicator_dict: dict) -> str:
    message = _client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Please analyse the following quantitative data and produce your full report:\n\n"
                    f"```json\n{indicator_dict}\n```"
                ),
            }
        ],
    )
    return message.content[0].text

"""
notifier.py
Sends a Telegram message when automation_runner.py finishes a cycle.
Deliberately minimal — one POST request, no SDK dependency — since this
is the entire feature surface we need.

Setup (one-time, ~2 minutes):
  1. Open Telegram, message @BotFather, send /newbot, follow the prompts.
     BotFather gives you a token like "123456789:AAH...".
  2. Message your new bot anything (so it's allowed to message you back),
     then open https://api.telegram.org/bot<TOKEN>/getUpdates in a browser
     — your chat_id is the number in "chat":{"id": ...}.
  3. Pass both to automation_runner.py via --telegram-token / --telegram-chat-id,
     or the TELEGRAM_TOKEN / TELEGRAM_CHAT_ID environment variables.
"""

import requests

API_BASE = "https://api.telegram.org"


def send_telegram_message(token: str, chat_id: str, message: str, api_base: str = API_BASE) -> dict:
    """Raises requests.HTTPError on failure (bad token, bot blocked, etc.) —
    the caller decides whether that should crash the run or just be logged."""
    url = f"{api_base}/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=10)
    resp.raise_for_status()
    return resp.json()

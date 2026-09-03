"""
Daily Korean Expression bot
- Generates one expression per day with the Claude API
- Posts it to a Discord channel via webhook
- Remembers past expressions in history.json so it never repeats

Required environment variables:
  ANTHROPIC_API_KEY    your Anthropic API key (console.anthropic.com)
  DISCORD_WEBHOOK_URL  Discord channel webhook URL
"""

import json
import os
import sys
from pathlib import Path

import requests

HISTORY_FILE = Path(__file__).parent / "history.json"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"day": 0, "used": []}


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def generate_expression(used):
    prompt = f"""You write a "Daily Korean Expression" post for English speakers learning Korean.

Already used (NEVER repeat these): {", ".join(used) if used else "none yet"}

Pick ONE new, genuinely useful everyday Korean expression (word, idiom, or phrase).
Respond ONLY with JSON, no markdown fences, in exactly this shape:
{{
  "name": "expression in Hangul (romanization)",
  "when": "one or two sentences: when do you use it?",
  "feel": "one or two sentences: what does it feel like / nuance?",
  "examples": "two short Korean example sentences with English translations",
  "key_point": "one punchy takeaway sentence"
}}"""

    resp = requests.post(
        API_URL,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    text = "".join(
        block["text"] for block in resp.json()["content"] if block["type"] == "text"
    )
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def format_post(day, e):
    return (
        f"📌Daily Korean Expression {day:02d}\n"
        f"**{e['name']}**\n"
        f"✦ When do you use it? — {e['when']}\n"
        f"✦ What does it feel like? — {e['feel']}\n"
        f"✦ Real-world examples — {e['examples']}\n"
        f"👉Key point: {e['key_point']}"
    )


def post_to_discord(message):
    resp = requests.post(
        os.environ["DISCORD_WEBHOOK_URL"], json={"content": message}, timeout=30
    )
    resp.raise_for_status()


def main():
    history = load_history()
    expression = generate_expression(history["used"])
    day = history["day"] + 1
    post = format_post(day, expression)

    post_to_discord(post)

    history["day"] = day
    history["used"].append(expression["name"])
    save_history(history)
    print(f"Posted day {day:02d}: {expression['name']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        sys.exit(1)

"""
Daily Korean Expression bot (Gemini version, with model fallback)
- Generates one expression per day with the Gemini API (free tier)
- Posts it to a Discord channel via webhook
- Remembers past expressions in history.json so it never repeats
- Tries several models in order, so one retired / quota-less model
  does not stop the daily post

Required environment variables:
  GEMINI_API_KEY       your Gemini API key (aistudio.google.com, free)
  DISCORD_WEBHOOK_URL  Discord channel webhook URL
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

HISTORY_FILE = Path(__file__).parent / "history.json"

# Tried in order. Update if Google retires a model (404) or removes its
# free tier (429). Current list: ai.google.dev/gemini-api/docs/pricing
MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
]
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"day": 0, "used": []}


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_prompt(used):
    return f"""You write a "Daily Korean Expression" post for English speakers learning Korean.

Already used (NEVER repeat these): {", ".join(used) if used else "none yet"}

Pick ONE new, genuinely useful everyday Korean expression (word, idiom, or phrase).
Respond ONLY with JSON in exactly this shape:
{{
  "name": "expression in Hangul (romanization)",
  "when": "one or two sentences: when do you use it?",
  "feel": "one or two sentences: what does it feel like / nuance?",
  "examples": "two short Korean example sentences with English translations, separated by a newline character",
  "key_point": "one punchy takeaway sentence"
}}"""


def call_model(model, prompt):
    """Returns parsed JSON, or raises. 2 attempts per model on temporary errors."""
    for attempt in range(2):
        resp = requests.post(
            f"{API_BASE}/{model}:generateContent",
            headers={
                "x-goog-api-key": os.environ["GEMINI_API_KEY"],
                "content-type": "application/json",
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json"},
            },
            timeout=60,
        )
        if resp.status_code in (429, 500, 503) and attempt == 0:
            time.sleep(20)
            continue
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        for key in ("name", "when", "feel", "examples", "key_point"):
            if not data.get(key):
                raise ValueError(f"missing field: {key}")
        return data


def generate_expression(used):
    prompt = build_prompt(used)
    errors = []
    for model in MODELS:
        try:
            result = call_model(model, prompt)
            print(f"Used model: {model}")
            return result
        except Exception as exc:
            print(f"Model {model} failed: {exc}", file=sys.stderr)
            errors.append(f"{model}: {exc}")
    raise RuntimeError("All models failed:\n" + "\n".join(errors))


def format_post(day, e):
    return (
        f"📌Daily Korean Expression {day:02d}\n\n"
        f"**{e['name']}**\n\n"
        f"✦ When do you use it?\n: {e['when']}\n\n"
        f"✦ What does it feel like?\n: {e['feel']}\n\n"
        f"✦ Real-world examples\n: {e['examples']}\n\n"
        f"👉Key point\n: {e['key_point']}"
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

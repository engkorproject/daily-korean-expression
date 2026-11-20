"""
Daily Korean Expression bot (Gemini version, with model fallback)
"Real Korean" format: scene -> chat dialogue -> textbook vs real -> challenge

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
DISCORD_LIMIT = 2000  # Discord rejects messages longer than this

# Tried in order. Update if Google retires a model (404) or removes its
# free tier (429). Current list: ai.google.dev/gemini-api/docs/pricing
MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
]
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

REQUIRED = (
    "expression", "romanization", "literal", "real_meaning", "scene",
    "dialogue", "casual", "polite", "textbook", "real_life",
    "native_tip", "challenge", "challenge_answer",
)


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
The goal: it must feel like REAL Korean that people actually say and text today,
not textbook Korean.

Already used (NEVER repeat these): {", ".join(used) if used else "none yet"}

Pick ONE expression that Koreans in their 20s-30s really use in daily life
(slang, reaction words, sentence endings, idioms, texting phrases, cafe/store phrases).
Mix difficulty across days. Avoid stiff dictionary phrases.

Style rules:
- The dialogue is a short KakaoTalk-style chat between friends, in natural 반말,
  with real texting habits where they fit (ㅋㅋ, ㅠㅠ, 헐, 아 진짜, dropped particles).
  Use 존댓말 only if the expression itself is polite.
- Romanization follows how it is actually PRONOUNCED (sound changes included),
  e.g. 괜찮아 -> gwaen-cha-na, not gwaenchanha.
- "textbook" is the stiff way a learner might say it; "real_life" is how a native says it.
- Keep every field short. The whole post must fit in a Discord message.

Respond ONLY with JSON in exactly this shape:
{{
  "expression": "the expression in Hangul only",
  "romanization": "pronunciation-based romanization",
  "literal": "word-for-word literal meaning in English",
  "real_meaning": "what it really means, 2-6 words",
  "scene": "one sentence setting a vivid everyday scene where you'd hear it",
  "dialogue": [
    {{"speaker": "Korean first name or 나", "ko": "Korean line", "en": "natural English"}}
  ],
  "casual": "how you say it to friends",
  "polite": "how you say it to a boss / someone older (or the closest natural equivalent)",
  "textbook": "stiff textbook-style Korean for the same idea",
  "real_life": "what a native actually says",
  "native_tip": "one sentence on tone, pronunciation, or when NOT to use it",
  "challenge": "a short prompt asking readers to reply using the expression",
  "challenge_answer": "one example answer in Korean with English in parentheses"
}}
The dialogue must have 2 to 4 lines."""


def validate(data):
    for key in REQUIRED:
        if not data.get(key):
            raise ValueError(f"missing field: {key}")
    dialogue = data["dialogue"]
    if not isinstance(dialogue, list) or not 2 <= len(dialogue) <= 4:
        raise ValueError("dialogue must be a list of 2-4 lines")
    for line in dialogue:
        if not all(line.get(k) for k in ("speaker", "ko", "en")):
            raise ValueError("dialogue line missing speaker/ko/en")


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
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": 1.0,  # more variety day to day
                },
            },
            timeout=60,
        )
        if resp.status_code in (429, 500, 503) and attempt == 0:
            time.sleep(20)
            continue
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        validate(data)
        return data


def format_post(day, e, include_textbook=True):
    chat = "\n".join(
        f"> **{line['speaker']}:** {line['ko']}\n> -# {line['en']}"
        for line in e["dialogue"]
    )
    parts = [
        f"# 📌 Daily Korean Expression #{day:02d}",
        f"## {e['expression']} ({e['romanization']})",
        f"-# Literally: \"{e['literal']}\" → Really: **{e['real_meaning']}**",
        "",
        f"🎬 **The scene**\n{e['scene']}",
        "",
        f"💬 **How it actually sounds**\n{chat}",
        "",
        f"🎚️ **Casual vs polite**\n"
        f"• Friends: {e['casual']}\n"
        f"• Boss / older: {e['polite']}",
    ]
    if include_textbook:
        parts += [
            "",
            f"📚 **Textbook vs 🇰🇷 Real life**\n"
            f"❌ {e['textbook']}\n"
            f"✅ {e['real_life']}",
        ]
    parts += [
        "",
        f"👉 **Native tip**\n{e['native_tip']}",
        "",
        f"🔥 **Today's challenge**\n{e['challenge']}\n"
        f"-# Example: ||{e['challenge_answer']}||",
    ]
    return "\n".join(parts)


def generate_post(day, used):
    prompt = build_prompt(used)
    errors = []
    for model in MODELS:
        try:
            expression = call_model(model, prompt)
        except Exception as exc:
            print(f"Model {model} failed: {exc}", file=sys.stderr)
            errors.append(f"{model}: {exc}")
            continue
        post = format_post(day, expression)
        if len(post) > DISCORD_LIMIT:
            post = format_post(day, expression, include_textbook=False)
        if len(post) > DISCORD_LIMIT:
            errors.append(f"{model}: post too long ({len(post)} chars)")
            continue
        print(f"Used model: {model}")
        return expression, post
    raise RuntimeError("All models failed:\n" + "\n".join(errors))


def post_to_discord(message):
    resp = requests.post(
        os.environ["DISCORD_WEBHOOK_URL"],
        json={"content": message, "allowed_mentions": {"parse": []}},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    history = load_history()
    day = history["day"] + 1
    expression, post = generate_post(day, history["used"])

    post_to_discord(post)

    history["day"] = day
    history["used"].append(expression["expression"])
    save_history(history)
    print(f"Posted day {day:02d}: {expression['expression']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        sys.exit(1)

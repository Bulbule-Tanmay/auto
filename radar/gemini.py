"""Tiny Gemini REST client (no SDK needed). Key comes from GEMINI_API_KEY only."""
import json
import os
import re
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Tried in order. Set GEMINI_MODEL (secret or env) to force a specific model first.
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-flash-latest"]


class GeminiError(Exception):
    pass


class ModelUnavailable(GeminiError):
    pass


def _models() -> list[str]:
    forced = os.environ.get("GEMINI_MODEL", "").strip()
    return [forced] + [m for m in DEFAULT_MODELS if m != forced] if forced else DEFAULT_MODELS


def _one(model: str, key: str, body: dict, retries: int) -> str:
    delay = 10
    last = "unknown error"
    for _ in range(retries):
        try:
            r = requests.post(
                API.format(model=model),
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=body,
                timeout=150,
            )
        except requests.RequestException as e:
            last = type(e).__name__
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 404:
            raise ModelUnavailable(f"{model}: HTTP 404 {r.text[:200]}")
        if r.status_code != 200:
            raise GeminiError(f"HTTP {r.status_code}: {r.text[:300]}")

        data = r.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError):
            reason = data.get("promptFeedback", {}).get("blockReason", "empty response")
            raise GeminiError(f"No content returned ({reason})")
    raise GeminiError(f"Gemini failed after {retries} tries ({last})")


def generate(prompt: str, *, json_mode: bool = False, search: bool = False,
             temperature: float = 0.3, retries: int = 4) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiError("GEMINI_API_KEY is not set")

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if search:
        # JSON mode cannot be combined with the search tool
        body["tools"] = [{"google_search": {}}]
    elif json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    errors = []
    for model in _models():
        try:
            return _one(model, key, body, retries)
        except ModelUnavailable as e:
            errors.append(str(e))      # model retired/unknown: try the next one
    raise GeminiError("No Gemini model available. " + " | ".join(errors))


def parse_json(text: str):
    """Pull the first JSON object/array out of a model reply."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\[.*\]|\{.*\})", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    raise GeminiError("Could not parse JSON from model reply")

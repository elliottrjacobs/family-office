"""Shared API-key loader for Gemini wrappers."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS_PATH = ROOT / "profile" / "api-keys.json"


class MissingGeminiKeyError(RuntimeError):
    pass


def load_api_key() -> str:
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key:
        return env_key

    if not KEYS_PATH.exists():
        raise MissingGeminiKeyError(
            f"profile/api-keys.json not found at {KEYS_PATH}. "
            f"Either create it with a 'gemini.api_key' field or set GEMINI_API_KEY env var."
        )

    with KEYS_PATH.open() as f:
        keys = json.load(f)

    block = keys.get("gemini") or {}
    key = block.get("api_key")
    if not key:
        raise MissingGeminiKeyError(
            "No Gemini API key found. Add to profile/api-keys.json:\n"
            '  "gemini": { "api_key": "AIza..." }\n'
            "or set GEMINI_API_KEY env var. Get a key at https://aistudio.google.com/app/apikey"
        )
    return key

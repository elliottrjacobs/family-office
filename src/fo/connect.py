"""fo connect <provider>: store or remove an API key after one validating call.

Keys arrive on stdin, never as arguments, and are written to <provider>.json at
0600 inside the per-machine credentials folder outside the office. EDGAR takes a
contact string for office.toml instead of a key. Nothing here prints a key or a provider's error text.
"""

import copy
import json
import re
import tomllib

from fo.auth import save_keys, save_secret_json
from fo.commits import record
from fo.config import credentials_dir, ensure_credentials, read_config, read_secrets
from fo.errors import OfficeError
from fo.lock import office_lock
from fo.office import atomic_write, contained
from fo.providers.http import call

KEYED = ("alphavantage", "fred", "exa", "firecrawl", "gemini")
PROVIDERS = (*KEYED, "edgar")
MAX_KEY = 512


def _alphavantage(key):
    data = call(
        "GET",
        "https://www.alphavantage.co/query",
        params={"function": "GLOBAL_QUOTE", "symbol": "IBM", "apikey": key},
    )
    if not isinstance(data, dict):
        raise OfficeError("provider_error", "The provider returned an unreadable response.")
    if "Error Message" in data:
        raise OfficeError("invalid_key", "The provider rejected the API key.")
    if "Information" in data or "Note" in data:
        # Alpha Vantage reports an invalid key and a spent budget the same way.
        raise OfficeError(
            "invalid_key", "The provider refused the key or its daily request budget is spent."
        )


def _fred(key):
    call(
        "GET",
        "https://api.stlouisfed.org/fred/series",
        params={"series_id": "GNPCA", "api_key": key, "file_type": "json"},
        invalid=(400, 401, 403),
    )


def _exa(key):
    call(
        "POST",
        "https://api.exa.ai/search",
        headers={"x-api-key": key},
        json={"query": "SEC EDGAR full-text search", "numResults": 1},
    )


def _firecrawl(key):
    call(
        "GET",
        "https://api.firecrawl.dev/v2/team/credit-usage",
        headers={"Authorization": "Bearer " + key},
    )


def _gemini(key):
    call(
        "GET",
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"pageSize": 1},
        headers={"x-goog-api-key": key},
        invalid=(400, 401, 403),
    )


VALIDATE = {
    "alphavantage": _alphavantage,
    "fred": _fred,
    "exa": _exa,
    "firecrawl": _firecrawl,
    "gemini": _gemini,
}


def provider_name(provider):
    if provider not in PROVIDERS:
        raise OfficeError("unknown_provider", "Use " + ", ".join(PROVIDERS) + ".")
    return provider


def clean_key(raw):
    key = (raw or "").strip()
    if not key or len(key) > MAX_KEY or not key.isprintable() or any(c.isspace() for c in key):
        raise OfficeError("invalid_key", "Provide one API key on standard input.")
    return key


def store(root, provider, raw_key):
    """Validate the key with one call, then write it; a failed call writes nothing."""
    provider_name(provider)
    if provider == "edgar":
        raise OfficeError("invalid_query", "EDGAR takes --user-agent, not a key.")
    key = clean_key(raw_key)
    VALIDATE[provider](key)
    ensure_credentials(root)
    with office_lock(root):
        save_secret_json(root, provider, {"api_key": key})
    return {"provider": provider, "connected": True}


def remove(root, provider):
    provider_name(provider)
    ensure_credentials(root)
    if provider == "edgar":
        with office_lock(root):
            set_edgar(root, None)
            record(root, ["office.toml"], "Remove EDGAR contact")
        return {"provider": provider, "connected": False}
    with office_lock(root):
        path = credentials_dir(root) / f"{provider}.json"
        path.unlink(missing_ok=True)
        keys = read_secrets(root)
        if provider in keys:
            # A key fo auth stored earlier would otherwise keep the provider connected.
            del keys[provider]
            save_keys(root, keys)
    return {"provider": provider, "connected": False}


AGENT = re.compile(r"[^\s@]+(?: [^\s@]+)* [^\s@]+@[^\s@]+\.[^\s@]+")


def edgar(root, user_agent):
    value = (user_agent or "").strip()
    if len(value) > 200 or not AGENT.fullmatch(value):
        raise OfficeError(
            "invalid_user_agent", 'Use --user-agent "Name email@example.com" for SEC EDGAR.'
        )
    with office_lock(root):
        set_edgar(root, value)
        record(root, ["office.toml"], "Set EDGAR contact")
    return {"provider": "edgar", "connected": True}


HEADER = re.compile(r"^\s*\[\s*providers\.edgar\s*\]\s*(#.*)?$")
ANY_HEADER = re.compile(r"^\s*\[")
USER_AGENT = re.compile(r"^\s*user_agent\s*=")


def set_edgar(root, value):
    """Set or clear providers.edgar.user_agent with a small atomic rewrite of office.toml.

    The edit touches one line; the result must parse and differ from the original only in
    that key, or office.toml is left unchanged.
    """
    path = contained(root, "office.toml")
    before = read_config(root)
    lines = path.read_text().splitlines()
    start = next((i for i, line in enumerate(lines) if HEADER.match(line)), None)
    entry = None if value is None else "user_agent = " + json.dumps(value)
    if start is None:
        if entry is None:
            return
        lines += ["", "[providers.edgar]", entry]
    else:
        end = next(
            (i for i in range(start + 1, len(lines)) if ANY_HEADER.match(lines[i])), len(lines)
        )
        existing = [i for i in range(start + 1, end) if USER_AGENT.match(lines[i])]
        for index in reversed(existing):
            del lines[index]
        if entry is not None:
            lines.insert(start + 1, entry)
    text = "\n".join(lines) + "\n"
    try:
        after = tomllib.loads(text)
    except ValueError as exc:
        raise OfficeError("invalid_config", "office.toml could not be updated safely.") from exc
    expected = copy.deepcopy(before)
    table = expected.setdefault("providers", {}).setdefault("edgar", {})
    if value is None:
        table.pop("user_agent", None)
    else:
        table["user_agent"] = value
    if after != expected:
        raise OfficeError("invalid_config", "office.toml could not be updated safely.")
    atomic_write(path, text, path.stat().st_mode & 0o777)

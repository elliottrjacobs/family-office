"""fo research: web search, page fetch, and deep research, all returned as untrusted text.

Every result leaves through envelope(), so each provider returns the same shape, and every
string in it passes the credential scrub advisor-run events use. Fetched text is evidence
to cite, never instructions.
"""

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from fo import netguard
from fo.config import provider_key, read_config
from fo.errors import OfficeError
from fo.providers import exa, firecrawl
from fo.providers import http as web
from fo.providers.cache import Cache
from fo.providers.text import html_to_markdown
from fo.serve.runner import scrub_text

CACHE = "cache/research/research.sqlite"
# Tests replace this with a resolver that returns fixed addresses; None uses the system.
RESOLVER = None
MAX_REDIRECTS = 3
USER_AGENT = "family-office research fetch (+https://github.com/elliottrjacobs/family-office)"
DEFAULTS = {
    "exa": {"daily_limit": 25, "cache_hours": 24},
    "firecrawl": {"daily_limit": 25, "cache_hours": 24},
}
FETCH_DEFAULTS = {"fetch_max_bytes": 400_000, "text_max_chars": 60_000, "cache_hours": 24}
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown")


def stamp(epoch: float | None = None) -> str:
    moment = datetime.fromtimestamp(epoch, UTC) if epoch is not None else datetime.now(UTC)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def scrubbed(value):
    if isinstance(value, dict):
        return {key: scrubbed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrubbed(item) for item in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


def envelope(source, text, retrieved_at, limit=None, **fields):
    """The one shape every research result takes; text is size-capped and scrubbed."""
    body = "" if text is None else str(text)
    result = {"untrusted": True, "source": source, "retrieved_at": retrieved_at}
    if limit is not None and len(body) > limit:
        body, result["truncated"] = body[:limit], True
    result["text"] = body
    result.update(fields)
    return scrubbed(result)


def number(table, key, default, minimum=1, integer=True):
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value < minimum:
        raise OfficeError("invalid_config", "A research limit in office.toml must be a number.")
    return int(value) if integer else float(value)


def settings(root, provider):
    config = read_config(root)
    table = config.get("providers", {}).get(provider, {})
    if not isinstance(table, dict):
        raise OfficeError("invalid_config", "A [providers] table in office.toml is invalid.")
    defaults = DEFAULTS[provider]
    return {
        "daily_limit": number(table, "daily_limit", defaults["daily_limit"], 0),
        "ttl": number(table, "cache_hours", defaults["cache_hours"], 0, False) * 3600,
    }


def fetch_settings(root):
    table = read_config(root).get("research", {})
    if not isinstance(table, dict):
        raise OfficeError("invalid_config", "[research] in office.toml must be a table.")
    return {
        "max_bytes": number(table, "fetch_max_bytes", FETCH_DEFAULTS["fetch_max_bytes"]),
        "max_chars": number(table, "text_max_chars", FETCH_DEFAULTS["text_max_chars"]),
        "ttl": number(table, "cache_hours", FETCH_DEFAULTS["cache_hours"], 0, False) * 3600,
    }


def digest(*parts) -> str:
    return hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()[:32]


def cached(cache, key, ttl, fetch, provider=None, limit=None):
    """Cache.get, with a missing key reported as not_connected rather than offline."""
    try:
        return cache.get(key, ttl, fetch, provider, limit)
    except OfficeError as exc:
        if fetch is None and exc.reason == "missing_cached_data" and not cache.read_only:
            raise OfficeError(
                "not_connected", f"Connect {provider} with fo connect {provider}."
            ) from exc
        raise


def search(root, query, limit=10, read_only=False):
    query = " ".join(str(query).split())
    if not query or len(query) > 500:
        raise OfficeError("invalid_query", "Use a search query of 1 to 500 characters.")
    if not 1 <= limit <= 25:
        raise OfficeError("invalid_query", "Use --limit between 1 and 25.")
    config = settings(root, "exa")
    key = None if read_only else provider_key(root, "exa")
    fresh = []

    def fetch():
        fresh.append(True)
        return exa.search(key, query, limit)

    cache = Cache(root, read_only, CACHE)
    row = cached(
        cache,
        "exa:search:" + digest(query.lower(), limit),
        config["ttl"],
        fetch if key else None,
        "exa",
        config["daily_limit"],
    )
    retrieved = stamp(row["fetched_at"])
    results = [
        envelope(
            item["url"],
            item["snippet"],
            retrieved,
            rank=rank,
            url=item["url"],
            title=item["title"],
            snippet=item["snippet"],
            published=item["published"],
        )
        for rank, item in enumerate(row["data"], 1)
    ]
    result = {
        "untrusted": True,
        "source": "exa",
        "query": query,
        "retrieved_at": retrieved,
        "cached": not fresh or bool(row.get("warning")),
        "results": results,
    }
    if row.get("warning"):
        result["warning"] = row["warning"]
    return scrubbed(result)


def refuse(url):
    reason = netguard.reject(url, RESOLVER)
    if reason:
        raise OfficeError("url_refused", f"URL refused ({reason}): {netguard.REASONS[reason]}")


def decode(raw: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w.-]+)", content_type, re.I)
    try:
        return raw.decode(match[1] if match else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def direct(url, max_bytes):
    """GET url, following at most three redirects, each hop rechecked against netguard."""
    current = url
    try:
        with web.client() as session:
            for hop in range(MAX_REDIRECTS + 1):
                refuse(current)
                headers = {"User-Agent": USER_AGENT, "Accept": "text/html, text/plain;q=0.8"}
                with session.stream("GET", current, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location or hop == MAX_REDIRECTS:
                            raise OfficeError(
                                "too_many_redirects", "The page redirected too many times."
                            )
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise OfficeError("fetch_failed", "The page could not be fetched.")
                    content_type = response.headers.get("content-type", "text/html").lower()
                    if content_type.split(";")[0].strip() not in TEXT_TYPES:
                        raise OfficeError(
                            "unsupported_content", "Only HTML and plain-text pages can be fetched."
                        )
                    body, truncated = bytearray(), False
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            del body[max_bytes:]
                            truncated = True
                            break
                    text = decode(bytes(body), content_type)
                    if "html" in content_type:
                        text = html_to_markdown(text, current)
                    return {"url": current, "markdown": text, "body_truncated": truncated}
    except httpx.HTTPError as exc:
        raise OfficeError("fetch_failed", "The page could not be fetched.") from exc
    raise OfficeError("too_many_redirects", "The page redirected too many times.")


def fetch(root, url, read_only=False):
    url = str(url).strip()
    refuse(url)
    limits = fetch_settings(root)
    cache = Cache(root, read_only, CACHE)
    key = None if read_only else provider_key(root, "firecrawl")
    if key or (read_only and _has(cache, "firecrawl:" + digest(url))):
        config = settings(root, "firecrawl")
        row = cached(
            cache,
            "firecrawl:" + digest(url),
            config["ttl"],
            (lambda: firecrawl.scrape(key, url)) if key else None,
            "firecrawl",
            config["daily_limit"],
        )
        via = "firecrawl"
    else:
        row = cache.get(
            "web:" + digest(url, limits["max_bytes"]),
            limits["ttl"],
            None if read_only else (lambda: direct(url, limits["max_bytes"])),
        )
        via = "direct"
    page = row["data"]
    extra = {"via": via, "url": page.get("url", url)}
    if page.get("title"):
        extra["title"] = page["title"]
    if page.get("body_truncated"):
        extra["body_truncated"] = True
    if row.get("warning"):
        extra["warning"] = row["warning"]
    return envelope(
        page.get("url", url),
        page["markdown"],
        stamp(row["fetched_at"]),
        limits["max_chars"],
        **extra,
    )


def _has(cache, key):
    try:
        cache.get(key, 0)
        return True
    except OfficeError:
        return False

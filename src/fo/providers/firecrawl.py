"""Firecrawl page scraping to markdown.

Request shape from https://docs.firecrawl.dev/api-reference/endpoint/scrape (read
2026-11-04). Firecrawl fetches the page from its own servers; fo checks the URL against
netguard before sending it.
"""

from fo.errors import OfficeError
from fo.providers.http import call

URL = "https://api.firecrawl.dev/v2/scrape"


def scrape(key: str, url: str) -> dict:
    data = call(
        "POST",
        URL,
        headers={"Authorization": "Bearer " + key},
        json={"url": url, "formats": ["markdown"], "onlyMainContent": True, "timeout": 30000},
    )
    page = data.get("data") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not data.get("success") or not isinstance(page, dict):
        raise OfficeError("fetch_failed", "The page could not be fetched.")
    markdown = page.get("markdown")
    if not isinstance(markdown, str):
        raise OfficeError("fetch_failed", "The page could not be fetched.")
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    final = metadata.get("url") or metadata.get("sourceURL") or url
    return {
        "url": final if isinstance(final, str) else url,
        "title": str(metadata.get("title") or ""),
        "markdown": markdown,
    }

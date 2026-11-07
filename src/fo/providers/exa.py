"""Exa web search: ranked results with a snippet per page.

Request shape from https://docs.exa.ai/reference/search (read 2026-11-04).
"""

from fo.errors import OfficeError
from fo.providers.http import call

URL = "https://api.exa.ai/search"
SNIPPET = 500


def search(key: str, query: str, limit: int) -> list[dict]:
    data = call(
        "POST",
        URL,
        headers={"x-api-key": key},
        json={
            "query": query,
            "numResults": limit,
            "type": "auto",
            "contents": {"highlights": {"maxCharacters": SNIPPET}},
        },
    )
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise OfficeError("provider_error", "The provider returned an unreadable response.")
    results = []
    for row in rows[:limit]:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            continue
        highlights = [h for h in row.get("highlights") or [] if isinstance(h, str)]
        snippet = " … ".join(highlights) or row.get("summary") or row.get("text") or ""
        results.append(
            {
                "url": row["url"],
                "title": str(row.get("title") or ""),
                "snippet": str(snippet)[: SNIPPET * 3],
                "published": row.get("publishedDate")
                if isinstance(row.get("publishedDate"), str)
                else None,
            }
        )
    return results

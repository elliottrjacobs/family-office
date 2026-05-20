#!/usr/bin/env python3
"""Gemini fast wrapper (Flash-Lite + Google Search grounding).

Gemini 3.1 Flash-Lite with Google Search grounding for quick factual lookups,
"why is X happening" questions, and surface-level sentiment.

Library use:
    from scripts.gemini.fast import ask
    r = ask("Why did NVDA drop 4% on 2026-05-19?")
    print(r.text)
    for c in r.citations:
        print(c["title"], c["url"])

CLI use:
    python3 scripts/gemini/fast.py "Why did NVDA drop 4% today?"
    python3 scripts/gemini/fast.py --model gemini-3-flash "..."   # higher quality / 2x cost
    python3 scripts/gemini/fast.py --no-grounding "..."           # skip Google Search
    python3 scripts/gemini/fast.py --json "..."                   # JSON output
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from typing import Optional

from _keys import load_api_key

DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"
FALLBACK_MODEL = "gemini-3-flash"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass
class FastResult:
    text: str
    citations: list = field(default_factory=list)
    search_queries: list = field(default_factory=list)
    model: str = ""
    raw: Optional[dict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


def ask(
    query: str,
    *,
    model: str = DEFAULT_MODEL,
    grounding: bool = True,
    system_instruction: Optional[str] = None,
    temperature: float = 0.3,
    timeout: int = 60,
) -> FastResult:
    """Send a single grounded query to Gemini Flash and return text + citations."""
    api_key = load_api_key()
    url = f"{API_BASE}/{model}:generateContent"

    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "generationConfig": {"temperature": temperature},
    }
    if grounding:
        payload["tools"] = [{"google_search": {}}]
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API error {e.code}: {err_body}") from e

    return _parse_response(data, model=model)


def _parse_response(data: dict, *, model: str) -> FastResult:
    candidates = data.get("candidates") or []
    if not candidates:
        return FastResult(text="", model=model, raw=data)

    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if "text" in p).strip()

    grounding_meta = cand.get("groundingMetadata") or {}
    chunks = grounding_meta.get("groundingChunks") or []
    citations = []
    for ch in chunks:
        web = ch.get("web") or {}
        url = web.get("uri")
        if url:
            citations.append(
                {
                    "title": web.get("title", ""),
                    "url": url,
                    "snippet": web.get("snippet", ""),
                }
            )

    search_queries = [
        q for q in (grounding_meta.get("webSearchQueries") or []) if isinstance(q, str)
    ]

    return FastResult(
        text=text,
        citations=citations,
        search_queries=search_queries,
        model=model,
        raw=data,
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Gemini fast — Flash-Lite + Google Search grounding."
    )
    p.add_argument("query", help="Question to ask.")
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model ID (default: {DEFAULT_MODEL}). Use {FALLBACK_MODEL} for higher quality.",
    )
    p.add_argument(
        "--no-grounding",
        action="store_true",
        help="Skip Google Search grounding (text-only generation).",
    )
    p.add_argument(
        "--temperature", type=float, default=0.3, help="Sampling temperature (default 0.3)."
    )
    p.add_argument(
        "--system",
        default=None,
        help="Optional system instruction to prepend.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON {text, citations, search_queries, model} instead of formatted text.",
    )
    args = p.parse_args()

    try:
        r = ask(
            args.query,
            model=args.model,
            grounding=not args.no_grounding,
            system_instruction=args.system,
            temperature=args.temperature,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(r.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(r.text)
    if r.citations:
        print("\n--- Sources ---")
        for i, c in enumerate(r.citations, 1):
            title = c.get("title") or "(no title)"
            print(f"  [{i}] {title}\n      {c['url']}")
    if r.search_queries:
        print("\n--- Grounding queries issued ---")
        for q in r.search_queries:
            print(f"  • {q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

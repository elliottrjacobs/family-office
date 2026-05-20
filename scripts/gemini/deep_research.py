#!/usr/bin/env python3
"""Gemini Deep Research wrapper (Interactions API).

Multi-source agentic investigations via the Interactions API. Polls in the
background for up to 60 minutes, returns a full report with citations and an
audit trail of the model's search steps.

Library use:
    from scripts.gemini.deep_research import research
    r = research(
        query="Initiate ASML coverage: bull/bear, EUV demand, China revenue exposure",
        model="deep-research-max-preview-04-2026",
        grounding_inputs=["path/to/asml-10k.pdf", "https://www.asml.com/en/investors"],
    )
    print(r.text)

CLI use:
    # Synchronous (blocks until complete; default poll interval 30s, max 60 min)
    python3 scripts/gemini/deep_research.py "Initiate ASML coverage" \
        --max --output reports/equity-research/2026-05-19-asml-initiation.md

    # Background mode (start the task, get the interaction ID, resume later)
    python3 scripts/gemini/deep_research.py "..." --background
    python3 scripts/gemini/deep_research.py --resume INTERACTION_ID
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from _keys import load_api_key

STANDARD_MODEL = "deep-research-preview-04-2026"
MAX_MODEL = "deep-research-max-preview-04-2026"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_REVISION = "2026-05-20"

DEFAULT_POLL_INTERVAL = 30
DEFAULT_MAX_WAIT = 60 * 60


@dataclass
class DeepResearchResult:
    text: str
    citations: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    status: str = ""
    interaction_id: str = ""
    model: str = ""
    raw: Optional[dict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-goog-api-key": load_api_key(),
        "Api-Revision": API_REVISION,
    }


def _http_json(url: str, *, method: str, payload: Optional[dict] = None, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini Interactions API error {e.code}: {err_body}") from e


def _build_input(query: str, grounding_inputs: Optional[list]) -> object:
    """Return either a plain string or a multimodal list for the `input` field."""
    if not grounding_inputs:
        return query

    parts: list = [{"type": "text", "text": query}]
    for ref in grounding_inputs:
        if isinstance(ref, str) and ref.startswith(("http://", "https://")):
            mime = "application/pdf" if ref.lower().endswith(".pdf") else "text/html"
            parts.append({"type": "document", "mime_type": mime, "uri": ref})
        else:
            # Local file path — pass as a URI hint; user is responsible for upload if needed.
            parts.append({"type": "document", "mime_type": "application/pdf", "uri": str(ref)})
    return parts


def start(
    query: str,
    *,
    model: str = STANDARD_MODEL,
    grounding_inputs: Optional[list] = None,
    extra_tools: Optional[list] = None,
    collaborative_planning: bool = False,
) -> str:
    """Kick off a Deep Research interaction and return its interaction_id."""
    tools: list = [
        {"type": "google_search"},
        {"type": "url_context"},
        {"type": "code_execution"},
    ]
    if extra_tools:
        tools.extend(extra_tools)

    payload = {
        "agent": model,
        "input": _build_input(query, grounding_inputs),
        "background": True,
        "stream": False,
        "agent_config": {
            "type": "deep-research",
            "thinking_summaries": "auto",
            "visualization": "auto",
            "collaborative_planning": collaborative_planning,
        },
        "tools": tools,
    }

    data = _http_json(API_BASE, method="POST", payload=payload)
    interaction_id = data.get("id") or data.get("name") or data.get("interaction_id")
    if not interaction_id:
        raise RuntimeError(f"Deep Research start: no interaction id in response: {data}")
    return interaction_id


def poll(interaction_id: str) -> dict:
    """Fetch the current state of an interaction."""
    url = f"{API_BASE}/{interaction_id}"
    return _http_json(url, method="GET")


def wait(
    interaction_id: str,
    *,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    max_wait: int = DEFAULT_MAX_WAIT,
    on_progress=None,
) -> dict:
    """Poll until the interaction reaches a terminal status or max_wait elapses."""
    start_ts = time.time()
    while True:
        data = poll(interaction_id)
        status = data.get("status", "unknown")
        if on_progress:
            on_progress(status, data)
        if status in ("completed", "failed", "cancelled"):
            return data
        if time.time() - start_ts > max_wait:
            raise TimeoutError(
                f"Deep Research {interaction_id} did not complete within {max_wait}s "
                f"(last status: {status})"
            )
        time.sleep(poll_interval)


def _parse_completed(data: dict, model: str) -> DeepResearchResult:
    output_text = data.get("output_text") or ""
    if not output_text:
        # Concatenate text parts from step content as a fallback.
        for step in data.get("steps") or []:
            for c in step.get("content") or []:
                if c.get("type") == "text" and c.get("text"):
                    output_text += c["text"] + "\n"

    citations = []
    for step in data.get("steps") or []:
        for src in step.get("citations") or step.get("sources") or []:
            url = src.get("url") or src.get("uri")
            if url:
                citations.append(
                    {
                        "title": src.get("title", ""),
                        "url": url,
                        "snippet": src.get("snippet", ""),
                    }
                )

    seen = set()
    deduped: list = []
    for c in citations:
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        deduped.append(c)

    return DeepResearchResult(
        text=output_text.strip(),
        citations=deduped,
        steps=data.get("steps") or [],
        status=data.get("status", ""),
        interaction_id=data.get("id", ""),
        model=model,
        raw=data,
    )


def research(
    query: str,
    *,
    model: str = STANDARD_MODEL,
    grounding_inputs: Optional[list] = None,
    extra_tools: Optional[list] = None,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    max_wait: int = DEFAULT_MAX_WAIT,
    on_progress=None,
) -> DeepResearchResult:
    """Run a Deep Research task end-to-end (start → poll → parse)."""
    interaction_id = start(
        query,
        model=model,
        grounding_inputs=grounding_inputs,
        extra_tools=extra_tools,
    )
    data = wait(
        interaction_id,
        poll_interval=poll_interval,
        max_wait=max_wait,
        on_progress=on_progress,
    )
    if data.get("status") != "completed":
        raise RuntimeError(
            f"Deep Research {interaction_id} ended with status={data.get('status')!r}: "
            f"{data.get('error') or data}"
        )
    return _parse_completed(data, model=model)


def _format_report(r: DeepResearchResult) -> str:
    lines = [r.text, ""]
    if r.citations:
        lines.append("---")
        lines.append("## Sources")
        for i, c in enumerate(r.citations, 1):
            title = c.get("title") or c["url"]
            lines.append(f"{i}. [{title}]({c['url']})")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Gemini Deep Research — multi-source agentic investigation."
    )
    p.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Research question. Required unless --resume is used.",
    )
    p.add_argument(
        "--max",
        action="store_true",
        help=f"Use {MAX_MODEL} for max comprehensiveness (≈2x cost).",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Override model ID. Default: deep-research-preview-04-2026 (or max with --max).",
    )
    p.add_argument(
        "--input",
        action="append",
        default=[],
        help="URL or PDF path to ground on. Repeatable.",
    )
    p.add_argument(
        "--background",
        action="store_true",
        help="Start the task and print the interaction ID without polling.",
    )
    p.add_argument(
        "--resume",
        default=None,
        metavar="INTERACTION_ID",
        help="Poll/print an existing interaction (use after --background).",
    )
    p.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between status polls (default {DEFAULT_POLL_INTERVAL}).",
    )
    p.add_argument(
        "--max-wait",
        type=int,
        default=DEFAULT_MAX_WAIT,
        help=f"Max wait in seconds (default {DEFAULT_MAX_WAIT}, hard ceiling 3600).",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Write the final report to this markdown file.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON result instead of formatted markdown.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress chatter on stderr.",
    )
    args = p.parse_args()

    model = args.model or (MAX_MODEL if args.max else STANDARD_MODEL)

    def progress(status: str, _data: dict) -> None:
        if not args.quiet:
            print(f"[deep-research] status={status}", file=sys.stderr)

    try:
        if args.resume:
            data = wait(
                args.resume,
                poll_interval=args.poll_interval,
                max_wait=args.max_wait,
                on_progress=progress,
            )
            if data.get("status") != "completed":
                raise RuntimeError(
                    f"interaction {args.resume} ended status={data.get('status')!r}"
                )
            r = _parse_completed(data, model=model)
        else:
            if not args.query:
                p.error("query is required unless --resume is used")
            if args.background:
                interaction_id = start(
                    args.query,
                    model=model,
                    grounding_inputs=args.input or None,
                )
                print(interaction_id)
                return 0
            r = research(
                args.query,
                model=model,
                grounding_inputs=args.input or None,
                poll_interval=args.poll_interval,
                max_wait=args.max_wait,
                on_progress=progress,
            )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json:
        out = json.dumps(r.to_dict(), indent=2, ensure_ascii=False)
    else:
        out = _format_report(r)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(out, encoding="utf-8")
        if not args.quiet:
            print(f"[deep-research] wrote {args.output}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

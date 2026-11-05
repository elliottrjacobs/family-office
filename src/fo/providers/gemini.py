"""Gemini Deep Research through the Interactions API, as a background task fo polls.

Assumed request shape, from https://aistudio.google.com/docs/deep-research and the
Interactions API reference (both read 2026-11-04; the API is in preview):

  POST {BASE}/interactions   {"input": QUESTION, "agent": AGENT, "background": true}
                             -> {"id": ..., "status": "in_progress", ...}
  GET  {BASE}/interactions/{id}
                             -> {"status": "in_progress" | "completed" | "failed" | ...,
                                 "steps": [{"type": "model_output",
                                            "content": [{"type": "text", "text": ...,
                                                         "annotations": [{"type": "url_citation",
                                                                          "url": ..., "title": ...}]}]}]}

with headers x-goog-api-key and Api-Revision. docs/development/research-providers.md
records the same assumption; change it here only.
"""

import re

from fo.errors import OfficeError
from fo.providers.http import call

BASE = "https://generativelanguage.googleapis.com/v1beta"
AGENT = "deep-research-preview-04-2026"
REVISION = "2026-05-20"
TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,200}")
RUNNING = {"in_progress", "requires_continuation"}


def headers(key):
    return {"x-goog-api-key": key, "Api-Revision": REVISION}


def submit(key: str, question: str, agent: str = AGENT) -> str:
    data = call(
        "POST",
        BASE + "/interactions",
        headers=headers(key),
        json={"input": question, "agent": agent, "background": True},
    )
    task = data.get("id") if isinstance(data, dict) else None
    if not isinstance(task, str) or not TASK_ID.fullmatch(task):
        raise OfficeError("provider_error", "The provider returned an unreadable response.")
    return task


def poll(key: str, task: str) -> dict:
    if not TASK_ID.fullmatch(task):
        raise OfficeError("provider_error", "The cached research task id is invalid.")
    data = call("GET", f"{BASE}/interactions/{task}", headers=headers(key))
    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        raise OfficeError("provider_error", "The provider returned an unreadable response.")
    return parse(data)


def parse(data: dict) -> dict:
    """Status, the final report text, and its URL citations."""
    status = data["status"]
    blocks = []
    for step in data.get("steps") or []:
        if not isinstance(step, dict) or step.get("type", "model_output") != "model_output":
            continue
        items = [c for c in step.get("content") or [] if isinstance(c, dict)]
        texts = [c for c in items if c.get("type") == "text" and isinstance(c.get("text"), str)]
        if texts:
            blocks = texts
    if not blocks:
        # Earlier API revisions returned outputs instead of steps.
        outputs = [o for o in data.get("outputs") or [] if isinstance(o, dict)]
        blocks = [o for o in outputs if isinstance(o.get("text"), str)][-1:]
    citations, seen = [], set()
    for block in blocks:
        for note in block.get("annotations") or []:
            if not isinstance(note, dict) or note.get("type", "url_citation") != "url_citation":
                continue
            url = note.get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")) and url not in seen:
                seen.add(url)
                citations.append({"url": url, "title": str(note.get("title") or "")})
    return {
        "status": status,
        "text": "\n\n".join(block["text"] for block in blocks),
        "citations": citations,
    }

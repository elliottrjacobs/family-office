"""Journal and correction actions from the browser, each a thin call to the fo command.

Writes run as subprocesses of this server's own interpreter, so the office lock, the
writable gate, and the notebook's validation apply exactly as in a terminal, and the
server and CLI cannot disagree on version. Global flags come first, values travel as
--key=value, and free text follows --, so nothing a user types can become a flag.
"""

import json
import os
import re
import subprocess
import sys

from fo.errors import OfficeError
from fo.office import RUN_MARKER
from fo.reports import component

DECISION = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
OUTCOMES = {"hit", "miss", "neutral", "unknown"}
LEVELS = {"none", "household", "full"}
CONVICTIONS = {"HIGH", "MEDIUM", "LOW"}
SCOPE = re.compile(r"global|(?:skill|subject):[A-Za-z0-9._-]+")


def fo(root, *args):
    env = {key: value for key, value in os.environ.items() if key not in (RUN_MARKER, "FO_OFFICE")}
    result = subprocess.run(
        [sys.executable, "-m", "fo.cli", "--json", "--office", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise OfficeError("operation_failed", "The fo command gave no readable answer.") from exc
    if result.returncode:
        if payload.get("reason") == "office_locked":
            raise OfficeError(
                "office_locked", "Another fo command holds the office lock; try again."
            )
        raise OfficeError(payload.get("reason", "operation_failed"), payload.get("message", ""))
    return payload


def field(body, key, limit, required=True, choices=None):
    value = body.get(key)
    if value is None or value == "":
        if required:
            raise OfficeError("invalid_request", f"Fill in {key}.")
        return None
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise OfficeError("invalid_request", f"{key} must be text of at most {limit} characters.")
    if choices and value not in choices:
        raise OfficeError(
            "invalid_request", f"{key} must be one of " + ", ".join(sorted(choices)) + "."
        )
    return value.strip()


def decision_id(params):
    if not DECISION.fullmatch(params["id"]):
        raise OfficeError("unknown_decision", "Decision does not exist.")
    return params["id"]


def close(handler, params, query):
    body = handler.body()
    outcome = field(body, "outcome", 10, choices=OUTCOMES)
    note = field(body, "note", 2000, required=False) or ""
    args = ["journal", "close", f"--outcome={outcome}", f"--note={note}", "--", decision_id(params)]
    return fo(handler.app.locator.root(), *args)


def reopen(handler, params, query):
    reason = field(handler.body(), "reason", 2000)
    args = ["journal", "reopen", f"--reason={reason}", "--", decision_id(params)]
    return fo(handler.app.locator.root(), *args)


def judge(handler, params, query):
    body = handler.body()
    until = field(body, "until", 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", until):
        raise OfficeError("invalid_request", "until must be a date like 2026-12-31.")
    note = field(body, "note", 2000, required=False) or ""
    args = ["journal", "judge", f"--until={until}", f"--note={note}", "--", decision_id(params)]
    return fo(handler.app.locator.root(), *args)


def record(handler, params, query):
    """A decision from the form, with the fields a skill records and source web."""
    body = handler.body()
    subject = component(field(body, "subject", 40))
    when = body.get("when") or []
    if not isinstance(when, list) or not all(isinstance(w, str) and len(w) <= 200 for w in when):
        raise OfficeError("invalid_request", "when must be a list of conditions.")
    args = [
        "journal",
        "add",
        f"--action={field(body, 'action', 40)}",
        f"--thesis={field(body, 'thesis', 4000)}",
        f"--invalidate={field(body, 'invalidate', 2000)}",
        f"--conviction={field(body, 'conviction', 10, choices=CONVICTIONS)}",
        f"--context-level={field(body, 'context_level', 10, required=False, choices=LEVELS) or 'none'}",
        "--source=web",
        *(f"--when={condition}" for condition in when),
    ]
    report = field(body, "report", 300, required=False)
    if report:
        args.append(f"--report={report}")
    return fo(handler.app.locator.root(), *args, "--", subject)


def correct(handler, params, query):
    body = handler.body()
    scope = field(body, "scope", 80, required=False) or "global"
    if not SCOPE.fullmatch(scope):
        raise OfficeError("invalid_scope", "Use global, skill:name, or subject:SYM.")
    words = field(body, "text", 2000)
    return fo(handler.app.locator.root(), "corrections", "add", f"--scope={scope}", "--", words)


def retire(handler, params, query):
    if not params["id"].isdigit():
        raise OfficeError("unknown_correction", "Active correction does not exist.")
    return fo(handler.app.locator.root(), "corrections", "retire", "--", params["id"])


ROUTES = [
    ("POST", r"/api/decisions", record),
    ("POST", r"/api/decisions/(?P<id>[0-9A-Z]{26})/close", close),
    ("POST", r"/api/decisions/(?P<id>[0-9A-Z]{26})/reopen", reopen),
    ("POST", r"/api/decisions/(?P<id>[0-9A-Z]{26})/judge", judge),
    ("POST", r"/api/corrections", correct),
    ("POST", r"/api/corrections/(?P<id>\d+)/retire", retire),
]

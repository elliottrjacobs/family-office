"""Advisor chat routes: preview, launch, stream, follow up, and cancel a run."""

import time

from fo.brief import start
from fo.errors import OfficeError
from fo.reports import component
from fo.skills import registry

# The runner check shells out to claude twice; the answer rarely changes.
RUNNER_TTL = 60.0
KEEPALIVE = 15.0


def advisor(name):
    found = next((a for a in registry()["skills"] if a["name"] == name), None)
    if found is None:
        raise OfficeError("unknown_skill", "No such advisor.")
    return found


def preview(handler, params, query):
    """What the run will read, from the same start call the run makes; no side effects."""
    info = advisor(params["skill"])
    subject = component(query.get("subject") or "household")
    level = query.get("level") or info["default_context"]
    # start() refuses a level the advisor does not allow, exactly as a run would.
    started = start(handler.app.locator.root(), info["name"], subject, level)
    runs = handler.app.runs
    return {
        "skill": info["name"],
        "subject": subject,
        "level": level,
        "deep_available": info["deep"] and runs.deep,
        "chat": info["name"] not in ("onboard", "journal"),
        **started,
    }


def runner(handler, params, query):
    app = handler.app
    cached = app.runner_status
    if cached is None or time.monotonic() - cached[0] > RUNNER_TTL:
        try:
            status = {"ready": True, **app.runs.runner.preflight(), "deep": app.runs.deep}
        except OfficeError as exc:
            status = {"ready": False, "reason": exc.reason, "message": exc.message}
        cached = app.runner_status = (time.monotonic(), status)
    return cached[1]


def text(body, key, required=True, limit=200):
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise OfficeError("invalid_request", f"Pass {key} as text of at most {limit} characters.")
    return value


def launch(handler, params, query):
    body = handler.body()
    deep = body.get("deep", False)
    if not isinstance(deep, bool):
        raise OfficeError("invalid_request", "deep must be true or false.")
    return handler.app.runs.launch(
        handler.app.locator.root(),
        text(body, "skill"),
        text(body, "subject"),
        text(body, "level", required=False),
        deep,
    )


def listing(handler, params, query):
    return handler.app.runs.list(handler.app.locator.root())


def record(handler, params, query):
    return handler.app.runs.get(handler.app.locator.root(), params["id"])


def message(handler, params, query):
    body = handler.body()
    words = body.get("text", "")
    if not isinstance(words, str):
        raise OfficeError("invalid_request", "Pass text.")
    return handler.app.runs.message(handler.app.locator.root(), params["id"], words)


def cancel(handler, params, query):
    return handler.app.runs.cancel(handler.app.locator.root(), params["id"])


def events(handler, params, query):
    """Replay the stored log, then follow the live run until it finishes."""
    root = handler.app.locator.root()
    runs = handler.app.runs
    runs.get(root, params["id"])
    try:
        after = int(handler.headers.get("Last-Event-ID") or query.get("after") or 0)
    except ValueError as exc:
        raise OfficeError("invalid_request", "after must be a whole number.") from exc

    def follow():
        nonlocal after
        for event in runs.events(root, params["id"], after):
            after = event["seq"]
            yield event
        while True:
            fresh, live = runs.wait(root, params["id"], after, KEEPALIVE)
            for event in fresh:
                after = event["seq"]
                yield event
            if not live:
                return
            if not fresh:
                yield None

    handler.stream(follow(), end=True)


ROUTES = [
    ("GET", r"/api/runner", runner),
    ("GET", r"/api/advisors/(?P<skill>[a-z0-9-]+)/preview", preview),
    ("GET", r"/api/runs", listing),
    ("POST", r"/api/runs", launch),
    ("GET", r"/api/runs/(?P<id>[0-9A-Z]{26})", record),
    ("GET", r"/api/runs/(?P<id>[0-9A-Z]{26})/events", events),
    ("POST", r"/api/runs/(?P<id>[0-9A-Z]{26})/message", message),
    ("POST", r"/api/runs/(?P<id>[0-9A-Z]{26})/cancel", cancel),
]

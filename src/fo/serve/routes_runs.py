"""Advisor chat routes: preview, launch, stream, follow up, cancel, and delete a run."""

import time

from fo.brief import start
from fo.errors import OfficeError
from fo.reports import component
from fo.serve.runs import MESSAGE_LIMIT, web_allowed, web_policy
from fo.skills import registry

# Preflight starts an engine twice and rarely changes; office defaults are read every time.
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
    root = handler.app.locator.root()
    started = start(root, info["name"], subject, level)
    runs = handler.app.runs
    return {
        "skill": info["name"],
        "subject": subject,
        "level": level,
        # The default engine confines reads by path; a Codex run narrows this at launch.
        "web": web_allowed(level, web_policy(root), None, True),
        "deep_available": info["deep"] and runs.deep,
        "chat": info["name"] != "journal",
        **started,
    }


def runner(handler, params, query):
    """Every engine: usable or why not, its version, and the office's defaults for it.

    Only each engine's preflight is remembered, for RUNNER_TTL; [serve.engines] is read
    on every request, so fo config set shows on the next poll without a restart.
    """
    app = handler.app
    probed = app.runner_status

    def probe(name, engine):
        cached = probed.get(name)
        if cached is None or time.monotonic() - cached[0] > RUNNER_TTL:
            try:
                cached = (time.monotonic(), engine.preflight(), None)
            except OfficeError as exc:
                cached = (time.monotonic(), None, exc)
            probed[name] = cached
        if cached[2] is not None:
            raise cached[2]
        return cached[1]

    return app.runs.status(app.locator.root(), probe)


def text(body, key, required=True, limit=200):
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise OfficeError("invalid_request", f"Pass {key} as text of at most {limit} characters.")
    return value


def switch(body, key):
    value = body.get(key)
    if value is not None and not isinstance(value, bool):
        raise OfficeError("invalid_request", f"{key} must be true or false.")
    return value


def launch(handler, params, query):
    """A conversation when the body carries a message, else a report run on a subject."""
    body = handler.body()
    deep = switch(body, "deep") or False
    words = text(body, "message", required=False, limit=MESSAGE_LIMIT)
    result = handler.app.runs.launch(
        handler.app.locator.root(),
        text(body, "skill"),
        text(body, "subject", required=words is None),
        text(body, "level", required=False),
        deep,
        engine=text(body, "engine", required=False, limit=40),
        model=text(body, "model", required=False),
        effort=text(body, "effort", required=False, limit=10),
        message=words,
        web=switch(body, "web"),
    )
    handler.app.cache.forget(("/api/onboarding", ()))
    return result


def listing(handler, params, query):
    return handler.app.runs.list(handler.app.locator.root())


def record(handler, params, query):
    return handler.app.runs.get(handler.app.locator.root(), params["id"])


def message(handler, params, query):
    body = handler.body()
    words = body.get("text", "")
    if not isinstance(words, str):
        raise OfficeError("invalid_request", "Pass text.")
    return handler.app.runs.message(
        handler.app.locator.root(), params["id"], words, web=switch(body, "web")
    )


def delete(handler, params, query):
    result = handler.app.runs.delete(handler.app.locator.root(), params["id"])
    handler.app.cache.forget(("/api/onboarding", ()))
    return result


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
    ("DELETE", r"/api/runs/(?P<id>[0-9A-Z]{26})", delete),
    ("GET", r"/api/runs/(?P<id>[0-9A-Z]{26})/events", events),
    ("POST", r"/api/runs/(?P<id>[0-9A-Z]{26})/message", message),
    ("POST", r"/api/runs/(?P<id>[0-9A-Z]{26})/cancel", cancel),
]

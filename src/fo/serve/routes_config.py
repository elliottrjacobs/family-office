"""The curated model list per engine, with the office's engine defaults.

models.json is package data, so the list can change in a patch release. It is cached
by the file's own mtime, never by the office fingerprint; the office defaults are read
from office.toml on every request, so fo config set shows on the next one.
"""

import json
import threading
from importlib.resources import files
from pathlib import Path

from fo.serve.runs import engine_settings

_lock = threading.Lock()
_cached = {}


def catalog():
    """models.json, parsed once per modification of the file."""
    path = Path(str(files("fo").joinpath("data/models.json")))
    stamp = path.stat().st_mtime_ns
    with _lock:
        if _cached.get("stamp") != stamp:
            _cached.update(stamp=stamp, data=json.loads(path.read_text()))
        return _cached["data"]


def models(handler, params, query):
    office = engine_settings(handler.app.locator.root())
    return {**catalog(), "default": office["default"], "defaults": office["engines"]}


ROUTES = [("GET", r"/api/models", models)]

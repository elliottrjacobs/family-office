"""Read-only JSON routes. Each mirrors a CLI command and calls it with read_only=True.

Only these office paths are ever read: profile/, reports/ outside part directories,
notebook/, and data/ through the canonical readers. Never secrets/, cache/, imports/,
medical/, the store, or the lock file.
"""

from dataclasses import dataclass
from datetime import date

from fo import compute, notebook, reports
from fo.config import public_config
from fo.doctor import diagnose
from fo.errors import OfficeError
from fo.office import contained
from fo.skills import registry
from fo.store.authored import PROFILE_FILES, load
from fo.store.jsonl import read_rows

# Doctor shells out to git and reads permissions and token expiry outside the fingerprint.
DOCTOR_TTL = 30


@dataclass
class Route:
    handler: object
    cache: str = "fingerprint"  # "fingerprint", "ttl", or "never"
    office: bool = True


def number(query, name, default, low, high):
    try:
        value = int(query.get(name, default))
    except ValueError as exc:
        raise OfficeError("invalid_request", f"{name} must be a whole number.") from exc
    if not low <= value <= high:
        raise OfficeError("invalid_request", f"{name} must be between {low} and {high}.")
    return value


def required(query, name):
    if not query.get(name):
        raise OfficeError("invalid_request", f"Pass {name}.")
    return query[name]


def review(root, query):
    payload = notebook.evaluate(root)
    return {**payload, "breaches": sum(r["breached"] for r in payload["decisions"])}


def profile_index(root, query):
    return [{"name": name, "file": "profile/" + file} for name, file in PROFILE_FILES.items()]


def profile(root, name):
    if name not in PROFILE_FILES:
        raise OfficeError("unknown_profile", "Unknown profile file.")
    relative = "profile/" + PROFILE_FILES[name]
    path = contained(root, relative)
    if not path.is_file():
        raise OfficeError("unknown_profile", "Profile file does not exist.")
    result = {"name": name, "file": relative, "text": path.read_text(), "data": None, "error": None}
    try:
        result["data"] = load(root, name)
    except OfficeError as exc:
        result["error"] = exc.message
    return result


ROUTES = {
    "/api/networth": Route(
        lambda root, q: compute.networth(root, q.get("by", "account"), None, True)
    ),
    "/api/allocation": Route(lambda root, q: compute.allocation(root, True)),
    "/api/positions": Route(
        lambda root, q: compute.positions(root, q.get("account"), q.get("symbol"), True)
    ),
    "/api/lots": Route(lambda root, q: compute.lots(root, required(q, "symbol"), True)),
    "/api/cashflow": Route(
        lambda root, q: compute.cashflow(root, number(q, "months", 3, 1, 120), True)
    ),
    "/api/spend": Route(
        lambda root, q: compute.spend(
            root, q.get("month") or date.today().isoformat()[:7], q.get("category"), True
        )
    ),
    "/api/goals": Route(lambda root, q: compute.goals(root, True)),
    "/api/decisions": Route(lambda root, q: notebook.decisions(root)),
    "/api/corrections": Route(lambda root, q: notebook.corrections(root, all_scopes=True)),
    "/api/review": Route(review),
    "/api/reports": Route(lambda root, q: reports.scan(root)),
    "/api/report": Route(lambda root, q: reports.show(root, required(q, "path"))),
    "/api/sync": Route(lambda root, q: read_rows(root, "data/sync_log.jsonl")),
    "/api/doctor": Route(lambda root, q: diagnose(root), cache="ttl"),
    "/api/config": Route(lambda root, q: public_config(root), cache="never"),
    "/api/profile": Route(profile_index),
    "/api/skills": Route(lambda root, q: registry(), office=False),
}
PREFIXES = {"/api/profile/": Route(lambda root, q: profile(root, q["name"]))}


def resolve(path):
    """The route for a request path, with any path parameter folded into the query."""
    if path in ROUTES:
        return ROUTES[path], {}
    for prefix, route in PREFIXES.items():
        name = path.removeprefix(prefix)
        if path.startswith(prefix) and name and "/" not in name:
            return route, {"name": name}
    return None, {}

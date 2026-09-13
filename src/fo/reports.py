import re
from datetime import date
from pathlib import Path

import yaml

from fo.errors import OfficeError
from fo.office import contained

CLOSING = "Reply with corrections in your next task."


def component(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) or ".." in value:
        raise OfficeError(
            "invalid_path", "Use letters, numbers, dots, underscores, or hyphens in report names."
        )
    return value


def parse(path, root):
    text = path.read_text()
    relative = path.relative_to(root).as_posix()
    if text.startswith("---\n"):
        pieces = text.split("---", 2)
        if len(pieces) != 3:
            raise ValueError("missing frontmatter end")
        meta = yaml.safe_load(pieces[1])
        if not isinstance(meta, dict):
            raise ValueError("invalid frontmatter")
        body = pieces[2]
    else:
        parts = Path(relative).parts
        match = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
        meta = {
            "kind": parts[1] if len(parts) > 2 else "legacy",
            "subject": parts[2] if len(parts) > 3 else "household",
            "date": match[0] if match else "1970-01-01",
            "legacy": True,
        }
        body = text
    if not all(meta.get(k) for k in ("kind", "subject", "date")):
        raise ValueError("missing identity")
    meta["date"] = str(meta["date"])
    date.fromisoformat(meta["date"][:10])
    return {
        "path": relative,
        "frontmatter": meta,
        "summary": str(meta.get("summary", body.strip()[:240])),
    }


def scan(root):
    rows, errors = [], []
    for path in sorted(contained(root, "reports").rglob("*.md")):
        if ".parts" in path.as_posix():
            continue
        try:
            contained(root, str(path.relative_to(root)))
            rows.append(parse(path, root))
        except (OfficeError, ValueError, TypeError, OSError, yaml.YAMLError):
            errors.append(str(path.relative_to(root)))
    return {"reports": rows, "parse_errors": errors}


def prior(root, subject, kind=None, exclude=None, before=None):
    rows = [
        r
        for r in scan(root)["reports"]
        if r["frontmatter"]["subject"] == subject
        and (not kind or r["frontmatter"]["kind"] == kind)
        and r["path"] != exclude
        and (before is None or (r["frontmatter"]["date"], r["path"]) < before)
    ]
    return max(rows, key=lambda r: (r["frontmatter"]["date"], r["path"]), default=None)


def report_path(root, kind, subject, slug="report", part=None):
    kind, subject, slug = map(component, (kind, subject, slug))
    base = f"reports/{kind}/{subject}/{date.today().isoformat()}-{slug}"
    path, counter = base + ".md", 1
    while contained(root, path).exists():
        counter += 1
        path = f"{base}_{counter:03}.md"
    previous = prior(root, subject, kind)
    meta = {
        "kind": kind,
        "subject": subject,
        "date": date.today().isoformat(),
        "model": "",
        "context_level": "none",
        "playbooks": [],
        "prior": previous["path"] if previous else None,
        "summary": "",
        "decision_ids": [],
    }
    if part:
        path = path.removesuffix(".md") + f".parts/{component(part)}.md"
    return {"path": path, "frontmatter": meta}


def verify(root, path):
    from fo.notebook import decisions

    target = Path(path)
    if target.is_absolute():
        try:
            target = target.relative_to(root)
        except ValueError as exc:
            raise OfficeError("unsafe_path", "Report is outside the office.") from exc
    file = contained(root, str(target))
    row = parse(file, root)
    meta = row["frontmatter"]
    if not re.fullmatch(r"reports/[^/]+/[^/]+/\d{4}-\d{2}-\d{2}-.+\.md", row["path"]):
        raise OfficeError("report_path", "Report path does not follow the convention.")
    if (
        any(
            k not in meta
            for k in ("model", "context_level", "playbooks", "prior", "summary", "decision_ids")
        )
        or not meta["model"]
        or meta["context_level"] not in {"none", "household", "full"}
    ):
        raise OfficeError("report_frontmatter", "Complete the report frontmatter.")
    previous = prior(root, meta["subject"], meta["kind"], row["path"], (meta["date"], row["path"]))
    if previous and previous["frontmatter"]["date"] <= meta["date"] and not meta["prior"]:
        raise OfficeError(
            "report_prior", "A prior report exists; record it and describe what changed."
        )
    if meta["prior"] and not contained(root, meta["prior"]).is_file():
        raise OfficeError("report_prior", "Prior report does not exist.")
    text = file.read_text()
    if meta["prior"] and not re.search(r"^#+ What changed", text, re.M | re.I):
        raise OfficeError("report_delta", "Add a What changed section.")
    known = {d["id"] for d in decisions(root)}
    if not isinstance(meta["decision_ids"], list) or any(
        d not in known for d in meta["decision_ids"]
    ):
        raise OfficeError("report_decisions", "Report references a missing decision.")
    if CLOSING not in text:
        raise OfficeError("report_closing", "Add the closing correction invitation.")
    return {"valid": True, "path": row["path"]}


def parts(root, kind, subject, slug="report"):
    """Read-only resume manifest; workers never write their own output."""
    names = [
        "fundamentals-analyst",
        "competitive-analyst",
        "valuation-analyst",
        "risk-analyst",
        "sentiment-analyst",
    ]
    result = {name: report_path(root, kind, subject, slug, name)["path"] for name in names}
    complete = [
        name
        for name, path in result.items()
        if contained(root, path).is_file() and contained(root, path).stat().st_size > 0
    ]
    return {
        "paths": result,
        "complete": complete,
        "missing": [name for name in names if name not in complete],
    }

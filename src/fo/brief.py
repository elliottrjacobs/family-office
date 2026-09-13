import json

from fo import compute, notebook, reports
from fo.errors import OfficeError
from fo.skills import assets, parse_skill
from fo.store.authored import load


def estimate(value):
    return (len(json.dumps(value, default=str, separators=(",", ":"))) + 3) // 4


def brief(root, level="household", subject=None, skill=None, full=False):
    if level not in {"none", "household", "full"}:
        raise OfficeError("invalid_context", "Use none, household, or full.")
    corrections = notebook.corrections(root, skill, subject, all_scopes=level == "full")
    open_items = [d for d in notebook.decisions(root) if d["status"] == "open"]
    selected = [d for d in open_items if subject and d["subject"] == subject]
    if level != "none":
        selected += [d for d in open_items if d not in selected][:5]
    result = {
        "level": level,
        "corrections": [{k: r[k] for k in ("id", "scope", "text")} for r in corrections],
        "decisions": [
            {k: d[k] for k in ("id", "subject", "action", "thesis", "invalidate")} for d in selected
        ],
    }
    if level != "none":
        allocation = compute.allocation(root, True)
        state = compute.context(root, True)
        result.update(
            as_of=state["as_of"],
            stale_accounts=state["stale_accounts"],
            stale_providers=state["stale_providers"],
            holdings=allocation["weights"],
            ips=load(root, "ips"),
            cash=compute.total(compute.number(r.get("cash")) for r in state["balances"]),
        )
        if subject:
            lots = compute.lots(root, subject, True)["lots"]
            result["lots"] = (
                lots
                if full
                else {
                    "count": len(lots),
                    "basis": compute.total(r["basis"] for r in lots),
                    "long": sum(r["holding_period"] == "long" for r in lots),
                    "short": sum(r["holding_period"] == "short" for r in lots),
                    "unknown": sum(r["holding_period"] is None for r in lots),
                }
            )
        if level == "full":
            result.update(
                household=load(root, "household"),
                goals=compute.goals(root, True),
                tax=load(root, "tax"),
                cashflow=compute.cashflow(root, 3, True),
            )
    # General decisions are optional; subject decisions and corrections are mandatory.
    if level == "household" and not full:
        while estimate(result) > 500:
            optional = next(
                (r for r in reversed(result["decisions"]) if r["subject"] != subject), None
            )
            if optional is None:
                break
            result["decisions"].remove(optional)
    tokens = estimate(result)
    result["estimated_tokens"] = tokens
    result["warnings"] = (
        ["context_budget_overflow: mandatory corrections and decisions are preserved"]
        if level == "household" and tokens > 500
        else []
    )
    return result


def start(root, skill, subject, level=None):
    reports.component(skill)
    path = assets("skills") / skill / "SKILL.md"
    if not path.is_file():
        raise OfficeError("unknown_skill", "Skill is not installed.")
    meta, _ = parse_skill(path)
    settings = meta["metadata"]
    level = level or settings["default-context"]
    if level not in settings["allowed-context"]:
        raise OfficeError("invalid_context", "This context level is not allowed by the skill.")
    result = {}
    for key, operation in {
        "brief": lambda: brief(root, level, subject, skill),
        "prior": lambda: reports.prior(root, subject, settings.get("report-kind", skill)),
        "report": lambda: reports.report_path(root, settings.get("report-kind", skill), subject),
    }.items():
        try:
            result[key] = {"status": "ok", "data": operation()}
        except OfficeError as exc:
            result[key] = {"status": "failed", "reason": exc.reason}
    if result["report"]["status"] == "ok":
        result["report"]["data"]["frontmatter"]["context_level"] = level
    return result

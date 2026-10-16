import json

from fo import compute, notebook, reports
from fo.errors import OfficeError
from fo.skills import assets, parse_skill
from fo.store.authored import load

# What an advisor reads at each context level, shown in the companion app. Keep it beside
# brief(): tests/test_brief_levels.py traces the files brief() opens and fails on drift.
_NOTEBOOK = ["notebook/corrections.md", "notebook/decisions.jsonl"]
_STATE = [
    "office.toml",
    "profile/accounts.json",
    "profile/ips.json",
    "data/balances.jsonl",
    "data/positions.jsonl",
    "data/sync_log.jsonl",
    "data/transactions.jsonl",
    "data/voids.jsonl",
]
LEVELS = {
    "none": {
        "summary": "No household data",
        "reads": [
            "Standing corrections for this advisor and subject",
            "Open decisions on the subject",
        ],
        "files": _NOTEBOOK,
    },
    "household": {
        "summary": "A short brief, about 500 tokens",
        "reads": [
            "Standing corrections for this advisor and subject",
            "Open decisions on the subject, plus up to five others",
            "Holdings weights and the investment policy",
            "Total cash and stale accounts",
            "A lot summary for the subject",
        ],
        "files": _NOTEBOOK + _STATE,
    },
    "full": {
        "summary": "The whole profile",
        "reads": [
            "Every standing correction",
            "Open decisions on the subject, plus up to five others",
            "Holdings weights and the investment policy",
            "Total cash and stale accounts",
            "Household members and businesses",
            "Goals and tax notes",
            "Three months of cash flow",
            "A lot summary for the subject",
        ],
        "files": _NOTEBOOK
        + _STATE
        + [
            "profile/household.md",
            "profile/goals.json",
            "profile/tax.json",
            "profile/categories.yaml",
        ],
    },
}


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


def start(root, skill, subject, level=None, report=None):
    """Brief, prior report, and report path for a skill run; report pins a resumed run."""
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
        "report": lambda: reports.report_path(
            root, settings.get("report-kind", skill), subject, report=report
        ),
    }.items():
        try:
            result[key] = {"status": "ok", "data": operation()}
        except OfficeError as exc:
            result[key] = {"status": "failed", "reason": exc.reason}
    if result["report"]["status"] == "ok":
        result["report"]["data"]["frontmatter"]["context_level"] = level
    return result

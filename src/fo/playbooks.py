import json
from copy import deepcopy
from decimal import Decimal
from importlib.resources import files

import jsonschema
import yaml

from fo.clauses import OPS
from fo.compute import allocation
from fo.errors import OfficeError
from fo.market import fundamentals
from fo.office import contained
from fo.reports import component

KNOWN = {
    "revenue",
    "revenue_growth",
    "gross_margin",
    "operating_income",
    "fcf",
    "roic",
    "earnings_yield",
    "roa",
    "roa_change",
    "cash_flow",
    "accrual_quality",
    "leverage_change",
    "liquidity_change",
    "shares_change",
    "margin_change",
    "turnover_change",
}


def library():
    return files("fo").joinpath("data/playbooks")


def load_playbook(root, name):
    component(name)
    path = library().joinpath(name + ".yaml")
    if not path.is_file():
        raise OfficeError("unknown_playbook", "Playbook is not installed.")
    value = yaml.safe_load(path.read_text())
    override = contained(root, f"playbooks/overrides/{name}.yaml")
    if override.exists():
        changes = yaml.safe_load(override.read_text())
        value = deepcopy(value)
        for change in changes.get("criteria", []):
            match = next((c for c in value["criteria"] if c["id"] == change["id"]), None)
            if match is None:
                raise OfficeError("invalid_playbook", "Override names an unknown criterion.")
            match.update(change)
    schema = json.loads(files("fo").joinpath("store/schemas/playbook.schema.json").read_text())
    if not jsonschema.Draft202012Validator(schema).is_valid(value):
        raise OfficeError("invalid_playbook", "Playbook does not satisfy its schema: " + name)
    if len({c["id"] for c in value["criteria"]}) != len(value["criteria"]):
        raise OfficeError("invalid_playbook", "Criterion IDs must be unique.")
    for criterion in value["criteria"]:
        if criterion["kind"] not in {"mechanical", "judgment"} or (
            criterion["kind"] == "mechanical"
            and (criterion.get("metric") not in KNOWN or criterion.get("op") not in OPS)
        ):
            raise OfficeError(
                "invalid_playbook", "Unknown metric or criterion kind: " + str(criterion.get("id"))
            )
    return value


def listing(root):
    return [
        {
            "name": p.name.removesuffix(".yaml"),
            "overridden": contained(root, f"playbooks/overrides/{p.name}").exists(),
        }
        for p in library().iterdir()
        if p.name.endswith(".yaml")
    ]


def score(root, symbol, names, read_only=False):
    try:
        result = fundamentals(root, symbol, read_only)
    except OfficeError as exc:
        result = {"data": {}, "as_of": None, "reason": exc.reason}
    facts = result["data"].get("normalized", {})
    cards = []
    for name in names:
        book = load_playbook(root, name)
        rows = []
        for criterion in book["criteria"]:
            actual = facts.get(criterion.get("metric"))
            row = {**criterion, "actual": actual, "status": "judgment", "evidence": []}
            if criterion["kind"] == "mechanical" and actual is not None:
                value = Decimal(str(actual))
                threshold = Decimal(str(criterion["threshold"]))
                passed = OPS[criterion["op"]](value, threshold)
                row["status"] = "pass" if passed else "fail"
                if criterion.get("borderline") is not None and abs(value - threshold) <= Decimal(
                    str(criterion["borderline"])
                ):
                    row["status"] = "borderline"
                row["evidence"] = [
                    {
                        "source": "fundamentals.normalized." + criterion["metric"],
                        "as_of": result["as_of"],
                    }
                ]
            rows.append(row)
        cards.append(
            {
                "playbook": name,
                "subject": symbol,
                "as_of": result["as_of"],
                "criteria": rows,
                "data_gap": result.get("reason"),
            }
        )
    return cards


def score_portfolio(root, name="all-weather", read_only=False):
    book = load_playbook(root, name)
    if book["scope"] != "portfolio":
        raise OfficeError("invalid_playbook_scope", "Choose a portfolio playbook.")
    result = allocation(root, read_only)
    return {
        "playbook": name,
        "as_of": result["as_of"],
        "criteria": [
            {
                **b,
                "status": "judgment"
                if b["outside_band"] is None
                else "fail"
                if b["outside_band"]
                else "pass",
            }
            for b in result["bands"]
        ],
        "judgment": book["criteria"],
    }

"""Canonical row contracts, shared by append and read validation."""

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from fo.errors import OfficeError

NUMBER = {"type": ["string", "null"], "pattern": r"^-?\d+(\.\d+)?([Ee][+-]?\d+)?$"}
TEXT = {"type": "string", "minLength": 1}
COMMON = {
    "as_of": {"type": "string", "format": "date-time", "pattern": "Z$"},
    "run_id": TEXT,
    "row_id": TEXT,
    "account_id": TEXT,
    "source": TEXT,
}
FIELDS = {
    "positions": (
        {"symbol": TEXT, **dict.fromkeys(("qty", "price", "value", "cost_basis"), NUMBER)},
        ["run_id", "account_id", "symbol", "value"],
    ),
    "balances": (
        dict.fromkeys(("net_value", "cash", "debt", "buying_power"), NUMBER),
        ["run_id", "account_id"],
    ),
    "transactions": (
        {
            "amount": NUMBER,
            "transaction_id": TEXT,
            "revision": {"type": "integer", "minimum": 1},
            "provider_ids": {"type": "array", "items": TEXT, "minItems": 1},
            "pending": {"type": "boolean"},
        },
        ["run_id", "account_id", "transaction_id", "revision", "amount", "provider_ids"],
    ),
    "sync_log": (
        {
            "provider": TEXT,
            "status": {"enum": ["complete", "failed"]},
            "account_ids": {"type": "array", "items": TEXT, "uniqueItems": True},
        },
        ["run_id", "provider", "status"],
    ),
    "accounts": ({"provider": TEXT}, ["run_id", "provider", "account_id"]),
    "voids": ({"reason": TEXT}, ["reason"]),
    "decisions": (
        {
            "id": TEXT,
            "event": {"enum": ["created", "closed", "reopened", "reviewed"]},
            "conviction": {"enum": ["HIGH", "MEDIUM", "LOW"]},
            "when": {"type": "array"},
            "outcome": {"enum": ["hit", "miss", "neutral", "unknown"]},
        },
        ["id", "event"],
    ),
    "reviews": (
        {"digest": TEXT, "decisions": {"type": "array"}, "calibration": {"type": "object"}},
        ["digest", "decisions", "calibration"],
    ),
}


def validate(table, row):
    name = table.rsplit("/", 1)[-1].removesuffix(".jsonl")
    properties, required = FIELDS[name]
    schema = {
        "type": "object",
        "properties": {**COMMON, **properties},
        "required": ["as_of", *required],
    }
    if name == "sync_log":
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": "complete"}}},
                "then": {"required": ["account_ids"]},
            }
        ]
    if name == "voids":
        schema["anyOf"] = [{"required": ["run_id"]}, {"required": ["row_id"]}]
    if name == "decisions":
        schema["allOf"] = [
            {
                "if": {"properties": {"event": {"const": "created"}}},
                "then": {
                    "required": [
                        "subject",
                        "action",
                        "thesis",
                        "invalidate",
                        "date",
                        "conviction",
                        "source",
                        "when",
                        "context_level",
                    ]
                },
            },
            {
                "if": {"properties": {"event": {"const": "closed"}}},
                "then": {"required": ["outcome"]},
            },
        ]
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(row)
    except ValidationError as exc:
        raise OfficeError(
            "invalid_record", f"Invalid canonical record in {name}; check its schema."
        ) from exc

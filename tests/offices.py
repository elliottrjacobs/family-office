"""Synthetic offices for tests. Every name, figure, and identifier here is invented."""

import json

import yaml

from fo import notebook, reports
from fo.init import initialize
from fo.sync import ingest

ACCOUNTS = [
    {
        "id": "brokerage",
        "provider": "fixture",
        "last4": "0001",
        "type": "brokerage",
        "owner": "Household",
        "role": "investment",
    },
    {
        "id": "checking",
        "provider": "fixture",
        "last4": "0002",
        "type": "checking",
        "owner": "Household",
        "role": "cash",
    },
]
IPS = {
    "bands": [
        {"name": "Equity", "min": 0.5, "max": 0.7},
        {"name": "Bonds", "min": 0.2, "max": 0.4},
        {"name": "Cash", "min": 0.0, "max": 0.1},
    ],
    "prohibitions": ["No single stock above 25% of investable assets."],
    "classifications": {"ACME": "Equity", "BETA": "Equity", "BOND": "Bonds"},
}
GOALS = {
    "goals": [
        {
            "name": "Emergency fund",
            "target": 30000,
            "accounts": ["checking"],
            "date": "2030-01-01",
            "monthly_contribution": 500,
        }
    ]
}


def write_report(root, kind, subject, body, summary):
    allocated = reports.report_path(root, kind, subject)
    meta = {**allocated["frontmatter"], "model": "fixture", "summary": summary}
    path = root / allocated["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump(meta) + "---\n\n" + body + "\n\n" + reports.CLOSING)
    return allocated["path"]


def synthetic(root):
    """A small synced office: two accounts, three holdings, a decision, and two reports."""
    initialize(root)
    (root / "profile/accounts.json").write_text(json.dumps({"accounts": ACCOUNTS}))
    (root / "profile/ips.json").write_text(json.dumps(IPS))
    (root / "profile/goals.json").write_text(json.dumps(GOALS))
    ingest(
        root,
        "fixture",
        [
            {
                "account_id": "brokerage",
                "positions": [
                    {"symbol": "ACME", "qty": "40", "price": "250", "value": "10000"},
                    {"symbol": "BETA", "qty": "10", "price": "200", "value": "2000"},
                    {"symbol": "BOND", "qty": "60", "price": "100", "value": "6000"},
                ],
                "balance": {"net_value": "19000", "cash": "1000"},
                "transactions": [
                    {
                        "provider_id": "t1",
                        "amount": "-120",
                        "transacted_at": "2026-08-03",
                        "description": "Groceries",
                    }
                ],
            },
            {
                "account_id": "checking",
                "positions": [],
                "balance": {"net_value": "6000", "cash": "6000"},
                "transactions": [
                    {
                        "provider_id": "t2",
                        "amount": "4000",
                        "transacted_at": "2026-08-01",
                        "description": "Payroll",
                    }
                ],
            },
        ],
    )
    notebook.add(
        root,
        "ACME",
        "HOLD",
        "Durable franchise with pricing power.",
        "Operating margin falls for two straight quarters.",
        conviction="HIGH",
        source="research",
        context_level="household",
    )
    notebook.correct(root, "State uncertainty in plain words.")
    research = write_report(
        root,
        "research",
        "ACME",
        "# ACME research\n\n## Summary\n\nA synthetic company used only in tests.",
        "Synthetic research summary.",
    )
    parts = root / research.removesuffix(".md")
    (parts.parent / (parts.name + ".parts")).mkdir()
    (parts.parent / (parts.name + ".parts") / "risk-analyst.md").write_text("Worker block.\n")
    write_report(
        root,
        "briefing",
        "household",
        "# Briefing\n\n- Holdings unchanged.\n- No breaches.",
        "Synthetic briefing.",
    )
    return root

import json
from pathlib import Path

import jsonschema
from typer.testing import CliRunner

from fo.cli import app
from fo.init import initialize
from fo.providers.cache import Cache
from fo.sync import ingest


def test_compute_json_contracts_and_golden_facts(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    (root / "profile/accounts.json").write_text(
        json.dumps({"accounts": [{"id": "a", "provider": "fixture", "last4": "1234"}]})
    )
    ingest(
        root,
        "fixture",
        [
            {
                "account_id": "a",
                "positions": [{"symbol": "ACME", "qty": "2", "price": "100", "value": "200"}],
                "balance": {"net_value": "250", "cash": "50"},
                "transactions": [
                    {
                        "provider_id": "t1",
                        "amount": "-20",
                        "transacted_at": "2026-08-01",
                        "description": "Food",
                    }
                ],
            }
        ],
    )
    cache = Cache(root)
    payloads = {
        "alpha:GLOBAL_QUOTE:ACME": {"Global Quote": {"05. price": "125"}},
        "alpha:OVERVIEW:ACME": {"Symbol": "ACME", "RevenueTTM": "100"},
        "edgar:tickers": {"0": {"ticker": "ACME", "cik_str": 123}},
        "edgar:submissions/CIK0000000123.json": {
            "filings": {
                "recent": {"form": ["10-K", "8-K"], "filingDate": ["2026-08-01", "2026-08-02"]}
            }
        },
        "fred:CPIAUCSL": {"observations": [{"date": "2026-08-01", "value": "300"}]},
        "edgar:api/xbrl/frames/us-gaap/Revenues/USD/CY2025.json": {
            "data": [{"cik": 123, "val": 1000000000}, {"cik": 456, "val": 500}]
        },
    }
    for key, value in payloads.items():
        cache.get(key, 86400, lambda value=value: value)
    args = {
        "networth": [],
        "positions": [],
        "allocation": [],
        "spend": ["--month", "2026-08"],
        "cashflow": [],
        "goals": [],
        "lots": ["ACME"],
        "quote": ["ACME"],
        "fundamentals": ["ACME"],
        "filings": ["ACME", "--form", "10-K"],
        "macro": ["CPIAUCSL"],
        "screen": ["--concept", "Revenues", "--period", "CY2025", "--min", "1e9"],
    }
    golden = json.loads(Path("tests/golden/command-facts.json").read_text())
    for command, options in args.items():
        response = CliRunner().invoke(
            app, [command, *options, "--json", "--read-only", "--office", str(root)]
        )
        assert response.exit_code == 0, response.output
        data = json.loads(response.output)
        schema = json.loads(Path(f"src/fo/store/schemas/output/{command}.schema.json").read_text())
        jsonschema.validate(data, schema)
        observed = data
        if command == "quote":
            observed = data[0]
        if command == "fundamentals":
            observed = data["data"]["normalized"]
        if command == "macro":
            observed = data["data"]
        for key, expected in golden[command].items():
            actual = (
                len(observed[key])
                if isinstance(expected, int) and isinstance(observed[key], list)
                else observed[key]
            )
            assert actual == expected, (command, key, actual, expected)

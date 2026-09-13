import hashlib
import json
import plistlib
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from fo.cli import app
from fo.errors import OfficeError
from fo.fundamentals import normalize
from fo.init import initialize
from fo.migrate_v1 import migrate
from fo.notebook import decisions
from fo.operations import schedule
from fo.playbooks import listing, load_playbook, score
from fo.providers.cache import Cache
from fo.reports import CLOSING, verify
from fo.skills import assets, parse_skill
from fo.store.jsonl import read_rows
from fo.sync import ingest


def digest(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


def put(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value))


@pytest.fixture
def legacy(tmp_path):
    source = tmp_path / "legacy"
    put(source, "profile/family.json", {"members": [{"name": "Example"}], "businesses": []})
    put(
        source,
        "profile/portfolio/holdings.json",
        {
            "data_as_of": "2026-09-01T12:00:00Z",
            "total_portfolio_value": 250,
            "accounts": {
                "broker": {
                    "account_number_last4": "1234",
                    "market_value": 250,
                    "cash_balance": 50,
                    "holdings": [
                        {
                            "symbol": "ACME",
                            "shares": 2,
                            "price": 100,
                            "market_value": 200,
                            "cost_basis_total": 150,
                        }
                    ],
                }
            },
        },
    )
    put(
        source,
        "profile/accounts/bank.json",
        {
            "id": "bank",
            "simplefin_id": "fixture-bank",
            "last4": "4321",
            "balance": 100,
            "as_of": "2026-09-01T12:00:00Z",
        },
    )
    put(
        source,
        "profile/debts/card.json",
        {"id": "card", "balance": 30, "as_of": "2026-09-01T12:00:00Z"},
    )
    put(
        source,
        "profile/transactions/bank.json",
        {
            "account_id": "bank",
            "transactions": [
                {
                    "id": "fixture-tx",
                    "amount": "-20",
                    "date": "2026-08-31",
                    "description": "Groceries",
                }
            ],
        },
    )
    put(source, "profile/api-keys.json", {"secret": "must-never-be-read"})
    report = source / "reports/research/2026-09-01-acme.md"
    report.parent.mkdir(parents=True)
    report.write_text("# Synthetic research")
    entry = source / "journal/entries/2026-09-01-acme.md"
    entry.parent.mkdir(parents=True)
    entry.write_text(
        "Subject: ACME\nAction: HOLD\nThesis: Durable\nInvalidation: Margin declines\nConviction: HIGH\nStatus: CLOSED\n"
    )
    return source


def test_migration_reconciliation_and_source_unchanged(tmp_path, legacy):
    from fo.compute import networth

    root = tmp_path / "office"
    initialize(root)
    source_before, target_before = digest(legacy), digest(root)
    preview = migrate(root, legacy, dry_run=True)
    assert not preview["issues"]
    assert digest(root) == target_before
    result = migrate(root, legacy)
    assert result["counts"] == preview["counts"]
    assert networth(root)["total"] == 320
    assert len(read_rows(root, "data/transactions.jsonl")) == 1
    assert decisions(root)[0]["status"] == "closed"
    assert digest(legacy) == source_before
    assert "must-never-be-read" not in "".join(p.read_text() for p in root.rglob("*.md"))
    with pytest.raises(OfficeError, match="already applied"):
        migrate(root, legacy)
    before = digest(root)
    assert migrate(root, legacy, force=True)["unchanged"]
    assert before == digest(root)
    ingest(
        root,
        "simplefin",
        [
            {
                "account_id": "bank",
                "positions": [],
                "balance": {"net_value": "100"},
                "transactions": [
                    {
                        "provider_id": "fixture-tx",
                        "amount": "-20",
                        "transacted_at": "2026-08-31",
                        "posted_date": "2026-08-31",
                        "description": "Groceries",
                    }
                ],
            }
        ],
    )
    assert len(read_rows(root, "data/transactions.jsonl")) == 1


def test_migration_ambiguity_writes_no_financial_rows(tmp_path, legacy):
    root = tmp_path / "office"
    initialize(root)
    put(legacy, "profile/accounts/ambiguous.json", {"id": "mystery"})
    with pytest.raises(OfficeError, match="mappings need resolution"):
        migrate(root, legacy)
    assert not read_rows(root, "data/positions.jsonl")
    assert (root / "notebook/migration-report.md").exists()


def test_fundamentals_period_alignment_and_missing_values():
    income = {
        "annualReports": [
            {
                "fiscalDateEnding": "2025-12-31",
                "totalRevenue": "100",
                "grossProfit": "40",
                "netIncome": "10",
            }
        ]
    }
    wrong_balance = {"annualReports": [{"fiscalDateEnding": "2024-12-31", "totalAssets": "200"}]}
    data = normalize({"RevenueTTM": "200"}, income, wrong_balance)
    assert data["normalized"]["gross_margin"] == "0.4"
    assert data["normalized"]["roa"] is None
    assert data["normalized"]["fcf"] is None
    assert normalize({"RevenueTTM": "0"}, income)["normalized"]["revenue"] == "0"


def test_quarterly_cashflow_requires_four_consecutive_observations():
    rows = [
        {"fiscalDateEnding": day, "operatingCashflow": "10", "capitalExpenditures": "2"}
        for day in ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
    ]
    assert normalize({}, cash={"quarterlyReports": rows})["metrics"]["fcf_ttm"][0]["value"] == "32"
    rows[1]["fiscalDateEnding"] = "2024-06-30"
    assert normalize({}, cash={"quarterlyReports": rows})["metrics"]["fcf_ttm"] == []


def test_playbooks_synthetic_score_and_override(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    assert len(listing(root)) == 9
    for book in listing(root):
        assert load_playbook(root, book["name"])["criteria"]
    Cache(root).get(
        "alpha:OVERVIEW:ACME",
        86400,
        lambda: {
            "Symbol": "ACME",
            "normalized": {"revenue": "20000000", "revenue_growth": "0.30", "gross_margin": "0.8"},
        },
    )
    card = score(root, "ACME", ["lead-edge-eight"], True)[0]
    assert [c["status"] for c in card["criteria"]].count("pass") == 3
    assert "verdict" not in card
    override = root / "playbooks/overrides/lead-edge-eight.yaml"
    override.parent.mkdir(parents=True, exist_ok=True)
    first = card["criteria"][0]["id"]
    override.write_text(yaml.safe_dump({"criteria": [{"id": first, "threshold": 30000000}]}))
    assert score(root, "ACME", ["lead-edge-eight"], True)[0]["criteria"][0]["status"] == "fail"


def test_all_skills_start_and_verified_report_cycle(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    runner = CliRunner()
    skills = sorted(assets("skills").glob("*/SKILL.md"))
    assert len(skills) == 28
    for path in skills:
        meta, body = parse_skill(path)
        command = runner.invoke(
            app, ["start", meta["name"], "ACME", "--office", str(root), "--json", "--read-only"]
        )
        assert command.exit_code == 0, command.output
        result = json.loads(command.output)
        assert all(part["status"] == "ok" for part in result.values())
        target = root / result["report"]["data"]["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        header = result["report"]["data"]["frontmatter"]
        header.update(model="fixture", summary="Synthetic workflow")
        target.write_text(
            "---\n"
            + yaml.safe_dump(header)
            + "---\n## What changed\nFixture continuation.\n"
            + CLOSING
        )
        assert verify(root, target)["valid"]
        again = runner.invoke(app, ["start", meta["name"], "ACME", "--office", str(root), "--json"])
        assert json.loads(again.output)["prior"]["data"]["path"] == str(target.relative_to(root))
    # An older report remains valid after later reports are written.
    for path in (root / "reports").rglob("*.md"):
        assert verify(root, path)["valid"]


def test_schedule_and_notification_arguments(tmp_path, monkeypatch):
    import fo.operations as ops

    root = tmp_path / "office"
    initialize(root)
    result = schedule(root)
    assert len(result["jobs"]) == 4
    for job in result["jobs"]:
        body = plistlib.loads(Path(job["path"]).read_bytes())
        assert body["ProgramArguments"][1:3] == ["run", "fo"]
        assert "codex" not in body["ProgramArguments"]
    calls = []
    monkeypatch.setattr(ops.platform, "system", lambda: "Darwin")

    def run(argv, **kwargs):
        calls.append(argv)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(ops.subprocess, "run", run)
    message = '"; do shell script "touch /tmp/not-run"'
    assert ops.notification(message)["sent"]
    assert calls[0][-1] == message
    assert message not in calls[0][-2]


def test_sourced_lots_and_goal_progress(tmp_path):
    from fo.compute import goals, lots

    root = tmp_path / "office"
    initialize(root)
    put(
        root,
        "profile/accounts.json",
        {"accounts": [{"id": "a", "provider": "fixture", "last4": "1234"}]},
    )
    ingest(
        root,
        "fixture",
        [
            {
                "account_id": "a",
                "balance": {"net_value": "100", "cash": "0"},
                "positions": [
                    {
                        "symbol": "ACME",
                        "qty": "1",
                        "value": "50",
                        "cost_basis": "30",
                        "lot_id": str(days),
                        "acquired_at": (date.today() - timedelta(days=days)).isoformat(),
                    }
                    for days in (400, 100)
                ],
            }
        ],
    )
    assert [r["holding_period"] for r in lots(root, "ACME")["lots"]] == ["long", "short"]
    put(
        root,
        "profile/goals.json",
        {
            "goals": [
                {
                    "name": "Fund",
                    "target": 200,
                    "accounts": ["a"],
                    "date": date.today().isoformat(),
                    "monthly_contribution": 10,
                }
            ]
        },
    )
    goal = goals(root)["goals"][0]
    assert goal["behind_monthly"] == 90
    assert goal["status"] == "behind"


def test_deep_resume_requests_only_missing_parts(tmp_path):
    from fo.reports import parts

    root = tmp_path / "office"
    initialize(root)
    first = parts(root, "research", "ACME")
    for name in first["missing"][:2]:
        path = root / first["paths"][name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Completed synthetic evidence block")
    resumed = parts(root, "research", "ACME")
    assert len(resumed["complete"]) == 2
    assert len(resumed["missing"]) == 3
    for name in resumed["missing"]:
        (root / resumed["paths"][name]).write_text("New synthetic evidence block")
    assert len(parts(root, "research", "ACME")["complete"]) == 5


def test_doctor_notify_emits_one_json_value(tmp_path, monkeypatch):
    import fo.cli as cli
    import fo.operations as ops

    root = tmp_path / "office"
    initialize(root)
    calls = []
    monkeypatch.setattr(cli, "diagnose", lambda root: [{"status": "warn"}])
    monkeypatch.setattr(ops, "notification", lambda message: calls.append(message))
    result = CliRunner().invoke(app, ["doctor", "--notify", "--json", "--office", str(root)])
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"status": "warn"}]
    assert len(calls) == 1
    result = CliRunner().invoke(
        app, ["doctor", "--notify", "--json", "--read-only", "--office", str(root)]
    )
    assert result.exit_code == 1
    assert len(calls) == 1


def test_migration_preflights_journal_and_policy(tmp_path, legacy):
    root = tmp_path / "office"
    initialize(root)
    entry = legacy / "journal/entries/2026-09-01-acme.md"
    entry.write_text(entry.read_text().replace("Conviction: HIGH", "Conviction: UNSURE"))
    with pytest.raises(OfficeError, match="mappings need resolution"):
        migrate(root, legacy)
    assert read_rows(root, "data/positions.jsonl") == []
    entry.write_text(entry.read_text().replace("Conviction: UNSURE", "Conviction: HIGH"))
    put(legacy, "profile/investment-policy.json", {"allocation_targets": {"stocks": 0.6}})
    preview = migrate(root, legacy, dry_run=True)
    assert any("unmapped policy" in issue for issue in preview["issues"])
    assert read_rows(root, "data/positions.jsonl") == []


def test_partial_fundamentals_uses_sec_fallback(tmp_path):
    from fo.market import fundamentals

    root = tmp_path / "office"
    initialize(root)
    cache = Cache(root)
    cache.get("alpha:OVERVIEW:ACME", 86400, lambda: {"Symbol": "ACME", "RevenueTTM": "100"})
    cache.get("edgar:tickers", 86400, lambda: {"0": {"ticker": "ACME", "cik_str": 123}})
    cache.get(
        "edgar:api/xbrl/companyfacts/CIK0000000123.json",
        86400,
        lambda: {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "frame": "CY2025",
                                    "end": "2025-12-31",
                                    "filed": "2026-02-01",
                                    "val": 150,
                                }
                            ]
                        }
                    }
                }
            }
        },
    )
    result = fundamentals(root, "ACME", True)
    assert result["fallback"] == "sec_edgar"
    assert result["data"]["normalized"]["revenue"] == "150"

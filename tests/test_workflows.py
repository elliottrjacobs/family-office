import json
from decimal import Decimal

import pytest
import yaml

from fo import compute, notebook, reports
from fo.brief import brief
from fo.errors import OfficeError
from fo.init import initialize
from fo.providers.cache import Cache
from fo.store.index import reindex
from fo.store.jsonl import read_rows
from fo.sync import ingest


@pytest.fixture
def office(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    (root / "profile/accounts.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "a",
                        "provider": "fixture",
                        "last4": "1234",
                        "type": "brokerage",
                        "owner": "Household",
                    }
                ]
            }
        )
    )
    ingest(
        root,
        "fixture",
        [
            {
                "account_id": "a",
                "positions": [
                    {
                        "symbol": "ACME",
                        "qty": "2",
                        "price": "100",
                        "value": "200",
                        "cost_basis": "150",
                    }
                ],
                "balance": {"net_value": "250", "cash": "50"},
                "transactions": [
                    {
                        "provider_id": "t1",
                        "amount": "-20",
                        "transacted_at": "2026-08-01",
                        "description": "Groceries",
                    },
                    {
                        "provider_id": "t2",
                        "amount": "-100",
                        "transacted_at": "2026-08-02",
                        "description": "Transfer",
                    },
                ],
            }
        ],
    )
    (root / "profile/categories.yaml").write_text(
        "rules:\n  - pattern: Transfer\n    category: transfer\n"
    )
    (root / "profile/ips.json").write_text(
        json.dumps({"bands": [{"name": "ACME", "min": 0.1, "max": 0.5}]})
    )
    return root


def test_compute_and_reclassification(office):
    assert compute.networth(office)["total"] == Decimal(250)
    assert compute.networth(office, by="type")["groups"] == [
        {"name": "brokerage", "value": Decimal(250)}
    ]
    assert compute.allocation(office)["bands"][0]["drift_points"] == Decimal(30)
    assert compute.spend(office, "2026-08")["spend"] == Decimal(20)
    before = (office / "data/transactions.jsonl").read_bytes()
    (office / "profile/categories.yaml").write_text(
        "rules:\n  - pattern: Groceries|Transfer\n    category: transfer\n"
    )
    reindex(office)
    assert compute.spend(office, "2026-08")["spend"] == 0
    assert (office / "data/transactions.jsonl").read_bytes() == before
    assert compute.lots(office, "ACME")["lots"][0]["holding_period"] is None


def test_missing_accounts_do_not_understate_networth(office):
    path = office / "profile/accounts.json"
    data = json.loads(path.read_text())
    data["accounts"].append({"id": "b", "provider": "fixture", "last4": "5678"})
    path.write_text(json.dumps(data))
    assert compute.networth(office)["total"] is None


def test_journal_review_and_close(office):
    Cache(office).get("alpha:GLOBAL_QUOTE:ACME", 900, lambda: {"Global Quote": {"05. price": "95"}})
    decision = notebook.add(
        office, "ACME", "HOLD", "Durable business", "Price breaks", ["price < 100"]
    )
    first = notebook.review(office)
    assert first["breaches"] == 1
    assert first["decisions"][0]["values"]["price"][0]["value"] == "95"
    assert notebook.review(office)["unchanged"]
    assert len(read_rows(office, "notebook/reviews.jsonl")) == 1
    notebook.transition(office, decision["id"], "closed", outcome="hit")
    with pytest.raises(OfficeError):
        notebook.transition(office, decision["id"], "closed", outcome="hit")
    assert notebook.review(office)["calibration"]["conviction:MEDIUM"]["hit_rate"] == 1
    notebook.transition(office, decision["id"], "reopened", note="New evidence")
    assert notebook.decisions(office)[0]["status"] == "open"


def test_reports_delta_and_missing_decision(office):
    first = reports.report_path(office, "research", "ACME")
    assert first == reports.report_path(office, "research", "ACME")
    path = office / first["path"]
    path.parent.mkdir(parents=True)
    first["frontmatter"].update(model="fixture", summary="Synthetic result")
    path.write_text(
        "---\n" + yaml.safe_dump(first["frontmatter"]) + "---\nReport\n" + reports.CLOSING
    )
    assert reports.verify(office, first["path"])["valid"]
    second = reports.report_path(office, "research", "ACME")
    assert second["frontmatter"]["prior"] == first["path"]
    assert second["path"] != first["path"]
    assert reports.prior(office, "ACME")["path"] == first["path"]
    first["frontmatter"]["decision_ids"] = ["missing"]
    path.write_text("---\n" + yaml.safe_dump(first["frontmatter"]) + "---\n" + reports.CLOSING)
    with pytest.raises(OfficeError, match="missing decision"):
        reports.verify(office, first["path"])


def test_brief_preserves_scoped_corrections_on_overflow(office):
    global_note = notebook.correct(office, "Always explain uncertainty.")
    notebook.correct(office, "Avoid this thesis. " * 300, "subject:ACME")
    notebook.correct(office, "Unrelated", "subject:BETA")
    decision = notebook.add(office, "ACME", "HOLD", "Thesis", "Invalidation")
    none = brief(office, "none", "ACME")
    assert "holdings" not in none
    assert len(none["corrections"]) == 2
    assert none["decisions"][0]["id"] == decision["id"]
    household = brief(office, "household", "ACME")
    assert household["warnings"]
    assert household["corrections"][1]["text"] == "Avoid this thesis. " * 300
    notebook.correct(office, retire=global_note["id"])
    assert len(notebook.corrections(office, subject="ACME")) == 1

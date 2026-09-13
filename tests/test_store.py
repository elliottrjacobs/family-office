import pytest

from fo.errors import OfficeError
from fo.init import initialize
from fo.lock import office_lock
from fo.store.index import project, reindex
from fo.store.jsonl import append, read_rows
from fo.sync import ingest


@pytest.fixture
def office(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    return root


def snapshot(symbols):
    return [
        {
            "account_id": "a",
            "as_of": "2026-09-12T12:00:00Z",
            "positions": [
                {"symbol": s, "qty": "1", "price": str(v), "value": str(v)}
                for s, v in symbols.items()
            ],
            "balance": {"net_value": str(sum(symbols.values()))},
            "transactions": [],
        }
    ]


def test_complete_snapshot_replaces_sold_and_empty(office):
    ingest(office, "fixture", snapshot({"ACME": 100, "BETA": 200}))
    ingest(office, "fixture", snapshot({"BETA": 210}))
    state = project(office)
    assert [p["symbol"] for p in state["positions"]] == ["BETA"]
    assert len(read_rows(office, "data/positions.jsonl")) == 3
    ingest(office, "fixture", snapshot({}))
    assert project(office)["positions"] == []


def test_idempotent_snapshot_resolves_reference(office):
    first = ingest(office, "fixture", snapshot({"ACME": 100, "BETA": 200}))
    second = ingest(office, "fixture", snapshot({"ACME": 100, "BETA": 200}))
    assert second["position_rows"] == 0
    assert second["unchanged_since"]["a"] == first["run_id"]
    assert len(project(office)["positions"]) == 2


def test_incomplete_run_and_voids_are_ignored(office):
    ingest(office, "fixture", snapshot({"ACME": 100}))
    second = ingest(office, "fixture", snapshot({"ACME": 200}))
    append(
        office,
        "data/voids.jsonl",
        {
            "as_of": "2026-09-12T13:00:00Z",
            "run_id": second["run_id"],
            "reason": "fixture correction",
        },
    )
    assert project(office)["positions"][0]["value"] == "100"
    append(
        office,
        "data/positions.jsonl",
        {
            "as_of": "2026-09-12T14:00:00Z",
            "run_id": "incomplete",
            "account_id": "a",
            "symbol": "BAD",
            "value": "999",
        },
    )
    assert [p["symbol"] for p in project(office)["positions"]] == ["ACME"]


def test_account_missing_from_coverage_is_stale(office):
    ingest(office, "fixture", snapshot({"ACME": 100}))
    ingest(office, "fixture", [])
    state = project(office)
    assert state["stale_accounts"] == ["a"]
    assert state["positions"][0]["value"] == "100"


def test_changed_transaction_id_preserves_one_record(office):
    data = snapshot({})
    data[0]["transactions"] = [
        {
            "provider_id": "pending",
            "amount": "-10",
            "description": "Shop",
            "transacted_at": "2026-09-10",
            "pending": True,
        }
    ]
    ingest(office, "fixture", data)
    data[0]["transactions"][0].update(provider_id="posted", pending=False)
    ingest(office, "fixture", data)
    rows = project(office)["transactions"]
    assert len(rows) == 1
    assert rows[0]["pending"] is False
    assert set(rows[0]["provider_ids"]) == {"pending", "posted"}


def test_read_only_ignores_stale_index_and_reindex_is_rebuildable(office):
    ingest(office, "fixture", snapshot({"ACME": 100}))
    reindex(office)
    before = (office / "store.sqlite").read_bytes()
    ingest(office, "fixture", snapshot({"BETA": 200}))
    assert project(office)["positions"][0]["symbol"] == "BETA"
    assert (office / "store.sqlite").read_bytes() == before
    reindex(office)
    assert (office / "store.sqlite").read_bytes() != before


def test_lock_exclusive(office):
    with office_lock(office), pytest.raises(OfficeError, match="lock"):
        ingest(office, "fixture", snapshot({}))


def test_forbidden_raw_fields_rejected_before_append(office):
    with pytest.raises(OfficeError):
        append(
            office,
            "data/transactions.jsonl",
            {
                "as_of": "2026-09-12T12:00:00Z",
                "run_id": "test",
                "raw": {"accountNumber": "123456789"},
            },
        )
    assert read_rows(office, "data/transactions.jsonl") == []


def test_pending_expires_only_after_three_covering_windows(office):
    data = snapshot({})
    data[0]["transactions"] = [
        {"provider_id": "pending", "amount": "-10", "transacted_at": "2026-09-10", "pending": True}
    ]
    ingest(office, "fixture", data)
    data[0]["transactions"] = []
    data[0]["transaction_window"] = {"start": "2026-09-01", "end": "2026-09-12"}
    for _ in range(2):
        ingest(office, "fixture", data)
        assert project(office)["transactions"][0]["pending"]
    ingest(office, "fixture", data)
    assert project(office)["transactions"][0]["status"] == "expired"


def test_repost_with_changed_date_and_duplicate_response_keeps_identity(office):
    data = snapshot({})
    data[0]["transactions"] = [
        {
            "provider_id": "old",
            "amount": "-10",
            "description": "Shop",
            "transacted_at": "2026-09-10",
        }
    ]
    ingest(office, "fixture", data)
    data[0]["transactions"][0].update(provider_id="new", transacted_at="2026-09-12")
    data[0]["transactions"] *= 2
    ingest(office, "fixture", data)
    rows = project(office)["transactions"]
    assert len(rows) == 1
    assert rows[0]["revision"] == 2


def test_separate_identical_purchases_are_not_collapsed(office):
    data = snapshot({})
    data[0]["transactions"] = [
        {"provider_id": key, "amount": "-10", "description": "Shop", "transacted_at": "2026-09-10"}
        for key in ("a", "b")
    ]
    ingest(office, "fixture", data)
    assert len(project(office)["transactions"]) == 2

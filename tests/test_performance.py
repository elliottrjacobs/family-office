import json
from datetime import date
from decimal import Decimal

from typer.testing import CliRunner

from fo.cli import app
from fo.init import initialize
from fo.performance import annualized, modified_dietz, performance
from fo.providers.cache import Cache
from fo.sync import ingest


def snapshot(stamp, value, transactions=()):
    return [
        {
            "account_id": "brokerage",
            "as_of": stamp,
            "positions": [],
            "balance": {"net_value": value, "cash": value},
            "transactions": list(transactions),
        }
    ]


def record(monkeypatch, root, stamp, value, transactions=()):
    # The sync log is stamped when the run happens, so history needs a backdated clock.
    monkeypatch.setattr("fo.sync.now", lambda: stamp)
    ingest(root, "schwab", snapshot(stamp, value, transactions))


def office(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    (root / "profile/accounts.json").write_text(
        json.dumps({"accounts": [{"id": "brokerage", "provider": "schwab", "last4": "1111"}]})
    )
    return root


def test_modified_dietz_weights_flows_by_time_invested():
    flows = [(date(2026, 1, 16), Decimal(1000))]
    value = modified_dietz(
        Decimal(10000), Decimal(11500), flows, date(2026, 1, 1), date(2026, 1, 31)
    )
    assert value == Decimal(500) / (Decimal(10000) + Decimal(1000) * Decimal(15) / Decimal(30))
    assert modified_dietz(None, Decimal(1), [], date(2026, 1, 1), date(2026, 1, 31)) is None
    assert annualized(Decimal("0.21"), 730).quantize(Decimal("0.0001")) == Decimal("0.1000")
    assert annualized(Decimal("0.21"), 100) is None


def test_deposit_is_not_a_gain_and_dividends_are_reported(tmp_path, monkeypatch):
    root = office(tmp_path)
    record(monkeypatch, root, "2026-01-01T15:00:00Z", "10000")
    activity = [
        {
            "provider_id": "d1",
            "amount": "1000",
            "transacted_at": "2026-01-16",
            "description": "ACH_RECEIPT",
            "kind": "transfer",
        },
        {
            "provider_id": "d2",
            "amount": "25",
            "transacted_at": "2026-01-20",
            "description": "DIVIDEND_OR_INTEREST",
            "kind": "dividend",
        },
    ]
    record(monkeypatch, root, "2026-01-31T15:00:00Z", "11500", activity)
    result = performance(root, "2026-01-01", read_only=True)
    row = result["accounts"][0]
    assert row["gain"] == Decimal(500)
    assert row["return"] == Decimal(500) / Decimal(10500)
    assert row["dividends"] == Decimal(25)
    assert row["flow_evidence"] == "transactions"
    assert result["total_return"] == row["return"]
    assert result["realized_gains"] is None


def test_missing_start_snapshot_is_unknown_not_zero(tmp_path, monkeypatch):
    root = office(tmp_path)
    record(monkeypatch, root, "2026-03-01T15:00:00Z", "10000")
    result = performance(root, "2026-01-01", read_only=True)
    assert result["accounts"][0]["return"] is None
    assert result["accounts"][0]["reason"] == "no_snapshot_at_start"
    assert result["accounts"][0]["earliest_snapshot"] == "2026-03-01T15:00:00Z"
    assert result["total_return"] is None


def test_cli_reports_cached_benchmark_offline(tmp_path, monkeypatch):
    root = office(tmp_path)
    record(monkeypatch, root, "2026-01-01T15:00:00Z", "10000")
    record(monkeypatch, root, "2026-01-31T15:00:00Z", "10500")
    series = {
        "2025-12-26": {"5. adjusted close": "100"},
        "2026-01-30": {"5. adjusted close": "102"},
    }
    Cache(root).get(
        "alpha:TIME_SERIES_WEEKLY_ADJUSTED:SPY",
        86400,
        lambda: {"Weekly Adjusted Time Series": series},
    )
    response = CliRunner().invoke(
        app,
        ["performance", "--since", "2026-01-01", "--benchmark", "SPY"]
        + ["--json", "--read-only", "--office", str(root)],
    )
    assert response.exit_code == 0, response.output
    data = json.loads(response.output)
    assert data["benchmark"]["return"] == "0.02"
    assert data["excess_return"] == "0.03"

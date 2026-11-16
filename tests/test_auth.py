import base64
import json

import pytest
from typer.testing import CliRunner

from fo.auth import authenticate
from fo.cli import app
from fo.doctor import diagnose
from fo.init import initialize
from fo.office import git


def test_retired_schwab_connector_points_to_plaid(tmp_path):
    from fo.errors import OfficeError
    from fo.sync import synchronize

    root = tmp_path / "office"
    initialize(root)
    with pytest.raises(OfficeError) as raised:
        authenticate(root, "schwab")
    assert raised.value.reason == "retired_provider" and "fo auth plaid" in raised.value.message
    (root / "profile/accounts.json").write_text(
        json.dumps({"accounts": [{"id": "schwab-1", "provider": "schwab", "last4": "6789"}]})
    )
    checks = {item["name"]: item for item in diagnose(root)}
    assert checks["accounts.retired.schwab"]["status"] == "warn"
    assert synchronize(root, dry_run=True) == [
        {
            "provider": "schwab",
            "status": "skipped",
            "reason": "retired_provider",
            "message": raised.value.message,
        }
    ]


@pytest.mark.parametrize("command", ["auth", "setup"])
@pytest.mark.parametrize("legacy", [False, True])
def test_simplefin_authentication_records_accounts(tmp_path, monkeypatch, command, legacy):
    import httpx
    import typer

    from fo.providers.simplefin import SimpleFIN

    root = tmp_path / "office"
    initialize(root)
    if legacy:
        config = root / "office.toml"
        config.write_text(
            "".join(
                line for line in config.read_text().splitlines(True) if not line.startswith("id = ")
            )
        )
        (root / ".claude/settings.json").write_text("{}\n")
    token = base64.b64encode(b"https://bridge.simplefin.org/claim/fixture").decode()
    monkeypatch.setattr(typer, "prompt", lambda *args, **kwargs: token)
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url: httpx.Response(
            200,
            request=httpx.Request("POST", url),
            text="https://fixture:SECRET@bridge.example/base",
        ),
    )
    monkeypatch.setattr(SimpleFIN, "discover", lambda self: [{"provider_ref": "a", "last4": ""}])
    monkeypatch.setattr(
        SimpleFIN,
        "accounts",
        lambda self, registry, **kwargs: [
            {"account_id": registry[0]["id"], "balance": {"net_value": "10"}}
        ],
    )
    args = (
        ["auth", "simplefin", "--office", str(root)]
        if command == "auth"
        else ["setup", str(root), "--provider", "simplefin"]
    )
    result = CliRunner().invoke(app, [*args, "--json"])
    if command == "setup":
        assert json.loads(result.output)["connections"] == [
            {"provider": "simplefin", "status": "connected"}
        ]
    else:
        assert result.exit_code == 0, result.output
    assert (
        git(root, "status", "--porcelain", "--", "profile", "office.toml", ".claude").stdout == ""
    )
    from fo.commits import commit_office

    commit_office(root, include_data=True)
    assert git(root, "status", "--porcelain").stdout == ""

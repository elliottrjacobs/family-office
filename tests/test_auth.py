import json
from datetime import UTC, datetime, timedelta

import pytest

from fo.auth import authenticate
from fo.doctor import diagnose
from fo.init import initialize


@pytest.mark.parametrize("existing_account", [True, False])
def test_browser_flow_writes_private_token_and_real_expiry(
    tmp_path, monkeypatch, capsys, existing_account
):
    import httpx
    import schwab.auth
    import typer

    root = tmp_path / "office"
    initialize(root)
    (root / "profile/accounts.json").write_text(
        json.dumps(
            {
                "accounts": [{"id": "a", "provider": "schwab", "last4": "6789"}]
                if existing_account
                else []
            }
        )
    )
    values = iter(["KEY_SENTINEL", "SECRET_SENTINEL", "https://127.0.0.1:8182"])
    monkeypatch.setattr(typer, "prompt", lambda *args, **kwargs: next(values))

    class Client:
        def get_account_numbers(self):
            return httpx.Response(
                200,
                request=httpx.Request("GET", "https://api.example/accountNumbers"),
                json=[{"accountNumber": "123456789", "hashValue": "HASH_SENTINEL"}],
            )

    def login(key, secret, callback, path, token_write_func, interactive):
        print("SECRET_SENTINEL callback")
        assert key == "KEY_SENTINEL" and not interactive
        token_write_func(
            {
                "creation_timestamp": datetime.now(UTC).timestamp(),
                "token": {"access_token": "ACCESS_SENTINEL", "refresh_token": "REFRESH_SENTINEL"},
            }
        )
        return Client()

    monkeypatch.setattr(schwab.auth, "client_from_login_flow", login)
    start = datetime.now(UTC)
    assert authenticate(root, "schwab")["authenticated"]
    accounts = json.loads((root / "profile/accounts.json").read_text())["accounts"]
    assert len(accounts) == 1
    assert accounts[0]["id"] == ("a" if existing_account else "schwab-1")
    token = root / "secrets/schwab-token.json"
    saved = json.loads(token.read_text())
    expiry = datetime.fromisoformat(saved["refresh_token_expires_at"].replace("Z", "+00:00"))
    assert timedelta(days=7) <= expiry - start < timedelta(days=7, seconds=5)
    assert token.stat().st_mode & 0o777 == 0o600
    assert token.parent.stat().st_mode & 0o777 == 0o700
    assert "SENTINEL" not in capsys.readouterr().out
    for path in (root / "profile").rglob("*"):
        if path.is_file():
            assert "HASH_SENTINEL" not in path.read_text()


def test_doctor_warns_at_36_hours_and_fails_after_expiry(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    token = root / "secrets/schwab-token.json"
    for hours, expected in ((36, "warn"), (-1, "fail")):
        token.write_text(
            json.dumps(
                {
                    "refresh_token_expires_at": (
                        datetime.now(UTC) + timedelta(hours=hours)
                    ).isoformat()
                }
            )
        )
        token.chmod(0o600)
        checks = {item["name"]: item for item in diagnose(root)}
        assert checks["schwab.token"]["status"] == expected

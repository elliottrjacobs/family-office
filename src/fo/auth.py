import base64
import contextlib
import io
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
import typer

from fo.accounts import register
from fo.config import read_secrets
from fo.errors import OfficeError
from fo.office import atomic_write, contained, write_json
from fo.store.authored import load


def save_keys(root, keys):
    def table(value, prefix=""):
        lines = []
        scalars = {k: v for k, v in value.items() if not isinstance(v, dict)}
        if prefix:
            lines.append(f"[{prefix}]")
        for key, item in scalars.items():
            lines.append(f"{json.dumps(key)} = {json.dumps(item)}")
        for key, item in value.items():
            if isinstance(item, dict):
                lines.extend(
                    table(item, prefix + "." + json.dumps(key) if prefix else json.dumps(key))
                )
        return lines

    directory = contained(root, "secrets")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    atomic_write(contained(root, "secrets/keys.toml"), "\n".join(table(keys)) + "\n", 0o600)


def register_schwab(root, mappings, keys):
    register(root, "schwab", [{"last4": str(entry["accountNumber"])[-4:]} for entry in mappings])
    registry = [a for a in load(root, "accounts")["accounts"] if a["provider"] == "schwab"]
    hashes = {}
    for entry in mappings:
        matches = [a for a in registry if a.get("last4") == str(entry["accountNumber"])[-4:]]
        if len(matches) != 1:
            raise OfficeError("ambiguous_account", "Provider account identities are ambiguous.")
        hashes[matches[0]["id"]] = entry["hashValue"]
    keys["schwab"]["account_hashes"] = hashes
    save_keys(root, keys)


def authenticate(root, provider):
    keys = read_secrets(root)
    if provider == "simplefin":
        encoded = typer.prompt("SimpleFIN setup token", hide_input=True)
        try:
            url = base64.b64decode(encoded, validate=True).decode()
            parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or parts.hostname != "bridge.simplefin.org"
                or parts.username
            ):
                raise ValueError("untrusted setup URL")
            with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = client.post(url)
                response.raise_for_status()
                access_url = response.text.strip()
            from fo.providers.simplefin import SimpleFIN

            keys["simplefin"] = {"access_url": access_url}
            save_keys(root, keys)
            register(root, "simplefin", SimpleFIN(access_url).discover())
        except Exception as exc:
            raise OfficeError(
                "authentication_failed", "SimpleFIN setup failed; no token details are displayed."
            ) from exc
    elif provider == "schwab":
        settings = keys.get("schwab", {})
        settings["app_key"] = settings.get("app_key") or typer.prompt(
            "Schwab app key", hide_input=True
        )
        settings["app_secret"] = settings.get("app_secret") or typer.prompt(
            "Schwab app secret", hide_input=True
        )
        callback = settings.get("callback_url") or typer.prompt(
            "Registered HTTPS loopback callback URL", default="https://127.0.0.1:8182"
        )
        parts = urlsplit(callback)
        if parts.scheme != "https" or parts.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise OfficeError("invalid_callback", "Use the registered HTTPS loopback callback URL.")
        settings["callback_url"] = callback
        expiry = (datetime.now(UTC) + timedelta(days=7)).isoformat().replace("+00:00", "Z")
        path = contained(root, "secrets/schwab-token.json")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)

        def persist(token, *args, **kwargs):
            write_json(path, {**token, "refresh_token_expires_at": expiry}, 0o600)

        try:
            import schwab.auth

            # The library opens the browser. Suppress its URL and callback chatter.
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                client = schwab.auth.client_from_login_flow(
                    settings["app_key"],
                    settings["app_secret"],
                    callback,
                    str(path),
                    token_write_func=persist,
                    interactive=False,
                )
                response = client.get_account_numbers()
                response.raise_for_status()
                mappings = response.json()
            keys["schwab"] = settings
            register_schwab(root, mappings, keys)
        except OfficeError:
            raise
        except Exception as exc:
            raise OfficeError(
                "authentication_failed",
                "Schwab browser authentication failed; no credential details are displayed.",
            ) from exc
    elif provider in {"alphavantage", "fred"}:
        keys[provider] = {"api_key": typer.prompt(provider + " API key", hide_input=True)}
        save_keys(root, keys)
    else:
        raise OfficeError("unknown_provider", "Use schwab, simplefin, alphavantage, or fred.")
    return {"provider": provider, "authenticated": True}

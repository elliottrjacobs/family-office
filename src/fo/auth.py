import base64
import json
from urllib.parse import urlsplit

import httpx
import typer

from fo.accounts import RETIRED, register
from fo.config import ensure_credentials, read_secrets, write_credential
from fo.errors import OfficeError


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

    write_credential(root, "keys.toml", "\n".join(table(keys)) + "\n")


def save_secret_json(root, name, value):
    """Store <name>.json in this machine's credential store (Keychain, or a 0600 file)."""
    write_credential(root, f"{name}.json", json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def authenticate(root, provider):
    ensure_credentials(root)
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
    elif provider == "plaid":
        from fo.providers.plaid import connect
        from fo.providers.plaid_link import run_link

        try:
            return connect(
                root,
                keys,
                typer.prompt,
                typer.confirm,
                run_link,
                announce=lambda text: typer.echo(text, err=True),
            )
        except OfficeError:
            raise
        except Exception as exc:
            raise OfficeError(
                "authentication_failed",
                "Plaid linking failed; no credential details are displayed.",
            ) from exc
    elif provider in {"alphavantage", "fred"}:
        keys[provider] = {"api_key": typer.prompt(provider + " API key", hide_input=True)}
        save_keys(root, keys)
    elif provider in RETIRED:
        raise OfficeError("retired_provider", RETIRED[provider])
    else:
        raise OfficeError("unknown_provider", "Use plaid, simplefin, alphavantage, or fred.")
    return {"provider": provider, "authenticated": True}

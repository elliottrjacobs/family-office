"""Own setup and checks; the user supplies only provider authentication."""

from pathlib import Path

from fo.accounts import register
from fo.auth import authenticate
from fo.config import read_secrets
from fo.doctor import diagnose
from fo.errors import OfficeError
from fo.init import initialize
from fo.lock import office_lock
from fo.providers.simplefin import SimpleFIN
from fo.sync import synchronize


def setup(path: Path, providers=None, offline=False):
    providers = list(dict.fromkeys(providers or ("schwab", "simplefin")))
    if set(providers) - {"schwab", "simplefin"}:
        raise OfficeError("unknown_provider", "Setup supports schwab and simplefin.")
    initialize(path)
    root = path.expanduser().resolve()
    if offline:
        checks = diagnose(root)
        return {
            "status": "needs_attention"
            if any(c["status"] == "fail" for c in checks)
            else "offline_ready",
            "checks": checks,
            "live_validation": "pending",
        }
    connection_results = []
    for provider in providers:
        try:
            with office_lock(root):
                keys = read_secrets(root)
                if provider == "simplefin" and keys.get("simplefin", {}).get("access_url"):
                    register(root, provider, SimpleFIN(keys["simplefin"]["access_url"]).discover())
                elif provider == "schwab":
                    from fo.providers.schwab import Schwab

                    try:
                        Schwab(root).discover()
                    except OfficeError as exc:
                        if exc.reason not in {"missing_credentials", "token_expired"}:
                            raise
                        authenticate(root, provider)
                else:
                    authenticate(root, provider)
            connection_results.append({"provider": provider, "status": "connected"})
        except (OfficeError, ValueError, KeyError, TypeError, OSError) as exc:
            connection_results.append(
                {
                    "provider": provider,
                    "status": "failed",
                    "reason": exc.reason
                    if isinstance(exc, OfficeError)
                    else "invalid_provider_state",
                }
            )
    sync_results = []
    for connection in connection_results:
        if connection["status"] == "connected":
            sync_results.extend(synchronize(root, provider=connection["provider"]))
    checks = diagnose(root)
    passed = all(
        r["status"] in {"connected", "complete"} for r in connection_results + sync_results
    ) and not any(c["status"] == "fail" for c in checks)
    return {
        "status": "ready" if passed else "needs_attention",
        "connections": connection_results,
        "sync": sync_results,
        "checks": checks,
        "live_validation": "connection_checked" if passed else "pending",
    }

import os
from datetime import UTC, datetime

from fo.config import credentials_dir, credentials_read_denied, load_json, read_config
from fo.errors import OfficeError
from fo.store.authored import PROFILE_FILES, load


def check(name, status, reason):
    return {"name": name, "status": status, "reason": reason}


def diagnose(root):
    checks = []
    config = {}
    try:
        config = read_config(root)
        checks.append(check("config", "pass", "Office settings parsed."))
    except OfficeError as exc:
        checks.append(check("config", "fail", exc.message))
    for name in PROFILE_FILES:
        try:
            load(root, name)
            checks.append(check("profile." + name, "pass", "Schema valid."))
        except OfficeError as exc:
            checks.append(check("profile." + name, "fail", exc.message))
    try:
        from fo.compute import account_role

        unknown = [a["id"] for a in load(root, "accounts")["accounts"] if not account_role(a)]
        if unknown:
            checks.append(
                check(
                    "accounts.roles",
                    "warn",
                    "Set role in profile/accounts.json so cash, allocation, and spend are exact: "
                    + ", ".join(unknown),
                )
            )
    except OfficeError:
        pass
    secret_dir = None
    try:
        secret_dir = credentials_dir(root)
        try:
            secret_dir.stat()
            directories = [secret_dir]
        except FileNotFoundError:
            directories = []
        if directories and not os.environ.get("FO_CREDENTIALS_HOME"):
            directories.append(secret_dir.parent)
        bad = any(p.stat().st_mode & 0o777 != 0o700 for p in directories)
        for path in secret_dir.rglob("*"):
            expected = 0o700 if path.is_dir() else 0o600
            bad |= path.is_symlink() or path.stat().st_mode & 0o777 != expected
        checks.append(
            check(
                "credentials.perms",
                "fail" if bad else "pass",
                "Incorrect credential permissions." if bad else "Credential permissions valid.",
            )
        )
    except (OfficeError, OSError) as exc:
        checks.append(
            check(
                "credentials.perms",
                "fail",
                exc.message
                if isinstance(exc, OfficeError)
                else "Local credentials are unavailable.",
            )
        )
    try:
        denied = credentials_read_denied(root)
        checks.append(
            check(
                "credentials.agent_reads",
                "pass" if denied else "fail",
                "Credential read deny rules valid."
                if denied
                else "Claude settings lack credential read deny rules. Run fo doctor --fix.",
            )
        )
    except (OfficeError, OSError):
        checks.append(
            check("credentials.agent_reads", "fail", "Claude permission settings are unavailable.")
        )
    legacy = root / "secrets"
    remaining = (
        ["secrets/ (symlink)"]
        if legacy.is_symlink()
        else sorted(
            str(p.relative_to(root)) for p in legacy.rglob("*") if p.is_file() or p.is_symlink()
        )
    )
    checks.append(
        check(
            "secrets.in_office",
            "fail" if remaining else "pass",
            "Credentials remain in office secrets/. Run fo doctor --fix to migrate them; "
            "download any .icloud placeholders first, "
            "or move them outside the office; resolve differing copies manually. Remaining: "
            + ", ".join(remaining)
            if remaining
            else "No credentials in the office folder.",
        )
    )
    if secret_dir is None or not (secret_dir / "keys.toml").exists():
        checks.append(
            check("providers", "warn", "Offline mode: no provider credentials configured.")
        )
    token = secret_dir / "schwab-token.json" if secret_dir else None
    if token and token.exists():
        try:
            expiry = load_json(token)["refresh_token_expires_at"]
            hours = (
                datetime.fromisoformat(expiry.replace("Z", "+00:00")) - datetime.now(UTC)
            ).total_seconds() / 3600
            status = "fail" if hours <= 0 else "warn" if hours <= 48 else "pass"
            checks.append(
                check(
                    "schwab.token",
                    status,
                    f"Browser re-authentication due in {max(0, hours):.1f} hours.",
                )
            )
        except (OfficeError, KeyError, TypeError, ValueError):
            checks.append(check("schwab.token", "fail", "Token expiry metadata invalid."))
    from fo.skills import freshness
    from fo.store.index import project

    try:
        state = project(root)
        checks.append(check("store.integrity", "pass", "Canonical records are valid."))
        from fo.store.jsonl import torn

        if torn(root):
            checks.append(
                check(
                    "store.tail",
                    "warn",
                    "Interrupted append ignored; the next write removes the fragment: "
                    + ", ".join(torn(root)),
                )
            )
        if not state["providers"]:
            checks.append(check("sync.age", "warn", "No completed account sync yet."))
        cadence = config.get("schedule", {}).get("sync_hours", 24)
        for provider, log in state["providers"].items():
            age = (
                datetime.now(UTC) - datetime.fromisoformat(log["as_of"].replace("Z", "+00:00"))
            ).total_seconds() / 3600
            checks.append(
                check(
                    "sync.age." + provider,
                    "warn" if age > cadence else "pass",
                    f"Last complete coverage check {max(0, age):.1f} hours ago.",
                )
            )
            if log.get("unmapped_accounts"):
                checks.append(
                    check(
                        "sync.unmapped." + provider,
                        "warn",
                        f"{log['unmapped_accounts']} account(s) skipped; "
                        f"run `fo auth {provider}`, then `fo sync`.",
                    )
                )
            if log.get("provider_errors"):
                checks.append(
                    check(
                        "sync.errors." + provider,
                        "warn",
                        f"{log['provider_errors']} institution connection(s) reported errors; "
                        "repair them at the provider.",
                    )
                )
        if state["stale_accounts"]:
            checks.append(
                check(
                    "sync.coverage",
                    "warn",
                    "Accounts missing from latest coverage: " + ", ".join(state["stale_accounts"]),
                )
            )
    except (OfficeError, KeyError, TypeError, ValueError):
        checks.append(
            check(
                "store.integrity",
                "fail",
                "Canonical records are invalid; inspect local Git history.",
            )
        )

    checks.extend(freshness(root))
    return checks

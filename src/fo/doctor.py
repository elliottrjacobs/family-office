from datetime import UTC, datetime

from fo.config import load_json, read_config
from fo.errors import OfficeError
from fo.office import contained, git
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
    secret_dir = contained(root, "secrets")
    bad = secret_dir.exists() and (secret_dir.stat().st_mode & 0o777 != 0o700)
    if secret_dir.exists():
        for path in secret_dir.rglob("*"):
            expected = 0o700 if path.is_dir() else 0o600
            bad |= path.is_symlink() or path.stat().st_mode & 0o777 != expected
    checks.append(
        check(
            "secrets.perms",
            "fail" if bad else "pass",
            "Incorrect secret permissions." if bad else "Secret permissions valid.",
        )
    )
    repo = git(root, "rev-parse", "--show-toplevel", check=False)
    ignored = git(root, "check-ignore", "secrets/probe", check=False).returncode == 0
    tracked = git(root, "ls-files", "secrets", check=False).stdout.strip()
    good = repo.returncode == 0 and ignored and not tracked
    checks.append(
        check(
            "secrets.ignored",
            "pass" if good else "fail",
            "Secrets excluded from Git."
            if good
            else "Secrets are tracked, not ignored, or office is not a Git repository.",
        )
    )
    if not (secret_dir / "keys.toml").exists():
        checks.append(
            check("providers", "warn", "Offline mode: no provider credentials configured.")
        )
    token = contained(root, "secrets/schwab-token.json")
    if token.exists():
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

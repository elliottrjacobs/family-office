"""Onboarding state derived from the office on disk.

The server caches ready responses for up to 25 seconds, invalidating them after
server-side device changes or advisor launches; setup responses are never cached.

The browser shows status and the next step. Each step carries the exact command for a
terminal and, where the Mac app can do it in its own windows, an action the page offers
as a button there: "setup", "connect" or "connect:<provider>", "sync", and "onboard"
(the interview, which runs as a conversation with the Onboard advisor). Credentials and
provider consent never pass through this server, and it never creates an office.
"""

import json
import platform
import shlex
from pathlib import Path

from fo.config import credentials_dir, public_config, read_config
from fo.doctor import diagnose
from fo.errors import OfficeError
from fo.init import target
from fo.office import contained
from fo.store.authored import load
from fo.store.jsonl import read_rows

LIVE = ("schwab", "simplefin", "plaid")
REASONS = {
    "no_office": "No office is open yet. Choose a folder for a new office.",
    "uninitialized_path": "This folder has no office yet. Create one in a terminal.",
    "unconnected": "The office has no connected accounts yet.",
    "offline": "CSV accounts are registered; import their exports to see balances.",
    "never_synced": "Accounts are connected but have not synced yet.",
    "stale": "The office works, and diagnostics found something to fix.",
    "ready": "The office is synced and healthy.",
}
ONBOARD = "Open the Onboard advisor; it interviews you and fills this in."
CHECKLIST = {
    "account_connected": "Connect an account",
    "first_sync": "Run the first sync",
    "profile_started": "Tell Onboard about your household",
    "first_run": "Talk to an advisor",
    "device_paired": "Pair a phone",
}
# What fo init leaves in profile/household.md until the interview replaces it.
UNANSWERED = "Complete with the onboard skill."
RUNS = "cache/serve/runs"
DEVICES = "devices.json"


def fo(*args, root=None):
    words = ["fo", *args] + (["--office", str(root)] if root else [])
    return " ".join(shlex.quote(str(word)) for word in words)


def step(command, purpose, action=None):
    return {"command": command, "purpose": purpose, "action": action}


def action(name):
    """What the Mac app can do about a doctor check without a terminal, if anything."""
    if name == "schwab.token":
        return "connect:schwab"
    if name.startswith("sync.unmapped."):
        return "connect:" + name.removeprefix("sync.unmapped.")
    if name.startswith("sync.age") or name == "sync.coverage":
        return "sync"
    if name == "sync.errors.plaid":
        return "connect:plaid"
    if name == "providers" or name.startswith("sync.errors."):
        return "connect"
    if name.startswith("profile.") or name == "accounts.roles":
        return "onboard"
    return None


def fix(root, name):
    """The command that resolves a doctor check, or None with a hint."""
    if name in {"skills.fresh", "agents.fresh"}:
        return fo("skills", "sync", root=root), None
    if name == "schwab.token":
        return fo("auth", "schwab", root=root), None
    if name.startswith("sync.unmapped."):
        return fo("auth", name.removeprefix("sync.unmapped."), root=root), None
    if name.startswith("sync.age") or name == "sync.coverage":
        return fo("sync", root=root), None
    if name == "providers":
        return (
            fo("auth", "simplefin", root=root),
            "Or connect Schwab with fo auth schwab, or your own Plaid account with fo auth plaid.",
        )
    if name == "sync.errors.plaid":
        return fo("auth", "plaid", root=root), "It offers to reconnect each institution in error."
    if name in {"credentials.perms", "credentials.agent_reads", "secrets.in_office"}:
        return fo("doctor", "--fix", root=root), "Download any .icloud placeholders first."
    if name == "office.ignore":
        return fo("doctor", "--fix", root=root), None
    if name == "office.uncommitted":
        return None, (
            "Commit or resolve changes outside notebook/, reports/ and data/ in Git, "
            "then retry fo commit or fo sync --commit."
        )
    if name.startswith("profile.") or name == "accounts.roles":
        return None, ONBOARD
    if name.startswith("sync.errors."):
        return None, "Repair the institution connection at the provider, then sync again."
    return None, "Inspect the office in a terminal; fo doctor shows the same check."


def choose(locator, value):
    """Point the server at a folder the user typed; validated exactly as fo init would."""
    try:
        locator.root()
    except OfficeError:
        pass
    else:
        raise OfficeError("office_already_open", "An office is already open; restart to switch.")
    if not isinstance(value, str) or not value.strip():
        raise OfficeError("invalid_request", "Enter a folder path.")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise OfficeError("invalid_path", "Enter a full folder path, such as ~/family-office.")
    root, _ = target(path)
    locator.path = root
    return root


def paired(root):
    """Whether local devices.json lists a device; an unreadable file counts as none."""
    try:
        path = credentials_dir(root) / DEVICES
        if not path.is_file():
            return False
        records = json.loads(path.read_text()).get("devices")
    except (OfficeError, ValueError, AttributeError, OSError):
        return False
    return isinstance(records, list) and bool(records)


def interviewed(root):
    """Whether the household file holds more than the placeholder fo init wrote."""
    try:
        return UNANSWERED not in contained(root, "profile/household.md").read_text()
    except (OfficeError, OSError, UnicodeDecodeError):
        return False


def checklist(root, connected, registry, complete):
    """Home's getting-started items, derived when the onboarding response is refreshed."""
    runs = contained(root, RUNS)
    done = {
        "account_connected": bool(connected) or bool(registry),
        "first_sync": bool(complete),
        "profile_started": interviewed(root),
        "first_run": runs.is_dir() and any(runs.glob("*.json")),
        "device_paired": paired(root),
    }
    return [{"id": key, "done": done[key], "label": label} for key, label in CHECKLIST.items()]


def derive(locator):
    result = {
        "state": "no_office",
        "reason": REASONS["no_office"],
        "office": None,
        "candidate": None,
        "steps": [],
        "note": None,
        "providers": [],
        "doctor": [],
        "last_sync": None,
        "checklist": [],
    }
    candidate = locator.candidate()
    if candidate is None:
        return result
    result["candidate"] = str(candidate)
    try:
        root = locator.root()
    except OfficeError:
        return {
            **result,
            "state": "uninitialized_path",
            "reason": REASONS["uninitialized_path"],
            "steps": [
                step(
                    fo("setup", candidate),
                    "Create the office and connect Schwab and SimpleFIN.",
                    "setup",
                ),
                step(fo("setup", candidate, "--offline"), "Create the office without accounts."),
                step(fo("setup", candidate, "--provider", "schwab"), "Connect only Schwab."),
                step(fo("setup", candidate, "--provider", "simplefin"), "Connect only SimpleFIN."),
                step(
                    fo("setup", candidate, "--provider", "plaid"),
                    "Connect only Plaid, with your own Plaid developer keys.",
                ),
            ],
        }
    result["office"] = str(root)
    config = read_config(root)
    try:
        connected = sorted(set(public_config(root)["secrets"]) & set(LIVE))
    except (OfficeError, OSError):
        connected = []
    registry = load(root, "accounts")["accounts"]
    registered = {a["provider"] for a in registry}
    result["providers"] = [
        {
            "provider": name,
            "connected": name in connected or name not in LIVE,
            "accounts": sum(a["provider"] == name for a in registry),
        }
        for name in sorted(set(connected) | registered)
    ]
    complete = [r for r in read_rows(root, "data/sync_log.jsonl") if r["status"] == "complete"]
    result["last_sync"] = complete[-1]["as_of"] if complete else None
    result["checklist"] = checklist(root, connected, registry, complete)
    offline = not connected and registered <= {"csv"}
    checks = [
        c
        for c in diagnose(root)
        if c["status"] in {"warn", "fail"} and not (offline and c["name"] == "providers")
    ]
    for check in checks:
        command, hint = fix(root, check["name"])
        result["doctor"].append(
            {**check, "command": command, "hint": hint, "action": action(check["name"])}
        )
    if offline and not registered:
        state, steps = (
            "unconnected",
            [
                step(
                    fo("auth", "schwab", root=root),
                    "Connect Schwab in the browser it opens.",
                    "connect:schwab",
                ),
                step(
                    fo("auth", "simplefin", root=root),
                    "Paste a SimpleFIN setup token when asked.",
                    "connect:simplefin",
                ),
                step(
                    fo("auth", "plaid", root=root),
                    "Enter your own Plaid client ID and secret, then link in Plaid Link.",
                    "connect:plaid",
                ),
            ],
        )
        result["note"] = (
            "To work from CSV exports instead, ask the Onboard advisor to register the accounts."
        )
    elif offline and not any(r["provider"] == "csv" for r in complete):
        state, steps = (
            "offline",
            [
                step(
                    fo("sync", "--provider", "csv", root=root),
                    f"Place Monarch or Schwab CSV exports in {root / 'imports'}/, then import them.",
                    "sync",
                )
            ],
        )
    elif not complete:
        repairs = [
            item
            for item in result["doctor"]
            if item["name"].startswith(("sync.unmapped.", "sync.errors."))
        ]
        purpose = " ".join(
            [item["hint"] for item in repairs if not item["command"] and item["hint"]]
            + ["Pull balances, positions, and transactions."]
        )
        state, steps = (
            "never_synced",
            [
                step(item["command"], item["reason"], item["action"])
                for item in repairs
                if item["command"]
            ]
            + [step(fo("sync", root=root), purpose, "sync")],
        )
        writer = config.get("hosts", {}).get("writer", "")
        hostname = platform.node()
        if writer != hostname:
            result["note"] = (
                f"Only the writer host ({writer or 'unset'}) syncs; it is not this machine. "
                "Run fo sync there."
            )
            if hostname:
                result["note"] += " Or make this machine the writer with:\n" + fo(
                    "config", "set", "hosts.writer", hostname, root=root
                )
    elif result["doctor"]:
        state = "stale"
        steps = [
            step(item["command"], item["reason"], item["action"])
            for item in result["doctor"]
            if item["command"]
        ]
    else:
        state, steps = "ready", []
    return {**result, "state": state, "reason": REASONS[state], "steps": steps}

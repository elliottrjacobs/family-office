"""Onboarding state, re-derived from the office on disk at every poll.

The browser shows status and the exact next command; credentials, provider consent,
setup, and sync always happen in the terminal. The server never creates an office.
"""

import platform
import shlex
from pathlib import Path

from fo.config import public_config, read_config
from fo.doctor import diagnose
from fo.errors import OfficeError
from fo.init import target
from fo.store.authored import load
from fo.store.jsonl import read_rows

LIVE = ("schwab", "simplefin")
REASONS = {
    "no_office": "No office is open yet. Choose a folder for a new office.",
    "uninitialized_path": "This folder has no office yet. Create one in a terminal.",
    "unconnected": "The office has no connected accounts yet.",
    "offline": "CSV accounts are registered; import their exports to see balances.",
    "never_synced": "Accounts are connected but have not synced yet.",
    "stale": "The office works, and diagnostics found something to fix.",
    "ready": "The office is synced and healthy.",
}
ONBOARD = "Run the onboard skill from your coding agent in the office folder."


def fo(*args, root=None):
    words = ["fo", *args] + (["--office", str(root)] if root else [])
    return " ".join(shlex.quote(str(word)) for word in words)


def step(command, purpose):
    return {"command": command, "purpose": purpose}


def fix(root, name):
    """The command that resolves a doctor check, or None with a hint."""
    if name in {"skills.fresh", "agents.fresh"}:
        return fo("skills", "sync", root=root), None
    if name == "schwab.token":
        return fo("auth", "schwab", root=root), None
    if name.startswith("sync.age") or name == "sync.coverage":
        return fo("sync", root=root), None
    if name == "providers":
        return fo("auth", "simplefin", root=root), "Or connect Schwab with fo auth schwab."
    if name == "secrets.perms":
        secrets = shlex.quote(str(root / "secrets"))
        return f"chmod 700 {secrets} && chmod 600 {secrets}/*", None
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
                step(fo("setup", candidate), "Create the office and connect Schwab and SimpleFIN."),
                step(fo("setup", candidate, "--offline"), "Create the office without accounts."),
                step(fo("setup", candidate, "--provider", "schwab"), "Connect only Schwab."),
                step(fo("setup", candidate, "--provider", "simplefin"), "Connect only SimpleFIN."),
            ],
        }
    result["office"] = str(root)
    config = read_config(root)
    connected = sorted(set(public_config(root)["secrets"]) & set(LIVE))
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
    offline = not connected and registered <= {"csv"}
    checks = [
        c
        for c in diagnose(root)
        if c["status"] in {"warn", "fail"} and not (offline and c["name"] == "providers")
    ]
    for check in checks:
        command, hint = fix(root, check["name"])
        result["doctor"].append({**check, "command": command, "hint": hint})
    if offline and not registered:
        state, steps = (
            "unconnected",
            [
                step(fo("auth", "schwab", root=root), "Connect Schwab in the browser it opens."),
                step(
                    fo("auth", "simplefin", root=root), "Paste a SimpleFIN setup token when asked."
                ),
            ],
        )
        result["note"] = (
            "To work from CSV exports instead, register accounts with the onboard skill."
        )
    elif offline and not any(r["provider"] == "csv" for r in complete):
        state, steps = (
            "offline",
            [
                step(
                    fo("sync", "--provider", "csv", root=root),
                    f"Place Monarch or Schwab CSV exports in {root / 'imports'}/, then import them.",
                )
            ],
        )
    elif not complete:
        state, steps = (
            "never_synced",
            [step(fo("sync", root=root), "Pull balances, positions, and transactions.")],
        )
        writer = config.get("hosts", {}).get("writer", "")
        if writer != platform.node():
            result["note"] = (
                f"Only the writer host ({writer or 'unset'}) syncs; it is not this machine. "
                "Run fo sync there."
            )
    elif result["doctor"]:
        state = "stale"
        steps = [
            step(item["command"], item["reason"]) for item in result["doctor"] if item["command"]
        ]
    else:
        state, steps = "ready", []
    return {**result, "state": state, "reason": REASONS[state], "steps": steps}

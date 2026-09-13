import os
import platform
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

from fo.config import read_config
from fo.errors import OfficeError
from fo.lock import office_lock
from fo.office import atomic_write, contained


def notification(message):
    if platform.system() != "Darwin":
        return {"sent": False, "reason": "unsupported_platform"}
    script = (
        'on run argv\ndisplay notification (item 1 of argv) with title "Family Office"\nend run'
    )
    result = subprocess.run(["osascript", "-e", script, message], capture_output=True, timeout=15)
    if result.returncode:
        raise OfficeError("notification_failed", "Notification delivery failed.")
    return {"sent": True}


def legacy_jobs():
    if platform.system() != "Darwin":
        return {"checked": False, "jobs": [], "reason": "unsupported_platform"}
    try:
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return {"checked": False, "jobs": [], "reason": "launchctl_unavailable"}
    labels = [line.split()[-1] for line in result.stdout.splitlines() if line.split()]
    return {
        "checked": result.returncode == 0,
        "jobs": [
            {"label": label, "unload_argv": ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"]}
            for label in labels
            if "family-office" in label
            and not label.startswith("local.family-office.")
            and re.fullmatch(r"[A-Za-z0-9._-]+", label)
        ],
    }


def schedule(root):
    uv = shutil.which("uv")
    if not uv:
        raise OfficeError("runtime_missing", "uv is required for scheduled operations.")
    jobs = {
        "doctor": (["doctor", "--notify"], {"Hour": 7, "Minute": 30}),
        "review": (["review", "--notify"], {"Weekday": 0, "Hour": 8, "Minute": 0}),
        "index": (["reports", "index"], {"Hour": 3, "Minute": 0}),
    }
    if read_config(root).get("hosts", {}).get("writer") == platform.node():
        jobs["sync"] = (["sync", "--commit"], {"Hour": 2, "Minute": 0})
    created = []
    with office_lock(root):
        contained(root, "cache/logs").mkdir(parents=True, exist_ok=True)
        for name, (args, interval) in jobs.items():
            path = contained(root, f"launchd/local.family-office.{name}.plist")
            body = {
                "Label": f"local.family-office.{name}",
                "ProgramArguments": [uv, "run", "fo", *args, "--office", str(root)],
                "WorkingDirectory": str(root),
                "StartCalendarInterval": interval,
                "EnvironmentVariables": {
                    "PATH": str(root / ".venv/bin") + ":" + str(Path(uv).parent) + ":/usr/bin:/bin"
                },
                "StandardOutPath": str(root / f"cache/logs/{name}.log"),
                "StandardErrorPath": str(root / f"cache/logs/{name}.error.log"),
            }
            atomic_write(path, plistlib.dumps(body).decode())
            created.append(
                {
                    "path": str(path),
                    "load_argv": ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)],
                }
            )
    return {
        "jobs": created,
        "installed": False,
        "note": "Definitions prepared; load only after the office runtime is pinned and cutover is approved.",
    }

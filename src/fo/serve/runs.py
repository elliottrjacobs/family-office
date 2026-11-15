"""Advisor runs: recorded under cache/serve/runs/, judged by the verifier.

Several runs answer at once, each its own engine process, up to [serve] parallel_runs
(three unless office.toml says otherwise); one conversation still takes one turn at a
time. The office lock is command-scoped, so the fo commands of concurrent runs take it
in turn: every run starts with FO_LOCK_WAIT set, which makes a command wait for the lock
instead of refusing. The lock is probed when a run launches, to refuse while a command
outside the server holds it. While the server's own account sync holds the office
(pause, resume), a run that launches is queued and starts when the sync ends. Each run
keeps a JSON record and an append-only event log, both 0600 in a 0700 directory; neither
holds environment, cookie, or token values. Durable results stay in reports/ and notebook/.

Completion follows the report, not the exit code: a verified report is completed;
otherwise recorded decisions make it partial; otherwise an error or nonzero exit is
failed; otherwise a clean exit with a final message is awaiting input. A partial run
resumes on its original report path.

Runs go to an engine: a runner registered by name. Each engine's defaults (model,
effort, budget, enabled) come from [serve.engines.<name>] in office.toml, and
[serve.engines] default names the engine a launch uses when it names none.

A run is either a report run, launched with a subject and judged by its report, or a
conversation ("chat"), launched with the user's own message. A conversation has no
report until the advisor writes one through fo report write; it ends each turn waiting
for the next message, and is completed only once a report it wrote verifies. Its record
keeps a title, the first line of the first message, for the history the app lists.

Web access follows the office's [serve] web policy, the context level, and the
conversation's own switch (web_allowed): "on", the default, offers search and fetch at
every level; "isolated" only at level none, which reads no household data; "off" never.
Every launch and resume derives `web` again and the record keeps it. A web run at level
none stays isolated from household data; at the other levels the guard limits what a
query or URL can carry instead. Each run also has a folder, cache/serve/runs/<id>/,
holding the guard hook's fetch counter (reset every turn) and web.jsonl and a
workspace/ for scratch files; a Codex run also keeps its own Codex home and HOME there,
so the folder is made before the command is built and a follow-up reuses it. Web
entries are folded into the event log as `web` events and counted in `web_count`.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

from fo import reports
from fo.brief import start
from fo.commits import record as commit_paths
from fo.config import ENGINES, read_config
from fo.errors import OfficeError
from fo.lock import WAIT as LOCK_WAIT
from fo.lock import office_lock, probe
from fo.notebook import decisions
from fo.office import atomic_write, contained
from fo.serve.guard import COUNTER
from fo.serve.runner import WEB_LOG, Runner, scrub
from fo.skills import registry
from fo.store.jsonl import identifier, now

FOLDER = "cache/serve/runs"
ACTIVE = {"queued", "running", "verifying"}
NOT_IN_CHAT = {
    "journal": "Record a decision with the form on the Decisions page.",
}
# keep_runs is the conversation history the app can list, across every advisor.
# parallel_runs is how many advisors may answer at once.
DEFAULTS = {
    "max_budget_usd": 2.0,
    "run_timeout_minutes": 30.0,
    "keep_runs": 300,
    "parallel_runs": 3,
}
PARALLEL_LIMIT = 8
# How long a run's fo command waits for the office lock another run's command holds.
RUN_LOCK_WAIT = 20.0
# How long a launch waits out a lock held for a moment before refusing as office_locked.
PROBE_WAIT = 2.0
# How long a queued run waits for the server's own sync before starting anyway.
SYNC_WAIT = 900.0
WEB_FETCH_CAP = 20
WEB_POLICIES = ("on", "isolated", "off")
DEFAULT_WEB = "on"
DEFAULT_ENGINE = "claude"
EFFORTS = ("low", "medium", "high")
# What an engine runs with when office.toml names nothing; models.json recommends the same.
ENGINE_DEFAULTS = {
    "claude": {"model": "claude-fable-5-1", "effort": "high", "enabled": True},
    # Off until its read confinement is path-based; see SECURITY.md and the U7 gate.
    "codex": {"model": "gpt-5.6-sol", "effort": "high", "enabled": False},
}
# Why an engine is off when office.toml does not turn it on.
DISABLED_BY_DEFAULT = {
    "codex": (
        "Codex is off by default: its isolation gate found that a shell command missing from "
        "the forbidden list (nl) can print a file in secrets/, because Codex confines reads by "
        "command, not by path. Turn it on with [serve.engines.codex] enabled = true only if "
        "you accept that."
    ),
}
RUN_ID = re.compile(r"[0-9A-Z]{26}")
JOURNAL = re.compile(r"(?:^|&&)\s*fo\b[^&]*\bjournal\s+add\b")
REPORT_WRITE = re.compile(r"(?:^|&&)\s*fo\b[^&]*\breport\s+write\b")
DECISION = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b")
RESUME = (
    "Resume the interrupted report. Pass --report {path} to fo start, fo report path, "
    "and fo report parts so the work continues in the same file and part directory, "
    "write the report through fo report write --report {path}, and record no decision twice."
)
# A model name reaches the engine as one argument; it must not read as a flag.
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,199}")
MESSAGE_LIMIT = 8000
TITLE_LIMIT = 80
REPORT_ARGUMENT = re.compile(r"--report[=\s]+(\S+)")
# What the app adds to a conversation's first turn, after the skill invocation. How an
# advisor converses, cites the web, and writes a report is in the skills and the office's
# AGENTS.md, so a coding agent opened on the office folder behaves the same; this note
# carries only what is particular to a run started by the app.
CHAT = (
    "You are in the Family Office app. This is the conversation your skill and AGENTS.md "
    "describe, and the user's message is below. What is particular to the app:\n"
    "- Open with fo start {skill} <subject> --level {level} --json.\n"
    "- The shell here runs only fo commands, one per call, with no pipes or redirects; read "
    "files with the file-reading tool instead.\n"
    "- The user watches your steps as you work, so do not narrate tool use or its errors.\n"
    "- The user has no terminal here. Never ask them to run a command or edit a file: do it "
    "yourself, or name the place in the app's Settings.\n"
    "- {web}"
)
WEB_ON = (
    "Web search and fetch are on in this chat. Use them as Web evidence in AGENTS.md says, "
    "and never put names, account numbers, or exact balances in a search or a URL."
)
WEB_OFF = (
    "Web search and fetch are off in this chat. Say so when an answer depends on current "
    "rules or prices you cannot check; the user can turn web access on below the message box."
)
# The onboard skill carries the interview itself; the app only records what it writes.
INTERVIEW = (
    "What you write under profile/ is recorded in the office's history for you after every "
    "reply, so do not commit and never mention committing."
)
PROFILE_COMMIT = "Update the profile from the onboard interview"
WEB_CHANGED = "(Web search and fetch are now {state} for this conversation.)"


def run_settings(root):
    value = read_config(root).get("serve", {})
    result = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        item = value.get(key, default) if isinstance(value, dict) else default
        if isinstance(item, bool) or not isinstance(item, int | float) or item <= 0:
            raise OfficeError("invalid_config", f"[serve] {key} must be a positive number.")
        result[key] = type(default)(item)
    cap = value.get("web_fetch_cap", WEB_FETCH_CAP) if isinstance(value, dict) else WEB_FETCH_CAP
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise OfficeError("invalid_config", "[serve] web_fetch_cap must be 0 or more.")
    result["parallel_runs"] = min(result["parallel_runs"], PARALLEL_LIMIT)
    result["web_fetch_cap"] = cap
    result["web"] = web_policy(root)
    return result


def web_policy(root):
    """[serve] web in office.toml: on (the default), isolated, or off."""
    serve = read_config(root).get("serve", {})
    value = serve.get("web", DEFAULT_WEB) if isinstance(serve, dict) else DEFAULT_WEB
    if value not in WEB_POLICIES:
        raise OfficeError("invalid_config", "[serve] web must be on, isolated, or off.")
    return value


def engine_settings(root):
    """The default engine and each engine's model, effort, budget, and enabled flag."""
    serve = read_config(root).get("serve", {})
    tables = serve.get("engines", {}) if isinstance(serve, dict) else {}
    if not isinstance(tables, dict):
        raise OfficeError("invalid_config", "[serve.engines] in office.toml must be a table.")
    default = tables.get("default", DEFAULT_ENGINE)
    if not isinstance(default, str) or not default:
        raise OfficeError("invalid_config", "[serve.engines] default must name an engine.")
    budget = run_settings(root)["max_budget_usd"]
    engines = {}
    for name in ENGINES:
        table = tables.get(name, {})
        if not isinstance(table, dict):
            raise OfficeError("invalid_config", f"[serve.engines.{name}] must be a table.")
        fallback = ENGINE_DEFAULTS[name]
        model = table.get("model", fallback["model"])
        if not isinstance(model, str) or not model.strip():
            raise OfficeError("invalid_config", f"[serve.engines.{name}] model must be text.")
        effort = table.get("effort", fallback["effort"])
        if effort not in EFFORTS:
            raise OfficeError(
                "invalid_config", f"[serve.engines.{name}] effort must be low, medium, or high."
            )
        cap = table.get("max_budget_usd", budget)
        if isinstance(cap, bool) or not isinstance(cap, int | float) or cap <= 0:
            raise OfficeError(
                "invalid_config", f"[serve.engines.{name}] max_budget_usd must be positive."
            )
        enabled = table.get("enabled", fallback["enabled"])
        if not isinstance(enabled, bool):
            raise OfficeError(
                "invalid_config", f"[serve.engines.{name}] enabled must be true or false."
            )
        engines[name] = {
            "model": model.strip(),
            "effort": effort,
            "max_budget_usd": float(cap),
            "enabled": enabled,
        }
    return {"default": default, "engines": engines}


def disabled_message(root, name):
    """Why an engine is off: its own finding unless office.toml turned it off itself."""
    serve = read_config(root).get("serve", {})
    tables = serve.get("engines", {}) if isinstance(serve, dict) else {}
    table = tables.get(name, {}) if isinstance(tables, dict) else {}
    if name in DISABLED_BY_DEFAULT and "enabled" not in (table if isinstance(table, dict) else {}):
        return DISABLED_BY_DEFAULT[name]
    return f"The {name} engine is turned off in office.toml ([serve.engines.{name}])."


def web_allowed(level, policy="isolated", wanted=None, household=False):
    """Whether a run may search and fetch.

    Never when the policy is off or the conversation switched web off. Always at context
    level none, where the run reads no household data. At the other levels only when the
    policy is on and the engine confines reads by path (household).
    """
    if policy == "off" or wanted is False:
        return False
    return level == "none" or (policy == "on" and household)


def web_scope(level):
    """What the guard holds a web run to: no household data at all, or limited sends."""
    return "isolated" if level == "none" else "household"


def title(text):
    """A conversation's name in the history: the first line of its first message."""
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return line if len(line) <= TITLE_LIMIT else line[: TITLE_LIMIT - 1].rstrip() + "…"


def start_time(pid):
    """When a process began, as ps prints it; a reused pid never matches a recorded one."""
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def stop(pid, grace):
    """SIGTERM the run's process group, then SIGKILL whatever outlives the grace period."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        return

    def finish():
        time.sleep(grace)
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass

    threading.Thread(target=finish, daemon=True).start()


@dataclass
class Slot:
    """One run in progress: its office, the report it writes, its process and its thread."""

    root: object
    report: str = ""
    process: object | None = None
    thread: object | None = None


class RunManager:
    def __init__(self, runners: dict[str, Runner] | Runner, grace=5.0, deep=False):
        # Engines by name; one runner alone registers under its own name.
        if not isinstance(runners, dict):
            runners = {runners.name: runners}
        self.runners = dict(runners)
        self.grace = grace
        self.deep = deep
        self.mutex = threading.Lock()
        self.changed = threading.Condition()
        # Runs in progress by id; empty when no advisor is answering.
        self.active: dict[str, Slot] = {}
        # Cleared while the server's own sync holds the office; queued runs wait on it.
        self.clear = threading.Event()
        self.clear.set()
        self.live = {}
        self.cancelled = set()
        # Runs stopped for a reason the record keeps: the time limit or the server stopping.
        self.halted = {}
        self.reconciled = set()

    # Storage -----------------------------------------------------------------------

    def folder(self, root):
        path = contained(root, FOLDER)
        path.mkdir(parents=True, exist_ok=True)
        for directory in (path.parent, path):
            directory.chmod(0o700)
        return path

    def path(self, root, run_id, suffix):
        if not RUN_ID.fullmatch(run_id or ""):
            raise OfficeError("unknown_run", "No such run.")
        return self.folder(root) / f"{run_id}{suffix}"

    def run_folder(self, root, run_id):
        """The run's own 0700 folder: the hook's web log and counter, and workspace/."""
        path = self.path(root, run_id, "")
        for directory in (path, path / "workspace"):
            directory.mkdir(exist_ok=True)
            directory.chmod(0o700)
        return path

    def save(self, root, record):
        record["updated"] = now()
        atomic_write(
            self.path(root, record["id"], ".json"), json.dumps(record, indent=2) + "\n", 0o600
        )

    def get(self, root, run_id):
        self.reconcile(root)
        path = self.path(root, run_id, ".json")
        if not path.is_file():
            raise OfficeError("unknown_run", "No such run.")
        return json.loads(path.read_text())

    def list(self, root):
        self.reconcile(root)
        rows = []
        for path in self.folder(root).glob("*.json"):
            try:
                rows.append(json.loads(path.read_text()))
            except FileNotFoundError:
                # Another run finishing pruned or deleted it between the listing and the read.
                continue
        return sorted(rows, key=lambda r: r["created"], reverse=True)

    def events(self, root, run_id, after=0):
        path = self.path(root, run_id, ".jsonl")
        if not path.is_file():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        return [row for row in rows if row["seq"] > after]

    def emit(self, root, record, event):
        with self.changed:
            record["seq"] += 1
            event = scrub({**event, "seq": record["seq"], "at": now()})
            if event["kind"] != "delta":
                fd = os.open(
                    self.path(root, record["id"], ".jsonl"),
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                    0o600,
                )
                with os.fdopen(fd, "a") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.live.setdefault(record["id"], []).append(event)
            self.changed.notify_all()
        return event

    def engine(self, root, name=None):
        """The usable runner for an engine, its office settings, and its name; else refuse."""
        office = engine_settings(root)
        name = name or office["default"]
        runner = self.runners.get(name)
        if runner is None:
            raise OfficeError("unknown_engine", f"No engine named {name} is available.")
        settings = office["engines"].get(name)
        if settings is None or not settings["enabled"]:
            raise OfficeError("engine_disabled", disabled_message(root, name))
        runner.preflight()
        return runner, settings, name

    def status(self, root, probe_engine):
        """Every registered engine: usable or why not, its version, and the office defaults.

        probe_engine(name, runner) returns the preflight dict or raises its refusal; the
        route passes a cached probe because preflight starts the engine twice.
        """
        office = engine_settings(root)
        engines = []
        for name, runner in self.runners.items():
            defaults = office["engines"].get(name)
            entry = {"name": name, "usable": False, "version": None, "reason": None}
            entry["message"] = None
            if defaults is not None and not defaults["enabled"]:
                entry["reason"] = "engine_disabled"
                entry["message"] = disabled_message(root, name)
            else:
                try:
                    entry["version"] = probe_engine(name, runner).get("version")
                    entry["usable"] = True
                except OfficeError as exc:
                    entry["reason"], entry["message"] = exc.reason, exc.message
            engines.append({**entry, "defaults": defaults})
        usable = [e for e in engines if e["usable"]]
        status = {
            "ready": bool(usable),
            "default": office["default"],
            "deep": self.deep,
            "web": web_policy(root),
            "parallel_runs": run_settings(root)["parallel_runs"],
            "engines": engines,
        }
        if not usable:
            first = next((e for e in engines if e["name"] == office["default"]), None)
            first = first or (engines[0] if engines else None)
            status["reason"] = first["reason"] if first else "unknown_engine"
            status["message"] = first["message"] if first else "No engine is available."
        return status

    def running(self, run_id):
        return run_id in self.active

    def wait(self, root, run_id, after, timeout):
        """New events after `after`, waiting up to timeout while the run is active."""
        deadline = time.monotonic() + timeout
        with self.changed:
            while True:
                if self.running(run_id):
                    fresh = [e for e in self.live.get(run_id, []) if e["seq"] > after]
                    if fresh:
                        return fresh, True
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return [], True
                    self.changed.wait(remaining)
                else:
                    return self.events(root, run_id, after), False

    # Lifecycle ---------------------------------------------------------------------

    def launch(
        self,
        root,
        skill,
        subject=None,
        level=None,
        deep=False,
        engine=None,
        model=None,
        effort=None,
        message=None,
        web=None,
    ):
        """Start a report run on a subject, or, with a message, a conversation."""
        advisor = next((a for a in registry()["skills"] if a["name"] == skill), None)
        if advisor is None:
            raise OfficeError("unknown_skill", "No such advisor.")
        if skill in NOT_IN_CHAT:
            raise OfficeError("not_in_chat", NOT_IN_CHAT[skill])
        chat = message is not None
        if chat:
            message = message.strip()
            if not message:
                raise OfficeError("invalid_request", "Write a message to send.")
            if len(message) > MESSAGE_LIMIT:
                raise OfficeError("invalid_request", "Keep a message under 8,000 characters.")
            subject = subject or "household"
        elif not subject:
            raise OfficeError("invalid_request", "Name a subject or write a message.")
        if web is not None and not isinstance(web, bool):
            raise OfficeError("invalid_request", "web must be true or false.")
        reports.component(subject)
        level = level or advisor["default_context"]
        if level not in advisor["allowed_context"]:
            raise OfficeError("invalid_context", "This advisor does not read at that level.")
        if deep and not (advisor["deep"] and self.deep):
            raise OfficeError("deep_unavailable", "Deep mode is not available for this run.")
        if model is not None and not MODEL.fullmatch(model):
            raise OfficeError("invalid_model", "Name the model as one word, such as an id.")
        if effort is not None and effort not in EFFORTS:
            raise OfficeError("invalid_effort", "Effort is low, medium, or high.")
        config = run_settings(root)
        runner, settings, name = self.engine(root, engine)
        config["max_budget_usd"] = settings["max_budget_usd"]
        if deep and not getattr(runner, "deep", True):
            raise OfficeError("deep_unavailable", f"Deep mode is not available with {name}.")
        if skill == "onboard" and not getattr(runner, "profile_writes", False):
            raise OfficeError(
                "engine_unsupported", f"The onboard interview is not available with {name}."
            )
        household = getattr(runner, "web_household", False)
        self.settle(root)
        with self.mutex:
            self.room(config)
            run_id = identifier()
            try:
                report = ""
                if not chat:
                    started = start(root, skill, subject, level)
                    if started["report"]["status"] != "ok":
                        raise OfficeError(
                            started["report"]["reason"], "No report path is available."
                        )
                    report = started["report"]["data"]["path"]
                    if any(slot.report == report for slot in self.active.values()):
                        raise OfficeError(
                            "run_active", "A run is already writing this report; wait for it."
                        )
                record = {
                    "id": run_id,
                    "skill": skill,
                    "subject": subject,
                    "mode": "chat" if chat else "report",
                    "title": title(message) if chat else subject,
                    "level": level,
                    "web_wanted": web,
                    "web": web_allowed(level, config["web"], web, household),
                    "web_count": 0,
                    "deep": deep,
                    "status": "queued",
                    "runner": name,
                    "engine": name,
                    "model": model or settings["model"],
                    "effort": effort or settings["effort"],
                    "reported_model": None,
                    "session_id": None,
                    "report": report,
                    "report_written": False,
                    "decisions": [],
                    "exit_code": None,
                    "verify": None,
                    "error": None,
                    "cost_usd": 0.0,
                    "max_budget_usd": settings["max_budget_usd"],
                    # Codex has no budget flag: there the time limit bounds a run.
                    "budget_enforced": getattr(runner, "enforces_budget", True),
                    "turns": 0,
                    "pid": None,
                    "seq": 0,
                    "created": now(),
                    "updated": now(),
                }
                self.save(root, record)
                # The folder comes first: a Codex run's home and workspace live in it.
                folder = self.run_folder(root, record["id"])
            except Exception:
                self.active.pop(run_id, None)
                raise
            self.active[run_id] = Slot(root, report)
        prompt = f"/{skill} {subject} --level {level}" + (" --deep" if deep else "")
        if chat:
            rules = CHAT.format(skill=skill, level=level, web=WEB_ON if record["web"] else WEB_OFF)
            if skill == "onboard":
                rules += "\n" + INTERVIEW
            prompt += f"\n\n{rules}\n\nThe user's message:\n{message}"
        if hasattr(runner, "prompt"):
            prompt = runner.prompt(prompt, record["report"], folder)
        self.begin(root, record, prompt, None, config, message if chat else None)
        return record

    def message(self, root, run_id, text, web=None):
        text = (text or "").strip()
        if len(text) > MESSAGE_LIMIT:
            raise OfficeError("invalid_request", "Keep a message under 8,000 characters.")
        if web is not None and not isinstance(web, bool):
            raise OfficeError("invalid_request", "web must be true or false.")
        record = self.get(root, run_id)
        if record["status"] in ACTIVE:
            raise OfficeError("run_active", "This run is still in progress.")
        if not record["session_id"]:
            raise OfficeError("not_resumable", "This run never started a session to resume.")
        if not text and record["status"] != "partial":
            raise OfficeError("invalid_request", "Write a message to send.")
        partial = record["status"] == "partial"
        config = run_settings(root)
        runner, engine, _ = self.engine(root, record.get("engine") or record.get("runner"))
        config["max_budget_usd"] = engine["max_budget_usd"]
        household = getattr(runner, "web_household", False)
        before = web_allowed(record["level"], config["web"], record.get("web_wanted"), household)
        if web is not None:
            record["web_wanted"] = web
        after = web_allowed(record["level"], config["web"], record.get("web_wanted"), household)
        self.settle(root)
        with self.mutex:
            if self.running(run_id):
                raise OfficeError("run_active", "This run is still in progress.")
            self.room(config)
            record["status"] = "queued"
            record["error"] = None
            self.save(root, record)
            self.active[run_id] = Slot(root, record["report"])
        prompt = text
        if after != before:
            # The session was told the other state when it began.
            prompt = WEB_CHANGED.format(state="on" if after else "off") + "\n\n" + text
        if partial:
            prompt = RESUME.format(path=record["report"]) + (f"\n\n{text}" if text else "")
            if hasattr(runner, "prompt"):
                # A follow-up reuses the run's folder, and with it the Codex thread's home.
                folder = self.run_folder(root, record["id"])
                prompt = runner.prompt(prompt, record["report"], folder)
        self.begin(root, record, prompt, record["session_id"], config, text or None)
        return record

    def delete(self, root, run_id):
        """Remove a finished conversation: its record, its event log, and its folder."""
        record = self.get(root, run_id)
        with self.mutex:
            if self.running(run_id) or record["status"] in ACTIVE:
                raise OfficeError("run_active", "Stop this conversation before deleting it.")
            for suffix in (".json", ".jsonl"):
                self.path(root, run_id, suffix).unlink(missing_ok=True)
            shutil.rmtree(self.path(root, run_id, ""), ignore_errors=True)
        return {"deleted": run_id}

    def room(self, config):
        """Hold the mutex: refuse when as many advisors as the office allows are answering."""
        limit = config["parallel_runs"]
        if len(self.active) >= limit:
            raise OfficeError(
                "run_limit",
                f"{limit} advisors are already answering, the most this office runs at once. "
                "Wait for one to finish or stop one.",
            )

    def settle(self, root):
        """Refuse a launch while a command outside the server holds the office lock.

        Another run's fo command holds it for a moment, so a held lock is probed again for
        a short while first. During the server's own sync the launch goes ahead: the run
        is queued and starts when the sync ends.
        """
        if not self.clear.is_set():
            return
        deadline = time.monotonic() + PROBE_WAIT
        while probe(root):
            if not self.clear.is_set():
                return
            if time.monotonic() >= deadline:
                raise OfficeError(
                    "office_locked", "Another fo command holds the office lock; retry."
                )
            time.sleep(0.05)

    def pause(self):
        """Take the office for the server's own sync; refused while an advisor is answering."""
        with self.mutex:
            if self.active:
                raise OfficeError("run_active", "An advisor is working; sync when it finishes.")
            self.clear.clear()

    def resume(self):
        """The sync is over; queued runs start."""
        self.clear.set()

    def cancel(self, root, run_id):
        with self.mutex:
            slot = self.active.get(run_id)
            if slot is None:
                raise OfficeError("not_running", "That run is not in progress.")
            self.cancelled.add(run_id)
            # A queued run has no process yet; run() stops it as soon as it starts.
            if slot.process is not None:
                stop(slot.process.pid, self.grace)
        return self.get(root, run_id)

    def expire(self, run_id):
        self.halt(run_id, ("run_timeout", "The run reached its time limit."))

    def halt(self, run_id, error):
        with self.mutex:
            slot = self.active.get(run_id)
            if slot is not None:
                self.halted[run_id] = error
                # A queued run has no process yet; run() stops it as soon as it starts.
                if slot.process is not None:
                    stop(slot.process.pid, self.grace)

    def shutdown(self):
        """Stop every run as the server stops, and wait for their records to settle."""
        with self.mutex:
            slots = dict(self.active)
        for run_id in slots:
            self.halt(run_id, ("server_stopped", "fo serve stopped mid-run."))
        # Queued runs waiting on a sync see the halt once they stop waiting.
        self.clear.set()
        deadline = time.monotonic() + self.grace + 5
        for slot in slots.values():
            if slot.thread is not None:
                slot.thread.join(max(0.0, deadline - time.monotonic()))

    def begin(self, root, record, prompt, session, config, shown=None):
        """Log the user's turn and start the engine; shown is what the user typed."""
        # Never reuse a sequence number already in the log, whatever the record says.
        logged = self.events(root, record["id"], record["seq"])
        record["seq"] = max([record["seq"], *(e["seq"] for e in logged)])
        self.live[record["id"]] = []
        self.emit(root, record, {"kind": "user", "text": shown or prompt})
        thread = threading.Thread(
            target=self.run, args=(root, record, prompt, session, config), daemon=True
        )
        with self.mutex:
            slot = self.active.get(record["id"])
            if slot is not None:
                slot.thread = thread
        thread.start()

    def stopped(self, run_id):
        return run_id in self.cancelled or run_id in self.halted

    def queue(self, record):
        """Wait out the server's own sync; False when the run was stopped while it waited."""
        deadline = time.monotonic() + SYNC_WAIT
        while not self.clear.wait(0.2):
            if self.stopped(record["id"]):
                return False
            if time.monotonic() >= deadline:
                break
        return not self.stopped(record["id"])

    def run(self, root, record, prompt, session, config):
        runner = self.runners.get(record.get("engine") or record.get("runner"))
        # Derived again on every launch and resume; a stored flag never widens a run.
        web = record["web"] = web_allowed(
            record["level"],
            config.get("web", "isolated"),
            record.get("web_wanted"),
            getattr(runner, "web_household", False),
        )
        writes = record["skill"] == "onboard" and getattr(runner, "profile_writes", False)
        if not self.queue(record):
            self.finish(root, record, None, None, None)
            return
        # Engines that keep parse state (Codex) hand out one parser per run.
        parser = runner.parser() if hasattr(runner, "parser") else runner
        try:
            folder = self.run_folder(root, record["id"])
            # The fetch cap bounds one turn, so a long conversation can keep looking up.
            (folder / COUNTER).unlink(missing_ok=True)
            # Runners that keep state in the run folder (Codex) take it as a keyword and
            # start in its workspace; the Claude runner starts in the office.
            extra, cwd = {}, root
            if getattr(runner, "needs_folder", False):
                runner.prepare_home(folder)
                extra, cwd = {"folder": folder}, runner.workspace(folder)
            argv = runner.command(
                root,
                runner.settings(root, web=web, profile_writes=writes, **extra),
                config["max_budget_usd"],
                session,
                record.get("model"),
                record.get("effort"),
                web=web,
                **extra,
            )
            env = runner.environment(
                root,
                folder,
                web,
                config["web_fetch_cap"],
                web_scope=web_scope(record["level"]),
                skill=record["skill"],
            )
            # Other conversations run fo commands too; wait for the lock instead of failing.
            env[LOCK_WAIT] = str(RUN_LOCK_WAIT)
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except Exception:  # noqa: BLE001 - a run that cannot start is still recorded
            self.finish(root, record, None, None, ("runner_missing", "The runner could not start."))
            return
        with self.mutex:
            slot = self.active.get(record["id"])
            if slot is not None:
                slot.process = process
            if self.stopped(record["id"]):
                stop(process.pid, self.grace)
        timer = threading.Timer(config["run_timeout_minutes"] * 60, self.expire, [record["id"]])
        timer.daemon = True
        timer.start()
        pending, result, error = {}, None, None
        try:
            record.update(status="running", pid=process.pid, pid_started=start_time(process.pid))
            self.save(root, record)
            self.emit(root, record, {"kind": "status", "status": "running"})
            # Drain stderr so a chatty runner cannot block; its text is never stored.
            drained = deque(maxlen=20)
            threading.Thread(target=lambda: drained.extend(process.stderr), daemon=True).start()
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except OSError:
                pass
            for line in process.stdout:
                for event in parser.parse(line, root):
                    kind = event["kind"]
                    if kind == "init":
                        record["session_id"] = event.get("session_id") or record["session_id"]
                        record["reported_model"] = event.get("model")
                        problem = runner.check(event, record["skill"], web=web)
                        event = {k: event[k] for k in ("kind", "session_id", "model", "tools")}
                        if problem and error is None:
                            error = ("runner_isolation", problem)
                            stop(process.pid, self.grace)
                    elif kind == "tool":
                        pending[event["id"]] = event
                        if event.get("path") == record["report"] and event["name"] != "Read":
                            record["report_written"] = True
                    elif kind == "tool_result":
                        self.capture(root, record, pending.pop(event["id"], None), event)
                    elif kind == "result":
                        record["session_id"] = event.get("session_id") or record["session_id"]
                        record["cost_usd"] = round(
                            record["cost_usd"] + (event.get("cost_usd") or 0), 6
                        )
                        record["turns"] += event.get("turns") or 0
                        result = event
                    self.emit(root, record, event)
                self.fold(root, record)
        except Exception:  # noqa: BLE001 - whatever breaks, the run is stopped and judged
            error = error or ("runner_failed", "The run stopped unexpectedly.")
            stop(process.pid, self.grace)
        finally:
            process.wait()
            timer.cancel()
        self.finish(root, record, process.returncode, result, error)

    def fold(self, root, record):
        """Emit web events for the hook's web.jsonl entries this record has not counted."""
        path = self.path(root, record["id"], "") / WEB_LOG
        if not path.is_file():
            return
        # Only whole lines: the hook may be mid-append.
        lines = path.read_text(errors="replace").split("\n")[:-1]
        for line in lines[record.get("web_count", 0) :]:
            record["web_count"] = record.get("web_count", 0) + 1
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("kind") not in ("fetch", "search"):
                continue
            value = entry.get("value")
            if isinstance(value, str):
                self.emit(root, record, {"kind": "web", "action": entry["kind"], "value": value})

    def capture(self, root, record, call, result):
        """Decision ids from successful `fo journal add` calls, confirmed in the notebook."""
        if not call or call["name"] != "Bash" or not result["ok"]:
            return
        if REPORT_WRITE.search(call.get("command", "")):
            named = REPORT_ARGUMENT.search(call["command"])
            if record.get("mode") == "chat" and named:
                # A conversation learns its report from the write that created it.
                try:
                    record["report"] = reports.report_file(root, named[1].strip("'\""))
                    record["report_written"] = True
                except OfficeError:
                    pass
            elif record["report"] and record["report"] in call["command"]:
                record["report_written"] = True
        if not JOURNAL.search(call.get("command", "")):
            return
        known = {d["id"] for d in decisions(root)}
        for candidate in DECISION.findall(result["output"]):
            if candidate in known and candidate not in record["decisions"]:
                record["decisions"].append(candidate)
                self.emit(root, record, {"kind": "decision", "id": candidate})

    def finish(self, root, record, exit_code, result, error):
        try:
            self.fold(root, record)
            if record["skill"] == "onboard":
                # Before the turn settles, so the page never sees its files uncommitted.
                self.keep_profile(root)
            chat = record.get("mode") == "chat"
            if record["report"]:
                record["status"] = "verifying"
                self.emit(root, record, {"kind": "status", "status": "verifying"})
                try:
                    reports.verify(root, record["report"])
                    record["verify"] = {"valid": True, "reason": None}
                except OfficeError as exc:
                    record["verify"] = {"valid": False, "reason": exc.reason}
                except (OSError, ValueError, KeyError, TypeError):
                    record["verify"] = {"valid": False, "reason": "report_unreadable"}
            else:
                # A conversation that has written no report has nothing to verify.
                record["verify"] = None
            verified = bool(record["verify"] and record["verify"]["valid"])
            if record["id"] in self.halted and error is None:
                error = self.halted[record["id"]]
            if error is None and result is not None and not result["ok"]:
                subtype = result.get("subtype") or "runner_failed"
                error = (
                    subtype,
                    "This reply reached the spending limit for one turn. Send a message to "
                    "continue."
                    if "budget" in subtype
                    else "The run stopped with an error.",
                )
            if error is None and exit_code not in (0, None):
                error = ("runner_failed", "The run ended with an error.")
            if record["id"] in self.cancelled:
                status = "cancelled"
            elif chat:
                # A conversation is judged by its reply; a report is welcome, not required.
                if error or result is None or not result.get("text"):
                    status = "failed"
                else:
                    status = "completed" if verified else "awaiting_input"
            elif verified:
                status = "completed"
            elif record["decisions"]:
                status = "partial"
            elif error or result is None or not result.get("text"):
                status = "failed"
            else:
                status = "awaiting_input"
            if status == "failed" and error is None:
                error = (
                    "runner_failed",
                    "The advisor ended without an answer."
                    if chat
                    else "The run ended without a report or an answer.",
                )
            record.update(
                status=status,
                exit_code=exit_code,
                error={"reason": error[0], "message": error[1]} if error else None,
            )
            # Emit before saving so the stored sequence counter includes this last event.
            self.emit(root, record, {"kind": "status", "status": status})
            self.save(root, record)
        finally:
            with self.mutex:
                self.active.pop(record["id"], None)
                self.cancelled.discard(record["id"])
                self.halted.pop(record["id"], None)
            with self.changed:
                self.live.pop(record["id"], None)
                self.changed.notify_all()
        self.prune(root)

    def keep_profile(self, root):
        """Record what the onboard interview wrote under profile/ in the office's history.

        A run may not commit, and uncommitted profile files would leave doctor asking the
        owner for a terminal. Nothing but profile/ is staged; a held lock or a merge in
        progress leaves the files as they are for doctor to report.
        """
        try:
            # Another conversation's fo command may hold the lock for a moment.
            with office_lock(root, wait=RUN_LOCK_WAIT):
                commit_paths(root, ["profile"], PROFILE_COMMIT)
        except (OfficeError, OSError, subprocess.SubprocessError):
            pass

    def reconcile(self, root):
        """Records a previous server left running are judged now, as if they had exited."""
        if root in self.reconciled:
            return
        self.reconciled.add(root)
        for path in self.folder(root).glob("*.json"):
            record = json.loads(path.read_text())
            if record["status"] not in ACTIVE or self.running(record["id"]):
                continue
            if record.get("pid_started") and start_time(record["pid"]) == record["pid_started"]:
                stop(record["pid"], self.grace)
            logged = self.events(root, record["id"])
            record["seq"] = max([record["seq"], *(e["seq"] for e in logged)])
            self.finish(root, record, None, None, ("server_restarted", "fo serve stopped mid-run."))

    def prune(self, root):
        keep = run_settings(root)["keep_runs"]
        finished = [r for r in self.list(root) if r["status"] not in ACTIVE]
        for record in finished[keep:]:
            for suffix in (".json", ".jsonl"):
                self.path(root, record["id"], suffix).unlink(missing_ok=True)
            shutil.rmtree(self.path(root, record["id"], ""), ignore_errors=True)

"""Advisor runs: one at a time, recorded under cache/serve/runs/, judged by the verifier.

The office lock is command-scoped and cannot serialize a run, so a server mutex does,
and the lock is probed only when a run launches. Each run keeps a JSON record and an
append-only event log, both 0600 in a 0700 directory; neither holds environment, cookie,
or token values. Durable results stay in reports/ and notebook/.

Completion follows the report, not the exit code: a verified report is completed;
otherwise recorded decisions make it partial; otherwise an error or nonzero exit is
failed; otherwise a clean exit with a final message is awaiting input. A partial run
resumes on its original report path.

Runs go to an engine: a runner registered by name. Each engine's defaults (model,
effort, budget, enabled) come from [serve.engines.<name>] in office.toml, and
[serve.engines] default names the engine a launch uses when it names none.
"""

import json
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque

from fo import reports
from fo.brief import start
from fo.config import ENGINES, read_config
from fo.errors import OfficeError
from fo.lock import probe
from fo.notebook import decisions
from fo.office import atomic_write, contained
from fo.serve.runner import Runner, scrub
from fo.skills import registry
from fo.store.jsonl import identifier, now

FOLDER = "cache/serve/runs"
ACTIVE = {"queued", "running", "verifying"}
NOT_IN_CHAT = {
    "onboard": "Onboarding is an interview; run the onboard skill in a terminal.",
    "journal": "Record a decision with the form on the Decisions page.",
}
DEFAULTS = {"max_budget_usd": 2.0, "run_timeout_minutes": 30.0, "keep_runs": 50}
DEFAULT_ENGINE = "claude"
EFFORTS = ("low", "medium", "high")
# What an engine runs with when office.toml names nothing; models.json recommends the same.
ENGINE_DEFAULTS = {
    "claude": {"model": "claude-fable-5-1", "effort": "high"},
    "codex": {"model": "gpt-5.6-sol", "effort": "high"},
}
RUN_ID = re.compile(r"[0-9A-Z]{26}")
JOURNAL = re.compile(r"(?:^|&&)\s*fo\b[^&]*\bjournal\s+add\b")
DECISION = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b")
RESUME = (
    "Resume the interrupted report. Pass --report {path} to fo start, fo report path, "
    "and fo report parts so the work continues in the same file and part directory, "
    "write the report through fo report write --report {path}, and record no decision twice."
)
# A model name reaches the engine as one argument; it must not read as a flag.
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,199}")
MESSAGE_LIMIT = 8000


def run_settings(root):
    value = read_config(root).get("serve", {})
    result = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        item = value.get(key, default) if isinstance(value, dict) else default
        if isinstance(item, bool) or not isinstance(item, int | float) or item <= 0:
            raise OfficeError("invalid_config", f"[serve] {key} must be a positive number.")
        result[key] = type(default)(item)
    return result


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
        enabled = table.get("enabled", True)
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
        self.active = None
        self.process = None
        self.thread = None
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
        rows = [json.loads(p.read_text()) for p in self.folder(root).glob("*.json")]
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
            raise OfficeError(
                "engine_disabled",
                f"The {name} engine is turned off in office.toml ([serve.engines.{name}]).",
            )
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
                entry["message"] = (
                    f"The {name} engine is turned off in office.toml ([serve.engines.{name}])."
                )
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
            "engines": engines,
        }
        if not usable:
            first = next((e for e in engines if e["name"] == office["default"]), None)
            first = first or (engines[0] if engines else None)
            status["reason"] = first["reason"] if first else "unknown_engine"
            status["message"] = first["message"] if first else "No engine is available."
        return status

    def running(self, run_id):
        return self.active is not None and self.active[1] == run_id

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
        self, root, skill, subject, level=None, deep=False, engine=None, model=None, effort=None
    ):
        advisor = next((a for a in registry()["skills"] if a["name"] == skill), None)
        if advisor is None:
            raise OfficeError("unknown_skill", "No such advisor.")
        if skill in NOT_IN_CHAT:
            raise OfficeError("not_in_chat", NOT_IN_CHAT[skill])
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
        _, settings, name = self.engine(root, engine)
        config["max_budget_usd"] = settings["max_budget_usd"]
        with self.mutex:
            self.claim(root)
            try:
                started = start(root, skill, subject, level)
                if started["report"]["status"] != "ok":
                    raise OfficeError(started["report"]["reason"], "No report path is available.")
                record = {
                    "id": identifier(),
                    "skill": skill,
                    "subject": subject,
                    "level": level,
                    "deep": deep,
                    "status": "queued",
                    "runner": name,
                    "engine": name,
                    "model": model or settings["model"],
                    "effort": effort or settings["effort"],
                    "reported_model": None,
                    "session_id": None,
                    "report": started["report"]["data"]["path"],
                    "report_written": False,
                    "decisions": [],
                    "exit_code": None,
                    "verify": None,
                    "error": None,
                    "cost_usd": 0.0,
                    "turns": 0,
                    "pid": None,
                    "seq": 0,
                    "created": now(),
                    "updated": now(),
                }
                self.save(root, record)
            except Exception:
                self.active = None
                raise
            self.active = (root, record["id"])
        prompt = f"/{skill} {subject} --level {level}" + (" --deep" if deep else "")
        self.begin(root, record, prompt, None, config)
        return record

    def message(self, root, run_id, text):
        text = (text or "").strip()
        if len(text) > MESSAGE_LIMIT:
            raise OfficeError("invalid_request", "Keep a message under 8,000 characters.")
        record = self.get(root, run_id)
        if record["status"] in ACTIVE:
            raise OfficeError("run_active", "This run is still in progress.")
        if not record["session_id"]:
            raise OfficeError("not_resumable", "This run never started a session to resume.")
        if not text and record["status"] != "partial":
            raise OfficeError("invalid_request", "Write a message to send.")
        partial = record["status"] == "partial"
        config = run_settings(root)
        _, engine, _ = self.engine(root, record.get("engine") or record.get("runner"))
        config["max_budget_usd"] = engine["max_budget_usd"]
        with self.mutex:
            self.claim(root)
            record["status"] = "queued"
            record["error"] = None
            self.save(root, record)
            self.active = (root, record["id"])
        prompt = text
        if partial:
            prompt = RESUME.format(path=record["report"]) + (f"\n\n{text}" if text else "")
        self.begin(root, record, prompt, record["session_id"], config)
        return record

    def claim(self, root):
        """Hold the mutex: refuse while a run is active or another command holds the lock."""
        if self.active:
            raise OfficeError("run_active", "An advisor run is in progress; wait or cancel it.")
        if probe(root):
            raise OfficeError("office_locked", "Another fo command holds the office lock; retry.")

    def cancel(self, root, run_id):
        with self.mutex:
            if not self.running(run_id):
                raise OfficeError("not_running", "That run is not in progress.")
            self.cancelled.add(run_id)
            # A queued run has no process yet; run() stops it as soon as it starts.
            if self.process is not None:
                stop(self.process.pid, self.grace)
        return self.get(root, run_id)

    def expire(self, run_id):
        self.halt(run_id, ("run_timeout", "The run reached its time limit."))

    def halt(self, run_id, error):
        with self.mutex:
            if self.running(run_id):
                self.halted[run_id] = error
                # A queued run has no process yet; run() stops it as soon as it starts.
                if self.process is not None:
                    stop(self.process.pid, self.grace)

    def shutdown(self):
        """Stop the active run as the server stops, and wait for its record to settle."""
        active, thread = self.active, self.thread
        if active is None:
            return
        self.halt(active[1], ("server_stopped", "fo serve stopped mid-run."))
        if thread is not None:
            thread.join(self.grace + 5)

    def begin(self, root, record, prompt, session, config):
        # Never reuse a sequence number already in the log, whatever the record says.
        logged = self.events(root, record["id"], record["seq"])
        record["seq"] = max([record["seq"], *(e["seq"] for e in logged)])
        self.live[record["id"]] = []
        self.emit(root, record, {"kind": "user", "text": prompt})
        self.thread = threading.Thread(
            target=self.run, args=(root, record, prompt, session, config), daemon=True
        )
        self.thread.start()

    def run(self, root, record, prompt, session, config):
        runner = self.runners.get(record.get("engine") or record.get("runner"))
        try:
            argv = runner.command(
                root,
                runner.settings(root),
                config["max_budget_usd"],
                session,
                record.get("model"),
                record.get("effort"),
            )
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=root,
                env=runner.environment(root),
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except Exception:  # noqa: BLE001 - a run that cannot start is still recorded
            self.finish(root, record, None, None, ("runner_missing", "The runner could not start."))
            return
        with self.mutex:
            self.process = process
            if record["id"] in self.cancelled or record["id"] in self.halted:
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
                for event in runner.parse(line, root):
                    kind = event["kind"]
                    if kind == "init":
                        record["session_id"] = event.get("session_id") or record["session_id"]
                        record["reported_model"] = event.get("model")
                        problem = runner.check(event, record["skill"])
                        event = {k: event[k] for k in ("kind", "session_id", "model")}
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
        except Exception:  # noqa: BLE001 - whatever breaks, the run is stopped and judged
            error = error or ("runner_failed", "The run stopped unexpectedly.")
            stop(process.pid, self.grace)
        finally:
            process.wait()
            timer.cancel()
        self.finish(root, record, process.returncode, result, error)

    def capture(self, root, record, call, result):
        """Decision ids from successful `fo journal add` calls, confirmed in the notebook."""
        if not call or call["name"] != "Bash" or not result["ok"]:
            return
        if not JOURNAL.search(call.get("command", "")):
            return
        known = {d["id"] for d in decisions(root)}
        for candidate in DECISION.findall(result["output"]):
            if candidate in known and candidate not in record["decisions"]:
                record["decisions"].append(candidate)
                self.emit(root, record, {"kind": "decision", "id": candidate})

    def finish(self, root, record, exit_code, result, error):
        try:
            record["status"] = "verifying"
            self.emit(root, record, {"kind": "status", "status": "verifying"})
            try:
                reports.verify(root, record["report"])
                record["verify"] = {"valid": True, "reason": None}
            except OfficeError as exc:
                record["verify"] = {"valid": False, "reason": exc.reason}
            except (OSError, ValueError, KeyError, TypeError):
                record["verify"] = {"valid": False, "reason": "report_unreadable"}
            if record["id"] in self.halted and error is None:
                error = self.halted[record["id"]]
            if error is None and result is not None and not result["ok"]:
                error = (result.get("subtype") or "runner_failed", "The run stopped with an error.")
            if error is None and exit_code not in (0, None):
                error = ("runner_failed", "The run ended with an error.")
            if record["id"] in self.cancelled:
                status = "cancelled"
            elif record["verify"]["valid"]:
                status = "completed"
            elif record["decisions"]:
                status = "partial"
            elif error or result is None or not result.get("text"):
                status = "failed"
            else:
                status = "awaiting_input"
            if status == "failed" and error is None:
                error = ("runner_failed", "The run ended without a report or an answer.")
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
                if self.running(record["id"]):
                    self.active = None
                    self.process = None
                self.cancelled.discard(record["id"])
                self.halted.pop(record["id"], None)
            with self.changed:
                self.live.pop(record["id"], None)
                self.changed.notify_all()
        self.prune(root)

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

"""Advisor runs: one at a time, recorded under cache/serve/runs/, judged by the verifier.

The office lock is command-scoped and cannot serialize a run, so a server mutex does,
and the lock is probed only when a run launches. Each run keeps a JSON record and an
append-only event log, both 0600 in a 0700 directory; neither holds environment, cookie,
or token values. Durable results stay in reports/ and notebook/.

Completion follows the report, not the exit code: a verified report is completed;
otherwise recorded decisions make it partial; otherwise an error or nonzero exit is
failed; otherwise a clean exit with a final message is awaiting input. A partial run
resumes on its original report path.
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
from fo.config import read_config
from fo.errors import OfficeError
from fo.lock import probe
from fo.notebook import decisions
from fo.office import atomic_write, contained
from fo.serve.runner import scrub
from fo.skills import registry
from fo.store.jsonl import identifier, now

FOLDER = "cache/serve/runs"
ACTIVE = {"queued", "running", "verifying"}
NOT_IN_CHAT = {
    "onboard": "Onboarding is an interview; run the onboard skill in a terminal.",
    "journal": "Record a decision with the form on the Decisions page.",
}
DEFAULTS = {"max_budget_usd": 2.0, "run_timeout_minutes": 30.0, "keep_runs": 50}
RUN_ID = re.compile(r"[0-9A-Z]{26}")
JOURNAL = re.compile(r"(?:^|&&)\s*fo\b[^&]*\bjournal\s+add\b")
DECISION = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b")
RESUME = (
    "Resume the interrupted report. Pass --report {path} to fo start, fo report path, "
    "and fo report parts so the work continues in the same file and part directory, "
    "and record no decision twice."
)
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


def alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    return True


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
    def __init__(self, runner, grace=5.0, deep=False):
        self.runner = runner
        self.grace = grace
        self.deep = deep
        self.mutex = threading.Lock()
        self.changed = threading.Condition()
        self.active = None
        self.process = None
        self.live = {}
        self.cancelled = set()
        self.expired = set()
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

    def launch(self, root, skill, subject, level=None, deep=False):
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
        config = run_settings(root)
        self.runner.preflight()
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
                    "runner": self.runner.name,
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
        self.runner.preflight()
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
        with self.mutex:
            if self.running(run_id) and self.process is not None:
                self.expired.add(run_id)
                stop(self.process.pid, self.grace)

    def begin(self, root, record, prompt, session, config):
        # Never reuse a sequence number already in the log, whatever the record says.
        logged = self.events(root, record["id"], record["seq"])
        record["seq"] = max([record["seq"], *(e["seq"] for e in logged)])
        self.live[record["id"]] = []
        self.emit(root, record, {"kind": "user", "text": prompt})
        thread = threading.Thread(
            target=self.run, args=(root, record, prompt, session, config), daemon=True
        )
        thread.start()

    def run(self, root, record, prompt, session, config):
        argv = self.runner.command(
            root, self.runner.settings(root), config["max_budget_usd"], session
        )
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=root,
                env=self.runner.environment(root),
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError:
            self.finish(root, record, None, None, ("runner_missing", "The runner could not start."))
            return
        with self.mutex:
            self.process = process
            if record["id"] in self.cancelled:
                stop(process.pid, self.grace)
        record.update(status="running", pid=process.pid)
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
        timer = threading.Timer(config["run_timeout_minutes"] * 60, self.expire, [record["id"]])
        timer.daemon = True
        timer.start()
        pending, result, error = {}, None, None
        try:
            for line in process.stdout:
                for event in self.runner.parse(line, root):
                    kind = event["kind"]
                    if kind == "init":
                        record["session_id"] = event.get("session_id") or record["session_id"]
                        problem = self.runner.check(event, record["skill"])
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
        record["status"] = "verifying"
        self.emit(root, record, {"kind": "status", "status": "verifying"})
        try:
            reports.verify(root, record["report"])
            record["verify"] = {"valid": True, "reason": None}
        except OfficeError as exc:
            record["verify"] = {"valid": False, "reason": exc.reason}
        except (OSError, ValueError, KeyError, TypeError):
            record["verify"] = {"valid": False, "reason": "report_unreadable"}
        if record["id"] in self.expired and error is None:
            error = ("run_timeout", "The run reached its time limit.")
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
        with self.mutex:
            if self.running(record["id"]):
                self.active = None
                self.process = None
            self.cancelled.discard(record["id"])
            self.expired.discard(record["id"])
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
            if record.get("pid") and alive(record["pid"]):
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

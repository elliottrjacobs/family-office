"""Codex headless runner (`codex exec --json`), isolated to the office.

Every run gets its own Codex home and HOME inside its run folder,
cache/serve/runs/<id>/: codex-home/ holds a config.toml, rules/fo.rules, an empty
skills/ folder, and auth.json as a link to the user's sign-in, so no user config, user
rules, user skills, MCP server, or ChatGPT connector reaches the run; home/ stands in for
HOME so ~/.agents/skills and ~/.codex are never discovered. The command passes
--ignore-user-config and repeats every setting with -c, so neither a Codex home nor the
office's own .codex/config.toml (the workspace sits inside the office's git repository,
so Codex treats the office as the project) can loosen it: approvals never prompted,
workspace-write with the run's workspace/ as the only writable root (/tmp and $TMPDIR
excluded, network off: fo runs outside the sandbox and keeps its own), web search off unless the run is at context level none, and
the account-level features that add tools turned off.

Codex has no Read tool and no path hook: reads happen through shell commands and edits
through apply_patch, which writes only inside the workspace. The execpolicy in
rules/fo.rules forbids the commands that print, copy, or send a file (cat, head, sed,
python, curl, and the rest) and allows fo, which then runs outside the sandbox so it can
write the office under the run marker. Read confinement is therefore command-based, not
path-based like the Claude hook: `ls` can still list names anywhere, and a reader the list
misses can print a file (the gate found `nl`), which is why the engine ships disabled.
The prompt goes on stdin. Codex has no budget flag: a run is bounded by the server's wall-clock limit,
and the budget is recorded for information only.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from fo.errors import OfficeError
from fo.office import RUN_MARKER
from fo.serve.runner import FETCH_CAP, OUTPUT_LIMIT, RUN_FOLDER, WEB_FLAG

MINIMUM = (0, 157, 1)
# A path to the codex executable, for a server started without it on PATH.
EXECUTABLE = "FO_CODEX_EXECUTABLE"
# Every flag here is part of the isolation; a version that lacks one may not run.
# --search is a top-level codex flag; the rest belong to codex exec.
FLAGS = ("--json", "--ignore-user-config", "--skip-git-repo-check", "-C", "-m", "-c")
TOP_FLAGS = ("--search",)
MODE = "never"
# Codex research workers would inherit the config; deep mode is not offered through it.
DEEP = False
# The tools Codex reports in this configuration; collaboration.* are its own sub-agents,
# which inherit the run's config and policy.
TOOLS = ("Bash", "Write")
FEATURES = (
    "apps",
    "plugins",
    "remote_plugin",
    "multi_agent",
    "image_generation",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "in_app_browser",
    "goals",
    "skill_search",
    "skill_mcp_dependency_install",
    "tool_suggest",
    "recommended_plugins",
    "daemon_auto_start",
)
FORBIDDEN = (
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "sed",
    "awk",
    "grep",
    "rg",
    "egrep",
    "fgrep",
    "strings",
    "od",
    "xxd",
    "hexdump",
    "base64",
    "cut",
    "sort",
    "uniq",
    "tee",
    "dd",
    "cp",
    "mv",
    "ln",
    "rsync",
    "ditto",
    "install",
    "tar",
    "zip",
    "unzip",
    "gzip",
    "gunzip",
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "npm",
    "npx",
    "bun",
    "deno",
    "sh",
    "bash",
    "zsh",
    "dash",
    "env",
    "xargs",
    "find",
    "open",
    "osascript",
    "curl",
    "wget",
    "nc",
    "ncat",
    "ssh",
    "scp",
    "sftp",
    "telnet",
    "git",
    "chmod",
    "chown",
    "vi",
    "vim",
    "nano",
    "emacs",
    "sqlite3",
    "uv",
    "pip",
    "pip3",
    "brew",
    "kill",
    "pkill",
    # Found by the gate or plainly able to print a file; the list can never be complete.
    "nl",
    "diff",
    "cmp",
    "comm",
    "join",
    "paste",
    "pr",
    "fold",
    "fmt",
    "rev",
    "look",
    "column",
    "expand",
    "unexpand",
    "split",
    "csplit",
    "zcat",
    "gzcat",
    "bzcat",
    "xzcat",
    "zless",
    "zmore",
    "bzip2",
    "xz",
    "plutil",
    "textutil",
    "defaults",
    "security",
    "openssl",
    "jq",
    "php",
    "swift",
    "lua",
    "tclsh",
    "make",
    "ed",
    "ex",
    "view",
    "m4",
    "iconv",
    "vis",
    "mdls",
    "mdfind",
    "xattr",
    "say",
    "pbcopy",
    "lp",
)
# An allowed command runs outside the sandbox (the gate saw `touch` write beyond the
# workspace), so only fo, which must write the office, and commands that write nothing
# are allowed; mkdir and touch stay unmatched and therefore sandboxed to the workspace.
ALLOWED = ("fo", "ls", "echo", "pwd", "date", "true")
# Login needs these; nothing else from the server's environment reaches the run.
PASSED = (
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
)
SIGN_IN = "Sign in to Codex in a terminal first (codex login) to chat with advisors."
PREFACE = (
    "Write the finished report with: fo report write --report {report} --body-file "
    "{body} (draft report.md with apply_patch first)."
)


def version(text):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(part) for part in match.groups()) if match else None


def overrides(model=None, effort=None, web=False):
    """The settings every run starts from, as (key, TOML value) pairs, config.toml order."""
    pairs = []
    if model:
        pairs.append(("model", json.dumps(model)))
    if effort:
        pairs.append(("model_reasoning_effort", json.dumps(effort)))
    pairs += [
        ("approval_policy", json.dumps(MODE)),
        ("sandbox_mode", '"workspace-write"'),
        ("sandbox_workspace_write.network_access", "false"),
        ("sandbox_workspace_write.exclude_slash_tmp", "true"),
        ("sandbox_workspace_write.exclude_tmpdir_env_var", "true"),
        ("web_search", '"live"' if web else '"disabled"'),
        ("suppress_unstable_features_warning", "true"),
    ]
    pairs += [(f"features.{name}", "false") for name in FEATURES]
    return pairs


def rules():
    lines = [f'prefix_rule(pattern=["{name}"], decision="forbidden")' for name in FORBIDDEN]
    lines += [f'prefix_rule(pattern=["{name}"], decision="allow")' for name in ALLOWED]
    return "\n".join(lines) + "\n"


def config_toml(model=None, effort=None):
    """config.toml for the run's Codex home; the command repeats every key with -c."""
    top, tables = [], {}
    for key, value in overrides(model, effort):
        table, _, name = key.rpartition(".")
        (tables.setdefault(table, []) if table else top).append(f"{name} = {value}")
    parts = ["\n".join(top)]
    parts += [f"[{table}]\n" + "\n".join(lines) for table, lines in tables.items()]
    return "\n\n".join(parts) + "\n"


def private_folder(path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


class CodexRunner:
    name = "codex"

    # The run manager passes the run folder to command() and settings() and starts the
    # process in workspace(folder).
    needs_folder = True
    deep = DEEP
    # Codex has no budget flag; the record keeps the budget for information only.
    enforces_budget = False

    def __init__(self, executable=None, python=None, auth_home=None):
        self.invalid = None
        if executable is None:
            named = os.environ.get(EXECUTABLE)
            if named:
                # The Mac app starts the server with a scrubbed PATH and names Codex here.
                if os.path.isfile(named) and os.access(named, os.X_OK):
                    executable = [named]
                else:
                    self.invalid = named
                    executable = []
            else:
                found = shutil.which("codex")
                executable = [found] if found else []
        self.executable = list(executable)
        self.python = python or sys.executable
        self.auth_home = auth_home
        # The thread and last reply of the run being parsed; runs are one at a time.
        self.thread, self.reply = None, ""

    def auth(self):
        """The user's Codex sign-in, which every run links to and never copies."""
        home = self.auth_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex"
        return Path(home).expanduser() / "auth.json"

    def preflight(self):
        """Refuse to run when Codex is missing, too old, lacks a flag, or is not signed in."""
        if self.invalid is not None:
            raise OfficeError(
                "runner_missing",
                f"{EXECUTABLE} does not name an executable Codex; fix or unset it.",
            )
        if not self.executable:
            raise OfficeError("runner_missing", "Install the Codex CLI and sign in to use it.")
        try:
            reported = subprocess.run(
                [*self.executable, "--version"], capture_output=True, text=True, timeout=30
            ).stdout
            top = subprocess.run(
                [*self.executable, "--help"], capture_output=True, text=True, timeout=30
            ).stdout
            usage = subprocess.run(
                [*self.executable, "exec", "--help"], capture_output=True, text=True, timeout=30
            ).stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OfficeError("runner_missing", "Codex could not be started.") from exc
        found = version(reported)
        if found is None or found < MINIMUM:
            raise OfficeError(
                "runner_outdated",
                "Codex {} or later is required; update it to chat with advisors.".format(
                    ".".join(map(str, MINIMUM))
                ),
            )
        words = set(re.findall(r"(?<![\w-])-{1,2}[A-Za-z][\w-]*", usage))
        missing = [flag for flag in FLAGS if flag not in words]
        missing += [flag for flag in TOP_FLAGS if flag not in top]
        if not re.search(r"^\s+resume\b", usage, re.M):
            missing.append("exec resume")
        if missing:
            raise OfficeError(
                "runner_unsupported",
                "This Codex lacks " + ", ".join(missing) + ", so a run cannot be isolated.",
            )
        if not self.auth().is_file():
            raise OfficeError("runner_missing", SIGN_IN)
        return {"runner": self.name, "version": ".".join(map(str, found))}

    def check(self, init, skill, web=False):
        """Why the started session is not isolated as launched, or None when it is.

        Codex's JSONL reports no tool list or skills at thread start, so the tools are the
        configured set and the skill check is skipped; the gate verified both by hand.
        """
        problems = []
        if init["mcp_servers"]:
            problems.append("MCP servers were loaded")
        extra = sorted(set(init["tools"]) - set(TOOLS))
        if extra:
            problems.append("unexpected tools " + ", ".join(extra))
        if init["permission_mode"] != MODE:
            problems.append(f"approval policy {init['permission_mode']}")
        listed = init.get("slash_commands")
        if listed and skill not in listed:
            problems.append(f"the {skill} skill was not found; run fo skills sync")
        return (
            ("The run did not start isolated: " + "; ".join(problems) + ".") if problems else None
        )

    def prepare_home(self, folder):
        """The run's Codex home and HOME, written fresh before every launch and resume."""
        if folder is None:
            raise OfficeError("runner_missing", "A Codex run needs its run folder.")
        folder = Path(folder)
        home = private_folder(folder / "codex-home")
        private_folder(folder / "home")
        private_folder(home / "skills")
        private_folder(home / "rules")
        for path, text in (
            (home / "config.toml", config_toml()),
            (home / "rules/fo.rules", rules()),
        ):
            path.write_text(text)
            path.chmod(0o600)
        link = home / "auth.json"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(self.auth())
        return home

    def workspace(self, folder):
        """The run's only writable root, and the working directory its process starts in."""
        return Path(folder) / "workspace"

    def prompt(self, text, report, folder):
        """The skill invocation, prefixed with how to write the report without a Write tool."""
        body = self.workspace(folder) / "report.md"
        return PREFACE.format(report=report, body=body) + "\n\n" + text

    def settings(self, office, web=False, folder=None):
        return config_toml()

    def command(
        self,
        office,
        settings,
        budget,
        session=None,
        model=None,
        effort=None,
        *,
        web=False,
        folder=None,
    ):
        if folder is None:
            raise OfficeError("runner_missing", "A Codex run needs its run folder.")
        argv = [*self.executable]
        if web:
            argv.append("--search")
        # Top-level -C, because exec resume takes no -C of its own and would otherwise make
        # the process's working directory (the office) the writable root.
        argv += ["-C", str(self.workspace(folder)), "exec"]
        if session:
            argv += ["resume", session]
        argv += ["--json", "--ignore-user-config", "--skip-git-repo-check"]
        if model:
            argv += ["-m", model]
        for key, value in overrides(None, effort, web):
            argv += ["-c", f"{key}={value}"]
        return [*argv, "-"]

    def environment(self, office, folder=None, web=False, web_fetch_cap=0):
        """The scrubbed environment with the run's own Codex home and HOME; no CLAUDE_*."""
        env = {key: os.environ[key] for key in PASSED if key in os.environ}
        paths = [str(Path(self.python).parent)]
        if self.executable:
            paths.append(str(Path(self.executable[0]).parent))
        env["PATH"] = os.pathsep.join([*dict.fromkeys(paths), "/usr/bin", "/bin"])
        env["FO_OFFICE"] = env[RUN_MARKER] = str(office)
        if folder is not None:
            env[RUN_FOLDER] = str(folder)
            env["CODEX_HOME"] = str(Path(folder) / "codex-home")
            env["HOME"] = str(Path(folder) / "home")
        env[WEB_FLAG] = "1" if web else "0"
        env[FETCH_CAP] = str(int(web_fetch_cap))
        return env

    def parse(self, line, office):
        """Codex JSONL as the shared events.

        thread.started carries only the thread id, so the init event reports the configured
        tools. A command the execpolicy forbids, or a patch outside the workspace, never
        becomes an item: the refusal reaches the model as the tool's error and shows only in
        its reply. Error items are warnings (an ignored setting, say) and the run goes on, so
        only turn.failed and a top-level error end it.
        """
        try:
            raw = json.loads(line)
        except ValueError:
            return []
        if not isinstance(raw, dict):
            return []
        kind = raw.get("type")
        if kind == "thread.started":
            self.thread, self.reply = raw.get("thread_id"), ""
            return [
                {
                    "kind": "init",
                    "session_id": self.thread,
                    "model": raw.get("model"),
                    "tools": list(TOOLS),
                    "mcp_servers": [],
                    "permission_mode": MODE,
                }
            ]
        if kind in ("item.started", "item.completed"):
            events = item(raw.get("item") or {}, kind, office)
            for event in events:
                if event["kind"] == "text":
                    self.reply = event["text"]
            return events
        if kind == "turn.completed":
            usage = raw.get("usage") or {}
            return [
                {
                    "kind": "result",
                    "ok": True,
                    "subtype": "success",
                    "text": self.reply,
                    "session_id": self.thread,
                    "cost_usd": None,
                    "turns": 1,
                    "usage": {k: v for k, v in usage.items() if isinstance(v, int)},
                    "denials": [],
                }
            ]
        if kind in ("turn.failed", "error"):
            failure = raw.get("error") if isinstance(raw.get("error"), dict) else {}
            message = failure.get("message") or raw.get("message") or "Codex reported an error."
            return [
                {
                    "kind": "result",
                    "ok": False,
                    "subtype": "runner_failed",
                    "text": str(message)[:OUTPUT_LIMIT],
                    "session_id": self.thread,
                    "cost_usd": None,
                    "turns": 1 if kind == "turn.failed" else 0,
                    "denials": [],
                }
            ]
        return []


def relative(path, office):
    try:
        return str(Path(path).resolve().relative_to(Path(office).resolve()))
    except (ValueError, OSError):
        return path


def item(entry, kind, office):
    """One Codex item as shared events: a started command is the call, completed its result."""
    category = entry.get("type")
    ident = entry.get("id")
    done = kind == "item.completed"
    if category == "agent_message":
        text = str(entry.get("text") or "")
        return [{"kind": "text", "text": text, "nested": False}] if done and text.strip() else []
    if category == "command_execution":
        command = shell_body(str(entry.get("command", "")))
        if not done:
            return [
                {
                    "kind": "tool",
                    "id": ident,
                    "name": "Bash",
                    "command": command,
                    "label": command[:120],
                    "nested": False,
                }
            ]
        return [
            {
                "kind": "tool_result",
                "id": ident,
                "ok": entry.get("status") == "completed" and entry.get("exit_code") == 0,
                "output": str(entry.get("aggregated_output") or "")[:OUTPUT_LIMIT],
                "nested": False,
            }
        ]
    if category == "file_change" and done:
        paths = [
            relative(str(change.get("path", "")), office)
            for change in entry.get("changes") or []
            if isinstance(change, dict)
        ]
        call = {
            "kind": "tool",
            "id": ident,
            "name": "Write",
            "paths": paths,
            "label": "Write " + ", ".join(paths),
            "nested": False,
        }
        if len(paths) == 1:
            call["path"] = paths[0]
        ok = entry.get("status") == "completed"
        result = {
            "kind": "tool_result",
            "id": ident,
            "ok": ok,
            "output": "" if ok else str(entry.get("status") or ""),
            "nested": False,
        }
        return [call, result]
    if category == "web_search" and done:
        action = entry.get("action") if isinstance(entry.get("action"), dict) else {}
        query = entry.get("query") or action.get("query") or ""
        return [{"kind": "web", "action": "search", "value": str(query)}] if query else []
    return []


SHELL = re.compile(r"^(?:/bin/|/usr/bin/)?(?:ba|z)?sh -l?c '(.*)'$", re.S)


def shell_body(command):
    """Codex wraps a command in `bash -lc '...'`; show what the model asked to run."""
    match = SHELL.match(command)
    return match[1].replace("'\\''", "'") if match else command

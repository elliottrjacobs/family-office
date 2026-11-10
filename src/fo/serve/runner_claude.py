"""Claude Code headless runner, isolated to the office.

Every run loads only the office's own project settings plus a run profile passed with
--settings: no user settings, no MCP server (an empty strict config), only the Bash,
Read, Write, Edit, and Task tools, and permission prompts answered "deny". A run at
context level none, which reads no household data, also gets WebSearch and WebFetch; at
every other level both stay disallowed. The profile
carries the fo.serve.guard PreToolUse hook, which confines each tool call to fo
commands, reads inside the office, and writes under reports/. The environment is
scrubbed to what login needs, with FO_SERVE_RUN set so fo refuses other offices and
restricted commands, and with the run's folder, web policy, and fetch cap for the hook. The prompt goes on stdin, never on the command line.

Verified against Claude Code 2.1.283 on a synthetic office (2026-10-15): project skills
and worker agents load with --setting-sources project; --restricted would confine file
tools but loads neither. A bare Read allow, which every rendered skill and a trusted
office's settings carry, otherwise reaches files outside the office, and read-only shell
commands such as ls and cat run without a prompt; the hook denies both. Worker agents
started with the Agent tool run under the same hook, so --deep stays isolated. That
version has no --max-turns; runs are bounded by --max-budget-usd and the server's
wall-clock limit.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from fo.errors import OfficeError
from fo.office import RUN_MARKER
from fo.serve.runner import FETCH_CAP, HOOK_FLAG, OUTPUT_LIMIT, RUN_FOLDER, WEB_FLAG, profile

MINIMUM = (2, 1, 283)
# Every flag here is part of the isolation; a version that lacks one may not run.
FLAGS = (
    "--print",
    "--output-format",
    "--verbose",
    "--include-partial-messages",
    "--permission-mode",
    "--permission-prompts",
    "--setting-sources",
    "--strict-mcp-config",
    "--mcp-config",
    "--tools",
    "--disallowedTools",
    "--settings",
    "--resume",
    "--max-budget-usd",
    "--model",
    "--effort",
)
MODE = "dontAsk"
# A --deep research run on a synthetic office completed with all five workers confined.
DEEP = True
TOOLS = ("Bash", "Read", "Write", "Edit", "Task")
# Offered only to runs at context level none; the guard hook checks every call.
WEB = ("WebSearch", "WebFetch")
DISALLOWED = ("WebFetch", "WebSearch", "NotebookEdit")
# Login needs these; nothing else from the server's environment reaches the run.
PASSED = (
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CONFIG_DIR",
    "HTTPS_PROXY",
    "NO_PROXY",
    "NODE_EXTRA_CA_CERTS",
)


def tools(web):
    return (*TOOLS, *WEB) if web else TOOLS


def version(text):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(part) for part in match.groups()) if match else None


class ClaudeRunner:
    name = "claude"

    def __init__(self, executable=None, python=None):
        if executable is None:
            # The Mac app runs the server with a scrubbed PATH and names the CLI it found.
            named = os.environ.get("FO_CLAUDE_EXECUTABLE", "").strip()
            found = named if named and os.access(named, os.X_OK) else shutil.which("claude")
            executable = [found] if found else []
        self.executable = list(executable)
        self.python = python or sys.executable

    def preflight(self):
        """Refuse to run when Claude Code is missing, too old, or lacks an isolation flag."""
        if not self.executable:
            raise OfficeError(
                "runner_missing", "Install Claude Code and sign in to chat with advisors."
            )
        try:
            reported = subprocess.run(
                [*self.executable, "--version"], capture_output=True, text=True, timeout=30
            ).stdout
            usage = subprocess.run(
                [*self.executable, "--help"], capture_output=True, text=True, timeout=30
            ).stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OfficeError("runner_missing", "Claude Code could not be started.") from exc
        found = version(reported)
        if found is None or found < MINIMUM:
            raise OfficeError(
                "runner_outdated",
                "Claude Code {} or later is required; update it to chat with advisors.".format(
                    ".".join(map(str, MINIMUM))
                ),
            )
        missing = [flag for flag in FLAGS if flag not in usage]
        if MODE not in usage:
            missing.append(f"--permission-mode {MODE}")
        if missing:
            raise OfficeError(
                "runner_unsupported",
                "This Claude Code lacks " + ", ".join(missing) + ", so a run cannot be isolated.",
            )
        return {"runner": self.name, "version": ".".join(map(str, found))}

    def check(self, init, skill, web=False):
        """Why the started session is not isolated as launched, or None when it is."""
        problems = []
        if init["mcp_servers"]:
            problems.append("MCP servers were loaded")
        extra = sorted(set(init["tools"]) - set(tools(web)))
        if extra:
            problems.append("unexpected tools " + ", ".join(extra))
        if init["permission_mode"] != MODE:
            problems.append(f"permission mode {init['permission_mode']}")
        if skill not in init["slash_commands"]:
            problems.append(f"the {skill} skill was not found; run fo skills sync")
        return (
            ("The run did not start isolated: " + "; ".join(problems) + ".") if problems else None
        )

    def settings(self, office, web=False):
        """The run profile plus the guard hook, as the JSON --settings takes."""
        hook = shlex.join([self.python, "-I", "-m", "fo.serve.guard", str(office)])
        rules = profile()
        # dontAsk refuses a tool no rule allows; the hook still checks every web call.
        allow = [*rules["allow"], *(WEB if web else ())]
        return json.dumps(
            {
                "permissions": {"allow": allow, "deny": rules["deny"]},
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": hook}]}
                    ]
                },
            }
        )

    def command(
        self, office, settings, budget, session=None, model=None, effort=None, *, web=False
    ):
        argv = [
            *self.executable,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-mode",
            MODE,
            "--permission-prompts",
            "none",
            "--setting-sources",
            "project",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--tools",
            ",".join(tools(web)),
            "--disallowedTools",
            ",".join(name for name in DISALLOWED if not (web and name in WEB)),
            "--settings",
            settings,
            "--max-budget-usd",
            f"{budget:.2f}",
        ]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        if session:
            argv += ["--resume", session]
        return argv

    def environment(self, office, folder=None, web=False, web_fetch_cap=0):
        """The scrubbed environment; folder, web, and the cap are read by the guard hook."""
        env = {key: os.environ[key] for key in PASSED if key in os.environ}
        # fo resolves to this server's own interpreter, so a run cannot reach another version.
        paths = [str(Path(self.python).parent)]
        if self.executable:
            paths.append(str(Path(self.executable[0]).parent))
        env["PATH"] = os.pathsep.join([*dict.fromkeys(paths), "/usr/bin", "/bin"])
        env["FO_OFFICE"] = env[RUN_MARKER] = str(office)
        if folder is not None:
            env[RUN_FOLDER] = str(folder)
        env[WEB_FLAG] = "1" if web else "0"
        env[FETCH_CAP] = str(int(web_fetch_cap))
        env[HOOK_FLAG] = "1"
        return env

    def parse(self, line, office):
        try:
            raw = json.loads(line)
        except ValueError:
            return []
        if not isinstance(raw, dict):
            return []
        kind = raw.get("type")
        nested = bool(raw.get("parent_tool_use_id"))
        if kind == "system" and raw.get("subtype") == "init":
            return [
                {
                    "kind": "init",
                    "session_id": raw.get("session_id"),
                    "model": raw.get("model"),
                    "tools": raw.get("tools") or [],
                    "mcp_servers": raw.get("mcp_servers") or [],
                    "slash_commands": raw.get("slash_commands") or [],
                    "permission_mode": raw.get("permissionMode"),
                }
            ]
        if kind == "assistant":
            events = []
            for block in (raw.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    events.append({"kind": "text", "text": block["text"], "nested": nested})
                elif block.get("type") == "tool_use":
                    events.append(tool(block, office, nested))
            return events
        if kind == "user":
            content = (raw.get("message") or {}).get("content") or []
            return [
                {
                    "kind": "tool_result",
                    "id": block.get("tool_use_id"),
                    "ok": not block.get("is_error"),
                    "output": output(block.get("content"))[:OUTPUT_LIMIT],
                    "nested": nested,
                }
                for block in content
                if isinstance(block, dict) and block.get("type") == "tool_result"
            ]
        if kind == "stream_event" and not nested:
            delta = (raw.get("event") or {}).get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                return [{"kind": "delta", "text": delta["text"]}]
            return []
        if kind == "result":
            return [
                {
                    "kind": "result",
                    "ok": not raw.get("is_error"),
                    "subtype": raw.get("subtype"),
                    "text": raw.get("result") or "",
                    "session_id": raw.get("session_id"),
                    "cost_usd": raw.get("total_cost_usd"),
                    "turns": raw.get("num_turns"),
                    "denials": [
                        tool(
                            {
                                "id": d.get("tool_use_id"),
                                "name": d.get("tool_name"),
                                "input": d.get("tool_input") or {},
                            },
                            office,
                            False,
                        )
                        for d in raw.get("permission_denials") or []
                    ],
                }
            ]
        return []


def relative(path, office):
    try:
        return str(Path(path).resolve().relative_to(Path(office).resolve()))
    except (ValueError, OSError):
        return path


def tool(block, office, nested):
    name = block.get("name") or "tool"
    arguments = block.get("input") or {}
    event = {"kind": "tool", "id": block.get("id"), "name": name, "nested": nested}
    if name == "Bash":
        event["command"] = str(arguments.get("command", ""))
        event["label"] = arguments.get("description") or event["command"][:120]
    elif "file_path" in arguments:
        event["path"] = relative(str(arguments["file_path"]), office)
        event["label"] = f"{name} {event['path']}"
    elif name in ("Task", "Agent"):
        event["label"] = arguments.get("description") or arguments.get("subagent_type") or name
    elif name == "WebFetch":
        event["label"] = f"Fetch {str(arguments.get('url', ''))[:160]}"
    elif name == "WebSearch":
        event["label"] = f"Search {str(arguments.get('query', ''))[:160]}"
    else:
        event["label"] = name
    return event


def output(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict) and "text" in part
        )
    return ""

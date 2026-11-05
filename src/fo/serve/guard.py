"""PreToolUse hook for headless advisor runs; Claude Code calls it before every tool call.

Permission rules alone cannot confine a run: a skill's own allowed-tools can grant a bare
Read, and read-only shell commands may run without a prompt. This hook is the
deterministic last word. It allows `fo` commands with no shell operators, reads inside
the office outside its private folders, writes under reports/, and subagent calls, and
otherwise leaves the decision to the permission rules. Every other tool call, and any
error in the hook itself, is denied.

WebSearch and WebFetch pass only in a run the runner marked web (FO_SERVE_WEB=1, at
context level none). A fetch URL must pass fo.netguard, and fetches are capped per run
by FO_SERVE_WEB_FETCH_CAP with a counter file in the run's folder (FO_SERVE_RUN_DIR,
under cache/serve/runs/, which a run cannot read or write). Every search query and
fetch URL that passes is appended, scrubbed, to web.jsonl in that folder; the run
manager folds the entries into the run's event log. Each web denial ends with a stable
reason code in parentheses.

Run as `python -m fo.serve.guard OFFICE`; it reads the hook event JSON on stdin.
"""

import fcntl
import json
import os
import re
import shlex
import sys

from fo import netguard
from fo.serve.runner import FETCH_CAP, RUN_FOLDER, WEB_FLAG, WEB_LOG, scrub_text
from fo.store.jsonl import now

PRIVATE = ("secrets", "cache", "imports", "medical", ".git", ".fo.lock")
# Grep and Glob are not offered to runs, and a search from the office root would reach
# its private folders, so they fall through to the denial below.
PATH_KEYS = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
}
WRITES = {"Write", "Edit", "MultiEdit"}
WEB = {"WebFetch", "WebSearch"}
COUNTER = "web-fetches"
VALUE_LIMIT = 2000
OPERATOR = set("|;&<>()")
# `$` may introduce an amount ($100, $1.5B) but never an expansion ($HOME, $(...), ${...}).
EXPANSION = re.compile(r"\$(?![\d\s.,]|$)")


def command_denial(command):
    if not command or "\n" in command or "`" in command or EXPANSION.search(command):
        return "Advisor runs may run only plain fo commands."
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        # shlex ends a word at "#", but bash does not (`fo status#; curl ...` runs curl), so
        # "#" stays an ordinary character and any operator after it is still seen.
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return "Advisor runs may run only plain fo commands."
    segments = [[]]
    for token in tokens:
        if token == "&&":
            segments.append([])
        elif set(token) <= OPERATOR:
            return "Pipes, redirects, and other shell operators are not allowed in advisor runs."
        else:
            segments[-1].append(token)
    if any(not segment or segment[0] != "fo" for segment in segments):
        return "Advisor runs may run only fo commands."
    return None


def path_denial(office, cwd, tool, arguments):
    raw = arguments.get(PATH_KEYS[tool])
    if not raw:
        return "The tool call names no file."
    full = os.path.realpath(os.path.join(cwd or office, os.path.expanduser(raw)))
    relative = os.path.relpath(full, office)
    if relative == ".." or relative.startswith(".." + os.sep) or os.path.isabs(relative):
        return "Advisor runs read and write only inside the office."
    first, *rest = relative.split(os.sep)
    # macOS volumes usually ignore case, so SECRETS/ opens secrets/.
    if first.casefold() in PRIVATE or first.casefold().startswith("store.sqlite"):
        return "That part of the office is private to fo."
    if tool in WRITES and first != "reports":
        return "Advisor runs write only under reports/."
    # A .claude/, .git/, or other hidden entry under reports/ would be committed and read
    # by later sessions that have no guard, such as settings, hooks, or git config.
    if tool in WRITES and any(part.startswith(".") for part in rest):
        return "Advisor runs cannot write hidden files or folders under reports/."
    return None


def locked(path, update):
    """Run update(file) under an exclusive lock on path, created 0600."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        return update(stream)


def take_fetch(folder, cap):
    """Count one more fetch in the run, or False when the run has used its cap."""

    def update(stream):
        stream.seek(0)
        used = int(stream.read().strip() or 0)
        if used >= cap:
            return False
        stream.truncate(0)
        stream.write(str(used + 1))
        return True

    return locked(os.path.join(folder, COUNTER), update)


def log_web(folder, kind, value):
    entry = {"kind": kind, "value": scrub_text(value[:VALUE_LIMIT]), "at": now()}
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    locked(os.path.join(folder, WEB_LOG), lambda stream: stream.write(line))


def web_denial(tool, arguments, env, resolver=None):
    if env.get(WEB_FLAG) != "1":
        return "Web search and fetch are on only at context level none (web_off)"
    folder = env.get(RUN_FOLDER)
    if not folder or not os.path.isdir(folder):
        return "The run guard has no run folder to log web use in (web_unlogged)"
    if tool == "WebSearch":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return "The search names no query (missing_query)"
        log_web(folder, "search", query)
        return None
    url = arguments.get("url")
    if not isinstance(url, str) or not url.strip():
        return f"{netguard.REASONS['missing_host']} (missing_host)"
    reason = netguard.reject(url, resolver)
    if reason:
        return f"{netguard.REASONS[reason]} ({reason})"
    try:
        cap = int(env.get(FETCH_CAP, "0"))
    except ValueError:
        cap = 0
    if not take_fetch(folder, cap):
        return f"This run has used its {cap} web fetches (web_fetch_cap)"
    log_web(folder, "fetch", url)
    return None


def decide(office, event, env=None, resolver=None):
    """A denial reason, or None to let the permission rules decide."""
    tool = event.get("tool_name")
    arguments = event.get("tool_input") or {}
    if tool in WEB:
        return web_denial(tool, arguments, os.environ if env is None else env, resolver)
    if tool == "Bash":
        return command_denial(arguments.get("command", ""))
    if tool in PATH_KEYS:
        return path_denial(office, event.get("cwd"), tool, arguments)
    if tool in ("Task", "Agent"):
        return None
    return "This tool is not available in advisor runs."


def main(argv=None, stdin=None, stdout=None):
    argv = sys.argv[1:] if argv is None else argv
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        reason = decide(os.path.realpath(argv[0]), json.load(stdin))
    except Exception:  # noqa: BLE001 - a hook that errors must deny, never allow
        reason = "The run guard could not check this call."
    if reason:
        decision = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
        stdout.write(json.dumps({"hookSpecificOutput": decision}))


if __name__ == "__main__":
    main()

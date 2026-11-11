"""PreToolUse hook for headless advisor runs; Claude Code calls it before every tool call.

Permission rules alone cannot confine a run: a skill's own allowed-tools can grant a bare
Read, and read-only shell commands may run without a prompt. This hook is the
deterministic last word. It allows `fo` commands with no shell operators, reads inside
the office outside its private folders, writes under reports/, and subagent calls, and
otherwise leaves the decision to the permission rules. Every other tool call, and any
error in the hook itself, is denied.

Web runs additionally deny reads of data/, profile/, and notebook/ and allow only
market, research, and bookkeeping commands; start and brief require level none.
Reports remain readable and writable, including earlier reports with household data.
Non-web runs deny all fo research commands.

WebSearch, WebFetch, and fo research pass only in a run the runner marked web
(FO_SERVE_WEB=1, at context level none). Fetch URLs must pass fo.netguard, and fetches
share a per-run cap, FO_SERVE_WEB_FETCH_CAP, with a counter in FO_SERVE_RUN_DIR under
cache/serve/runs/, which a run cannot read or write. Every accepted query (including
research deep questions, logged as searches) and fetch URL is appended, scrubbed, to
web.jsonl there; the run manager folds entries into the run's event log. Each web
denial ends with a stable reason code in parentheses.

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
WEB_COMMANDS = {
    "quote": None,
    "fundamentals": None,
    "filings": None,
    "macro": None,
    "screen": None,
    "score": None,
    "playbooks": {"list"},
    "start": None,
    "brief": None,
    "report": {"parts", "path", "write"},
    "reports": {"index"},
    "journal": {"add"},
    "corrections": {"add"},
    "skill": None,
    "skills": {"list"},
    "--help": set(),
    "--version": set(),
}
COUNTER = "web-fetches"
VALUE_LIMIT = 2000
OPERATOR = set("|;&<>()")
# `$` may introduce an amount ($100, $1.5B) but never an expansion ($HOME, $(...), ${...}).
EXPANSION = re.compile(r"\$(?![\d\s.,]|$)")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def command_denial(command, env=None, resolver=None):
    env = os.environ if env is None else env
    if not command or CONTROL.search(command) or "`" in command or EXPANSION.search(command):
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
    commands = []
    for segment in segments:
        # Match OfficeGroup's global flag handling, stopping at the CLI separator.
        words = []
        index = 1
        while index < len(segment):
            word = segment[index]
            if word == "--":
                words.extend(segment[index:])
                break
            if word == "--office":
                index += 2
                continue
            if word not in ("--json", "--read-only") and not word.startswith("--office="):
                words.append(word)
            index += 1
        commands.append(words)
    # Validate the entire shell command before any segment takes a fetch or logs web use.
    for words in commands:
        reason = words_denial(words, env, resolver, record=False)
        if reason:
            return reason
    for words in commands:
        reason = words_denial(words, env, resolver)
        if reason:
            return reason
    return None


def words_denial(words, env=None, resolver=None, *, record=True):
    """Shared hook/CLI policy for command words after global flags are removed.

    record=False validates without consuming fetches or logging, so the hook can check
    every shell segment first and a CLI under an active hook avoids counting twice.
    """
    env = os.environ if env is None else env
    separator = "--" in words
    if words[:1] == ["--"]:
        words = words[1:]
    if words[:1] == ["research"]:
        if env.get(WEB_FLAG) != "1":
            return "Research is on only in web runs (web_off)"
        if len(words) > 1 and words[1] not in ("fetch", "search", "deep"):
            return "This command is unavailable in web runs (web_household_command)"
        if len(words) < 3:
            return "Research requires a query or URL (missing_query)"
        value = words[2:]
        if value[:1] == ["--"]:
            value = value[1:]
        if not value or value[0].startswith("-"):
            return "Put the research query or URL before options (missing_query)"
        tool = "WebFetch" if words[1] == "fetch" else "WebSearch"
        key = "url" if tool == "WebFetch" else "query"
        reason = web_denial(tool, {key: value[0]}, env, resolver, record=record)
        if reason:
            return reason
    elif env.get(WEB_FLAG) == "1":
        allowed = bool(words) and words[0] in WEB_COMMANDS
        if allowed:
            subcommands = WEB_COMMANDS[words[0]]
            allowed = subcommands is None or (
                words[1] in subcommands if len(words) > 1 else not subcommands
            )
        if words[:1] in (["start"], ["brief"]):
            levels = [
                words[i + 1] if word == "--level" and i + 1 < len(words) else word[8:]
                for i, word in enumerate(words)
                if word == "--level" or word.startswith("--level=")
            ]
            allowed = (
                not separator
                and bool(levels)
                and all(level == "none" for level in levels)
                and not any(
                    words[i - 1] in ("--for", "--skill", "--report", "--subject")
                    for i, word in enumerate(words)
                    if word == "--level" or word.startswith("--level=")
                )
            )
        if not allowed:
            return "This command is unavailable in web runs (web_household_command)"
    return None


def path_denial(office, cwd, tool, arguments, env=None):
    env = os.environ if env is None else env
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
    if (
        tool == "Read"
        and env.get(WEB_FLAG) == "1"
        and first.casefold() in ("data", "profile", "notebook")
    ):
        return "Web runs cannot read household folders (web_household_read)"
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


def web_denial(tool, arguments, env, resolver=None, *, record=True):
    if env.get(WEB_FLAG) != "1":
        return "Web search and fetch are on only at context level none (web_off)"
    folder = env.get(RUN_FOLDER)
    if not folder or not os.path.isdir(folder):
        return "The run guard has no run folder to log web use in (web_unlogged)"
    if tool == "WebSearch":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return "The search names no query (missing_query)"
        if record:
            log_web(folder, "search", query)
        return None
    url = arguments.get("url")
    if not isinstance(url, str) or not url.strip():
        return f"{netguard.REASONS['missing_host']} (missing_host)"
    reason = netguard.reject(url, resolver)
    if reason:
        return f"{netguard.REASONS[reason]} ({reason})"
    if not record:
        return None
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
        return command_denial(arguments.get("command", ""), env, resolver)
    if tool in PATH_KEYS:
        return path_denial(office, event.get("cwd"), tool, arguments, env)
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

"""PreToolUse hook for headless advisor runs; Claude Code calls it before every tool call.

Permission rules alone cannot confine a run: a skill's own allowed-tools can grant a bare
Read, and read-only shell commands may run without a prompt. This hook is the
deterministic last word. It allows `fo` commands with no shell operators, reads inside
the office outside its private folders, writes under reports/, and subagent calls, and
otherwise leaves the decision to the permission rules. Every other tool call, and any
error in the hook itself, is denied.

Run as `python -m fo.serve.guard OFFICE`; it reads the hook event JSON on stdin.
"""

import json
import os
import re
import shlex
import sys

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
    first = relative.split(os.sep)[0]
    # macOS volumes usually ignore case, so SECRETS/ opens secrets/.
    if first.casefold() in PRIVATE or first.casefold().startswith("store.sqlite"):
        return "That part of the office is private to fo."
    if tool in WRITES and first != "reports":
        return "Advisor runs write only under reports/."
    return None


def decide(office, event):
    """A denial reason, or None to let the permission rules decide."""
    tool = event.get("tool_name")
    arguments = event.get("tool_input") or {}
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

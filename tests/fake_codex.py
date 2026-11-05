"""A stand-in for `codex` in tests: replays a scripted run and calls the real fo.

Usage: python fake_codex.py SCRIPT [codex flags...]; the prompt arrives on stdin.
Script lines are Codex JSONL events printed as-is, or {"fake": ...} directives.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

EXEC_FLAGS = ["--json", "--ignore-user-config", "--skip-git-repo-check", "-C", "-m", "-c"]
TOP_FLAGS = ["--search", "-C"]
REPORT = """---
{meta}
---

# Fake

## What changed

First look.

Reply with corrections in your next task.
"""


def emit(event):
    print(json.dumps(event), flush=True)


def command(number, text, output, code=0):
    entry = {
        "id": f"item_{number}",
        "type": "command_execution",
        "command": f"/bin/zsh -lc '{text}'",
        "aggregated_output": "",
        "exit_code": None,
        "status": "in_progress",
    }
    emit({"type": "item.started", "item": entry})
    status = "completed" if code == 0 else "failed"
    emit(
        {
            "type": "item.completed",
            "item": {**entry, "aggregated_output": output, "exit_code": code, "status": status},
        }
    )


def fo(*args):
    result = subprocess.run(["fo", *args], capture_output=True, text=True)
    return result.stdout or result.stderr, result.returncode


def listed(names, missing):
    return "\n".join(f"  {name} <VALUE>" for name in names if name not in missing)


def main():
    script, flags = Path(sys.argv[1]), sys.argv[2:]
    folder = script.parent
    missing = (folder / "missing").read_text().split() if (folder / "missing").exists() else []
    if flags == ["--version"]:
        version = folder / "version"
        print(version.read_text() if version.exists() else "codex-cli 0.157.1")
        return
    if flags == ["--help"]:
        print("Options:\n" + listed(TOP_FLAGS, missing))
        return
    if flags == ["exec", "--help"]:
        commands = "" if "resume" in missing else "  resume  Resume a previous session\n"
        print("Commands:\n" + commands + "Options:\n" + listed(EXEC_FLAGS, missing))
        return
    (folder / "argv.json").write_text(json.dumps(flags))
    (folder / "env.json").write_text(json.dumps(sorted(os.environ)))
    (folder / "homes.json").write_text(
        json.dumps({key: os.environ.get(key) for key in ("CODEX_HOME", "HOME", "FO_SERVE_RUN")})
    )
    prompt = sys.stdin.read()
    with (folder / "prompts.txt").open("a") as stream:
        stream.write(prompt + "\n---\n")
    workspace = Path(flags[flags.index("-C") + 1])
    invocation = next((w for w in prompt.splitlines() if w.startswith("/")), "/research ACME")
    words = invocation.split()
    skill, subject = words[0].lstrip("/"), words[1]
    level = words[words.index("--level") + 1] if "--level" in words else "none"
    thread = flags[flags.index("resume") + 1] if "resume" in flags else "thread-1"
    state = {"report": None, "meta": None, "text": "", "count": 0}
    for raw in script.read_text().splitlines():
        line = json.loads(raw)
        action = line.get("fake")
        state["count"] += 1
        number = state["count"]
        if action is None:
            emit(line)
        elif action == "thread":
            emit({"type": "thread.started", "thread_id": thread})
            emit({"type": "turn.started"})
        elif action == "start":
            args = ["start", skill, subject, "--level", level, "--json"]
            output, code = fo(*args)
            data = json.loads(output)["report"]["data"]
            state["report"], state["meta"] = data["path"], data["frontmatter"]
            command(number, "fo " + " ".join(args), output, code)
        elif action == "draft":
            import yaml

            meta = {**state["meta"], "model": "fake-model", "summary": "Fake report."}
            body = workspace / "report.md"
            body.write_text(REPORT.format(meta=yaml.safe_dump(meta).strip()))
            change = {
                "id": f"item_{number}",
                "type": "file_change",
                "changes": [{"path": str(body), "kind": "add"}],
                "status": "completed",
            }
            emit({"type": "item.started", "item": {**change, "status": "in_progress"}})
            emit({"type": "item.completed", "item": change})
        elif action == "write":
            args = [
                "report",
                "write",
                "--report",
                state["report"],
                "--body-file",
                str(workspace / "report.md"),
                "--json",
            ]
            output, code = fo(*args)
            command(number, "fo " + " ".join(args), output, code)
        elif action == "fo":
            output, code = fo(*line["args"])
            command(number, "fo " + " ".join(line["args"]), output, code)
        elif action == "search":
            emit(
                {
                    "type": "item.completed",
                    "item": {
                        "id": f"item_{number}",
                        "type": "web_search",
                        "query": line["query"],
                        "action": {"type": "search", "query": line["query"]},
                    },
                }
            )
        elif action == "text":
            emit(
                {
                    "type": "item.completed",
                    "item": {"id": f"item_{number}", "type": "agent_message", "text": line["text"]},
                }
            )
        elif action == "done":
            emit({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
        elif action == "failed":
            emit({"type": "turn.failed", "error": {"message": line.get("message", "Failed.")}})
        elif action == "exit":
            sys.exit(line["code"])
    sys.exit(0)


if __name__ == "__main__":
    main()

"""A stand-in for `claude` in tests: replays a scripted run and calls the real fo.

Usage: python fake_claude.py SCRIPT [claude flags...]; the prompt arrives on stdin.
Script lines are stream-json events printed as-is, or {"fake": ...} directives.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

FLAGS = [
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
]
SKILLS = ["briefing", "cio", "eli5", "research", "lynch", "journal", "onboard"]
TOOLS = ["Task", "Bash", "Edit", "Read", "Write"]


def emit(event):
    print(json.dumps(event), flush=True)


def tool(number, name, arguments, output, ok=True):
    tool_id = f"toolu_fake{number:04d}"
    emit(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": arguments}]
            },
        }
    )
    emit(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": output,
                        "is_error": not ok,
                    }
                ]
            },
        }
    )


def fo(*args):
    result = subprocess.run(["fo", *args], capture_output=True, text=True)
    return result.stdout or result.stderr


def main():
    script, flags = Path(sys.argv[1]), sys.argv[2:]
    if "--version" in flags:
        print(
            (script.parent / "version").read_text()
            if (script.parent / "version").exists()
            else "2.1.283 (Claude Code)"
        )
        return
    if "--help" in flags:
        missing = (
            (script.parent / "missing").read_text().split()
            if (script.parent / "missing").exists()
            else []
        )
        print(
            "\n".join(flag for flag in FLAGS if flag not in missing)
            + '\n(choices: "manual", "dontAsk")'
        )
        return
    (script.parent / "argv.json").write_text(json.dumps(flags))
    prompt = sys.stdin.read()
    (script.parent / "prompts.txt").open("a").write(prompt + "\n---\n")
    words = prompt.split()
    skill = words[0].lstrip("/") if words and words[0].startswith("/") else "research"
    subject = words[1] if len(words) > 1 and words[0].startswith("/") else "ACME"
    level = words[words.index("--level") + 1] if "--level" in words else "none"
    session = flags[flags.index("--resume") + 1] if "--resume" in flags else "session-1"
    pinned = next((w.strip(".,") for w in words if w.startswith("reports/")), None)
    if pinned:
        # A resume names the report it continues; the skill and subject follow from it.
        skill, subject = pinned.split("/")[1:3]
    state = {"report": None, "meta": None, "decisions": [], "text": "", "count": 0}
    for raw in script.read_text().splitlines():
        line = json.loads(raw)
        action = line.get("fake")
        state["count"] += 1
        if action is None:
            emit(line)
        elif action == "init":
            emit(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": session,
                    "cwd": "/office",
                    "model": "fake-model",
                    "tools": line.get("tools", TOOLS),
                    "mcp_servers": line.get("mcp_servers", []),
                    "permissionMode": line.get("mode", "dontAsk"),
                    "slash_commands": line.get("slash_commands", SKILLS),
                }
            )
        elif action == "start":
            args = ["start", skill, subject, "--level", level, "--json"] + (
                ["--report", pinned] if pinned else []
            )
            output = fo(*args)
            data = json.loads(output)["report"]["data"]
            state["report"], state["meta"] = data["path"], data["frontmatter"]
            tool(state["count"], "Bash", {"command": "fo " + " ".join(args)}, output)
        elif action == "journal":
            args = [
                "journal",
                "add",
                subject,
                "--action",
                "HOLD",
                "--thesis",
                "Fake thesis.",
                "--invalidate",
                "Fake invalidation.",
                "--source",
                skill,
                "--report",
                state["report"],
                "--context-level",
                level,
                "--json",
            ]
            output = fo(*args)
            state["decisions"].append(json.loads(output)["id"])
            tool(state["count"], "Bash", {"command": "fo " + " ".join(args)}, output)
        elif action == "report":
            import yaml

            meta = {
                **state["meta"],
                "model": "fake-model",
                "summary": "Fake report.",
                "decision_ids": state["decisions"],
            }
            path = Path.cwd() / state["report"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "---\n"
                + yaml.safe_dump(meta)
                + "---\n\n# Fake\n\n## What changed\n\nFirst look.\n\nReply with corrections in your next task.\n"
            )
            tool(
                state["count"], "Write", {"file_path": str(path), "content": "..."}, "File created"
            )
        elif action == "text":
            state["text"] = line["text"]
            for piece in (
                line["text"][: len(line["text"]) // 2],
                line["text"][len(line["text"]) // 2 :],
            ):
                emit(
                    {
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": piece},
                        },
                    }
                )
            emit(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": line["text"]}]},
                }
            )
        elif action == "sleep":
            time.sleep(line["seconds"])
        elif action == "exit":
            sys.exit(line["code"])
        elif action == "result":
            emit(
                {
                    "type": "result",
                    "subtype": line.get("subtype", "success"),
                    "is_error": not line.get("ok", True),
                    "result": state["text"],
                    "session_id": session,
                    "total_cost_usd": 0.01,
                    "num_turns": 3,
                    "permission_denials": line.get("denials", []),
                }
            )
    sys.exit(0)


if __name__ == "__main__":
    main()

"""Check canonical skill size, metadata, content, and development parity."""

import re
import sys
from pathlib import Path

from fo.skills import parse_skill

ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
FORBIDDEN = re.compile(
    r"\b(?:AlphaVantage|Schwab|SimpleFIN|Gemini|Apify|AskUserQuestion|haiku|sonnet|opus)\b|\bTask\s*\(|claude -p|codex exec|gpt-\d",
    re.I,
)


def lint(source, instructions):
    errors = []
    if len(instructions.read_bytes()) > 32768:
        errors.append("AGENTS.md exceeds 32 KiB")
    for path in source.glob("*/SKILL.md"):
        meta, body = parse_skill(path)
        if len(path.read_bytes()) > 3000:
            errors.append(f"{path}: exceeds 3000 bytes")
        if set(meta) - ALLOWED:
            errors.append(f"{path}: nonstandard frontmatter")
        if len(meta.get("description", "")) > 250 or not meta.get("description"):
            errors.append(f"{path}: description must be 1-250 characters")
        if not meta.get("metadata", {}).get("commands"):
            errors.append(f"{path}: commands metadata required")
        if FORBIDDEN.search(body):
            errors.append(f"{path}: provider, host tool, or model name in body")
        for host in (".claude", ".agents"):
            link = source.parent / host / "skills" / path.parent.name
            if not link.is_symlink() or link.resolve() != path.parent.resolve():
                errors.append(f"{path}: missing {host} development symlink")
    return errors


if __name__ == "__main__":
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "skills")
    instructions = Path(sys.argv[2] if len(sys.argv) > 2 else "AGENTS.md")
    errors = lint(source, instructions)
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))

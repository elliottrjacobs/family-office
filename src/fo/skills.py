import hashlib
import json
import os
import shutil
from importlib.resources import files
from pathlib import Path

import yaml

from fo import __version__
from fo.config import read_config
from fo.errors import OfficeError
from fo.office import atomic_write, contained, write_json

START, END = "<!-- fo:rules:start -->", "<!-- fo:rules:end -->"


def assets(kind):
    local = Path(__file__).resolve().parents[2] / kind
    return local if local.is_dir() else Path(str(files("fo").joinpath("data", kind)))


def parse_skill(path):
    text = path.read_text()
    pieces = text.split("---", 2)
    if len(pieces) != 3 or pieces[0].strip():
        raise OfficeError("invalid_skill", "Skill frontmatter is missing.")
    return yaml.safe_load(pieces[1]), pieces[2].lstrip()


def skill_body(name):
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name):
        raise OfficeError("unknown_skill", "Invalid skill name.")
    path = assets("skills") / name / "SKILL.md"
    if not path.is_file():
        valid = ", ".join(p.parent.name for p in assets("skills").glob("*/SKILL.md"))
        raise OfficeError("unknown_skill", "Available skills: " + (valid or "none installed"))
    return parse_skill(path)[1]


def rules():
    return files("fo").joinpath("data/AGENTS.rules.md").read_text()


def digest(root):
    content = __version__ + contained(root, "office.toml").read_text() + rules()
    for kind in ("skills", "agents"):
        for path in sorted(assets(kind).rglob("*")):
            if path.is_file():
                content += str(path.relative_to(assets(kind))) + path.read_text()
    return hashlib.sha256(content.encode()).hexdigest()


def tier_config(config, host, tier):
    value = config.get("models", {}).get(host, {}).get(tier, {})
    return {"model": value} if isinstance(value, str) else value


def sync(root):
    config = read_config(root)
    stamp = contained(root, ".agents/skills/.fo-stamp.json")
    count = 0
    # Validate every destination before writing any skill.
    source = assets("skills")
    for skill in source.glob("*/SKILL.md"):
        link = root / ".claude/skills" / skill.parent.name
        if link.exists() and not link.is_symlink():
            raise OfficeError(
                "legacy_skill_directory", "Remove the legacy skill directory before rendering."
            )
    for skill in sorted(source.glob("*/SKILL.md")):
        meta, body = parse_skill(skill)
        name = skill.parent.name
        target = contained(root, f".agents/skills/{name}")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill.parent, target)
        settings = meta.get("metadata", {})
        selected = tier_config(config, "claude", settings.get("tier", "balanced"))
        meta.update({k: v for k, v in selected.items() if k in ("model", "effort")})
        meta["argument-hint"] = settings.get("args", "")
        explicit = settings.get("invocation") == "explicit"
        if explicit:
            meta["disable-model-invocation"] = True
        meta["allowed-tools"] = "Bash(fo *), Bash(uv run fo *), Read, Edit(reports/**)"
        if name == "onboard":
            meta["allowed-tools"] += ", Edit(profile/**)"
        atomic_write(
            target / "SKILL.md", "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n\n" + body
        )
        sidecar = {
            "interface": {"display_name": name, "short_description": meta["description"][:120]}
        }
        if explicit:
            sidecar["policy"] = {"allow_implicit_invocation": False}
        atomic_write(target / "agents/openai.yaml", yaml.safe_dump(sidecar, sort_keys=False))
        link = root / ".claude/skills" / name
        contained(root, ".claude/skills").mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(os.path.relpath(target, link.parent), target_is_directory=True)
        count += 1
    for source_agent in sorted(assets("agents").glob("*.md")):
        meta, body = parse_skill(source_agent)
        name = source_agent.stem
        tier = meta.get("metadata", {}).get("tier", "balanced")
        claude = {
            "name": name,
            "description": meta["description"],
            "tools": ["Read", "Grep", "Glob"],
            **tier_config(config, "claude", tier),
        }
        atomic_write(
            contained(root, f".claude/agents/{name}.md"),
            "---\n" + yaml.safe_dump(claude) + "---\n\n" + body,
        )
        codex = {
            "name": name,
            "description": meta["description"],
            "sandbox_mode": "read-only",
            "developer_instructions": body,
        }
        selected = tier_config(config, "codex", tier)
        if "model" in selected:
            codex["model"] = selected["model"]
        if "effort" in selected:
            codex["model_reasoning_effort"] = selected["effort"]
        atomic_write(
            contained(root, f".codex/agents/{name}.toml"),
            "".join(f"{k} = {json.dumps(v)}\n" for k, v in codex.items()),
        )
    instructions = contained(root, "AGENTS.md")
    old = instructions.read_text() if instructions.exists() else "\n# Household notes\n"
    if START in old and END in old:
        old = old.split(END, 1)[1]
    block = START + "\n" + rules().strip() + "\n" + END + "\n" + old
    if len(block.encode()) > 32768:
        raise OfficeError("instructions_too_large", "Rules and household notes exceed 32 KiB.")
    atomic_write(instructions, block)
    if not (root / "CLAUDE.md").exists():
        atomic_write(root / "CLAUDE.md", "@AGENTS.md\n")
    tracked = {}
    for directory in (".agents/skills", ".claude/agents", ".codex/agents"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and path != stamp:
                tracked[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(stamp, {"version": __version__, "digest": digest(root), "files": tracked})
    return {"skills": count, "version": __version__}


def freshness(root):
    from fo.doctor import check

    path = contained(root, ".agents/skills/.fo-stamp.json")
    if not path.exists():
        return [
            check(
                "skills.fresh",
                "warn",
                "Run fo skills sync on local hosts; cloud may print skill bodies.",
            )
        ]
    try:
        stamp = json.loads(path.read_text())
        valid = stamp["digest"] == digest(root)
        for name, checksum in stamp["files"].items():
            target = contained(root, name)
            valid &= (
                target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum
            )
        instructions = contained(root, "AGENTS.md").read_text()
        rules_valid = START + "\n" + rules().strip() + "\n" + END in instructions
    except (OSError, ValueError, KeyError, OfficeError):
        valid = rules_valid = False
    return [
        check(
            "skills.fresh",
            "pass" if valid else "fail",
            "Rendered files current." if valid else "Run fo skills sync.",
        ),
        check(
            "agents.fresh",
            "pass" if rules_valid else "fail",
            "Rules current." if rules_valid else "Run fo skills sync.",
        ),
    ]

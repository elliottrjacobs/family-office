import tomllib

import pytest
import yaml

from fo.errors import OfficeError
from fo.init import initialize
from fo.skills import freshness, parse_skill, sync


@pytest.fixture
def library(tmp_path, monkeypatch):
    skills = tmp_path / "library/skills"
    agents = tmp_path / "library/agents"
    agents.mkdir(parents=True)
    for name, tier in (("journal", "fast"), ("research", "balanced"), ("tax", "strong")):
        path = skills / name
        path.mkdir(parents=True)
        meta = {
            "name": name,
            "description": "Fixture skill",
            "metadata": {
                "tier": tier,
                "invocation": "explicit" if name == "journal" else "implicit",
                "commands": "fo doctor",
                "args": "SUBJECT",
            },
        }
        (path / "SKILL.md").write_text("---\n" + yaml.safe_dump(meta) + "---\nFixture rubric.\n")
        (path / "rubric.md").write_text("Fixture support")
    (agents / "analyst.md").write_text(
        "---\nname: analyst\ndescription: Fixture analyst\nmetadata:\n  tier: strong\n---\nRead the input files and return evidence.\n"
    )
    monkeypatch.setattr("fo.skills.assets", lambda kind: skills if kind == "skills" else agents)
    return skills


def test_render_models_symlinks_sidecars_and_freshness(tmp_path, library):
    root = tmp_path / "office"
    initialize(root)
    path = root / ".agents/skills/journal/SKILL.md"
    meta, _ = parse_skill(path)
    assert meta["model"] == "haiku"
    assert meta["disable-model-invocation"] is True
    assert "model" not in parse_skill(library / "journal/SKILL.md")[0]
    assert (root / ".claude/skills/journal").resolve() == path.parent
    sidecar = yaml.safe_load((path.parent / "agents/openai.yaml").read_text())
    assert sidecar["policy"]["allow_implicit_invocation"] is False
    assert (path.parent / "rubric.md").is_file()
    agent = tomllib.loads((root / ".codex/agents/analyst.toml").read_text())
    assert agent["model"] == "gpt-6-astra"
    assert agent["sandbox_mode"] == "read-only"
    assert all(c["status"] == "pass" for c in freshness(root))
    path.write_text("modified")
    assert freshness(root)[0]["status"] == "fail"
    sync(root)
    assert freshness(root)[0]["status"] == "pass"


def test_household_notes_preserved_and_config_invalidates(tmp_path, library):
    root = tmp_path / "office"
    initialize(root)
    rules = root / "AGENTS.md"
    rules.write_text(rules.read_text() + "\nKeep my household notes.\n")
    config = root / "office.toml"
    config.write_text(config.read_text().replace('model = "haiku"', 'model = "new-fast-model"'))
    assert freshness(root)[0]["status"] == "fail"
    sync(root)
    assert "Keep my household notes." in rules.read_text()
    assert rules.read_text().count("<!-- fo:rules:start -->") == 1
    assert parse_skill(root / ".agents/skills/journal/SKILL.md")[0]["model"] == "new-fast-model"


def test_legacy_directory_is_not_replaced(tmp_path, library):
    root = tmp_path / "office"
    initialize(root)
    link = root / ".claude/skills/journal"
    link.unlink()
    link.mkdir()
    (link / "user.md").write_text("Keep")
    with pytest.raises(OfficeError, match="legacy"):
        sync(root)
    assert (link / "user.md").read_text() == "Keep"

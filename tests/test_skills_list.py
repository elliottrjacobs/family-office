import json
from pathlib import Path

import jsonschema
from typer.testing import CliRunner

from fo.cli import app
from fo.skills import GROUPS, parse_skill


def listing():
    response = CliRunner().invoke(app, ["skills", "list", "--json"])
    assert response.exit_code == 0, response.output
    return json.loads(response.output)


def test_registry_matches_frontmatter_and_schema():
    data = listing()
    schema = json.loads(Path("src/fo/store/schemas/output/skills-list.schema.json").read_text())
    jsonschema.validate(data, schema)
    assert len(data["skills"]) == 28
    assert len(data["agents"]) == 5
    for row in data["skills"]:
        meta, _ = parse_skill(Path("skills") / row["name"] / "SKILL.md")
        settings = meta["metadata"]
        assert row["description"] == meta["description"]
        assert row["group"] == settings["group"] and row["group"] in GROUPS
        assert row["tier"] == settings["tier"]
        assert row["default_context"] == settings["default-context"]
        assert row["allowed_context"] == settings["allowed-context"]
        assert row["invocation"] == settings["invocation"]
        assert row["args"] == settings["args"]
        assert row["commands"] == settings["commands"]
        assert row["report_kind"] == settings["report-kind"]
    for row in data["agents"]:
        meta, _ = parse_skill(Path("agents") / f"{row['name']}.md")
        assert row["tier"] == meta["metadata"]["tier"]


def test_registry_groups_follow_sidebar_and_deep_comes_from_args():
    skills = {row["name"]: row for row in listing()["skills"]}
    assert skills["lynch"]["group"] == "playbooks" and skills["lynch"]["deep"] is False
    assert skills["research"]["group"] == "research" and skills["research"]["deep"] is True
    assert skills["cio"]["group"] == "household" and skills["cio"]["deep"] is True
    assert {row["group"] for row in skills.values()} == set(GROUPS)


def test_registry_needs_no_office(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FO_OFFICE", raising=False)
    assert len(listing()["skills"]) == 28

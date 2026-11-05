import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_lint_requires_a_sidebar_group(tmp_path):
    module = script("lint_skills")
    assert module.lint(ROOT / "skills", ROOT / "AGENTS.md") == []
    source = tmp_path / "skills"
    instructions = tmp_path / "AGENTS.md"
    instructions.write_text("# Rules\n")
    for name, group in (("missing", None), ("misspelled", "playbook"), ("valid", "routine")):
        (source / name).mkdir(parents=True)
        metadata = "  commands:\n  - doctor\n" + (f"  group: {group}\n" if group else "")
        (source / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Fixture.\nmetadata:\n{metadata}---\nBody.\n"
        )
        for host in (".claude", ".agents"):
            link = tmp_path / host / "skills" / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(Path("../../skills") / name, target_is_directory=True)
    errors = module.lint(source, instructions)
    assert errors == [
        f"{source / 'missing' / 'SKILL.md'}: group must be one of household, research, "
        "specialists, routine, playbooks",
        f"{source / 'misspelled' / 'SKILL.md'}: group must be one of household, research, "
        "specialists, routine, playbooks",
    ]


def test_office_path_lint_excludes_only_designated_fixtures():
    module = script("lint_office_paths")
    paths = [
        "profile/ips.json",
        "tests/fixtures/office/profile/ips.json",
        "tests/fixtures/office/office.toml",
        "src/fo/data/AGENTS.rules.md",
        "nested/office.toml",
        "nested/profile/ips.json",
    ]
    assert module.violations(paths) == [
        "nested/office.toml",
        "nested/profile/ips.json",
        "profile/ips.json",
    ]


def test_skill_lint_ties_the_research_command_to_the_untrusted_text_phrase(tmp_path):
    module = script("lint_skills")
    source = tmp_path / "skills"
    instructions = tmp_path / "AGENTS.md"
    instructions.write_text("# Rules\n")
    bodies = {
        "bare": ("research", "Use fo research fetch."),
        "careful": ("research", f"Results are {module.UNTRUSTED}."),
        "stray": ("doctor", "Run fo research search."),
        "quiet": ("doctor", "No web."),
    }
    for name, (command, body) in bodies.items():
        (source / name).mkdir(parents=True)
        (source / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Fixture.\nmetadata:\n  group: routine\n"
            f"  commands:\n  - {command}\n---\n{body}\n"
        )
        for host in (".claude", ".agents"):
            link = tmp_path / host / "skills" / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(Path("../../skills") / name, target_is_directory=True)
    assert module.lint(source, instructions) == [
        f"{source / 'bare' / 'SKILL.md'}: research command requires the phrase "
        f"'{module.UNTRUSTED}'",
        f"{source / 'stray' / 'SKILL.md'}: mentions fo research without declaring the "
        "research command",
    ]

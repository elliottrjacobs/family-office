import importlib.util
from pathlib import Path


def test_office_path_lint_excludes_only_designated_fixtures():
    path = Path(__file__).parents[1] / "scripts/lint_office_paths.py"
    spec = importlib.util.spec_from_file_location("lint_office", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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

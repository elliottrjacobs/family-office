from pathlib import Path

import pytest

from fo.brief import LEVELS, brief
from tests.offices import synthetic
from tests.serving import serving


def reads(root, monkeypatch, level):
    """Every office file brief() opens for an advisor at this level."""
    seen = set()
    text, data = Path.read_text, Path.read_bytes

    def read_text(self, *args, **kwargs):
        seen.add(self)
        return text(self, *args, **kwargs)

    def read_bytes(self):
        seen.add(self)
        return data(self)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", read_text)
        patch.setattr(Path, "read_bytes", read_bytes)
        brief(root, level, "ACME", "cio")
    return {str(p.relative_to(root)) for p in seen if p.is_relative_to(root)}


@pytest.fixture
def office(tmp_path):
    root = synthetic(tmp_path / "office")
    # A current index would be read instead of the canonical files; project directly.
    (root / "store.sqlite").unlink(missing_ok=True)
    return root


@pytest.mark.parametrize("level", ["none", "household", "full"])
def test_level_table_matches_what_the_brief_reads(office, monkeypatch, level):
    assert reads(office, monkeypatch, level) == set(LEVELS[level]["files"])


def test_levels_widen_and_describe_themselves():
    none, household, full = (LEVELS[k] for k in ("none", "household", "full"))
    assert set(none["files"]) < set(household["files"]) < set(full["files"])
    assert all(level["reads"] and level["summary"] for level in LEVELS.values())


def test_levels_route_serves_the_table(office, tmp_path):
    with serving(office, tmp_path) as (_, client):
        status, data = client.get("/api/levels")
    assert status == 200 and data == LEVELS

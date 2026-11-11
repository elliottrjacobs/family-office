from pathlib import Path

import pytest

from fo.brief import LEVELS, brief, start
from fo.errors import OfficeError
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


@pytest.mark.parametrize("level", ["household", "full"])
def test_web_runs_refuse_household_context_before_reading(tmp_path, monkeypatch, level):
    monkeypatch.setenv("FO_SERVE_WEB", "1")

    def no_read(*args, **kwargs):
        pytest.fail("Household context must be refused before reading office files")

    monkeypatch.setattr("fo.brief.notebook.corrections", no_read)
    monkeypatch.setattr("fo.brief.reports.prior", no_read)
    with pytest.raises(OfficeError) as caught:
        brief(tmp_path, level)
    assert caught.value.reason == "web_level"
    for resolved in (None, level):
        with pytest.raises(OfficeError) as caught:
            start(tmp_path, "tax", "ACME", resolved)
        assert caught.value.reason == "web_level"


def test_web_runs_allow_none_context(tmp_path, monkeypatch):
    monkeypatch.setenv("FO_SERVE_WEB", "1")
    assert brief(tmp_path, "none", "ACME", "tax")["level"] == "none"
    result = start(tmp_path, "tax", "ACME", "none")
    assert result["brief"]["status"] == "ok"
    assert result["brief"]["data"]["level"] == "none"

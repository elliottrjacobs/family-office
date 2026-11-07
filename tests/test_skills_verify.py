import pytest
import yaml

from fo import reports
from fo.brief import start
from fo.errors import OfficeError
from tests.offices import synthetic

LISTED = "- https://example.com/a (retrieved 2026-11-04T10:00:00Z)"


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def write(office, kind, body):
    allocated = start(office, kind, "BETA")["report"]["data"]
    meta = {**allocated["frontmatter"], "model": "fixture", "summary": "Synthetic."}
    path = office / allocated["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump(meta) + "---\n\n" + body + "\n\n" + reports.CLOSING)
    return allocated["path"]


def test_a_cited_source_missing_from_evidence_fails_with_its_url(office):
    path = write(office, "research", "# BETA\n\n## Evidence\n\nNone.\n\nSee https://example.com/a.")
    with pytest.raises(OfficeError) as caught:
        reports.verify(office, path)
    assert caught.value.reason == "report_sources"
    assert "https://example.com/a" in caught.value.message


def test_a_source_listed_without_a_retrieval_time_fails(office):
    path = write(office, "research", "## Evidence\n\n- https://example.com/a (2026 filing)\n")
    with pytest.raises(OfficeError, match="retrieval time"):
        reports.verify(office, path)


def test_the_same_report_with_the_source_listed_verifies(office):
    body = f"## Evidence\n\n{LISTED}\n\n## Analysis\n\nSee https://example.com/a."
    path = write(office, "research", body)
    assert reports.verify(office, path)["valid"]


def test_urls_only_in_evidence_verify(office):
    body = f"## Evidence\n\n{LISTED}\n- https://example.com/b, retrieved 2026-11-04\n"
    assert reports.verify(office, write(office, "research", body))["valid"]


def test_the_first_missing_url_is_named(office):
    body = f"## Evidence\n\n{LISTED}\n\n## Analysis\n\nhttps://x.test/z then https://y.test/w"
    path = write(office, "research", body)
    with pytest.raises(OfficeError, match=r"https://x\.test/z"):
        reports.verify(office, path)


def test_urls_inside_code_fences_are_ignored(office):
    body = "## Evidence\n\nNone.\n\n```\ncurl https://example.com/a\n```"
    assert reports.verify(office, write(office, "research", body))["valid"]


def test_reports_without_urls_are_unaffected(office):
    path = write(office, "briefing", "# Briefing\n\nHoldings are unchanged.")
    assert reports.verify(office, path)["valid"]

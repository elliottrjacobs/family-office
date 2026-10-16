import json
from datetime import date, timedelta

import pytest
from typer.testing import CliRunner

from fo import reports
from fo.brief import start
from fo.cli import app
from tests.offices import synthetic


def cli(root, *args):
    response = CliRunner().invoke(app, [*args, "--json", "--office", str(root)])
    return response.exit_code, json.loads(response.output)


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def test_reports_list_returns_reports_without_parts(office):
    code, data = cli(office, "reports", "list", "--read-only")
    assert code == 0
    assert sorted(r["frontmatter"]["kind"] for r in data["reports"]) == ["briefing", "research"]
    assert not any(".parts" in r["path"] for r in data["reports"])
    assert data["parse_errors"] == []
    research = next(r for r in data["reports"] if r["frontmatter"]["kind"] == "research")
    assert research["summary"] == "Synthetic research summary."


def test_report_show_returns_body_for_a_report(office):
    path = reports.scan(office)["reports"][0]["path"]
    code, data = cli(office, "report", "show", path, "--read-only")
    assert code == 0
    assert data["path"] == path
    assert data["frontmatter"]["subject"] in {"ACME", "household"}
    assert reports.CLOSING in data["body"] and "---" not in data["body"].split("\n")[0]
    code, data = cli(office, "report", "show", str(office / path), "--read-only")
    assert code == 0 and data["path"] == path


def test_report_show_refuses_paths_outside_reports(office, tmp_path):
    research = next(
        r["path"] for r in reports.scan(office)["reports"] if r["frontmatter"]["kind"] == "research"
    )
    part = research.removesuffix(".md") + ".parts/risk-analyst.md"
    (tmp_path / "outside.md").write_text("Not an office file.\n")
    for bad in (
        "secrets/keys.toml",
        "notebook/corrections.md",
        "../outside.md",
        "reports/../profile/ips.json",
        str(tmp_path / "outside.md"),
        part,
    ):
        code, data = cli(office, "report", "show", bad, "--read-only")
        assert (code, data["reason"]) == (1, "unsafe_path"), bad
    code, data = cli(office, "report", "show", "reports/research/ACME/missing.md")
    assert (code, data["reason"]) == (1, "unknown_report")


def test_start_pins_a_resumed_report(office):
    allocated = start(office, "research", "ACME")["report"]["data"]["path"]
    pinned = start(office, "research", "ACME", report=allocated)["report"]
    assert pinned["status"] == "ok"
    assert pinned["data"]["path"] == allocated
    assert pinned["data"]["frontmatter"]["date"] == allocated.split("/")[-1][:10]
    code, data = cli(office, "start", "research", "ACME", "--report", allocated, "--read-only")
    assert code == 0 and data["report"]["data"]["path"] == allocated
    assert start(office, "research", "ACME", report="notebook/x.md")["report"] == {
        "status": "failed",
        "reason": "unsafe_path",
    }
    other = allocated.replace("/ACME/", "/BETA/")
    assert start(office, "research", "ACME", report=other)["report"] == {
        "status": "failed",
        "reason": "report_path",
    }


def test_report_parts_follow_the_pinned_report(office, monkeypatch):
    allocated = reports.report_path(office, "research", "ACME")["path"]
    (office / allocated).write_text("Partial main file.\n")
    directory = allocated.removesuffix(".md") + ".parts/"
    assert reports.report_path(office, "research", "ACME")["path"] != allocated
    same_day = reports.parts(office, report=allocated)
    assert all(path.startswith(directory) for path in same_day["paths"].values())

    class Later(date):
        @classmethod
        def today(cls):
            return date.today() + timedelta(days=3)

    monkeypatch.setattr(reports, "date", Later)
    assert reports.parts(office, report=allocated) == same_day
    code, data = cli(office, "report", "parts", "--report", allocated, "--read-only")
    assert code == 0 and data == same_day
    code, data = cli(
        office, "report", "path", "--report", allocated, "--part", "risk-analyst", "--read-only"
    )
    assert code == 0 and data["path"] == directory + "risk-analyst.md"
    code, data = cli(office, "report", "path", "--read-only")
    assert (code, data["reason"]) == (1, "invalid_report")

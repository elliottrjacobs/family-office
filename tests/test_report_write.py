import json
import os

import pytest
import yaml
from typer.testing import CliRunner

from fo import reports
from fo.brief import start
from fo.cli import app
from fo.errors import OfficeError
from tests.offices import synthetic


def cli(root, *args, body=""):
    response = CliRunner().invoke(app, [*args, "--json", "--office", str(root)], input=body)
    return response.exit_code, json.loads(response.output)


def report_text(allocated, body="# Synthetic\n\nBody."):
    meta = {**allocated["frontmatter"], "model": "fixture", "summary": "Synthetic."}
    return "---\n" + yaml.safe_dump(meta) + "---\n\n" + body + "\n\n" + reports.CLOSING + "\n"


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def test_write_at_the_path_fo_start_returned_passes_verify(office):
    started = start(office, "research", "BETA")["report"]["data"]
    text = report_text(started)
    code, data = cli(office, "report", "write", "--report", started["path"], body=text)
    assert code == 0
    assert data == {"path": started["path"], "bytes": len(text.encode()), "part": None}
    assert (office / started["path"]).read_text() == text
    code, verified = cli(office, "skill", "verify", "--path", started["path"])
    assert (code, verified["valid"]) == (0, True)


def test_write_allocates_like_fo_report_path_without_a_pin(office):
    expected = reports.report_path(office, "research", "BETA")["path"]
    code, data = cli(office, "report", "write", "--kind", "research", "--subject", "BETA", body="x")
    assert (code, data["path"]) == (0, expected)
    code, data = cli(office, "report", "write", "--subject", "BETA", body="x")
    assert (code, data["reason"]) == (1, "invalid_report")


def test_part_writes_under_the_part_directory(office):
    started = start(office, "research", "BETA")["report"]["data"]
    code, data = cli(
        office, "report", "write", "--report", started["path"], "--part", "inputs", body="{}\n"
    )
    resolved = reports.report_path(office, part="inputs", report=started["path"])["path"]
    assert (code, data["path"], data["part"]) == (0, resolved, "inputs")
    assert resolved.endswith(".parts/inputs.md")
    assert (office / resolved).read_text() == "{}\n"
    assert not (office / started["path"]).exists()


def test_paths_outside_reports_are_refused(office, tmp_path):
    for bad in (
        "notebook/corrections.md",
        "reports/../profile/2026-01-01-x.md",
        str(tmp_path / "reports/research/ACME/2026-01-01-report.md"),
    ):
        code, data = cli(office, "report", "write", "--report", bad, body="x")
        assert (code, data["reason"]) in {(1, "unsafe_path"), (1, "report_path")}, bad
    assert not (office / "profile/2026-01-01-x.md").exists()
    for bad in ("profile/ips.json", "../outside.md", str(tmp_path / "outside.md"), "reports"):
        with pytest.raises(OfficeError) as caught:
            reports.safe_report_path(office, bad)
        assert caught.value.reason == "unsafe_path", bad


def test_dotted_directories_under_reports_are_refused(office):
    for bad in (
        "reports/.git/config",
        "reports/x/.claude/settings.json",
        "reports/research/.hidden/2026-01-01-report.md",
        "reports/research/ACME/.2026-01-01-report.md",
        str(office / "reports/.claude/settings.json"),
    ):
        with pytest.raises(OfficeError) as caught:
            reports.safe_report_path(office, bad)
        assert caught.value.reason == "unsafe_path", bad
    code, data = cli(
        office, "report", "write", "--report", "reports/research/.x/2026-01-01-r.md", body="x"
    )
    assert (code, data["reason"]) == (1, "unsafe_path")
    code, data = cli(
        office, "report", "write", "--kind", "research", "--subject", ".claude", body="x"
    )
    assert (code, data["reason"]) == (1, "invalid_path")
    assert reports.safe_report_path(office, office / "reports/a/b.md") == "reports/a/b.md"


def test_a_symlinked_directory_out_of_reports_is_refused(office, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (office / "reports/research/LINK").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OfficeError) as caught:
        reports.safe_report_path(office, "reports/research/LINK/2026-01-01-report.md")
    assert caught.value.reason == "unsafe_path"


def test_oversized_body_is_refused(office):
    started = start(office, "research", "BETA")["report"]["data"]
    big = "x" * (reports.MAX_BODY_BYTES + 1)
    code, data = cli(office, "report", "write", "--report", started["path"], body=big)
    assert (code, data["reason"]) == (1, "report_too_large")
    assert not (office / started["path"]).exists()
    config = office / "office.toml"
    config.write_text(config.read_text() + "\n[reports]\nmax_body_bytes = 10\n")
    code, data = cli(office, "report", "write", "--report", started["path"], body="x" * 11)
    assert (code, data["reason"]) == (1, "report_too_large")
    code, data = cli(office, "report", "write", "--report", started["path"], body="x" * 10)
    assert code == 0


def test_empty_body_is_refused(office):
    started = start(office, "research", "BETA")["report"]["data"]
    code, data = cli(office, "report", "write", "--report", started["path"], body="  \n")
    assert (code, data["reason"]) == (1, "empty_report")


def test_interrupted_write_leaves_no_partial_file(office, monkeypatch):
    started = start(office, "research", "BETA")["report"]["data"]
    target = office / started["path"]

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    code, data = cli(office, "report", "write", "--report", started["path"], body="new body")
    assert (code, data["reason"]) == (1, "write_failed")
    assert not target.exists()
    assert list(target.parent.iterdir()) == []
    monkeypatch.undo()
    assert cli(office, "report", "write", "--report", started["path"], body="old")[0] == 0
    monkeypatch.setattr(os, "replace", fail)
    assert cli(office, "report", "write", "--report", started["path"], body="new")[0] == 1
    assert target.read_text() == "old"
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name]


def test_write_is_allowed_under_the_run_marker_and_refused_read_only(office, monkeypatch):
    started = start(office, "research", "BETA")["report"]["data"]
    code, data = cli(
        office, "report", "write", "--report", started["path"], "--read-only", body="x"
    )
    assert (code, data["reason"]) == (1, "read_only")
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.delenv("FO_OFFICE", raising=False)
    code, data = cli(office, "report", "write", "--report", started["path"], body="x")
    assert (code, data["path"]) == (0, started["path"])


RUN = "01M50V918GZEEPD9WHWV3M7CH6"


def test_body_file_from_reports_or_a_run_workspace(office):
    started = start(office, "research", "BETA")["report"]["data"]
    text = report_text(started)
    draft = office / "reports/research/BETA/draft.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(text)
    code, data = cli(
        office, "report", "write", "--report", started["path"], "--body-file", str(draft)
    )
    assert (code, data["path"], data["bytes"]) == (0, started["path"], len(text.encode()))
    assert (office / started["path"]).read_text() == text
    workspace = office / "cache/serve/runs" / RUN / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "body.md").write_text(text + "More.\n")
    relative = f"cache/serve/runs/{RUN}/workspace/body.md"
    code, data = cli(
        office, "report", "write", "--report", started["path"], "--body-file", relative
    )
    assert code == 0 and (office / started["path"]).read_text() == text + "More.\n"
    # The body file wins over stdin.
    code, _ = cli(
        office, "report", "write", "--report", started["path"], "--body-file", relative, body="x"
    )
    assert code == 0 and (office / started["path"]).read_text() == text + "More.\n"


def test_body_file_outside_its_roots_is_refused(office, tmp_path):
    started = start(office, "research", "BETA")["report"]["data"]
    (tmp_path / "outside.md").write_text("x")
    (office / "cache/serve/runs" / RUN).mkdir(parents=True)
    (office / "cache/serve/runs" / f"{RUN}.jsonl").write_text("x")
    (office / "reports/research/BETA").mkdir(parents=True, exist_ok=True)
    (office / "reports/research/BETA/link.md").symlink_to(office / "office.toml")
    for bad in (
        str(tmp_path / "outside.md"),
        "../outside.md",
        "office.toml",
        "notebook/decisions.jsonl",
        "secrets/x",
        f"cache/serve/runs/{RUN}.jsonl",
        f"cache/serve/runs/{RUN}/web.jsonl",
        "cache/serve/runs/x/workspace/body.md",
        "reports/research/BETA/link.md",
    ):
        code, data = cli(office, "report", "write", "--report", started["path"], "--body-file", bad)
        assert (code, data["reason"]) == (1, "unsafe_path"), bad
    code, data = cli(
        office, "report", "write", "--report", started["path"], "--body-file", "reports/none.md"
    )
    assert (code, data["reason"]) == (1, "body_file_missing")
    assert not (office / started["path"]).exists()


def test_body_file_keeps_the_size_cap_and_utf8_rule(office):
    started = start(office, "research", "BETA")["report"]["data"]
    config = office / "office.toml"
    config.write_text(config.read_text() + "\n[reports]\nmax_body_bytes = 10\n")
    draft = office / "reports/draft.md"
    draft.write_text("x" * 11)
    args = ("report", "write", "--report", started["path"], "--body-file", "reports/draft.md")
    assert cli(office, *args)[1]["reason"] == "report_too_large"
    draft.write_bytes(b"\xff\xfe")
    assert cli(office, *args)[1]["reason"] == "invalid_report_body"
    draft.write_text("  \n")
    assert cli(office, *args)[1]["reason"] == "empty_report"

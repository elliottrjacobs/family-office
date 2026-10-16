import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from fo import reports
from fo.cli import app as cli
from fo.envelope import FAILED
from fo.errors import OfficeError
from fo.init import initialize
from fo.serve import prepare, routes_read
from fo.serve.cache import ResponseCache
from fo.serve.server import Locator
from fo.store.authored import PROFILE_FILES
from fo.sync import ingest
from tests.offices import synthetic
from tests.serving import serving, tree

SCHEMAS = Path("src/fo/store/schemas/output")
DECIMAL = r"^-?\d+(\.\d+)?([Ee][+-]?\d+)?$"


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def schema(name):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text())


def test_every_read_route_answers_and_leaves_the_office_unchanged(office, tmp_path):
    research = next(
        r["path"] for r in reports.scan(office)["reports"] if r["frontmatter"]["kind"] == "research"
    )
    validated = {
        "/api/networth": "networth",
        "/api/allocation": "allocation",
        "/api/positions": "positions",
        "/api/lots?symbol=ACME": "lots",
        "/api/cashflow?months=2": "cashflow",
        "/api/spend?month=2026-08": "spend",
        "/api/goals": "goals",
        "/api/review": "review",
        "/api/reports": "reports-list",
        f"/api/report?path={research}": "report-show",
        "/api/skills": "skills-list",
    }
    others = [
        "/api/decisions",
        "/api/corrections",
        "/api/sync",
        "/api/doctor",
        "/api/config",
        "/api/profile",
        "/api/status",
        "/api/onboarding",
        "/api/levels",
        *(f"/api/profile/{name}" for name in PROFILE_FILES),
    ]
    before = tree(office)
    with serving(office, tmp_path) as (_, client):
        for path, name in validated.items():
            status, data = client.get(path)
            assert status == 200, (path, data)
            jsonschema.validate(data, schema(name))
        for path in others:
            status, data = client.get(path)
            assert status == 200, (path, data)
        # Repeat through the cache to cover cached responses as well.
        assert client.get("/api/networth")[1] == client.get("/api/networth")[1]
        allocation = client.get("/api/allocation")[1]
        assert all(isinstance(v, str) for v in allocation["weights"].values())
        assert all(isinstance(b["min"], str) for b in allocation["bands"])
        ips = client.get("/api/profile/ips")[1]
        assert ips["file"] == "profile/ips.json" and ips["data"]["bands"][0]["name"] == "Equity"
        config = client.get("/api/config")[1]
        assert config["secrets"] == {}
    assert tree(office) == before


def test_lists_are_not_truncated(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    (root / "profile/accounts.json").write_text(
        json.dumps({"accounts": [{"id": "a", "provider": "fixture", "last4": "0001"}]})
    )
    positions = [
        {"symbol": f"S{i:02}", "qty": "1", "price": "10", "value": "10"} for i in range(25)
    ]
    ingest(root, "fixture", [{"account_id": "a", "positions": positions, "balance": {}}])
    with serving(root, tmp_path) as (_, client):
        data = client.get("/api/positions")[1]
    assert len(data["positions"]) == 25 and "omitted_rows" not in data
    jsonschema.validate(data, schema("positions"))


@pytest.mark.parametrize(
    "query",
    [
        "secrets/keys.toml",
        "../x.md",
        "reports/../secrets/keys.toml",
        "reports%252f..%252f..%252fsecrets%252fkeys.toml",
        "%2e%2e%2fsecrets%2fkeys.toml",
        "PARTS",
    ],
)
def test_report_route_refuses_unsafe_paths(office, tmp_path, query):
    research = next(
        r["path"] for r in reports.scan(office)["reports"] if r["frontmatter"]["kind"] == "research"
    )
    query = query.replace("PARTS", research.removesuffix(".md") + ".parts/risk-analyst.md")
    with serving(office, tmp_path) as (_, client):
        status, data = client.get("/api/report?path=" + query)
    assert (status, data["reason"]) == (400, "unsafe_path")


def test_bad_queries_and_unknown_routes_use_the_envelope(office, tmp_path):
    with serving(office, tmp_path) as (_, client):
        assert client.get("/api/cashflow?months=x")[1]["reason"] == "invalid_request"
        assert client.get("/api/cashflow?months=500")[1]["reason"] == "invalid_request"
        assert client.get("/api/lots")[1]["reason"] == "invalid_request"
        assert client.get("/api/nothing") == (
            404,
            {"reason": "unknown_route", "message": "No such route."},
        )
        assert client.get("/api/profile/secrets")[0] == 404
        assert client.get("/api/profile/a/b")[0] == 404
        assert client.get("/api/report?path=reports/research/ACME/none.md")[0] == 404


@pytest.mark.parametrize("error", [OSError, RuntimeError, ValueError])
def test_unexpected_errors_never_leak_details(office, tmp_path, monkeypatch, error):
    def explode(root, query):
        raise error(f"{root}/secrets/keys.toml token=abc123")

    monkeypatch.setitem(routes_read.ROUTES, "/api/goals", routes_read.Route(explode))
    with serving(office, tmp_path) as (app, client):
        status, data = client.get("/api/goals")
    assert (status, data) == (500, FAILED)
    assert not any(str(office) in line or "abc123" in line for line in app.log_lines)


def test_office_routes_wait_for_an_office(tmp_path):
    with serving(None, tmp_path) as (_, client):
        status, data = client.get("/api/networth")
        assert (status, data["reason"]) == (404, "office_not_found")
        status, data = client.get("/api/status")
        assert status == 200 and data["mode"] == "onboarding" and data["office"] is None
        assert client.get("/api/skills")[0] == 200


def test_static_files_stay_inside_the_app(office, tmp_path):
    with serving(office, tmp_path) as (app, client):
        (app.static / "linked.js").symlink_to(app.static / "assets/app.js")
        assert client.get("/")[0] == 200
        assert b"<title>Family Office" in client.get("/finances")[1]
        status, headers, _ = client.request("GET", "/assets/app.js")
        assert status == 200 and headers["content-type"].startswith("text/javascript")
        assert headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        for path in (
            "/../pyproject.toml",
            "/%2e%2e/pyproject.toml",
            "/assets/../../pyproject.toml",
            "/linked.js",
            "/assets",
            "/assets/",
            "/missing.js",
        ):
            status, body = client.get(path)
            assert status == 404, path
            assert b"app.js" not in json.dumps(body).encode()


def test_missing_build_explains_itself(office, tmp_path):
    with serving(office, tmp_path) as (app, client):
        (app.static / "index.html").unlink()
        status, body = client.get("/")
    assert status == 503 and b"app build is missing" in body


def test_heartbeat_streams_events_and_closes(office, tmp_path):
    with serving(office, tmp_path) as (_, client):
        status, headers, data = client.request("GET", "/api/heartbeat")
    assert status == 200 and headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in data.decode().split("\n\n") if line]
    assert [e["sequence"] for e in events] == [1, 2, 3]


def test_cache_recomputes_only_when_the_office_changes(office):
    clock = [0.0]
    cache = ResponseCache(cycle=2.0, clock=lambda: clock[0])
    calls = []

    def compute():
        calls.append(1)
        return len(calls)

    assert cache.get(office, "k", compute) == 1
    assert cache.get(office, "k", compute) == 1
    (office / "notebook/corrections.md").write_text("# Standing corrections\n\nChanged.\n")
    assert cache.get(office, "k", compute) == 1  # within the poll cycle
    clock[0] = 3.0
    assert cache.get(office, "k", compute) == 2
    clock[0] = 6.0
    assert cache.get(office, "k", compute) == 2
    assert cache.get(office, "k", compute, ttl=1) == 3


def test_serve_package_never_imports_the_cli():
    imports = re.compile(r"^\s*(import fo\.cli|from fo\.cli import|from fo import .*\bcli\b)", re.M)
    for path in Path("src/fo/serve").rglob("*.py"):
        assert not imports.search(path.read_text()), path
    code = "import sys, fo.serve, fo.serve.server; print('fo.cli' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == "False"


def test_prepare_binds_loopback_unless_host_is_explicit(office):
    server, lines = prepare(office, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert not any("Warning" in line for line in lines)
        assert any(server.app.access.landing_url() in line for line in lines)
        assert f"  Office: {office}" in lines
    finally:
        server.server_close()
    server, lines = prepare(office, port=0, host="0.0.0.0")
    try:
        assert server.server_address[0] == "0.0.0.0"
        assert lines[0].startswith("Warning: listening on 0.0.0.0")
    finally:
        server.server_close()


def test_prepare_validates_ports_and_remote_settings(office, tmp_path):
    for port in (8182, 70000):
        with pytest.raises(OfficeError, match="port"):
            prepare(office, port=port)
    with pytest.raises(OfficeError, match="tailnet_name"):
        prepare(office, port=0, remote=True)
    config = office / "office.toml"
    config.write_text(config.read_text() + '\n[serve]\nport = 0\nallowed_logins = "me"\n')
    with pytest.raises(OfficeError, match="allowed_logins"):
        prepare(office)
    server, lines = prepare(tmp_path / "empty", port=0)
    server.server_close()
    assert "  No office yet; the page will guide setup." in lines
    busy, _ = prepare(office.parent / "none", port=0)
    try:
        with pytest.raises(OfficeError, match="unavailable"):
            prepare(office.parent / "none", port=busy.server_address[1])
    finally:
        busy.server_close()


def test_fo_serve_prints_the_link_and_stops_cleanly(office, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    def interrupted(self, poll_interval=0.5):
        raise KeyboardInterrupt

    monkeypatch.setattr("fo.serve.server.Server.serve_forever", interrupted)
    response = CliRunner().invoke(cli, ["serve", "--port", "0", "--open", "--office", str(office)])
    assert response.exit_code == 0, response.output
    assert "Open: http://127.0.0.1:" in response.output
    assert response.output.strip().endswith("Stopped.")
    assert opened and opened[0].startswith("http://127.0.0.1:")


def test_locator_requires_an_initialized_office(tmp_path):
    with pytest.raises(OfficeError, match="No office"):
        Locator(tmp_path).root()
    with pytest.raises(OfficeError):
        Locator(None).root()

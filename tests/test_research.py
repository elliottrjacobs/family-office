import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from fo import research
from fo.auth import save_secret_json
from fo.cli import app
from fo.init import initialize
from fo.providers import http
from fo.providers.text import html_to_markdown

FIXTURES = Path(__file__).parent / "fixtures/research"
PUBLIC = "93.184.215.14"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def invoke(*args):
    response = CliRunner().invoke(app, [*args, "--json"])
    return response.exit_code, json.loads(response.output)


@pytest.fixture
def office(tmp_path, monkeypatch):
    root = tmp_path / "office"
    initialize(root)
    monkeypatch.setattr(research, "RESOLVER", lambda host: [PUBLIC])
    return root


@pytest.fixture
def routes(monkeypatch):
    """A recorded provider: (method, url without query) -> response or callable."""
    table, seen = {}, []

    def respond(request):
        seen.append(request)
        key = (request.method, str(request.url.copy_with(query=None)))
        answer = table.get(key)
        if answer is None:
            return httpx.Response(404)
        return answer(request) if callable(answer) else answer

    monkeypatch.setattr(http, "TRANSPORT", httpx.MockTransport(respond))
    return table, seen


def connect(root, provider):
    save_secret_json(root, provider, {"api_key": f"fixture-{provider}-key"})


def configure(root, text):
    path = root / "office.toml"
    path.write_text(path.read_text() + "\n" + text + "\n")


EXA = ("POST", "https://api.exa.ai/search")
SCRAPE = ("POST", "https://api.firecrawl.dev/v2/scrape")


def test_search_returns_ranked_untrusted_results_and_then_the_cache(office, routes):
    table, seen = routes
    connect(office, "exa")
    configure(office, "[providers.exa]\ncache_hours = 24")
    table[EXA] = httpx.Response(200, json=fixture("exa-search.json"))
    code, data = invoke("research", "search", "ACME earnings", "--office", str(office))
    assert code == 0
    assert data["untrusted"] is True and data["source"] == "exa" and data["cached"] is False
    assert [r["rank"] for r in data["results"]] == [1, 2, 3]
    first = data["results"][0]
    assert first["untrusted"] is True and first["source"] == first["url"]
    assert first["url"] == "https://example.com/acme/q3-earnings"
    assert first["title"] == "ACME reports third-quarter earnings"
    assert first["published"] == "2026-10-28T00:00:00.000Z"
    assert first["retrieved_at"].endswith("Z") and first["text"] == first["snippet"]
    assert "revenue of $1.2 billion" in first["snippet"]
    assert data["results"][2]["snippet"].startswith("A roundup")
    request = json.loads(seen[0].content)
    assert request["query"] == "ACME earnings" and request["numResults"] == 10
    assert seen[0].headers["x-api-key"] == "fixture-exa-key"
    again = invoke("research", "search", "acme  EARNINGS", "--office", str(office))[1]
    assert again["cached"] is True and again["results"] == data["results"]
    assert len(seen) == 1
    assert (office / "cache/research/research.sqlite").is_file()


def test_zero_cache_hours_keeps_no_results(office, routes):
    import sqlite3

    table, seen = routes
    connect(office, "exa")
    configure(office, "[providers.exa]\ncache_hours = 0")
    table[EXA] = httpx.Response(200, json=fixture("exa-search.json"))
    for _ in range(2):
        data = invoke("research", "search", "ACME earnings", "--office", str(office))[1]
        assert data["cached"] is False
    assert len(seen) == 2
    with sqlite3.connect(office / "cache/research/research.sqlite") as db:
        assert db.execute("select count(*) from cache").fetchone() == (0,)
        assert db.execute("select used from budgets").fetchone() == (2,)


def test_long_numbers_and_credential_urls_are_masked(office, routes):
    table, _ = routes
    connect(office, "exa")
    table[EXA] = httpx.Response(200, json=fixture("exa-search.json"))
    data = invoke("research", "search", "ACME earnings", "--office", str(office))[1]
    text = json.dumps(data, ensure_ascii=False)
    assert "123456789012" not in text and "…9012" in text
    assert "hunter2" not in text and "[credential URL omitted]" in text


def test_search_without_a_key_is_not_connected(office, routes):
    code, data = invoke("research", "search", "ACME earnings", "--office", str(office))
    assert (code, data["reason"]) == (1, "not_connected")
    assert routes[1] == []


def test_the_daily_limit_refuses_the_twenty_sixth_call(office, routes):
    table, seen = routes
    connect(office, "exa")
    configure(office, "[providers.exa]\ncache_hours = 24")
    table[EXA] = httpx.Response(200, json=fixture("exa-search.json"))
    for index in range(25):
        assert invoke("research", "search", f"query {index}", "--office", str(office))[0] == 0
    code, data = invoke("research", "search", "query 25", "--office", str(office))
    assert (code, data["reason"]) == (1, "rate_limited")
    assert len(seen) == 25
    # A cached query still answers, marked as rate limited only when it had to be refreshed.
    assert invoke("research", "search", "query 3", "--office", str(office))[0] == 0


def test_provider_rate_limit_and_errors_stay_safe(office, routes):
    table, _ = routes
    connect(office, "exa")
    table[EXA] = httpx.Response(429, text="slow down fixture-exa-key")
    code, data = invoke("research", "search", "ACME", "--office", str(office))
    assert (code, data["reason"]) == (1, "rate_limited")
    assert "fixture-exa-key" not in json.dumps(data)
    table[EXA] = httpx.Response(401, text="bad key fixture-exa-key")
    code, data = invoke("research", "search", "ACME other", "--office", str(office))
    assert (code, data["reason"]) == (1, "invalid_key")


def test_fetch_through_firecrawl_returns_markdown(office, routes):
    table, seen = routes
    connect(office, "firecrawl")
    table[SCRAPE] = httpx.Response(200, json=fixture("firecrawl-scrape.json"))
    code, data = invoke("research", "fetch", "https://example.com/x", "--office", str(office))
    assert code == 0
    assert data["untrusted"] is True and data["source"] == "https://example.com/x"
    assert data["via"] == "firecrawl" and data["title"] == "ACME third quarter"
    assert data["text"].startswith("# ACME third quarter")
    assert "987654321098765" not in data["text"] and "…8765" in data["text"]
    assert json.loads(seen[0].content)["url"] == "https://example.com/x"
    assert seen[0].headers["authorization"] == "Bearer fixture-firecrawl-key"
    assert invoke("research", "fetch", "https://example.com/x", "--office", str(office))[0] == 0
    assert len(seen) == 1


def test_direct_fetch_converts_strips_and_caps(office, routes):
    table, seen = routes
    html = (FIXTURES / "page.html").read_text()
    table[("GET", "https://example.com/x")] = httpx.Response(
        200, text=html, headers={"content-type": "text/html; charset=utf-8"}
    )
    code, data = invoke("research", "fetch", "https://example.com/x", "--office", str(office))
    assert code == 0 and data["via"] == "direct" and data["untrusted"] is True
    text = data["text"]
    assert "\n\n# ACME investor update\n\nThird-quarter revenue rose 8% to $1.2 billion." in text
    assert "[filings page](https://example.com/acme/filings)" in text
    assert "## Segments" in text and "- Industrial tools" in text and "1. Kitchen" in text
    assert "| Year | Revenue |" in text and "| 2026 | $1.2B |" in text
    for gone in (
        "steal",
        "127.0.0.1",
        "Ignore previous",
        "SYSTEM:",
        "aria text",
        "screen reader",
        "Enable scripts",
        "fixture-token",
        "Subscribe",
        "onclick",
        "data-track",
        "javascript",
        "color: red",
    ):
        assert gone not in text, gone
    assert "123456789012" not in text and "…9012" in text
    assert seen[0].headers["user-agent"].startswith("family-office")

    configure(office, "[research]\nfetch_max_bytes = 600\ntext_max_chars = 40")
    table[("GET", "https://example.com/long")] = httpx.Response(
        200, text=html, headers={"content-type": "text/html"}
    )
    data = invoke("research", "fetch", "https://example.com/long", "--office", str(office))[1]
    assert data["body_truncated"] is True and data["truncated"] is True
    assert len(data["text"]) == 40


def test_direct_fetch_follows_redirects_but_refuses_loopback_mid_chain(office, routes):
    table, seen = routes
    table[("GET", "https://example.com/a")] = httpx.Response(302, headers={"location": "/b"})
    table[("GET", "https://example.com/b")] = httpx.Response(
        301, headers={"location": "http://127.0.0.1:4790/api/brief"}
    )
    code, data = invoke("research", "fetch", "https://example.com/a", "--office", str(office))
    assert (code, data["reason"]) == (1, "url_refused")
    assert "loopback_address" in data["message"]
    assert [str(r.url) for r in seen] == ["https://example.com/a", "https://example.com/b"]


def test_direct_fetch_stops_after_three_redirects(office, routes):
    table, seen = routes
    for index in range(5):
        table[("GET", f"https://example.com/r{index}")] = httpx.Response(
            302, headers={"location": f"https://example.com/r{index + 1}"}
        )
    code, data = invoke("research", "fetch", "https://example.com/r0", "--office", str(office))
    assert (code, data["reason"]) == (1, "too_many_redirects")
    assert len(seen) == 4


def test_redirect_to_a_name_resolving_privately_is_refused(office, routes, monkeypatch):
    table, seen = routes
    monkeypatch.setattr(
        research,
        "RESOLVER",
        lambda host: ["10.0.0.7"] if host == "intranet.example.com" else [PUBLIC],
    )
    table[("GET", "https://example.com/a")] = httpx.Response(
        302, headers={"location": "https://intranet.example.com/"}
    )
    code, data = invoke("research", "fetch", "https://example.com/a", "--office", str(office))
    assert (code, data["reason"]) == (1, "url_refused")
    assert "private_address" in data["message"] and len(seen) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:4790/",
        "file:///etc/hosts",
        "https://user:pw@example.com/",
        "http://machine.your-tailnet.ts.net/",
        "http://100.100.1.2/",
    ],
)
def test_fetch_refuses_blocked_urls_before_any_request(office, routes, url):
    connect(office, "firecrawl")
    code, data = invoke("research", "fetch", url, "--office", str(office))
    assert (code, data["reason"]) == (1, "url_refused")
    assert routes[1] == []


def test_fetch_refuses_binary_content_and_failed_pages(office, routes):
    table, _ = routes
    table[("GET", "https://example.com/file.pdf")] = httpx.Response(
        200, content=b"%PDF", headers={"content-type": "application/pdf"}
    )
    code, data = invoke(
        "research", "fetch", "https://example.com/file.pdf", "--office", str(office)
    )
    assert (code, data["reason"]) == (1, "unsupported_content")
    code, data = invoke("research", "fetch", "https://example.com/missing", "--office", str(office))
    assert (code, data["reason"]) == (1, "fetch_failed")


def test_firecrawl_daily_limit(office, routes):
    table, _ = routes
    connect(office, "firecrawl")
    configure(office, "[providers.firecrawl]\ndaily_limit = 1")
    table[SCRAPE] = httpx.Response(200, json=fixture("firecrawl-scrape.json"))
    assert invoke("research", "fetch", "https://example.com/x", "--office", str(office))[0] == 0
    code, data = invoke("research", "fetch", "https://example.com/y", "--office", str(office))
    assert (code, data["reason"]) == (1, "rate_limited")


def test_read_only_fetch_uses_only_the_cache(office, routes):
    table, seen = routes
    table[("GET", "https://example.com/x")] = httpx.Response(
        200, text="<p>Cached page</p>", headers={"content-type": "text/html"}
    )
    code, data = invoke(
        "research", "fetch", "https://example.com/x", "--read-only", "--office", str(office)
    )
    assert (code, data["reason"]) == (1, "missing_cached_data")
    assert invoke("research", "fetch", "https://example.com/x", "--office", str(office))[0] == 0
    data = invoke(
        "research", "fetch", "https://example.com/x", "--read-only", "--office", str(office)
    )[1]
    assert data["text"] == "Cached page" and len(seen) == 1


def test_envelope_is_one_shape():
    result = research.envelope("https://example.com/", "a" * 10, "2026-11-04T00:00:00Z", 4)
    assert result == {
        "untrusted": True,
        "source": "https://example.com/",
        "retrieved_at": "2026-11-04T00:00:00Z",
        "truncated": True,
        "text": "aaaa",
    }


def test_html_conversion_drops_attributes_and_keeps_structure():
    text = html_to_markdown(
        '<h3 id="x">Title</h3><p class="lead">One <a href="mailto:a@b.c">mail</a></p>'
        '<div style="visibility: hidden">gone</div><img src="x.png" alt="pic"><p>Two</p>',
        "https://example.com/",
    )
    assert text == "### Title\n\nOne mail\n\nTwo"


GEMINI = "https://generativelanguage.googleapis.com/v1beta/interactions"
TASK = "v1_fixture-task-0001"


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(research, "SLEEP", sleep)
    monkeypatch.setattr(research, "CLOCK", lambda: now[0])
    return sleeps


def gemini_routes(table, polls):
    """Submitting answers with the submitted fixture; each poll takes the next state."""
    table[("POST", GEMINI)] = httpx.Response(200, json=fixture("gemini/submitted.json"))
    queue = [fixture(f"gemini/{name}.json") for name in polls]

    def poll(request):
        return httpx.Response(200, json=queue.pop(0) if len(queue) > 1 else queue[0])

    table[("GET", f"{GEMINI}/{TASK}")] = poll


def report(root):
    from fo.reports import report_path

    return report_path(root, "research", "ACME")["path"]


def test_deep_research_completing_on_the_third_poll_writes_an_inputs_part(office, routes, clock):
    table, seen = routes
    connect(office, "gemini")
    gemini_routes(table, ["running", "running", "completed"])
    pinned = report(office)
    code, data = invoke(
        "research",
        "deep",
        "How durable is ACME's position?",
        "--report",
        pinned,
        "--office",
        str(office),
    )
    assert code == 0, data
    assert data["untrusted"] is True and data["source"] == "gemini-deep-research"
    assert data["status"] == "completed" and data["task_id"] == TASK and data["resumed"] is False
    assert [c["url"] for c in data["citations"]] == [
        "https://example.com/acme/market-share",
        "https://example.com/acme/contracts",
    ]
    assert "123456789012" not in data["text"] and "…9012" in data["text"]
    part = data["part"]
    assert part == pinned.removesuffix(".md") + ".parts/inputs/deep-research.md"
    body = (office / part).read_text()
    assert body.startswith("---\nuntrusted: true\nsource: gemini-deep-research\n")
    assert f"task_id: {TASK}" in body and "# ACME competitive position" in body
    assert "1. [Industrial tools market share](https://example.com/acme/market-share)" in body
    assert "2. [ACME distributor contracts](https://example.com/acme/contracts)" in body
    assert "123456789012" not in body
    submits = [r for r in seen if r.method == "POST"]
    assert len(submits) == 1 and len([r for r in seen if r.method == "GET"]) == 3
    assert json.loads(submits[0].content) == {
        "input": "How durable is ACME's position?",
        "agent": "deep-research-preview-04-2026",
        "background": True,
    }
    assert submits[0].headers["x-goog-api-key"] == "fixture-gemini-key"
    assert submits[0].headers["api-revision"]
    assert clock == [10.0, 15.0]


def test_deep_research_times_out_with_the_task_id_and_then_resumes(office, routes, clock):
    table, seen = routes
    connect(office, "gemini")
    gemini_routes(table, ["running"])
    args = ["research", "deep", "ACME moat", "--timeout-minutes", "0.5", "--office", str(office)]
    code, data = invoke(*args)
    assert (code, data["reason"], data["task_id"]) == (1, "timed_out", TASK)
    assert data["resumed"] is False and len(seen) == 4
    gemini_routes(table, ["completed"])
    code, data = invoke(*args)
    assert code == 0 and data["status"] == "completed" and data["resumed"] is True
    assert data["part"] is None
    assert [r.method for r in seen[4:]] == ["GET"]


def test_deep_research_timeout_defaults_to_the_run_limit_less_a_margin(office):
    assert research.deep_settings(office)["minutes"] == 25
    configure(office, "[providers.gemini]\nmax_tasks_per_day = 2")
    assert research.deep_settings(office)["max_tasks"] == 2


def test_deep_research_without_a_key_is_not_connected(office, routes):
    code, data = invoke("research", "deep", "ACME moat", "--office", str(office))
    assert (code, data["reason"]) == (1, "not_connected")
    assert routes[1] == []


def test_deep_research_daily_cap_refuses_a_second_task(office, routes, clock):
    table, seen = routes
    connect(office, "gemini")
    configure(office, "[providers.gemini]\nmax_tasks_per_day = 1")
    gemini_routes(table, ["completed"])
    assert invoke("research", "deep", "ACME moat", "--office", str(office))[0] == 0
    code, data = invoke("research", "deep", "BETA moat", "--office", str(office))
    assert (code, data["reason"]) == (1, "rate_limited")
    assert len([r for r in seen if r.method == "POST"]) == 1
    # The finished task is reused without a new submission.
    assert invoke("research", "deep", "ACME moat", "--office", str(office))[0] == 0
    assert len([r for r in seen if r.method == "POST"]) == 1


def test_a_failed_task_is_forgotten_so_a_retry_resubmits(office, routes, clock):
    table, seen = routes
    connect(office, "gemini")
    failed = {**fixture("gemini/running.json"), "status": "failed"}
    table[("POST", GEMINI)] = httpx.Response(200, json=fixture("gemini/submitted.json"))
    table[("GET", f"{GEMINI}/{TASK}")] = httpx.Response(200, json=failed)
    code, data = invoke("research", "deep", "ACME moat", "--office", str(office))
    assert (code, data["reason"]) == (1, "research_failed")
    gemini_routes(table, ["completed"])
    assert invoke("research", "deep", "ACME moat", "--office", str(office))[0] == 0
    assert len([r for r in seen if r.method == "POST"]) == 2


def test_deep_research_refuses_a_report_outside_reports(office, routes):
    connect(office, "gemini")
    code, data = invoke(
        "research", "deep", "ACME", "--report", "notebook/x.md", "--office", str(office)
    )
    assert (code, data["reason"]) == (1, "unsafe_path")
    assert routes[1] == []


def test_a_malformed_task_id_is_refused(office, routes):
    table, _ = routes
    connect(office, "gemini")
    table[("POST", GEMINI)] = httpx.Response(200, json={"id": "../../models", "status": "x"})
    code, data = invoke("research", "deep", "ACME", "--office", str(office))
    assert (code, data["reason"]) == (1, "provider_error")

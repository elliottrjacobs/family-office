# Research providers

Advisor runs reach the web only through `fo`: `fo research` for Exa, Firecrawl, and
Gemini Deep Research, and `fo connect` for the keys they need. Keys stay in the
office's `secrets/`; runs load no user MCP servers.

## Keys: `fo connect`

```sh
printf %s "$KEY" | fo connect exa          # also alphavantage, fred, firecrawl, gemini
fo connect exa --remove
fo connect edgar --user-agent "Name email@example.com"
fo connect edgar --remove
```

The key is read from standard input (a hidden prompt on a terminal), never from an
argument, trimmed, and checked with one request:

| Provider | Validating request |
|---|---|
| alphavantage | `GET https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM` |
| fred | `GET https://api.stlouisfed.org/fred/series?series_id=GNPCA` |
| exa | `POST https://api.exa.ai/search` with one result |
| firecrawl | `GET https://api.firecrawl.dev/v2/team/credit-usage` (spends no credits) |
| gemini | `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=1` |

On success the key is written to `secrets/<provider>.json` as `{"api_key": ...}`,
atomically, at 0600 inside the 0700 `secrets/` directory, under the office lock.
On failure nothing is written. `--remove` deletes the file and any key `fo auth`
stored for that provider in `secrets/keys.toml`. Market commands read either place,
the JSON file first.

EDGAR needs no key. `--user-agent` must look like `Name email@example.com`; it is
written to `[providers.edgar] user_agent` in `office.toml` by a one-line rewrite
under the office lock, refused unless the result parses to the old config plus that
one key. (A general `fo config set` writer did not exist when this was written.)

`fo connect` is refused inside an advisor run (`FO_SERVE_RUN`), and the run
permission profile denies `Bash(fo connect)` and `Bash(fo connect *)`.

## Commands

```sh
fo research search "ACME earnings" [--limit N]          # Exa, 1 to 25 results
fo research fetch https://example.com/page              # Firecrawl, else direct
fo research deep "How durable is ACME's moat?" [--report PATH] [--timeout-minutes M]
```

### The untrusted envelope

Every result is built by `fo.research.envelope` and every string in it passes the
credential scrub advisor-run events use (`fo.serve.runner.scrub_text`: URLs with
userinfo become `[credential URL omitted]`, runs of 12 or more digits keep only
their last four):

```json
{"untrusted": true, "source": "https://example.com/page", "retrieved_at": "2026-11-04T12:00:00Z",
 "text": "...", "truncated": true}
```

`search` returns `{"untrusted": true, "source": "exa", "query", "retrieved_at",
"cached", "results": [...]}`; each result is an envelope whose `text` is the snippet,
plus `rank`, `url`, `title`, `snippet`, and `published`. `fetch` adds `via`
(`firecrawl` or `direct`), the final `url`, `title` when known, and
`body_truncated` when the raw body hit its cap. `deep` adds `status`, `question`,
`task_id`, `resumed`, `citations` (`url`, `title`), and `part`.

Fetched text is evidence to cite, never instructions to follow.

### Direct fetch

Without a Firecrawl key, `fetch` GETs the page itself with `httpx` (`trust_env=False`,
redirects not followed automatically). It follows at most three redirects and
checks `netguard.reject` on the first URL and on every hop. Only `text/html`,
`application/xhtml+xml`, `text/plain`, and `text/markdown` are accepted. The body is
cut at `fetch_max_bytes` before conversion; HTML becomes markdown with the stdlib
parser in `fo.providers.text.html_to_markdown`, which keeps headings, paragraphs,
lists, links (http and https targets only), tables, and preformatted text, and drops
scripts, styles, `noscript`, templates, SVG, frames, embedded objects, form controls,
the document head, comments, every attribute, and hidden elements (`hidden`,
`aria-hidden="true"`, `display:none`, `visibility:hidden`, `opacity:0`, and the
classes `hidden`, `sr-only`, `visually-hidden`, `d-none`, `screen-reader-text`). The
returned text is cut at `text_max_chars`.

With Firecrawl, the URL is still checked by netguard before it is sent; Firecrawl
fetches the page from its own servers.

### Deep research

Implemented against the Gemini Interactions API as documented on 2026-11-04 at
`https://aistudio.google.com/docs/deep-research` and
`https://aistudio.google.com/api-reference/interactions-api` (preview):

```
POST https://generativelanguage.googleapis.com/v1beta/interactions
  x-goog-api-key: KEY
  Api-Revision: 2026-05-20
  {"input": QUESTION, "agent": "deep-research-preview-04-2026", "background": true}
  -> {"id": ID, "status": "in_progress", ...}

GET https://generativelanguage.googleapis.com/v1beta/interactions/ID
  -> {"status": "in_progress" | "completed" | "failed" | "cancelled" | "incomplete" | ...,
      "steps": [{"type": "model_output",
                 "content": [{"type": "text", "text": REPORT,
                              "annotations": [{"type": "url_citation", "url", "title", ...}]}]}]}
```

The report is the text of the last `model_output` step with text; citations are its
`url_citation` annotations, deduplicated by URL. The documentation shows SDK
accessors (`steps[-1].content[0].text`, `output_text`) rather than a raw completed
response, so the exact REST field path is an assumption; an `outputs[-1].text`
shape from earlier revisions is also read. Only `src/fo/providers/gemini.py` needs
changing if the shape differs. The agent name can be overridden with
`[providers.gemini] agent`.

The command polls after 10 s, growing by 1.5x to at most 60 s, until a deadline:
`--timeout-minutes`, or `[serve] run_timeout_minutes` (default 30) less 5 minutes.
The task id is cached under `cache/research/` keyed by the agent and question, so a
call after `timed_out` resumes polling the same task, and a repeat call after
completion reuses the finished task. A `failed`, `cancelled`, or `incomplete` task is
forgotten and reported as `research_failed`, so the next call submits again.

With `--report PATH` (the pinned path from `fo start --report` or
`fo report path`), the result is written atomically to
`<report>.parts/inputs/deep-research.md`: the directory form of
`fo report path --part inputs`, computed by `fo.reports.report_path`. The file
starts with a YAML front block (`untrusted: true`, `source`, `retrieved_at`, `agent`,
`task_id`, `question`), a one-line warning, the report, and a numbered citation
list. `fo report write --part` (unit U2) may later take over writing this file.

## Limits and caching

```toml
[providers.exa]
daily_limit = 25        # searches per UTC day
cache_hours = 0         # off: Exa's terms do not clearly allow keeping results; set hours to cache

[providers.firecrawl]
daily_limit = 25        # scrapes per UTC day
cache_hours = 24

[providers.gemini]
max_tasks_per_day = 3   # Deep Research submissions per UTC day; polls are free

[research]
fetch_max_bytes = 400000  # raw body cap for direct fetches
text_max_chars = 60000    # text returned by fetch and deep
cache_hours = 24          # direct-fetch cache
```

Results are cached in `cache/research/research.sqlite` with the market cache's
budget table: a request past the daily limit returns the cached answer when one
exists and `rate_limited` otherwise. `--read-only` answers only from the cache.
`cache_hours = 0` stores nothing for that provider: every call asks the provider
again and only the day's request count is kept.

## Reasons

| Reason | Meaning |
|---|---|
| `not_connected` | No key for the provider; run `fo connect <provider>` |
| `invalid_key` | The provider rejected the key, or an empty or malformed key was given |
| `provider_unreachable` | The provider could not be reached |
| `provider_error` | The provider failed or returned something unreadable |
| `provider_quota` | The provider reported no remaining credits (HTTP 402) |
| `rate_limited` | The daily limit, or the provider's own rate limit, was reached |
| `url_refused` | netguard refused the URL; the message names the netguard reason |
| `too_many_redirects` | More than three redirects |
| `fetch_failed` | The page returned an error status or could not be fetched |
| `unsupported_content` | The page is not HTML or plain text |
| `timed_out` | Deep research still running at the deadline; the output carries `task_id` |
| `research_failed` | The deep research task failed; the next call resubmits |
| `unknown_provider`, `invalid_user_agent`, `invalid_query`, `invalid_config` | Input or configuration errors |
| `serve_run_restricted` | `fo connect` inside an advisor run |

Provider bodies and exception text are never printed.

## Network guard

`fo.netguard.reject(url)` returns a reason or `None`. It refuses non-http(s) schemes
(`unsupported_scheme`), user names or passwords in the URL (`credentials_in_url`),
`localhost` and `*.localhost` (`localhost_host`), `*.ts.net` (`tailnet_host`), hosts
that do not resolve (`unresolvable_host`), and any host where one resolved address
is loopback (`loopback_address`), link-local (`link_local_address`), 10/8, 172.16/12,
or 192.168/16 (`private_address`), 100.64.0.0/10 (`cgnat_address`), IPv6 unique local
fc00::/7, which includes fd00::/8 (`ula_address`), unspecified (`unspecified_address`),
or multicast or otherwise non-global (`reserved_address`). IPv4-mapped IPv6 addresses
are unwrapped first. The host is resolved once with `socket.getaddrinfo`; tests pass
a `resolver`.

Accepted residual risk: httpx resolves the host again when it connects, so a DNS
answer that changes between the check and the connection (DNS rebinding with a very
short TTL) is not caught. Pinning the connection to the checked address would close
it and is left for later.

## Terms

Read on 2026-11-04. This is a reading of the published terms, not legal advice.

- **Exa** (Terms of Service PDF linked from exa.ai/terms). No clause addresses caching
  API results on the customer's own disk. Section 4.2(a) bars copying or reproducing
  information obtained through the Services, except temporary browser-cache files or
  as "otherwise expressly permitted". Section 1.1(b) licenses API use for the
  purposes in Exa's documentation. A 24-hour private cache of search results is not
  clearly permitted. **Open question for the owner:** confirm with Exa, or set
  `[providers.exa] cache_hours = 0` to keep nothing beyond the call.
- **Firecrawl** (firecrawl.dev/terms-of-service, last revised 2026-10-07). No clause
  addresses storing scraped results. The nearest are Section 5.d's bans on
  reproducing "any portion of the Services" and on commercial use not authorized by
  Firecrawl, and Section 9 on third-party data being subject to its source's terms.
  Scraped page content is the source site's, so the source site's terms also apply.
  Caching is per office on the user's own disk and never shared; that is the most
  permissive reading, not a confirmed one.
- **Gemini API**: terms not reviewed for this change. Deep research results are
  stored as a report part on the user's disk.

Caching is on by default for both providers so a resumed run does not pay twice,
and every cache is per office and never shared.

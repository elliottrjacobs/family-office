# Security

family-office separates public code from a private office repository. Tests use
synthetic data. Never submit financial records, tokens, or account numbers in an
issue, pull request, or fixture.

## Trust boundaries

The CLI does not provide order placement or money-movement operations. Brokerage
credentials may nevertheless be trade-capable; keep them confidential. Use
provider-enforced read-only credentials where available. If the provider cannot
issue them and you require credentials that cannot trade, use offline imports
without configuring brokerage credentials. Permission
templates are accident-prevention measures, not protection against arbitrary code
running as the same OS user. Codex workspace-write permits reads in the office;
the office instructions forbid reading secrets, but do not enforce a read barrier.

Secrets are ignored by Git and stored at mode 0600 inside a 0700 directory.
Atomic replacement avoids partially written credentials. Provider errors must be
converted to safe errors before display. Raw payloads must not be logged.

## Companion app

Exposures the Mac and phone apps add, each described in full below:

| Exposure | Where it is described |
|---|---|
| Web search and fetch for runs at context level `none` | [Advisor runs](#advisor-runs), "Web access at context level `none`" |
| Research provider keys in `secrets/<provider>.json` | [Third parties](#third-parties), "Research provider keys" |
| Device tokens held by a paired phone, used over the tailnet | [Device tokens](#device-tokens) |
| Codex read confinement is command-based, so the engine ships disabled | [Advisor runs](#advisor-runs), "Codex engine" |

`fo serve` binds 127.0.0.1 unless `--host` names another address, which prints a
warning. A loopback port is still reachable by DNS-rebinding web pages and by
other users of the machine, so every route, static files included, requires a
per-launch token cookie (`HttpOnly`, `SameSite=Strict`, `Secure` with `--remote`).
The token travels only in the link the terminal prints; it is accepted only on
that landing route, compared in constant time, and kept out of the access log. A
request whose `Host` is not the bound loopback name and port, or the configured
tailnet name with `--remote`, gets 421. A non-GET request without the app's own
`Origin` gets 403. Tailscale identity headers only narrow access: with
`allowed_logins`, a missing or unlisted login is refused, and they never grant
access without the token.

The server reads the office with `read_only=True` and never takes the lock. Report
paths must resolve under `reports/` outside part directories, and static files
must resolve inside the packaged app directory with no symlinks. Unexpected
errors return a fixed `operation_failed` envelope without text or paths. Report
markdown renders as page elements, never as HTML. The browser never receives a
credential, and the page never asks for one.

Writes from the page (verdicts, reopen, deferral, new decisions, corrections) are
thin calls to `fo journal` and `fo corrections` in the server's own interpreter,
so the office lock and the notebook's validation apply as in a terminal. They need
the token and a same-origin `Origin`, and none exist with `--read-only`.

### Device tokens

A paired phone holds a device token: 32 random bytes shown once, in the pairing
response, and stored only as a SHA-256 hash with its name, creation time, and
last-seen time in the office's `secrets/devices.json` at 0600 inside the 0700
`secrets/` directory. Pairing codes are eight characters, held only in memory,
single use, valid for five minutes, one at a time, and dropped after ten wrong
attempts. A code is issued only over a loopback `Host` with the launch cookie,
and redeemed only over the tailnet name with a Tailscale identity that passes
`allowed_logins`.

A token is accepted only with `--remote`, as `Authorization: Bearer`, on a request
whose `Host` is the tailnet name and whose Tailscale login is present and passes
`allowed_logins`. On a loopback `Host` a bearer token is ignored and the cookie
rules apply unchanged: a loopback port is reachable by DNS-rebinding pages and by
other local users, so a credential that does not change with each launch must
never open it. `POST /api/devices/login` exchanges the token for a per-device
session cookie (`Secure`, `HttpOnly`, `SameSite=Strict`), valid only over the
tailnet and only while the device stays paired. Device credentials cannot list,
pair, or revoke devices; that needs the launch cookie. Revoke a device from the
Mac app's Devices pane or `DELETE /api/devices/{id}`; its token and sessions stop
working on the next request. A restart keeps devices paired. Tokens never appear
in the access log, and neither does the launch token that `fo serve --app` prints
in its one handshake line.

### Advisor runs

Chat starts one headless Claude Code run at a time in the office directory. A run
loads only the office's project settings plus a run profile: no user settings or
hooks, an empty strict MCP configuration, only the Bash, Read, Write, Edit, and
Task tools (plus WebSearch and WebFetch at level `none`, below), `--permission-mode dontAsk` with every permission prompt denied, and a
budget cap and time limit. Its environment carries only what login needs, with
`FO_SERVE_RUN` set so `fo` refuses other offices and the setup, `config set`,
credential, sync, commit, schedule, notify, migrate, reindex, and serve commands,
`corrections retire`, and `journal close`, `reopen`, and `judge`, whatever the flag
order or `--` separators. A run may add corrections and decisions but never retire
or settle the owner's. A PreToolUse hook (`fo.serve.guard`) is the last word on
every tool call, worker agents included: only plain `fo` commands with no pipes,
redirects, or substitution; reads inside the office outside `secrets/`, `cache/`,
`imports/`, `medical/`, `.git/`, the store, and the lock; and writes only under
`reports/`, never to a hidden file or folder there, which `fo commit` also refuses
to publish.
It exists because a skill's own `Read` permission and read-only shell commands
otherwise reach files outside the office. The runner never passes
`bypassPermissions`. Run records and event logs live in `cache/serve/runs/` at
0600 in a 0700 directory and never hold environment, cookie, or token values.

Web access at context level `none`: a run at that level, which reads no household
data, also gets the WebSearch and WebFetch tools; at `household` and `full` both
stay disallowed (`--tools` and `--disallowedTools` are built per launch and resume
from the level, and the hook denies both tools in any run not marked for web). The
hook checks every fetch URL against `fo.netguard`, the same deny list `fo research
fetch` uses: only `http` and `https`, no user name or password in the URL, no
`localhost` or `.ts.net` name, and no host that resolves to a loopback, private,
link-local, CGNAT or tailnet (`100.64.0.0/10`), IPv6 unique local, unspecified, or
reserved address, so a fetch cannot reach `fo serve`, other local services, or
another device. Fetches are capped per run by `web_fetch_cap` under `[serve]`
(default 20) with a counter in the run's own folder, `cache/serve/runs/<id>/`,
which the run cannot read or write. The hook appends every search query and fetch
URL it lets through, scrubbed of credentials, to `web.jsonl` there; the run log
shows them as sites visited and the run record counts them. Each refusal names a
stable reason code. Accepted exposure: a hostile page or search result can at most
learn the question being researched and shape the report, and later briefs already
treat reports as untrusted text.

Codex engine. A Codex run (`codex exec --json`) is isolated differently, and more
weakly. It gets its own Codex home and `HOME` in its run folder, so no user config,
rules, skills, MCP server, or ChatGPT connector loads; every setting is passed with
`-c` so the office's `.codex/config.toml` cannot loosen it; approvals are never
prompted; and its sandbox (`workspace-write`, network off, `/tmp` and `$TMPDIR`
excluded) lets direct writes and patches land only in the run's workspace. `fo` is
allowed by the run's execpolicy and runs outside that sandbox under the same run marker,
which is how it writes reports. **Read confinement for Codex is command-based, not
path-based like the Claude hook:** a forbidden-command list (cat, head, sed, grep,
python, curl, git, the shells, and others) stops the usual readers, but `ls` can list
file names anywhere on disk, and any reader the list misses can print any file the user
can read; the gate found `nl` printing a key in `secrets/`. For that reason the Codex
engine ships turned off (`[serve.engines.codex] enabled = false` unless office.toml
says otherwise), and Claude Code stays the recommended engine. Codex has no budget
flag: its runs are bounded only by `run_timeout_minutes`, and the budget is recorded
for information. The gate is in
[research providers](docs/development/research-providers.md#codex-isolation).

Accepted risk: reports, corrections, and decisions are fed back into later briefs,
so text planted in provider data or an earlier report can steer later advice. The
run boundary removes the exfiltration channels (MCP servers, web tools at every
level that reads household data, network commands, reads outside the office), and
the page renders report text as elements,
never HTML, so stored text cannot run in the browser. Market commands reach only
their fixed provider hosts.

## Third parties

| Service | Data received when used |
|---|---|
| Anthropic or OpenAI | Office content included in an advisor session's context |
| Anthropic (companion app chat) | The brief, reports, and command output a run reads, per run |
| OpenAI (companion app chat, Codex engine) | The same, for a Codex run |
| OpenAI cloud agents | The entire tracked office checkout when connected |
| Schwab | Authentication information and account or market-data requests |
| SimpleFIN | Access credentials and requested account time windows |
| AlphaVantage | API key, tickers, and requested data functions |
| SEC EDGAR | Filing or financial-data queries and the configured User-Agent |
| FRED | Series queries and any configured API authentication |
| Exa | API key and search queries |
| Firecrawl | API key and the URLs fetched through it |
| Google Gemini | API key and deep research questions |
| Fetched websites | A GET request with a family-office User-Agent for each direct fetch |
| GitHub | Public code; tracked private office files only when its remote is configured |

Research provider keys live in `secrets/<provider>.json` at 0600, written by
`fo connect` only after one validating call; advisor runs cannot run `fo connect`.
`fo research fetch` refuses URLs with credentials, non-HTTP schemes, localhost,
`.ts.net`, and hosts resolving to loopback, link-local, private, CGNAT, or ULA
addresses, rechecking every redirect, so a run cannot reach `fo serve` or the
tailnet through it. A DNS answer that changes between that check and the
connection is not caught. Research text is returned with `untrusted: true` and
scrubbed; see [research providers](docs/development/research-providers.md).

Provider and web text is untrusted data, never an instruction source. A Git ignore
rule does not remove earlier commits. If a secret was committed, rotate it and
address history exposure separately; the legacy history-rewrite warning still
applies. Never automatically rewrite or force-push the user's office history.

## Token lifecycle and offline work

Schwab refresh tokens expire after seven days. Doctor warns within 48 hours of
expiry. Reauthentication uses the browser flow; expiry is never reset merely
because a local file was copied. SimpleFIN access URLs are bearer credentials.
Neither credential belongs in a cloud environment.

Read-only mode avoids providers, cache writes, and index writes. It can still
read the tracked office facts. Source text is scrubbed for credential URLs and
long account-number-like strings, but this is not a general anonymizer. Review
any report before sharing it outside the private office.

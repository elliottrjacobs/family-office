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

### Advisor runs

Chat starts one headless Claude Code run at a time in the office directory. A run
loads only the office's project settings plus a run profile: no user settings or
hooks, an empty strict MCP configuration, only the Bash, Read, Write, Edit, and
Task tools, `--permission-mode dontAsk` with every permission prompt denied, and a
budget cap and time limit. Its environment carries only what login needs, with
`FO_SERVE_RUN` set so `fo` refuses other offices and the setup, credential, sync,
commit, schedule, notify, migrate, reindex, and serve commands whatever the flag
order. A PreToolUse hook (`fo.serve.guard`) is the last word on every tool call,
worker agents included: only plain `fo` commands with no pipes, redirects, or
substitution; reads inside the office outside `secrets/`, `cache/`, `imports/`,
`medical/`, `.git/`, the store, and the lock; and writes only under `reports/`.
It exists because a skill's own `Read` permission and read-only shell commands
otherwise reach files outside the office. The runner never passes
`bypassPermissions`. Run records and event logs live in `cache/serve/runs/` at
0600 in a 0700 directory and never hold environment, cookie, or token values.

Accepted risk: reports, corrections, and decisions are fed back into later briefs,
so text planted in provider data or an earlier report can steer later advice. The
run boundary removes the exfiltration channels (MCP servers, web tools, network
commands, reads outside the office), and the page renders report text as elements,
never HTML, so stored text cannot run in the browser. Market commands reach only
their fixed provider hosts.

## Third parties

| Service | Data received when used |
|---|---|
| Anthropic or OpenAI | Office content included in an advisor session's context |
| Anthropic (companion app chat) | The brief, reports, and command output a run reads, per run |
| OpenAI cloud agents | The entire tracked office checkout when connected |
| Schwab | Authentication information and account or market-data requests |
| SimpleFIN | Access credentials and requested account time windows |
| AlphaVantage | API key, tickers, and requested data functions |
| SEC EDGAR | Filing or financial-data queries and the configured User-Agent |
| FRED | Series queries and any configured API authentication |
| GitHub | Public code; tracked private office files only when its remote is configured |

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

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
| Web search and fetch in advisor chats, on by default, including chats that read household data | [Advisor runs](#advisor-runs), "Web access" |
| The onboard interview writing `profile/` from a chat | [Advisor runs](#advisor-runs), "The onboard interview" |
| Sync started from the page (`POST /api/sync`) | [Advisor runs](#advisor-runs), "Sync from the app" |
| Research provider keys in the per-machine credentials folder | [Third parties](#third-parties), "Research provider keys" |
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
last-seen time in the per-machine credentials folder's `devices.json` at 0600 inside a 0700
directory outside the office. Pairing codes are eight characters, held only in memory,
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

Chat starts a headless Claude Code run in the office directory for each conversation
that is answering, up to `[serve] parallel_runs` at once (three by default, eight at
most); one conversation takes one turn at a time. Each run is its own process with
its own budget cap, time limit, fetch counter, and web log, and the rules below apply
to each alike. Their `fo` commands take the office lock in turn: a run starts with
`FO_LOCK_WAIT` set, so a command waits up to twenty seconds for the lock instead of
failing, and two runs are never given the same report to write. A run
loads only the office's project settings plus a run profile: no user settings or
hooks, an empty strict MCP configuration, only the Bash, Read, Write, Edit, and
Task tools (plus WebSearch and WebFetch when web is on for the chat, below), `--permission-mode dontAsk` with every permission prompt denied, and a
budget cap and time limit. Its environment carries only what login needs, with
`FO_SERVE_RUN` set so `fo` refuses other offices and the setup, `config set`,
credential, sync, commit, schedule, notify, migrate, reindex, and serve commands,
`corrections retire`, and `journal close`, `reopen`, and `judge`, whatever the flag
order or `--` separators. A run may add corrections and decisions but never retire
or settle the owner's. A PreToolUse hook (`fo.serve.guard`) is the last word on
every tool call, worker agents included: only plain `fo` commands with no pipes,
redirects, or substitution; reads inside the office outside `secrets/`, `cache/`,
`imports/`, `medical/`, `.git/`, the store, and the lock; and writes only under
`reports/` (and `profile/` for the onboard interview, below), never to a hidden file
or folder there, which `fo commit` also refuses to publish.
It exists because a skill's own `Read` permission and read-only shell commands
otherwise reach files outside the office. The runner never passes
`bypassPermissions`. Run records and event logs live in `cache/serve/runs/` at
0600 in a 0700 directory and never hold environment, cookie, or token values.

Web access. `[serve] web` in `office.toml` sets the policy, and each chat has its
own switch beside the message box:

| `web` | Chats at level `none` | Chats at `household` or `full` |
|---|---|---|
| `on` (the default) | web on, isolated from household data | web on, with the limits below |
| `isolated` (the only rule through 2.0.0b1) | web on, isolated from household data | web off |
| `off` | web off | web off |

The default changed because an advisor that answers tax, estate, or planning
questions from the household's own figures also has to check current law, limits,
and prices; without the web those answers rest on what the model remembers. The
cost is real and stated here: in a chat that reads household data with web on,
web and household data meet in one run. A page the advisor fetches, or text planted
in provider data or an earlier report, could instruct the model to put household
facts into a later search query or URL, where the search provider or the fetched
site would see them. The run cannot send data any other way: it has no shell
network commands, no MCP server, and no other tool. What limits this path:

- Every search query and fetch URL is logged before it is sent and listed in the
  chat ("Looked up on the web"), so a disclosure is visible afterward.
- In a chat that reads the household, a search query is refused when it holds nine
  or more digits in a row or a Social Security number as written
  (`web_identifier`), and a query over 400 characters or a URL over 600 is refused
  (`web_too_long`), so one request cannot carry a file.
- Fetches stop at `web_fetch_cap` per turn (default 20) and pass the same deny list
  as `fo research fetch`.
- The advisor is told to treat fetched text as untrusted evidence, never as
  instructions, and never to put names, account numbers, or exact balances in a
  search or URL. This is an instruction to a model, not an enforcement.
- Only the Claude Code engine gets web in a chat that reads the household. Codex
  confines reads by command rather than by path, so there the previous rule holds.

To go back to the previous rule, choose "Only without household data" under Web
access in the Mac app's Settings > Advanced, or run `fo config set serve.web
isolated`; to turn web off everywhere, choose "Never" there or run `fo config set
serve.web off`. The Settings control writes the same key through `fo config set`.
Either takes effect on the next message.

At level `none` a web chat stays isolated as before: the hook denies reads of
`data/`, `profile/`, and `notebook/`, including symlink targets. Skills,
instructions, and reports stay readable. Known residual: earlier reports may
contain household figures, which a web run can read and disclose. User prompts and
mandatory context can also contain household information; the guard does not scrub
these inputs.

Isolated web runs allow market commands, research, and scoped
report/journal/correction bookkeeping; `fo start` and `fo brief` require explicit
`--level none` (or `--level=none`). Other household commands remain denied. Reports
can be read and written for drafting, parts, and verification. The hook denies
WebSearch and WebFetch in non-web runs. The CLI enforces the same command allowlist
and research gate for both runners whenever `FO_SERVE_RUN` is set, refusing every
`fo research` subcommand outside web runs. Research queries
(including deep questions) and URLs use the same logging boundary as
WebSearch/WebFetch; a missing run folder denies access. Put the research query or
URL before subcommand options.

The hook and CLI check fetch URLs against `fo.netguard`: HTTP(S) only, no credentials,
localhost, tailnet names, or hosts resolving to non-public addresses. WebFetch and
`fo research fetch` share `web_fetch_cap` (default 20), counted per turn of a chat
so a long conversation can keep looking things up. Its counter
and scrubbed query/URL log, `web.jsonl`, live in the run folder, which the run
cannot read or write. The run log shows accepted queries and URLs; each refusal
has a stable reason code. Hostile web evidence can shape reports, which later
briefs treat as untrusted text.

Claude sets `FO_SERVE_HOOK_ACTIVE=1`: its hook counts and logs research calls, and
the CLI validates them without counting or logging again. Codex leaves that flag
unset, so the CLI counts and logs its research calls. The hook validates every
`&&` segment before any segment consumes a fetch or logs web use.

The onboard interview. The Onboard advisor runs as a chat and is the one run that
may write under `profile/`, because filling in the authored profile from the
owner's answers is its purpose: its permission rules allow edits there, and the hook
allows `profile/` writes only when the run's advisor is `onboard`. It still cannot
write `office.toml`, `data/`, `notebook/`, hidden files, or anything outside the
office, and cannot run setup, auth, sync, or commit. After each reply the server
commits `profile/` alone to the office's local Git history ("Update the profile from
the onboard interview"), so every change the interview made can be reviewed and
reverted. The interview is not available with Codex.

Sync from the app. `POST /api/sync` runs `fo sync` with no options as a child of the
server, exactly as the command runs in a terminal: it uses the credentials `fo auth`
stored, holds the office lock, and obeys the writer-host rule. The request needs the
same session and same-origin checks as every other write, does not exist under
`--read-only`, is refused while an advisor is working, and answers with each
provider's status and `fo`'s own reason text, never a provider's error. A message
sent to an advisor while a sync runs is queued and starts when the sync ends. After
a sync the server commits `notebook/`, `reports/`, and `data/` to the office's local
Git history, as the scheduled job's `--commit` does; unrelated uncommitted changes
leave that commit undone.

Automatic sync. While `fo serve` runs without `--read-only`, it syncs on its own when
any connected provider's last complete sync is older than `[serve] auto_sync_hours`
(six by default). This is the same `fo sync --if-writer` child process, so it calls
providers with the stored read-only credentials without a click, only on the writer
host, and never while an advisor is answering. A sync that fails or ends incomplete
is retried after half an hour, then one hour, doubling up to the interval, so a broken
connection is not called repeatedly. Turn it off under Account sync in the Mac app's
Settings > Advanced or with `fo config set serve.auto_sync false`; Sync now still
works. A paired
phone can start it. It reads from providers only; nothing in family-office can trade
or move money.

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
Codex never gets web in a chat that reads the household, whatever `[serve] web` says.
Codex's built-in web search at level `none` appears as `web` events in the run log,
but it bypasses `web.jsonl`, the fetch cap, and the netguard URL checks; this remains
a residual limitation alongside the read limitations.

Accepted risk: reports, corrections, and decisions are fed back into later briefs,
so text planted in provider data or an earlier report can steer later advice. The
Claude run boundary blocks MCP servers, arbitrary network commands, reads outside
the office, and web tools and `fo research` in non-web runs. Isolated web runs
instead block household folders and commands as described above; a web chat that
reads the household relies on the limits under "Web access". The Codex limitations
above still apply. The page renders report text as elements,
never HTML, so stored text cannot run in the browser. Market commands reach only
their fixed provider hosts.

## Third parties

| Service | Data received when used |
|---|---|
| Anthropic or OpenAI | Office content included in an advisor session's context |
| Anthropic (companion app chat) | The brief, reports, and command output a run reads, per run |
| OpenAI (companion app chat, Codex engine) | The same, for a Codex run |
| OpenAI cloud agents | The entire tracked office checkout when connected |
| SimpleFIN | Access credentials and requested account time windows |
| Plaid (only if you connect it) | Your own client ID and secret, Item access tokens, an opaque per-office user id, and account, holdings and transactions requests |
| AlphaVantage | API key, tickers, and requested data functions |
| SEC EDGAR | Filing or financial-data queries and the configured User-Agent |
| FRED | Series queries and any configured API authentication |
| Exa | API key and search queries |
| Firecrawl | API key and the URLs fetched through it |
| Google Gemini | API key and deep research questions |
| Fetched websites | A GET request with a family-office User-Agent for each direct fetch |
| GitHub | Public code; tracked private office files only when its remote is configured |

Research provider keys live in `<provider>.json` in the per-machine credentials
folder at 0600, written by `fo connect` only after one validating call; advisor runs cannot run `fo connect`.
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

SimpleFIN access URLs are bearer credentials.
Plaid access tokens do not expire but grant read access to a linked institution
until the Item is removed in the Plaid Dashboard; with the user's own client ID and
secret, which live in `keys.toml`, they are the user's to protect. None of these
credentials belongs in a cloud environment.

Plaid Link runs on a page that `fo auth plaid` serves at a random path on
`127.0.0.1`. The page answers only its own host and origin, loads Link from
`cdn.plaid.com` under a Content Security Policy that admits only nonce-tagged scripts
(styles are inline, as Plaid's injected styles require), accepts one result, logs no
requests, and stops when Link finishes, closes, or after 15 minutes. The public
token it receives is exchanged with Plaid directly and never stored or printed.

Read-only mode avoids providers, cache writes, and index writes. It can still
read the tracked office facts. Source text is scrubbed for credential URLs and
long account-number-like strings, but this is not a general anonymizer. Review
any report before sharing it outside the private office.

## Credential storage and synced offices

The office may live in iCloud Drive or another synced folder. Credentials live
outside it, per machine, under `~/Library/Application Support/FamilyOffice/credentials`
on macOS or `${XDG_DATA_HOME:-~/.local/share}/family-office/credentials` elsewhere.
`FO_CREDENTIALS_HOME` overrides that base. A random `[office].id` in `office.toml`
selects a 0700 subdirectory; credential files are 0600. The id is safe to sync;
each machine must connect separately. This uses files, not macOS Keychain;
Keychain integration remains possible future hardening.

On `fo init`, `fo setup`, `fo doctor --fix`, writable `fo serve`, or a
credential-writing command, fo-managed legacy office `secrets/` files move to
that folder; reads never migrate. An existing destination wins: identical office
copies are removed; differing copies
stay in both locations for manual resolution. `fo doctor` flags office leftovers
and local credential permissions. Keep `secrets/` ignored and blocked by the
pre-commit hook as defense for older offices.

Claude's guard denies direct reads outside the office. Codex's command-based
read confinement does not protect the external credentials directory any more
than it protected `secrets/`. Its engine remains disabled by default.

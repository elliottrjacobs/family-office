# Family Office v2 — Implementation Plan

**Status:** Draft for Elliott's review. Not yet approved for implementation.
**Audience:** The implementing agent (Claude Code or Codex) and Elliott.
**Supersedes:** `elliottrjacobs/family-office` v1 (27 prompt-heavy skills, JSON-file profile, `claude -p` fan-out). v1 is reference material only; nothing is carried over verbatim.

---

## 0. How to use this document

For the implementing agent:

1. Read all of it before writing code. Section 12 (Open decisions) lists items Elliott must answer first; do not guess at them.
2. Build in the phase order in Section 11. Each phase ends with its acceptance checks passing and a short summary to Elliott. Do not start the next phase without a go-ahead.
3. One branch and one PR per phase. Keep commits small.
4. Never read, copy, or commit anything from a real `office/` directory. Use the fixture office in `tests/fixtures/office/` for everything.
5. When something in this plan turns out to be wrong or ambiguous, stop and ask rather than improvising around it.

---

## 1. Purpose

A persistent, centralized source of truth for the household's financial life (investments, cash, taxes, retirement and life goals, estate, business entities), with a set of AI advisors that reason over it — and a research toolkit that can also be used standalone with no household context at all.

The system must **compound**: every decision, report, and correction should make the next one cheaper and better.

### Principles (in priority order)

1. **Look, never touch.** The system reads financial accounts. It has no code path to place a trade or move money, and none will be added.
2. **One home for every fact.** Each fact lives in exactly one place. No parallel copies, no derived files that can go stale.
3. **Fat data and code, thin prompts.** Anything deterministic (fetching, arithmetic, categorization rules, thresholds) is Python. LLMs are spent only on judgment.
4. **Context is a dial.** Every advisor takes `none | household | full` and has a sensible default. Research defaults to `none`.
5. **Write down why, and what would prove it wrong.** No recommendation is filed without a thesis and an invalidation condition. A scheduled job checks them.
6. **The boring work never needs an LLM.** Sync, categorize, review, health-check all run as plain code on a schedule.
7. **Read your own last note first.** Repeat work on the same subject is a delta, not a fresh start.

### Non-goals for v2.0

- Any write action against a brokerage, bank, or card.
- A web or mobile UI. (Slack delivery of the briefing is optional; see Open decisions.)
- Multi-user / multi-household.
- Medical/EOB processing as a first-class advisor (folder + bookkeeper read access only; see Open decisions).

---

## 2. Two repositories

| | `family-office` (public) | `office` (private) |
|---|---|---|
| Contains | Python package `fo`, skills, playbook checklists, schema, migrations, example configs, tests, docs | Authored profile docs, config with real keys, the SQLite store, the notebook, reports, imports, statements, medical folder |
| Git | Public on GitHub, CI on every push | Private repo with full history (this is a feature: edits to the IPS are versioned) |
| Relationship | Installed into `office/` as a dependency (`uv add`), pinned to a tag | Created by `fo init`, which writes the layout and example files |

Structural privacy: personal data never has a path inside the public repo, so there's nothing for a lint to catch. CI still runs gitleaks as belt-and-braces.

---

## 3. Public repo layout (`family-office`)

```
family-office/
├── pyproject.toml              # uv-managed; python >=3.11; console script `fo`
├── README.md
├── SECURITY.md
├── CLAUDE.md                   # thin: what fo is, how skills must behave, permission model
├── AGENTS.md                   # GENERATED from CLAUDE.md by `scripts/gen_agents.py` (see Open decisions)
├── .claude/
│   ├── settings.json           # allow: Bash(fo *), Read, Write(office/reports/**), Write(office/notebook/**); deny: everything else in Bash
│   ├── skills/                 # one folder per skill, SKILL.md <= 3 KB each
│   └── agents/                 # sub-agent definitions used only by --deep
├── src/fo/
│   ├── cli.py                  # Typer app; every command supports --json
│   ├── config.py               # loads office/config.toml; resolves paths; never logs secrets
│   ├── store/
│   │   ├── db.py               # sqlite3 connection, WAL, migrations runner
│   │   ├── migrations/         # 0001_init.sql, ...
│   │   └── authored.py         # loads and validates office/profile/*.json|md
│   ├── providers/
│   │   ├── base.py             # Provider protocol: read-only by construction (no write methods exist)
│   │   ├── schwab.py           # schwab-py wrapper; token refresh; account suffix map from config
│   │   ├── simplefin.py
│   │   ├── alphavantage.py     # plain HTTP, not MCP
│   │   ├── edgar.py
│   │   ├── fred.py
│   │   └── cache.py            # TTL cache table in SQLite; all providers go through it
│   ├── sync/                   # pulls from providers into store; idempotent; logs to sync_log
│   ├── compute/                # networth, allocation, drift vs IPS, spend, goals progress, tax lots
│   ├── brief.py                # builds the household/full context brief
│   ├── notebook/               # decisions ledger, review, standing corrections, reports index
│   ├── playbooks/
│   │   ├── schema.py           # validates checklist YAML
│   │   ├── scorer.py           # computes mechanical criteria; marks judgment criteria for the LLM
│   │   └── library/            # lead-edge-eight.yaml, compounder.yaml, lynch.yaml, ...
│   ├── doctor.py               # env, keys, token expiry, DB integrity, last sync age
│   └── init.py                 # scaffolds a new office/
├── scripts/
│   ├── gen_agents.py           # CLAUDE.md + skills -> AGENTS.md / .agents (if Codex parity is kept)
│   └── migrate_v1.py           # one-shot import from a v1 checkout (Phase 6)
├── tests/
│   ├── fixtures/office/        # a complete fake office with fake data
│   └── ...
├── docs/
│   ├── explainers/             # the three ELI5 HTML files already produced
│   └── skill-authoring.md
└── .github/workflows/ci.yml   # ruff, pytest, gitleaks, skill size lint
```

## 4. Private office layout (created by `fo init`)

```
office/
├── config.toml                 # keys, account suffix map, provider toggles, model routing — chmod 600
├── profile/                    # AUTHORED. Human-edited, git-tracked.
│   ├── household.md            # who's in the family, entities, employers, residency (prose + a small JSON block)
│   ├── ips.json                # investment policy: bands, limits, prohibited, rebalancing rules
│   ├── goals.json              # each goal: name, target amount, target date, funding account, priority
│   ├── tax.json                # filing status, state, elections, carryforwards, known bracket
│   ├── accounts.json           # account registry: id, institution, type (taxable/IRA/401k/529/...), owner, provider mapping
│   └── corrections.md          # standing corrections from the user ("stop doing X", "always Y")
├── store.sqlite                # DERIVED. Machine-written only. Git-ignored.
├── notebook/                   # git-tracked
│   ├── decisions.jsonl         # append-only ledger (see 6.3)
│   └── reviews/                # weekly review outputs, YYYY-MM-DD.md
├── reports/                    # git-tracked; every advisor output; frontmatter-indexed
├── imports/                    # drop zone for statements/CSVs; consumed by fo sync; git-ignored
├── medical/                    # git-ignored; out of scope for v2.0 except as a folder
└── .gitignore                  # store.sqlite, imports/, medical/, config.toml
```

---

## 5. Store

### 5.1 Authored (files)

Validated on load by `authored.py` with clear errors. Schemas live in `src/fo/store/schemas/*.json` (JSON Schema). `fo doctor` validates them.

### 5.2 Derived (SQLite, WAL mode)

Minimum tables for v2.0. The implementing agent may add columns but should not add tables without noting why.

```
accounts        (id TEXT PK, institution, type, owner, provider, provider_ref, currency, active)
positions       (as_of DATE, account_id, symbol, qty, price, value, cost_basis, lot_id NULL, source)   -- snapshot per sync
transactions    (id TEXT PK, account_id, date, amount, description, category, subcategory, symbol NULL, source, raw JSON)
balances        (as_of DATE, account_id, cash, total, source)
prices          (symbol, as_of TIMESTAMP, price, source)                                               -- cache
fundamentals    (symbol, as_of TIMESTAMP, payload JSON, source)                                        -- cache
filings         (symbol, accession, form, filed DATE, url, payload JSON)                                -- cache
macro_series    (series_id, as_of DATE, value, source)                                                 -- cache
cache_meta      (key TEXT PK, fetched_at, ttl_seconds)
sync_log        (id, started, finished, provider, status, rows, message)
decisions       (mirror of decisions.jsonl for querying; jsonl is canonical)
reports_index   (path TEXT PK, kind, subject, created, model, context_level, summary, frontmatter JSON)
```

Rules:
- `positions` and `balances` are append-only snapshots keyed by `as_of`; "current" = latest `as_of`.
- Every provider call goes through `cache.py`. Default TTLs: prices 15 min during market hours / until next open otherwise; fundamentals 24 h; filings 24 h; macro 24 h.
- Categorization of transactions is rule-based (`office/profile/categories.yaml`, user-editable) with an optional Haiku fallback for uncategorized rows, batched, off by default.

---

## 6. CLI surface (`fo`)

Every command: `--json` for machine output, human table otherwise; exit code non-zero on failure; never prints secrets. **There are no write verbs against any provider.** The `Provider` protocol has no write methods, so this is enforced by construction, not by convention.

### 6.1 Setup and health
```
fo init [PATH]                    scaffold office/, write example configs and schemas
fo doctor                         python, deps, config validity, key presence, Schwab token expiry, DB integrity, last-sync age, authored-file schema validation
fo auth schwab                    interactive OAuth; stores token 0600
fo auth simplefin                 claim setup token -> access URL
```

### 6.2 Sync
```
fo sync [--provider schwab|simplefin|imports|all] [--dry-run]
fo sync status                    last run per provider, row counts, errors
```

### 6.3 Questions with numbers (compute)
```
fo networth [--as-of DATE] [--by account|type|owner]
fo positions [--account ID] [--symbol SYM]
fo allocation                     current vs IPS bands; drift flagged
fo spend --month YYYY-MM [--category X]
fo cashflow --months N
fo goals                          progress per goal: on track / behind by X
fo lots SYM                       tax lots with gain/loss and holding period
fo quote SYM [SYM...]
fo fundamentals SYM
fo filings SYM [--form 10-K|10-Q|DEF 14A|4]
fo macro SERIES_ID [--since DATE]
```

### 6.4 Context brief
```
fo brief --level none|household|full [--for SYM]
```
- `none` prints nothing (exists so skills can call it unconditionally).
- `household` (~400 tokens): IPS constraints, held symbols with weights, cash available, top open decisions. `--for SYM` adds "you hold X% of SYM, lots: ...".
- `full`: household + goals with status + tax picture + last 90 days cash flow + `corrections.md`.

### 6.5 Notebook
```
fo journal add --subject SYM|goal|portfolio --action buy|sell|hold|rebalance|other --thesis "..." --invalidate "..." [--conviction 1-5] [--source skill-name]
fo journal list [--open] [--subject X]
fo journal close ID --outcome "..." 
fo review                         checks every open decision's invalidation against current data; writes notebook/reviews/YYYY-MM-DD.md; prints breaches
fo prior SYM [--kind research|score]   returns the latest prior report(s) for a subject, frontmatter + path
fo reports index                  rebuilds reports_index from frontmatter
fo corrections add "..."           appends to corrections.md with date
```

`decisions.jsonl` line schema:
```json
{"id":"2026-09-11-nvda-1","date":"2026-09-11","subject":"NVDA","action":"buy","thesis":"...","invalidate":"revenue growth < 20% YoY for two quarters, or price < 95","price_at":123.45,"conviction":4,"context_level":"household","source":"/research","status":"open","closed":null,"outcome":null}
```
`fo review` parses `invalidate` for machine-checkable clauses (price thresholds, growth thresholds via fundamentals cache) and flags the rest as "needs judgment" for the weekly review skill.

### 6.6 Playbooks
```
fo playbooks list
fo score SYM --playbook NAME [--playbook NAME2]   computes mechanical criteria, emits evidence for judgment criteria; never writes a verdict
fo score-portfolio --playbook all-weather        portfolio-level playbooks
```

Checklist YAML schema (`playbooks/library/*.yaml`):
```yaml
name: lead-edge-eight
title: Lead Edge Eight
attribution: Mitchell Green, Lead Edge Capital (paraphrased public framework)
scope: company            # company | portfolio
criteria:
  - id: revenue_scale
    text: Real revenue scale
    kind: mechanical       # mechanical | judgment
    metric: revenue_ttm    # resolved by scorer from fundamentals
    op: ">="
    threshold: 10000000
  - id: customer_concentration
    text: No single customer that can sink it
    kind: judgment
    evidence: [filings:10-K:customer concentration, fundamentals:top_customer_pct]
verdict:
  format: "score/8"
```
Thresholds are user-tunable in `office/playbooks/overrides/*.yaml` (merged over library defaults).

### 6.7 Report conventions
Every skill writes to `office/reports/<kind>/<subject>/<YYYY-MM-DD>-<slug>.md` with frontmatter:
```yaml
kind: research | score | cio | cfo | tax | plan | review | briefing | ...
subject: NVDA
date: 2026-09-11
model: <model used for synthesis>
context_level: none|household|full
playbooks: [lead-edge-eight]
prior: reports/research/NVDA/2026-06-02-....md   # if a delta
summary: one line
decision_ids: [...]                               # journal entries created
```
`fo reports index` keeps `reports_index` current; `fo prior` reads from it.

---

## 7. Skills (Claude Code)

### 7.1 Rules for every skill
- `SKILL.md` ≤ 3 KB. CI fails otherwise.
- Frontmatter: `name`, `description`, `default_context: none|household|full`, `allowed_context: [...]`, `model: haiku|sonnet|opus` (routing hint), `disable-model-invocation` where appropriate.
- The only tools a skill needs are `Bash(fo *)`, `Read`, and `Write` into `office/reports/` and `office/notebook/`. No skill contains provider names, API priority, or thresholds.
- Skeleton every skill follows:
  1. `fo brief --level <resolved level> [--for SUBJECT]`
  2. `fo prior SUBJECT` — if a prior exists, this run is a delta.
  3. `fo <compute commands>` as needed.
  4. Reason. Write the report with frontmatter.
  5. If the output contains a recommendation: `fo journal add ...` with thesis + invalidation. Reference the ids in frontmatter.
  6. End with one line asking the user for a correction, and if given, `fo corrections add`.
- `--deep` is the only way to fan out. It spawns the sub-agents in `.claude/agents/` via the native Task tool (never `claude -p` subprocesses). Off by default everywhere.
- Shared behavior lives in `.claude/skills/_shared/` files that skills reference with `@`; nothing is copy-pasted between skills.

### 7.2 Core roster (10)

| Skill | Default context | Model | Notes |
|---|---|---|---|
| `/research SYM [--lens semis\|biotech\|energy\|financials\|...] [--playbooks a,b] [--deep]` | none | sonnet (opus with `--deep`) | Lenses are short `@` includes, not separate skills. Reads prior; produces delta when one exists. |
| `/diligence SYM` | none | sonnet | Management: capital allocation, alignment, incentives, candor. Uses `fo filings --form DEF 14A,4`. |
| `/scout [--kind equities\|alts\|funds] [--criteria ...]` | household | sonnet | Screens and ideas; excludes held names. |
| `/macro [--focus rates\|inflation\|credit\|...]` | none | sonnet | Dated read; compared to its own prior. |
| `/cio [--playbook all-weather] [--deep]` | full | opus | Allocation vs IPS, drift, rebalance suggestions. Every suggestion journaled. |
| `/cfo` | full | sonnet | Cash, spend, debt, insurance. Monthly picture. |
| `/tax` | full | opus | TLH, account filling, timing, bracket management. Deadline list with $ impact. |
| `/plan` | full | sonnet | Goal progress and what-it-takes. |
| `/journal` | none | haiku | Structured entry via `fo journal add`; asks for the invalidation line if missing. Also the corrections entry point. |
| `/briefing` | household | sonnet, one call | Reads overnight sync + last review; no web search; no fan-out. |

### 7.3 Playbooks (standalone slash-commands, one shared scorer)
Each is a ~1 KB skill: `fo score SYM --playbook X`, read the evidence, decide the judgment criteria, write the scorecard, journal if asked. Initial library: `lead-edge-eight`, `compounder`, `lynch`, `fisher`, `greenblatt`, `piotroski`, `powers`, `marks` (cycle, scope: market), `all-weather` (scope: portfolio). Order of implementation is an Open decision.

### 7.4 Specialists (standalone)
`/options` (household), `/technicals` (none), `/risk` (full, always), `/realestate` (household), `/ventures` (full), `/estate` (full). Same skeleton; no fan-out by default.

### 7.5 Sub-agents (used only by `--deep`)
Kept small and generic: `fundamentals-analyst`, `competitive-analyst`, `valuation-analyst`, `risk-analyst`, `sentiment-analyst`. Each returns a bounded structured block the parent skill assembles. Model: sonnet.

---

## 8. Scheduling (Mac Mini, launchd)

`fo init` writes plists to `office/launchd/` (user installs them):

| Job | Cadence | LLM? |
|---|---|---|
| `fo sync` | nightly 02:00 + after imports drop | no |
| `fo doctor` | daily; non-zero exit → notification | no |
| `fo review` | weekly Sunday | no (writes breaches; the `/review` skill is run by hand if judgment is needed) |
| `fo reports index` | after each sync | no |
| `/briefing` | optional weekday 07:00 | yes, one Sonnet call, only if Elliott opts in (Open decision on delivery) |

---

## 9. Security and permissions

- `.claude/settings.json`: allow `Bash(fo *)`, `Read`, `Write(office/reports/**)`, `Write(office/notebook/**)`, `Task`; deny `Bash(python*)`, `Bash(pip*)`, `Bash(curl*)`, `Bash(*schwab*)`, `Edit(src/**)` inside an office session. Development sessions on the public repo use a different, broader settings file.
- Secrets only in `office/config.toml` (0600) and the Schwab token file (0600). `fo` never echoes them; `--json` output redacts anything under `config.secrets`.
- `Provider` protocol has no write methods. A test asserts via introspection that no provider module defines a method matching `/order|trade|transfer|withdraw|deposit|place|submit/`.
- README privacy claim is accurate: data is stored locally; at query time, prompt content (which may include holdings) is sent to the configured LLM provider, and tickers/queries are sent to configured data providers. SECURITY.md lists every third party and what it receives.
- CI: ruff, pytest, gitleaks, skill size lint, "no path under `office/` is tracked" lint.
- No `claude -p` anywhere.

---

## 10. Cost policy

- Model routing in `office/config.toml` (`[models] synthesis="opus" research="sonnet" extract="haiku"`), read by skills via `fo config models --json`. One place to update when models change.
- Fan-out is opt-in. Default `/cio` is one Opus call over precomputed numbers; `/cio --deep` is the six-agent version.
- Deltas over rewrites: `fo prior` before any research; the prompt asks for "what changed" when a prior exists.
- Caching: all provider reads TTL-cached; `fo sync` is the only thing that hits Schwab/SimpleFIN.
- Providers dropped for v2.0 unless Elliott reinstates them: Gemini deep research, Apify (Reddit), context7 MCP, AlphaVantage MCP (replaced by direct HTTP).

---

## 11. Phases

### Phase 0 — Scaffold (½ day)
- `pyproject.toml` (uv), `src/fo/cli.py` with `fo --version`, `fo init`, `fo doctor` (stub), tests skeleton, CI green, `tests/fixtures/office/` with fake data covering every authored file.
- **Accept:** `uv run fo init /tmp/office && uv run fo doctor` exits 0 on the fixture; CI green.

### Phase 1 — Store + sync + doctor (1 week)
- Migrations, authored loaders + JSON Schemas, providers (schwab, simplefin, imports-CSV), cache, `fo sync`, full `fo doctor`, `fo auth *`.
- **Accept:** against fixture providers (recorded responses), `fo sync` is idempotent (running twice adds zero rows); `fo doctor` catches: missing key, expired token, stale sync, invalid ips.json; provider write-method introspection test passes.

### Phase 2 — Compute + brief (3–4 days)
- `networth`, `positions`, `allocation`, `spend`, `cashflow`, `goals`, `lots`, `quote`, `fundamentals`, `filings`, `macro`, `brief`.
- **Accept:** golden-file tests for each command on the fixture; `fo brief --level household` ≤ 500 tokens on the fixture; `--json` output for every command validates against a schema.

### Phase 3 — Notebook (3 days)
- `journal add/list/close`, `review`, `prior`, `reports index`, `corrections add`, frontmatter parser.
- **Accept:** a fixture decision with `invalidate: "price < 100"` is flagged by `fo review` when the cached price is 95; `fo prior NVDA` returns the newest fixture report.

### Phase 4 — Core skills (1 week)
- `_shared/` includes; the ten core skills; `.claude/settings.json` for office sessions; `docs/skill-authoring.md`.
- **Accept:** each SKILL.md ≤ 3 KB (CI); a scripted dry run of `/research ACME` against the fixture office produces a report with valid frontmatter and a journal entry; a second run produces a delta referencing the first.

### Phase 5 — Playbooks + specialists (1 week)
- YAML schema, scorer, library of nine, override merge, the nine playbook skills, six specialist skills.
- **Accept:** `fo score ACME --playbook lead-edge-eight --json` returns every criterion with `pass|fail|borderline|judgment` and evidence pointers; overrides change thresholds without editing the library.

### Phase 6 — Scheduling + briefing + migration (3–4 days)
- launchd plists from `fo init`; `/briefing`; `scripts/migrate_v1.py` (v1 `profile/*.json` → authored files + accounts; v1 `journal/` → `decisions.jsonl`; v1 `reports/` → `reports/` with generated frontmatter); `gen_agents.py` if Codex parity is kept.
- **Accept:** migration runs on a v1 fixture checkout without error and `fo doctor` passes afterward; briefing runs with network off using cached data.

### Phase 7 — Docs + release (1–2 days)
- README (accurate privacy statement), SECURITY.md, the three ELI5 explainers under `docs/explainers/`, tag `v2.0.0`.

Rough total: 4–5 weeks of agent time at a deliberate pace, with review gates between phases.

---

## 12. Open decisions (Elliott to answer before Phase 0)

1. **Store:** SQLite only (recommended), or SQLite with a mirror to the existing Supabase on the Mini for Slack/mobile access later?
2. **Codex parity:** generate `AGENTS.md`/`.agents/` from `.claude/` now (adds `gen_agents.py` to every phase), or Claude Code only for v2.0 and revisit?
3. **Providers to keep:** Gemini deep research? Apify? Any MCP at all, or direct HTTP only? Plan assumes direct HTTP only.
4. **Bank aggregation:** SimpleFIN (assumed) vs Plaid.
5. **Playbook order:** which of the nine ship first? Plan assumes Lead Edge Eight first since it exists, then compounder, piotroski, greenblatt (mechanical-heavy, fastest to test), then the judgment-heavy ones.
6. **Briefing delivery:** local file only, or push to Slack via the existing bridge? If Slack, which channel, and does the Slack bridge run with the office permission profile?
7. **Medical:** folder only in v2.0 (assumed), or keep the v1 EOB-audit behavior as a `/records` specialist?
8. **Migration:** import v1 data (assumed yes), or start the private office empty and re-onboard?
9. **Model routing defaults:** `synthesis=opus, research=sonnet, extract=haiku` — confirm, or set Fable/Sonnet 5 names explicitly?
10. **Package layout:** is `office/` a sibling directory the public package points at via config, or a git repo that vendors the public package? Plan assumes sibling + `uv add` dependency.

---

## 13. Definition of done for v2.0

- All Phase acceptance checks pass in CI on the fixture office.
- A fresh clone + `fo init` + real keys reaches `fo doctor` green in under 15 minutes following README only.
- `/research`, `/cio`, `/tax`, and `/lead-edge` each produce a correctly indexed report on a real office, and `fo review` flags a deliberately breached fixture decision.
- No skill exceeds 3 KB; no provider has a write method; no `office/` path is tracked in the public repo; gitleaks clean across history.

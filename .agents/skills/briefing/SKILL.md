---
name: briefing
description: Morning Market Briefing. Spawns 4 parallel Sonnet research agents via CLI, then synthesizes with Opus for a concise daily market overview. Use for daily market intelligence and portfolio-relevant news.
disable-model-invocation: true
---

# /briefing — Morning Market Briefing (Sonnet Research → Opus Synthesis)

<!-- RESEARCH-TOOL-PRIORITY:BEGIN -->
## Research Tool Priority (MANDATORY)

**WebSearch is a LAST RESORT for structured data — never the first stop.** Use the right API for the data type:

- **Account positions / balances / transactions / orders (Schwab) →** `scripts/schwab/client.py` (read-only wrapper). Mutating methods (`place_order`, etc.) are blocked at the wrapper. Data lives only at Schwab — no fallback.
- **Stock quotes (live & EOD), options chains, price history / OHLC — for held AND unheld tickers →** **Schwab Market Data API** via `scripts/schwab/client.py` (`get_quote(s)`, `get_option_chain`, `get_price_history*`). **Fallback when Schwab unavailable / refresh-token expired:** AlphaVantage MCP (`GLOBAL_QUOTE`, `REALTIME_OPTIONS`, `TIME_SERIES_*`).
- **Stock fundamentals / ratios / P/E / earnings / income statements →** AlphaVantage MCP (`COMPANY_OVERVIEW`, `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`). **When rate-limited (25/day, response contains `"...rate limit..."`), switch to SEC EDGAR via Bash curl (XBRL Company Facts / Concept / Frames) — NOT WebSearch.**
- **SEC filings (10-K, 10-Q, 8-K, Form 4, 13F) / XBRL financials / insider trades / institutional holdings →** SEC EDGAR via Bash curl with `User-Agent` header.
- **Earnings transcripts / commodities / FX / crypto / technical indicators →** AlphaVantage MCP.
- **Treasury yields / CPI / Fed Funds / GDP / unemployment / mortgage rates / macro data →** FRED via WebFetch.
- **Qualitative research, sentiment, narratives, "why is X happening" questions, multi-source synthesis →** Gemini wrappers: `scripts/gemini/deep_research.py` for full agentic investigations, `scripts/gemini/fast.py` (Flash-Lite + Google Search grounding) for quick lookups. On Gemini 429/quota, retry fast with `--model gemini-3-flash`, then fall to WebSearch + WebFetch.
- **Reddit retail sentiment / comment threads (retail-driven names: NVDA, TSLA, crypto, memes) →** Apify `mcp__apify__trudax--reddit-scraper-lite`. Gemini fast (`scripts/gemini/fast.py`) covers surface-level sentiment only.
- **JS-heavy article extraction (Substack, blogs, mid-tier publishers when WebFetch returns garbage) →** WebFetch first, then Apify `mcp__apify__lukaskrivka--article-extractor-smart`. Does NOT bypass hard paywalls (Bloomberg/WSJ/FT) — find a free source instead.
- **Library / framework / SDK / API docs →** `context7` MCP (`resolve-library-id` → `query-docs`).
- **Same-day / breaking news / overnight recap →** WebSearch is correct here (only place it's the first stop).
- **Background news themes (24h delayed OK) →** NewsAPI via WebFetch.

**When you spawn sub-agents, they default to WebSearch unless told otherwise — pass this priority to every sub-agent prompt, especially the Schwab-first directive for quotes/options/history.** Schwab refresh token expires every 7 days; if `profile/api-keys.json` shows `schwab.tokens.refresh_token_expires_at` is past, the wrapper will fail and you should fall back to AlphaVantage with a warning. See `profile/api-guide.md` for the full reference table and examples.
<!-- RESEARCH-TOOL-PRIORITY:END -->

You are the Morning Briefing orchestrator for the Family Office. You coordinate 4 parallel Sonnet research agents and synthesize their output into a concise daily briefing.

## Trigger
Invoked with `/briefing`.

## Before You Begin

1. **Establish today's date**. This entire skill is date-dependent.
2. **Read holdings**: `profile/portfolio/holdings.json` (canonical)
3. **Read watchlist**: `profile/portfolio/watchlist.json`
4. **Read recent briefings** from `briefings/daily/` for continuity.

## Phase 1: Parallel Research (Sonnet)

Delegate research to 4 Sonnet agents for cost efficiency. Use the Bash tool to run each agent as a separate `Codex -p` process. Launch all 4 Bash calls IN PARALLEL in a single message.

For each Bash call:
- Use `--model Codex-sonnet-4-6`
- Use `--allowedTools "WebSearch,WebFetch,Bash"`
- Pipe the prompt via stdin using a heredoc (use `cat <<'EOF'` with single-quoted delimiter to prevent shell expansion)
- Capture output: `> /tmp/fo-briefing-{name}.md 2>/dev/null`
- Set Bash timeout to 300000 (5 minutes)
- Include today's date in every agent prompt
- Include this instruction in every agent prompt: *"Held-ticker prices are LIVE in the embedded holdings data (`holdings.json`, synced from Schwab Trader API — do not re-fetch). For UNHELD tickers, indices, futures, commodities, FX, and crypto, use WebSearch for same-day prices/news. SEC EDGAR via Bash curl for SEC filings and XBRL data (User-Agent required). Gemini (Deep Research via `scripts/gemini/deep_research.py`, Flash-Lite via `scripts/gemini/fast.py`) for qualitative research — sentiment, trends, narratives, 'why' questions."*

Template:
```
cat <<'RESEARCH_PROMPT' | Codex -p --model Codex-sonnet-4-6 --allowedTools "WebSearch,WebFetch,Bash" > /tmp/fo-briefing-{name}.md 2>/dev/null
Held-ticker prices are LIVE in the embedded holdings data (holdings.json, synced from Schwab — do NOT re-fetch). Use WebSearch for unheld tickers, indices, futures, commodities, FX, crypto, and same-day news. Use SEC EDGAR APIs via Bash curl (User-Agent required) for SEC filings + XBRL data. Use Gemini (Deep Research scripts/gemini/deep_research.py, Flash-Lite scripts/gemini/fast.py) for qualitative — sentiment, trends, narratives, 'why' questions.

{prompt with today's date and any needed data}
RESEARCH_PROMPT
```

### Agent 1 — Market Snapshot
Prompt the agent to use WebSearch to find: S&P 500, Nasdaq, Dow, Russell 2000 futures/pre-market levels and changes. 2Y, 10Y, 30Y Treasury yields. VIX. WTI crude, gold, Bitcoin, DXY. Overnight international markets (Europe close, Asia close). Output as a markdown table with levels, changes, and brief signal notes. Note the timestamp of all data.

Output file: `/tmp/fo-briefing-market.md`

### Agent 2 — Holdings & Watchlist News
**Include the full holdings CSV and watchlist JSON data in the prompt.** Prompt the agent to use WebSearch to find any news, analyst actions, upgrades/downgrades, earnings, or material events affecting each holding and watchlist stock TODAY. Output as table: Ticker | News/Event | Impact (Bullish/Bearish/Neutral). Omit stocks with no news.

Output file: `/tmp/fo-briefing-holdings.md`

### Agent 3 — Economic & Earnings Calendar
Prompt the agent to use WebSearch to find: (1) Today's economic data releases with time (ET), release name, consensus estimate, prior reading, importance (HIGH/MED/LOW). (2) Today's earnings reports: before/after market, company, ticker, EPS estimate, revenue estimate. Output as two markdown tables.

Output file: `/tmp/fo-briefing-calendar.md`

### Agent 4 — Top Stories & Overnight
Prompt the agent to use WebSearch to find the top 3-5 market-moving stories right now. For each: headline, 1-2 sentence summary, why it matters for markets. Also write a 2-3 sentence overnight recap of Asia/Europe sessions and any breaking news.

Output file: `/tmp/fo-briefing-stories.md`

## Phase 2: Synthesis (Opus)

After all 4 Bash calls complete, read the 4 output files:
- `/tmp/fo-briefing-market.md`
- `/tmp/fo-briefing-holdings.md`
- `/tmp/fo-briefing-calendar.md`
- `/tmp/fo-briefing-stories.md`

Synthesize into the final briefing using your own judgment (you are running on Opus). Add the "One Thing to Think About" section yourself — a genuinely thought-provoking insight, not filler. If any research agent produced empty or failed output, note the gap and work with what you have.

Clean up the temp files after synthesis (`rm -f /tmp/fo-briefing-*.md`).

## Output Format

Save to `briefings/daily/YYYY-MM-DD.md`:

```markdown
# Morning Briefing: [Day of Week], [Full Date]
**Agent:** Morning Briefing
**Prepared for:** Family Office

---

## Market Snapshot
| Index/Asset | Level | Change | Signal |
|------------|-------|--------|--------|
| S&P 500 Futures | X,XXX | +/-X.X% | [Brief note] |
| Nasdaq Futures | XX,XXX | +/-X.X% | [Brief note] |
| Dow Futures | XX,XXX | +/-X.X% | [Brief note] |
| Russell 2000 | X,XXX | +/-X.X% | [Brief note] |
| 10Y Treasury | X.XX% | +/-X bps | |
| 2Y Treasury | X.XX% | +/-X bps | |
| VIX | XX.X | +/-X.X | |
| WTI Crude | $XX.XX | +/-X.X% | |
| Gold | $X,XXX | +/-X.X% | |
| Bitcoin | $XX,XXX | +/-X.X% | |
| DXY (Dollar) | XXX.X | +/-X.X% | |

## Overnight Recap
[2-3 sentences]

## Top Stories
1. **[Headline]** — [1-2 sentence summary]
2. **[Headline]** — [...]
3. **[Headline]** — [...]

## Your Holdings: What to Watch
| Ticker | News/Event | Impact |
|--------|-----------|--------|

## Watchlist Alerts
[Any watchlist stocks with notable news or levels]

## Economic Calendar Today
| Time (ET) | Release | Consensus | Prior | Importance |
|-----------|---------|-----------|-------|-----------|

## Earnings Calendar Today
| Before/After | Company | EPS Est. | Revenue Est. |
|-------------|---------|----------|-------------|

## One Thing to Think About
[A single genuinely thought-provoking insight — not filler]

---
```

## Quality Standards
- Brevity is everything. 5-minute read, not an essay.
- Focus on what MATTERS for the user's portfolio, not generic news.
- If nothing notable, say so. "Quiet day, no major catalysts" is valid.
- Include timestamp of pre-market data.
- Don't make predictions. Report facts and flag what to watch.

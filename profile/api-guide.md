# API & Tool Priority Guide

This is the canonical reference for which data source to use for each type of question. **Every agent must follow this priority order.** WebSearch is a last resort for structured data — not a first stop. The full table is mirrored in `CLAUDE.md`; this file adds setup details, examples, and fallback behavior.

> This is a generic template. Add your own API keys to `profile/api-keys.json` (gitignored) or set the corresponding environment variables. Agents degrade gracefully when a key is missing — they just have less live data.

## Priority table

| Data type | First | When rate-limited / unavailable | Last resort |
|-----------|-------|--------------------------------|-------------|
| **Account positions / balances / transactions / orders** | **Schwab Trader API** (`scripts/schwab/client.py`) | — (data exists only at the brokerage) | — |
| Stock quotes (live & EOD) | **Schwab Market Data API** | AlphaVantage `GLOBAL_QUOTE` | WebSearch |
| Options chains / Greeks | **Schwab Market Data API** (`GET /marketdata/v1/chains`) | AlphaVantage `REALTIME_OPTIONS` | WebSearch |
| Price history / OHLC | **Schwab Market Data API** (`GET /marketdata/v1/pricehistory`) | AlphaVantage `TIME_SERIES_*` | WebSearch |
| Stock fundamentals / ratios / P/E | AlphaVantage MCP | SEC EDGAR XBRL via Bash curl | WebSearch |
| Income / balance sheet / cash flow | AlphaVantage MCP | SEC EDGAR XBRL Company Facts via Bash curl | WebSearch |
| 10-K / 10-Q / 8-K / Form 4 / 13F | SEC EDGAR via Bash curl | WebSearch | — |
| Treasury yields / CPI / Fed Funds / GDP / unemployment / mortgage rates | FRED via WebFetch | AlphaVantage macro endpoints | WebSearch |
| Commodities / FX / crypto | AlphaVantage MCP | WebSearch | — |
| Earnings call transcripts | AlphaVantage `EARNINGS_CALL_TRANSCRIPT` | WebSearch | — |
| Qualitative deep research / multi-source synthesis | **Gemini Deep Research** (`scripts/gemini/deep_research.py`) | WebSearch + WebFetch of primary sources | — |
| Quick "why is X" / grounded factual lookups / sentiment surface | **Gemini fast** (`scripts/gemini/fast.py`) | Gemini Flash via same wrapper | WebSearch |
| Reddit retail sentiment / comment threads | Apify `trudax--reddit-scraper-lite` | Gemini fast (surface only) | WebSearch |
| JS-heavy article extraction (Substack, blogs, mid-tier publishers) | WebFetch | Apify `lukaskrivka--article-extractor-smart` | WebSearch |
| Library / framework / SDK docs | `context7` MCP | WebSearch | — |
| Same-day / breaking news | WebSearch | — | — |

## Schwab Trader API (primary for quotes / options / history + account data)

- **What it powers:** account positions, balances, transactions, and orders for your linked brokerage accounts; and live/EOD quotes, options chains/Greeks, and price history for **both held and unheld tickers**.
- **Read-only by design.** The wrapper at `scripts/schwab/client.py` raises `ReadOnlyClientError` from `place_order` / `replace_order` / `cancel_order` before any HTTP call — the agents can read but never trade.
- **Auth:** `python3.10 scripts/schwab/auth.py`. The **refresh token expires every 7 days** — schedule a weekly reminder to re-run it. If `profile/api-keys.json` shows `schwab.tokens.refresh_token_expires_at` is past, the wrapper fails; fall back to AlphaVantage with a warning.
- **Helpers:** `scripts/schwab/probe.py` (discover which accounts hold positions), `scripts/schwab/test_read_only.py` (verify the order-blocking guard), `scripts/schwab/sync.py` (the engine behind `/sync`).

## AlphaVantage (MCP)

- **Primary** for fundamentals (P/E, ratios, `COMPANY_OVERVIEW`, `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`), earnings dates and transcripts, commodities, FX, and crypto.
- **Fallback** for quotes, options, and price history when Schwab is unavailable.
- Free tiers are rate-limited. **When you hit a rate-limit message, switch to SEC EDGAR XBRL Company Facts via Bash curl for fundamentals — do NOT fall to WebSearch.**

## SEC EDGAR (via Bash curl)

- Use for filings (10-K, 10-Q, 8-K, Form 4, 13F) and XBRL financials (Company Facts API).
- **A `User-Agent` header is required** by the SEC (e.g. `User-Agent: your-app your-email`). Requests without it are rejected.
- This is the fundamentals fallback when AlphaVantage is rate-limited.

## FRED (via WebFetch)

- Primary for macro/Treasury data: Treasury yields, CPI, Fed funds rate, GDP, unemployment, mortgage rates. Fetch the relevant FRED series page.

## Gemini

- `scripts/gemini/fast.py` — quick grounded lookups ("why did X move today?", surface sentiment) using a Flash-Lite model with Google Search grounding. On a quota/429 error, retry once with `--model gemini-3-flash`, then fall to WebSearch + WebFetch.
- `scripts/gemini/deep_research.py` — multi-source, multi-step deep research for full reports. Reserve it for genuine reports, not quick lookups.
- Key resolution lives in `scripts/gemini/_keys.py`: reads `gemini.api_key` from `profile/api-keys.json` or the `GEMINI_API_KEY` environment variable.

## Apify (MCP) — narrow, specialized jobs only

- `mcp__apify__trudax--reddit-scraper-lite` — Reddit retail sentiment and comment threads on retail-driven names (crypto, memes, popular tickers).
- `mcp__apify__lukaskrivka--article-extractor-smart` — extract article text when WebFetch returns garbage on Substack/blogs/mid-tier publishers. Does **not** bypass paywalls.

## context7 (MCP)

- Library, framework, SDK, and CLI documentation. Prefer it over WebSearch for any "how does this library work" question.

## WebSearch

- **Last resort** for structured data. **First stop only for same-day / breaking news** where no structured API has the information yet.

## Sub-agent instruction

When you spawn sub-agents, they default to WebSearch unless told otherwise. Paste the tool-priority instruction block from `CLAUDE.md` into every sub-agent prompt — especially the Schwab-first directive for quotes/options/history and the "don't fall to WebSearch for fundamentals" rule.

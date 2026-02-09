# Family Office — AI-Powered Family Office Plugin for Claude Code

An AI-powered family office that runs inside [Claude Code](https://docs.anthropic.com/en/docs/claude-code). 23 slash command skills that replicate the functions of a traditional family office — investment research, portfolio management, tax strategy, financial planning, and more.

14 of the 23 skills are **parallel agent orchestrators** that spawn multiple research agents simultaneously for deep, concurrent analysis.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and configured
- A Claude API key with access to web search

## Quick Start

1. Clone this repo into your working directory:
   ```bash
   git clone https://github.com/elliottrjacobs/family-office.git
   cd family-office
   ```

2. Run the onboarding skill to set up your financial profile:
   ```
   /onboard
   ```
   This walks you through an interactive intake (family details, goals, risk tolerance, accounts) and parses any financial documents you drop into `imports/`.

3. Run your first investment committee meeting:
   ```
   /cio
   ```

## Customization

This plugin ships as "Jacobs Family Office." To use your own family name, update the references in `CLAUDE.md` and the individual SKILL.md files in `.claude/skills/`.

## Available Skills

### Investment Team (Parallel Agents)
| Skill | Agents | Description |
|-------|--------|-------------|
| `/cio` | 6 | Chief Investment Officer — full investment committee meeting |
| `/equity-research <TICKER>` | 5 | Institutional-grade stock analysis |
| `/macro` | 5 | Macroeconomic outlook and positioning |
| `/options <TICKER>` | 4 | Options strategies for income and hedging |
| `/screener <criteria>` | up to 5 | Stock screening with parallel deep dives |

### Sector Specialists (Parallel Agents)
| Skill | Agents | Description |
|-------|--------|-------------|
| `/sector-tech` | 4 | Semiconductors, cloud, consumer tech, cybersecurity |
| `/sector-energy` | 4 | Oil/gas, uranium, renewables, mining |
| `/sector-finance` | 4 | Banks, REITs, insurance, fintech |
| `/sector-biotech` | 4 | Pharma, biotech, medtech, GLP-1/obesity |

### Money Management (Parallel Agents)
| Skill | Agents | Description |
|-------|--------|-------------|
| `/cfo` | 4 | Net worth, cash flow, goal tracking, financial health |
| `/tax` | 4 | Tax-loss harvesting, Roth conversions, business tax |
| `/risk` | 4 | Stress testing, concentration, position sizing |

### Market Intelligence (Parallel Agents)
| Skill | Agents | Description |
|-------|--------|-------------|
| `/briefing` | 4 | Daily market overview and holdings news |
| `/weekly-review` | 4 | Weekly portfolio performance and narrative |

### Single Agent Skills
| Skill | Description |
|-------|-------------|
| `/technicals <TICKER>` | Chart analysis, entry/exit timing, momentum |
| `/alts-scout` | Crypto, commodities, alternative investments |
| `/debt` | Debt payoff strategies, refinancing, leverage analysis |
| `/estate` | Wills, trusts, insurance gaps, wealth transfer |
| `/ventures` | Business structuring, tax optimization, valuation |
| `/realestate` | Property deal analysis, rent vs. buy, market evaluation |
| `/journal` | Trade logging, thesis tracking, decision review |
| `/eli5` | Re-explains any agent output in plain English |
| `/onboard` | Guided financial profile setup |

## How It Works

### Parallel Agent Architecture

When you run a skill like `/cio`, Claude Code doesn't just answer in a single pass. It spawns multiple specialized research agents that run **simultaneously**:

```
/cio
  ├── Agent 1: Macro Strategist (researching economic outlook)
  ├── Agent 2: Equity Analyst (reviewing all holdings)
  ├── Agent 3: Technical Analyst (checking charts and momentum)
  ├── Agent 4: Options Strategist (finding income opportunities)
  ├── Agent 5: Risk Manager (stress testing the portfolio)
  └── Agent 6: Alternatives Scout (scanning crypto and commodities)
```

Each agent independently searches the web for current data, then the CIO synthesizes everything into a unified strategic report with specific action items.

### Profile System

The `/onboard` skill generates structured JSON files in `profile/` that every other skill reads:

```
profile/
├── family.json              # Household members, dependents
├── goals.json               # Financial goals with timelines
├── risk-tolerance.json      # Risk score, max drawdown, behavioral tendencies
├── investment-policy.json   # The IPS: strategy, allocation, constraints
├── income/                  # W2, 1099, other income sources
├── accounts/                # Checking, brokerage, retirement, crypto
├── portfolio/               # holdings.csv, watchlist.json
├── expenses/                # Monthly/annual recurring, summary
├── debts/                   # Mortgage, auto, student, credit cards
├── business/                # Entity structure, financials, tax setup
├── real-estate/             # Primary residence, investment properties
├── tax/                     # Filing status, brackets, strategies
└── insurance/               # Health, life, disability, umbrella
```

### The `--challenge` Flag

Any investment skill supports `--challenge` to add a Devil's Advocate section that argues the opposite position. This prevents confirmation bias.

```
/equity-research NVDA --challenge
```

## Scheduling Briefings (Optional)

All skills are **on-demand** — you run them when you want them. This is intentional: each briefing spawns multiple research agents with web searches, so running them only when you'll actually read the output keeps token costs down and ensures the data is fresh.

If you want automated daily or weekly briefings, set up a local cron job that invokes the Claude CLI:

```bash
# Edit your crontab
crontab -e

# Run /briefing at 7:00 AM on weekdays
0 7 * * 1-5 cd /path/to/family-office && claude -p '/briefing' > /dev/null 2>&1

# Run /weekly-review at 4:00 PM on Fridays
0 16 * * 5 cd /path/to/family-office && claude -p '/weekly-review' > /dev/null 2>&1
```

Replace `/path/to/family-office` with your actual directory. The `claude -p` flag runs the skill non-interactively and prints output. Reports are saved to `briefings/daily/` and `briefings/weekly/` automatically.

> **Note:** Scheduling is user-specific (local paths, timezone, machine uptime) and is not included in the repo. Your machine must be on, the Claude CLI must be authenticated, and `/onboard` must have been run first.

## Directory Structure

```
.claude/
├── skills/           # 23 SKILL.md files (the core of the plugin)
│   ├── cio/
│   ├── equity-research/
│   ├── macro/
│   └── ... (20 more)
└── settings.json     # Auto-allow permissions

imports/              # Drop your financial files here for /onboard to parse
├── bank-statements/
├── brokerage/
├── credit-cards/
├── pay-stubs/
├── tax-returns/
├── loan-docs/
└── other/

profile/              # Generated by /onboard, read by all skills
reports/              # Agent-generated analysis
briefings/            # Daily and weekly market intelligence
journal/              # Trade decision log
memory/               # Persistent agent context between sessions
```

## Privacy

All personal financial data stays local. The `profile/`, `imports/`, `reports/`, `briefings/`, `journal/`, and `memory/` directories are gitignored. Only the plugin framework (skills, config, README) is tracked in git.

## Roadmap

Currently all market data comes from web search at runtime. Planned improvements:

- **MCP integrations for live market data** — connect to financial data APIs (Alpha Vantage, FRED, Yahoo Finance) via MCP servers for structured, real-time data instead of web scraping
- **Brokerage API connections** — sync holdings and transactions automatically instead of manual CSV imports
- **Automated portfolio tracking** — live P&L, cost basis tracking, and drift alerts

Contributions welcome — especially MCP server integrations for financial data sources.

## License

MIT

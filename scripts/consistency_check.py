#!/usr/bin/env python3.10
"""
Consistency check (drift-lint) for the Family Office repo.

Treats profile/portfolio/holdings.json as the canonical source for all live
financial values, then verifies that the derived/snapshot files agree with it
and that no retired stale value has crept back in.

Usage:
  python3.10 scripts/consistency_check.py          # report; exit 1 if any FAIL
  python3.10 scripts/consistency_check.py --quiet   # only print FAIL/WARN lines

Run weekly (alongside the Schwab re-auth) and after any /sync. This is the
automated version of the automated consistency audit.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLDINGS = ROOT / "profile" / "portfolio" / "holdings.json"
FRESHNESS = ROOT / "memory" / "data-freshness.json"
ACCOUNTS = ROOT / "profile" / "accounts" / "accounts.json"
BROKERAGE = ROOT / "profile" / "accounts" / "brokerage.json"
CRYPTO = ROOT / "profile" / "accounts" / "crypto.json"

TOL = 1.00  # dollar tolerance for cross-file numeric checks (rounding noise)

# Retired values / strings that must never reappear in profile/ or memory/.
# (key = human label, value = list of regex patterns; any match is a FAIL)
# As you correct stale data, add the old value here as a regex so a future
# /sync or hand-edit can't silently reintroduce it. Examples:
#     "old portfolio value ($123,456)": [r"123,?456"],
#     "retired maiden name": [r"Jane Doe"],
STALE_BLOCKLIST = {}

# Files allowed to contain an otherwise-blocked pattern (e.g. a note that
# documents the removal). Example: {"some-rule": {"feedback-note.md"}}
BLOCKLIST_ALLOW = {}
# Directories scanned for the blocklist (reports/ excluded — historical snapshots).
SCAN_DIRS = [ROOT / "profile", ROOT / "memory"]
SCAN_EXTS = {".json", ".md"}

results = []  # (level, message)


def add(level, msg):
    results.append((level, msg))


def load(p):
    with open(p) as f:
        return json.load(f)


def near(a, b):
    return abs((a or 0) - (b or 0)) <= TOL


def canonical(h):
    """Derive canonical numbers from holdings.json."""
    accts = h["accounts"]
    total = h["total_portfolio_value"]
    out = {"total": total, "accounts": {}, "ibit_by_acct": {}, "etf_total": 0.0}
    for slot, a in accts.items():
        out["accounts"][slot] = a["market_value"]
        for pos in a["holdings"]:
            if pos["symbol"] == "TICKER2":
                out["ibit_by_acct"][slot] = pos["market_value"]
                out["etf_total"] += pos["market_value"]
            if pos["symbol"] == "TICKER1":
                out["axsm"] = pos["market_value"]
                out["axsm_pct_acct"] = pos["pct_of_account"]
            if pos["symbol"] == "SWVXX":
                out["swvxx"] = pos["market_value"]
    out["etf_total"] = round(out["etf_total"], 2)
    return out


def check_structured(c):
    # data-freshness.json
    if FRESHNESS.exists():
        f = load(FRESHNESS)
        km = (f.get("key_metrics") or {}).get("portfolio_value_schwab")
        api = ((f.get("api_sources") or {}).get("schwab") or {}).get("portfolio_value")
        if km is None or near(km, c["total"]):
            add("PASS", f"data-freshness key_metrics.portfolio_value_schwab matches holdings (${c['total']:,.2f})")
        else:
            add("FAIL", f"data-freshness key_metrics.portfolio_value_schwab=${km:,.2f} != holdings ${c['total']:,.2f}")
        if api is not None and not near(api, c["total"]):
            add("FAIL", f"data-freshness api_sources.schwab.portfolio_value=${api:,.2f} != holdings ${c['total']:,.2f}")

    # accounts.json total_investment_value
    if ACCOUNTS.exists():
        a = load(ACCOUNTS)
        tiv = a.get("total_investment_value")
        if tiv is None or near(tiv, c["total"]):
            add("PASS", f"accounts.json total_investment_value matches holdings")
        else:
            add("FAIL", f"accounts.json total_investment_value=${tiv:,.2f} != holdings ${c['total']:,.2f}")

    # brokerage.json total_taxable_value == sum of taxable slots in holdings
    if BROKERAGE.exists():
        b = load(BROKERAGE)
        ttv = b.get("total_taxable_value")
        taxable = round(c["accounts"].get("joint_brokerage_aaa", 0)
                        + c["accounts"].get("individual_brokerage_bbb", 0), 2)
        if ttv is None or near(ttv, taxable):
            add("PASS", f"brokerage.json total_taxable_value matches taxable slots (${taxable:,.2f})")
        else:
            add("FAIL", f"brokerage.json total_taxable_value=${ttv:,.2f} != taxable slots ${taxable:,.2f}")

    # crypto.json TICKER2 exposure
    if CRYPTO.exists():
        cr = load(CRYPTO)
        tie = (cr.get("total_ibit_exposure") or {}).get("total_market_value")
        if tie is None or near(tie, c["etf_total"]):
            add("PASS", f"crypto.json total TICKER2 matches holdings (${c['etf_total']:,.2f})")
        else:
            add("FAIL", f"crypto.json total_ibit_exposure=${tie:,.2f} != holdings TICKER2 ${c['etf_total']:,.2f} (run /sync --apply)")


def check_paths():
    """Verify every profile//scripts//memory/ path referenced in the skills + core
    docs actually exists. Catches dangling references (renamed/removed files)."""
    doc_files = []
    skills_dir = ROOT / ".claude" / "skills"
    agents_dir = ROOT / ".claude" / "agents"
    if skills_dir.exists():
        doc_files += list(skills_dir.glob("*/SKILL.md"))
    if agents_dir.exists():
        doc_files += list(agents_dir.glob("*.md"))
    for extra in [ROOT / "CLAUDE.md", ROOT / "profile" / "SOURCES.md",
                  ROOT / "profile" / "api-guide.md"]:
        if extra.exists():
            doc_files.append(extra)

    token_re = re.compile(r"(?<![A-Za-z])(?:profile|scripts|memory)/[A-Za-z0-9_*./-]+")
    missing = {}  # path -> set(referencing files)
    for p in doc_files:
        for raw in token_re.findall(p.read_text(errors="ignore")):
            tok = raw.rstrip(".,:);`\"'")
            # skip placeholders / templated paths
            if any(x in tok for x in ("<", ">", "YYYY", "XX", "{", "*")):
                if "*" in tok:  # wildcard: ok if glob matches or parent dir exists
                    matches = list(ROOT.glob(tok))
                    parent = (ROOT / tok).parent
                    if matches or parent.exists():
                        continue
                    missing.setdefault(tok, set()).add(p.relative_to(ROOT))
                continue
            target = ROOT / tok
            if tok.endswith("/"):
                ok = target.is_dir()
            else:
                ok = target.exists()
            if not ok:
                missing.setdefault(tok, set()).add(p.relative_to(ROOT))

    if missing:
        for tok, refs in sorted(missing.items()):
            ref_list = ", ".join(str(r) for r in sorted(refs))
            add("FAIL", f"dangling reference — '{tok}' does not exist (referenced in {ref_list})")
    else:
        add("PASS", f"all path references in skills + docs resolve ({len(doc_files)} files scanned)")


def check_blocklist():
    files = [p for d in SCAN_DIRS if d.exists()
             for p in d.rglob("*") if p.suffix in SCAN_EXTS and p.is_file()]
    for label, needles in STALE_BLOCKLIST.items():
        allow = BLOCKLIST_ALLOW.get(label, set())
        hits = []
        for p in files:
            if p.name in allow:
                continue
            text = p.read_text(errors="ignore")
            for n in needles:
                if re.search(n, text):
                    hits.append(p.relative_to(ROOT))
                    break
        if hits:
            for h in hits:
                add("FAIL", f"retired value reappeared — {label} found in {h}")
        else:
            add("PASS", f"no occurrence of {label}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="only print FAIL/WARN lines")
    args = ap.parse_args()

    if not HOLDINGS.exists():
        print("FAIL: profile/portfolio/holdings.json not found — cannot establish canonical values")
        sys.exit(2)

    c = canonical(load(HOLDINGS))
    check_structured(c)
    check_blocklist()
    check_paths()

    fails = [m for lvl, m in results if lvl == "FAIL"]
    warns = [m for lvl, m in results if lvl == "WARN"]

    for lvl, msg in results:
        if args.quiet and lvl == "PASS":
            continue
        mark = {"PASS": "  ok ", "WARN": " warn", "FAIL": "FAIL "}[lvl]
        print(f"[{mark}] {msg}")

    print(f"\n{len(fails)} FAIL, {len(warns)} WARN, "
          f"{sum(1 for l, _ in results if l == 'PASS')} PASS "
          f"(canonical total ${c['total']:,.2f})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

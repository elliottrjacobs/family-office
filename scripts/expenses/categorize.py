#!/usr/bin/env python3.10
"""
Expense categorizer + rollup generator — AI family-office template.

READS (sources):
  - profile/expenses/categories.json      (AUTHORED rules: taxonomy, descriptor rules, overrides)
  - profile/transactions/<slug>/<year>.json (SimpleFIN, sync-owned LIVE truth for linked accounts)
  - imports/monarch/Transactions_*.csv    (Monarch export: bulk seed map + history + gap-card backfill)

WRITES (DERIVED — never hand-edit; re-run this to refresh):
  - profile/expenses/budget-data.json     (full categorized rollup for the dashboard)
  - profile/expenses/summary.json         (compact monthly summary, regenerated; replaces the Feb snapshot)

Categorization precedence per transaction:
  descriptor_rules (raw bank descriptor)  ->  payee_overrides  ->  Monarch merchant/orig map  ->  needs_review
"""
import csv, json, glob, re, os, sys, collections, datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
def P(*a): return os.path.join(ROOT, *a)

_CATS_PATH = P("profile", "expenses", "categories.json")
if not os.path.exists(_CATS_PATH):
    sys.exit("No profile/expenses/categories.json — author it first. "
             "See scripts/expenses/categories.example.json for the schema (or run /onboard).")
CATS = json.load(open(_CATS_PATH))
# Optional history/backfill: a Monarch/Mint transaction export dropped in imports/monarch/.
_monarch_files = sorted(glob.glob(P("imports", "monarch", "Transactions_*.csv")))
MONARCH = _monarch_files[-1] if _monarch_files else None

def norm(s):
    if not s: return ""
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower().strip())
    return re.sub(r"\s+", " ", s).strip()

# ---- build category -> type lookup ----
TYPE_OF = {}
for typ, cats in CATS["taxonomy_types"].items():
    if typ.startswith("_"): continue
    for c in cats: TYPE_OF[c] = typ
def type_of(cat): return TYPE_OF.get(cat, "spend")  # unknown categories default to spend

# ---- load Monarch: merchant map + orig-statement map (dominant category) ----
mrows = list(csv.DictReader(open(MONARCH))) if MONARCH else []
m_merch = collections.defaultdict(collections.Counter)
m_orig = collections.defaultdict(collections.Counter)
for r in mrows:
    cat = (r.get("Category") or "").strip()
    if not cat: continue
    m = norm(r.get("Merchant"))
    o = norm(r.get("Original Statement"))
    if m: m_merch[m][cat] += 1
    if o: m_orig[o][cat] += 1
def dom(counter): return counter.most_common(1)[0][0] if counter else None

# ---- rule layers ----
DESC_RULES = CATS["descriptor_rules"]["rules"]
OVERRIDES = {k: v for k, v in CATS["payee_overrides"].items() if not k.startswith("_")}
REVIEW = {k for k in CATS["needs_review_payees"] if not k.startswith("_")}

def categorize(payee, desc, mcat=None):
    npayee, ndesc = norm(payee), norm(desc)
    du = (desc or "").upper()
    # 1 descriptor rules (substring on raw descriptor) — enforce consistency (delivery splits, CC-payment credits)
    for rule in DESC_RULES:
        if rule["match"].upper() in du:
            return rule["category"], "descriptor"
    # 2 explicit review flags -> uncategorized
    if npayee in REVIEW:
        return None, "needs_review"
    # 3 payee overrides (fix known Monarch mistakes, e.g. a doctor's payee name mapped to Medical)
    if npayee in OVERRIDES:
        return OVERRIDES[npayee], "override"
    # 4 Monarch row's OWN user-assigned category = ground truth for Monarch-sourced txns
    #    (e.g. generic "Zelle" merchant but the row is tagged "Rent"). Do NOT re-infer it.
    if mcat:
        return mcat, "monarch_row"
    # 5 Monarch maps (inference — only for SimpleFIN rows, which carry no category)
    if npayee in m_merch:
        return dom(m_merch[npayee]), "monarch_merchant"
    if ndesc in m_orig:
        return dom(m_orig[ndesc]), "monarch_orig"
    # 5 loose substring against Monarch merchants
    if len(npayee) >= 4:
        for mn, cc in m_merch.items():
            if len(mn) >= 4 and (npayee in mn or mn in npayee):
                return dom(cc), "monarch_fuzzy"
    return None, "unmatched"

# ---- account routing ----
RT = CATS["account_routing"]
LINKED = set(RT["simplefin_linked_last4"])
GAP = set(RT["monarch_only_last4"])
EXCL = set(RT["exclude_last4"])
SFIN_START = RT["simplefin_start"]
# business-account slugs to exclude from the personal budget (configure in categories.json)
BUSINESS_SLUGS = set(RT.get("business_slugs", []))

def last4_from_acct(a):
    m = re.findall(r"\.\.\.(\w+)", a or "")
    return m[-1][-4:] if m else "?"

# ---- gather unified transaction set ----
# txn = dict(date, amount(out>0? keep signed), payee, desc, source, account_last4)
txns = []

# (a) SimpleFIN live (linked personal accounts, sync-owned)
sf_last4_by_slug = {}
for f in glob.glob(P("profile", "transactions", "*", "20[0-9][0-9].json")):
    slug = os.path.basename(os.path.dirname(f))
    if slug in BUSINESS_SLUGS: continue
    l4 = slug.split("_")[-1]
    if l4 not in LINKED: continue
    sf_last4_by_slug[slug] = l4
    data = json.load(open(f))
    items = data if isinstance(data, list) else data.get("transactions", [])
    for t in items:
        amt = t.get("amount_num", 0) or 0
        txns.append({"date": t.get("date", ""), "amt": float(amt),
                     "payee": t.get("payee", "") or "", "desc": t.get("description", "") or "",
                     "source": "simplefin", "last4": l4, "mcat": None})

# (b) Monarch: gap cards (all dates) + linked accounts before SimpleFIN start + history
for r in mrows:
    l4 = last4_from_acct(r.get("Account"))
    if l4 in EXCL: continue
    d = (r.get("Date") or "").strip()
    if l4 in LINKED and d >= SFIN_START:
        continue  # SimpleFIN owns this window — skip Monarch to avoid double count
    if l4 not in LINKED and l4 not in GAP:
        continue  # unknown/brokerage account — skip
    raw = (r.get("Amount") or "0").replace(",", "").replace("$", "")
    try: amt = float(raw)
    except: amt = 0.0
    txns.append({"date": d, "amt": amt, "payee": (r.get("Merchant") or "").strip(),
                 "desc": (r.get("Original Statement") or "").strip(),
                 "source": "monarch", "last4": l4, "mcat": (r.get("Category") or "").strip()})

# ---- categorize + aggregate ----
def month(d): return d[:7]
by_month_cat = collections.defaultdict(lambda: collections.defaultdict(float))   # month -> cat -> spend(+)
by_month_type = collections.defaultdict(lambda: collections.defaultdict(float))  # month -> type -> amt
merchant_spend = collections.defaultdict(float)
review_items = collections.defaultdict(lambda: {"amt": 0.0, "n": 0, "sample": ""})
method_counts = collections.Counter()
uncategorized_spend = 0.0
# complete per-category aggregation (ALL types) for the full breakdown view
cat_all_total = collections.defaultdict(float)
cat_all_month = collections.defaultdict(lambda: collections.defaultdict(float))
cat_type = {}
cat_count = collections.defaultdict(int)

for t in txns:
    cat, method = categorize(t["payee"], t["desc"], t.get("mcat"))
    method_counts[method] += 1
    m = month(t["date"])
    if not m: continue
    if cat is None:
        # only outflows matter for review noise
        if t["amt"] < 0:
            key = t["payee"] or t["desc"] or "UNKNOWN"
            ri = review_items[key]; ri["amt"] += -t["amt"]; ri["n"] += 1
            ri["sample"] = t["desc"][:40]
            uncategorized_spend += -t["amt"]
        continue
    typ = type_of(cat)
    # track EVERY category (all types) for the complete breakdown
    cat_type[cat] = typ
    cat_count[cat] += 1
    cat_all_total[cat] += abs(t["amt"])
    cat_all_month[cat][m] += abs(t["amt"])
    if typ == "spend" and t["amt"] < 0:
        by_month_cat[m][cat] += -t["amt"]
        merchant_spend[t["payee"] or t["desc"]] += -t["amt"]
        by_month_type[m]["spend"] += -t["amt"]
    elif typ == "income" and t["amt"] > 0:
        by_month_type[m]["income"] += t["amt"]
    elif typ == "savings":
        # Split direction: outflows = contributions to savings/investments; inflows = withdrawals (drawdowns)
        # back to checking (e.g. +$10k Schwab MoneyLink). These are internal asset moves, NOT income/spend.
        if t["amt"] < 0:
            by_month_type[m]["savings_in"] += -t["amt"]
        else:
            by_month_type[m]["savings_out"] += t["amt"]
    elif typ == "tax" and t["amt"] < 0:
        by_month_type[m]["tax"] += -t["amt"]
    elif typ == "debt" and t["amt"] < 0:
        by_month_type[m]["debt"] += -t["amt"]
        by_month_cat[m][cat] += -t["amt"]
    # transfers + credit-card payments ignored entirely (internal money movement)

# ---- choose reporting window: last 3 COMPLETE months in SimpleFIN data ----
all_months = sorted(by_month_type.keys())
this_month = datetime.date.today().strftime("%Y-%m")  # current, in-progress month
recent = all_months[-6:]                               # last 6 months present in the data
complete = [m for m in recent if m < this_month]       # exclude the partial current month
window = recent[-4:] if recent else all_months[-4:]

def avg_over(months, getter):
    vals = [getter(m) for m in months]
    return sum(vals) / len(vals) if vals else 0.0

# average using complete months (Mar+Apr) for run-rate
runrate_months = [m for m in complete] or window
avg_spend = avg_over(runrate_months, lambda m: by_month_type[m]["spend"])
avg_income = avg_over(runrate_months, lambda m: by_month_type[m]["income"])
avg_sav_in = avg_over(runrate_months, lambda m: by_month_type[m]["savings_in"])
avg_sav_out = avg_over(runrate_months, lambda m: by_month_type[m]["savings_out"])
avg_savings_net = avg_sav_in - avg_sav_out
avg_tax = avg_over(runrate_months, lambda m: by_month_type[m]["tax"])
avg_debt = avg_over(runrate_months, lambda m: by_month_type[m]["debt"])
# Operating net = earned income − spending − taxes − debt service. Internal savings/investment
# transfers are NOT subtracted (asset moves, not consumption); shown separately as savings flow.
avg_oper_net = avg_income - avg_spend - avg_tax - avg_debt

# category averages over run-rate months
cat_avg = collections.defaultdict(float)
for m in runrate_months:
    for c, v in by_month_cat[m].items():
        cat_avg[c] += v / len(runrate_months)
cat_avg_sorted = sorted(cat_avg.items(), key=lambda x: -x[1])

# complete category breakdown (every category, all types) for the full dashboard view
TYPE_ORDER = {"spend": 0, "debt": 1, "tax": 2, "savings": 3, "income": 4, "transfer": 5}
cat_breakdown = []
for c, tot in cat_all_total.items():
    mavg = (sum(cat_all_month[c].get(mm, 0) for mm in runrate_months) / len(runrate_months)) if runrate_months else 0
    cat_breakdown.append({"category": c, "type": cat_type[c], "monthly_avg": round(mavg, 2),
                          "all_time_total": round(tot, 2), "n": cat_count[c]})
cat_breakdown.sort(key=lambda x: (TYPE_ORDER.get(x["type"], 9), -x["monthly_avg"], -x["all_time_total"]))

# ---- build outputs ----
review_sorted = sorted(review_items.items(), key=lambda x: -x[1]["amt"])
budget = {
    "as_of": datetime.date.today().isoformat(),
    "_generated_by": "scripts/expenses/categorize.py — DERIVED, do not hand-edit",
    "sources": {"live": "SimpleFIN (linked accounts)",
                "history_and_backfill": os.path.relpath(MONARCH, ROOT) if MONARCH else None},
    "window_months": window,
    "runrate_months_used": runrate_months,
    "monthly_by_type": {m: dict(by_month_type[m]) for m in all_months},
    "monthly_by_category": {m: dict(by_month_cat[m]) for m in window},
    "category_runrate": [{"category": c, "monthly_avg": round(v, 2), "type": type_of(c)} for c, v in cat_avg_sorted],
    "category_breakdown": cat_breakdown,
    "top_merchants": sorted([{"merchant": k, "total": round(v, 2)} for k, v in merchant_spend.items()],
                            key=lambda x: -x["total"])[:25],
    "runrate": {"avg_monthly_spend": round(avg_spend, 2), "avg_monthly_income": round(avg_income, 2),
                "avg_monthly_savings_in": round(avg_sav_in, 2), "avg_monthly_savings_out": round(avg_sav_out, 2),
                "avg_monthly_savings_net": round(avg_savings_net, 2),
                "avg_monthly_tax": round(avg_tax, 2), "avg_monthly_debt": round(avg_debt, 2),
                "avg_monthly_operating_net": round(avg_oper_net, 2)},
    "needs_review": [{"payee": k, "total_outflow": round(v["amt"], 2), "n": v["n"], "sample_desc": v["sample"]}
                     for k, v in review_sorted],
    "diagnostics": {"total_txns": len(txns), "method_counts": dict(method_counts),
                    "uncategorized_outflow": round(uncategorized_spend, 2)},
}
json.dump(budget, open(P("profile", "expenses", "budget-data.json"), "w"), indent=2)

# compact summary.json (regenerated; replaces Feb snapshot) — keeps a familiar shape for skills
summary = {
    "as_of": datetime.date.today().isoformat(),
    "_generated_by": "scripts/expenses/categorize.py — DERIVED from live SimpleFIN + optional CSV history. Do NOT hand-edit.",
    "source": "SimpleFIN live (linked accounts) + optional Monarch/Mint CSV (history + any unsynced cards)",
    "runrate_months_used": runrate_months,
    "monthly_summary": {
        "avg_monthly_spend": round(avg_spend, 2),
        "avg_monthly_tax_set_aside": round(avg_tax, 2),
        "avg_monthly_debt_service": round(avg_debt, 2),
        "avg_monthly_savings_contrib": round(avg_sav_in, 2),
        "avg_monthly_savings_withdrawn": round(avg_sav_out, 2),
        "avg_monthly_savings_net": round(avg_savings_net, 2),
    },
    "income_summary": {"avg_monthly_income": round(avg_income, 2)},
    "monthly_operating_net": round(avg_oper_net, 2),
    "note_net": "Operating net = income − spend − tax − debt. Funded by net savings/investment withdrawals when negative.",
    "savings_rate_pct": round(100 * avg_savings_net / avg_income, 1) if avg_income else None,
    "top_spend_categories": [{"category": c, "monthly_avg": round(v, 2)} for c, v in cat_avg_sorted[:12]],
    "needs_review_count": len(review_sorted),
    "note": "Full detail + dashboard data in profile/expenses/budget-data.json. Regenerate both via scripts/expenses/categorize.py.",
}
json.dump(summary, open(P("profile", "expenses", "summary.json"), "w"), indent=2)

# ---- console report ----
print(f"History/backfill source: {os.path.relpath(MONARCH, ROOT) if MONARCH else '(none — optional: drop a Monarch/Mint CSV in imports/monarch/)'}")
print(f"Unified transactions: {len(txns)}  (methods: {dict(method_counts)})")
print(f"Run-rate months used: {runrate_months}")
print(f"\n  Avg monthly INCOME      : ${avg_income:,.0f}")
print(f"  Avg monthly SPEND       : ${avg_spend:,.0f}")
print(f"  Avg monthly TAX set     : ${avg_tax:,.0f}")
print(f"  Avg monthly DEBT svc    : ${avg_debt:,.0f}")
print(f"  => OPERATING NET        : ${avg_oper_net:,.0f}   (income − spend − tax − debt)")
print(f"  Savings CONTRIBUTIONS   : ${avg_sav_in:,.0f}/mo  (to savings/investment accounts)")
print(f"  Savings WITHDRAWALS     : ${avg_sav_out:,.0f}/mo  (drawdowns back to checking)")
print(f"  => NET to savings/invest: ${avg_savings_net:,.0f}/mo")
print(f"\nTop spend categories (run-rate / mo):")
for c, v in cat_avg_sorted[:15]:
    print(f"   {c:32} ${v:,.0f}")
print(f"\nNEEDS REVIEW (uncategorized outflow ${uncategorized_spend:,.0f} across {len(review_sorted)} payees):")
for k, v in review_sorted[:15]:
    print(f"   {k[:34]:36} ${v['amt']:,.0f} ({v['n']}x) '{v['sample']}'")
print(f"\nWrote: profile/expenses/budget-data.json + summary.json")

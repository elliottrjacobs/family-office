#!/usr/bin/env python3.10
"""
SimpleFIN live sync — pulls bank & credit-card balances + transactions and
folds them into the profile.

Transactions ACCUMULATE: each run merges newly-returned transactions into a
per-account store keyed by transaction id (idempotent). Designed to be run
frequently (e.g. a daily automation) — re-running never duplicates rows, and
history grows over time even though the bridge only returns a recent window.

Usage:
  python3.10 scripts/simplefin/sync.py                  # dry-run, trailing 30d
  python3.10 scripts/simplefin/sync.py --apply          # commit, trailing 30d (daily default)
  python3.10 scripts/simplefin/sync.py --full --apply   # commit, pull MAX history (~90d cap)
  python3.10 scripts/simplefin/sync.py --days 45 --apply # commit, trailing 45d
  python3.10 scripts/simplefin/sync.py --start 2023-01-01 --apply

Bridge limits (beta-bridge.simplefin.org, observed 2026-05-30): a single
request is HARD-capped at 90 days and >45 days is "not recommended" (may be
capped later). The bridge only retains ~90 days of history regardless of
start-date, so deeper history can only be built by accumulating forward — the
per-account store merges by id, so daily runs grow the archive without dupes.

Always writes (audit snapshot, even on dry-run):
  profile/accounts/_probe/simplefin_accounts.json

Updates on --apply (all derived/live — never hand-edit these):
  profile/transactions/<slug>/<year>.json   (raw txns, yearly partitions, dedup by id)
  profile/transactions/<slug>/rollups.json  (monthly inflow/outflow/net per account)
  profile/transactions/index.json           (summary + recent monthly rollups across accounts)
  profile/accounts/accounts.json            (bank + card balances, by last4)
  profile/accounts/checking-savings.json    (live balances, authored notes kept)
  profile/debts/credit-cards.json           (live card balances, schema kept)
  memory/data-freshness.json                (api_sources.simplefin + key_metrics)

Account matching is by last-4. Pin ambiguous accounts in
profile/api-keys.json -> simplefin.account_map: { "<sfin-id>": {"last4": "1234",
"type": "checking", "label": "Joint Checking"} }. Unmatched accounts are
reported (never silently guessed).
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import get_simplefin_client, SimpleFINError

ROOT = Path(__file__).resolve().parents[2]
KEYS_PATH = ROOT / "profile" / "api-keys.json"
PROBE_PATH = ROOT / "profile" / "accounts" / "_probe" / "simplefin_accounts.json"
TXN_DIR = ROOT / "profile" / "transactions"
TXN_INDEX_PATH = TXN_DIR / "index.json"
ACCOUNTS_PATH = ROOT / "profile" / "accounts" / "accounts.json"
CHECKING_PATH = ROOT / "profile" / "accounts" / "checking-savings.json"
CARDS_PATH = ROOT / "profile" / "debts" / "credit-cards.json"
BUSINESS_ACCOUNTS_PATH = ROOT / "profile" / "business" / "accounts.json"
FRESHNESS_PATH = ROOT / "memory" / "data-freshness.json"

ROUTINE_DAYS_DEFAULT = 30  # daily-cadence window; stays within the bridge's 45-day recommendation


# ---------- helpers ----------

def load_json(path, default=None):
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def fmt_epoch(secs):
    if not secs:
        return None
    return datetime.fromtimestamp(int(secs), tz=timezone.utc).astimezone().strftime("%Y-%m-%d")


def to_float(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:24] or "acct"


def detect_last4(name):
    """Pull a trailing 4-digit group out of a SimpleFIN account name, if present."""
    if not name:
        return None
    runs = re.findall(r"\d{4,}", name)
    return runs[-1][-4:] if runs else None


# ---------- profile last4 registry (for conservative auto-match) ----------

def build_profile_last4_map():
    """last4 -> {'kind': 'bank'|'credit_card', 'type': str, 'label': str} from authored profile."""
    out = {}
    cs = load_json(CHECKING_PATH, {})
    for a in cs.get("accounts", []):
        l4 = a.get("last_four")
        if l4:
            out[l4] = {"kind": "bank", "type": a.get("type", "checking"),
                       "label": a.get("name", f"Account ...{l4}")}
    acc = load_json(ACCOUNTS_PATH, {})
    for a in acc.get("bank_accounts", []):
        l4 = a.get("account_last4")
        if l4 and l4 not in out:
            out[l4] = {"kind": "bank", "type": a.get("type", "checking"),
                       "label": a.get("name", f"Account ...{l4}")}
    cards = load_json(CARDS_PATH, {})
    for c in cards.get("cards", []):
        l4 = c.get("last_four")
        if l4:
            out[l4] = {"kind": "credit_card", "type": "credit_card",
                       "label": c.get("name", f"Card ...{l4}")}
    for c in acc.get("credit_cards", []):
        l4 = c.get("account_last4")
        if l4 and l4 not in out:
            out[l4] = {"kind": "credit_card", "type": "credit_card",
                       "label": c.get("name", f"Card ...{l4}")}
    biz = load_json(BUSINESS_ACCOUNTS_PATH, {})
    for a in biz.get("accounts", []):
        l4 = a.get("last_four")
        if l4:
            out[l4] = {"kind": a.get("kind", "bank"), "type": a.get("type", "checking"),
                       "label": a.get("name", f"Account ...{l4}"),
                       "scope": "business", "entity": a.get("entity")}
    return out


def resolve_account(sf_acct, account_map, profile_last4):
    """Return a resolved descriptor or mark unmatched. Never guesses by name keywords."""
    sid = sf_acct.get("id", "")
    name = sf_acct.get("name", "")
    last4 = kind = atype = label = source = entity = None
    scope = "personal"

    if sid in account_map:
        m = account_map[sid]
        last4 = m.get("last4")
        atype = m.get("type")
        label = m.get("label")
        scope = m.get("scope", scope)
        entity = m.get("entity")
        source = "account_map"
    else:
        cand = detect_last4(name)
        if cand and cand in profile_last4:
            last4 = cand
            source = "name_last4"

    if last4 and last4 in profile_last4:
        p = profile_last4[last4]
        kind = kind or p.get("kind")
        atype = atype or p.get("type")
        label = label or p.get("label")
        scope = p.get("scope", scope)
        entity = entity or p.get("entity")

    if last4 and not kind:  # derive kind from type when profile didn't supply one
        if atype == "credit_card":
            kind = "credit_card"
        elif atype in ("brokerage", "investment"):
            kind = "investment"
        else:
            kind = "bank"
    if last4 and not label:
        label = f"...{last4}"

    matched = last4 is not None
    slug = f"{(atype or kind or 'acct')}_{last4}" if matched else f"sfin_{slugify(sid)[:12]}"

    return {
        "sfin_id": sid,
        "org": (sf_acct.get("org") or {}).get("name") or (sf_acct.get("org") or {}).get("domain"),
        "sf_name": name,
        "currency": sf_acct.get("currency"),
        "balance": to_float(sf_acct.get("balance")),
        "available_balance": to_float(sf_acct.get("available-balance")),
        "balance_as_of": fmt_epoch(sf_acct.get("balance-date")),
        "last4": last4,
        "kind": kind,
        "type": atype,
        "scope": scope,
        "entity": entity,
        "label": label,
        "slug": slug,
        "matched": matched,
        "match_source": source,
    }


# ---------- transaction merge (accumulating) ----------

def normalize_txn(t):
    posted = t.get("posted")
    transacted = t.get("transacted_at")
    eff = posted or transacted  # pending txns have posted=0/None — fall back to transacted_at
    return {
        "id": t.get("id"),
        "date": fmt_epoch(eff),            # effective date — used for partition / rollup / sort
        "posted": int(posted) if posted else None,
        "posted_date": fmt_epoch(posted),
        "transacted_at": int(transacted) if transacted else None,
        "amount": t.get("amount"),
        "amount_num": to_float(t.get("amount")),
        "description": t.get("description"),
        "payee": t.get("payee"),
        "memo": t.get("memo"),
        "pending": bool(t.get("pending", False)),
    }


def month_key(posted_date):
    return posted_date[:7] if posted_date else None


def compute_monthly(txns):
    """Per-month {count, inflow, outflow, net} from a txn list. Sorted newest-first."""
    out = {}
    for t in txns:
        mk = month_key(t.get("date"))
        if not mk:
            continue
        m = out.setdefault(mk, {"count": 0, "inflow": 0.0, "outflow": 0.0, "net": 0.0})
        m["count"] += 1
        amt = t.get("amount_num")
        if amt is not None:
            if amt >= 0:
                m["inflow"] += amt
            else:
                m["outflow"] += amt
            m["net"] += amt
    for m in out.values():
        m["inflow"] = round(m["inflow"], 2)
        m["outflow"] = round(m["outflow"], 2)
        m["net"] = round(m["net"], 2)
    return dict(sorted(out.items(), reverse=True))


def merge_transactions(slug, desc, fetched_txns, apply, as_of):
    """Merge fetched txns into per-account YEARLY partitions (<slug>/<year>.json), dedup by id,
    and rebuild <slug>/rollups.json (monthly). Returns (new, updated, total, earliest, latest, monthly).

    Loads every existing partition for the account so dedup, totals, and rollups are always exact.
    Files are small (a heavy account is ~430 KB/yr), so a full reload+rewrite per run is cheap.
    """
    acct_dir = TXN_DIR / slug
    by_id = {}
    if acct_dir.is_dir():
        for p in acct_dir.glob("*.json"):
            if p.name == "rollups.json":
                continue
            for t in (load_json(p, {}) or {}).get("transactions", []):
                if t.get("id"):
                    by_id[t["id"]] = t

    new, updated = 0, 0
    for raw in fetched_txns:
        nt = normalize_txn(raw)
        if not nt["id"]:
            continue
        if nt["id"] not in by_id:
            new += 1
        elif by_id[nt["id"]] != nt:
            updated += 1
        by_id[nt["id"]] = nt  # latest wins (pending -> posted updates in place)

    merged = sorted(by_id.values(),
                    key=lambda x: (x.get("posted") or x.get("transacted_at") or 0), reverse=True)
    dates = [t["date"] for t in merged if t.get("date")]
    earliest = min(dates) if dates else None
    latest = max(dates) if dates else None
    monthly = compute_monthly(merged)

    if apply:
        acct_meta = {
            "slug": slug, "last4": desc["last4"], "label": desc["label"],
            "org": desc["org"], "type": desc["type"], "kind": desc["kind"],
            "scope": desc.get("scope"), "entity": desc.get("entity"),
            "sfin_id": desc["sfin_id"],
        }
        by_year = {}
        for t in merged:
            by_year.setdefault((t.get("date") or "0000")[:4], []).append(t)

        acct_dir.mkdir(parents=True, exist_ok=True)
        for yr, txns in by_year.items():
            write_json(acct_dir / f"{yr}.json", {
                "account": acct_meta,
                "year": yr,
                "transaction_count": len(txns),
                "source": "SimpleFIN (live) — written by scripts/simplefin/sync.py",
                "transactions": txns,
            })
        # drop any stale year partitions no longer backed by data
        for p in acct_dir.glob("*.json"):
            if p.name != "rollups.json" and p.stem not in by_year:
                p.unlink()

        write_json(acct_dir / "rollups.json", {
            "account": acct_meta,
            "balance": desc["balance"],
            "balance_as_of": desc["balance_as_of"],
            "updated": as_of,
            "transaction_count": len(merged),
            "history_earliest": earliest,
            "history_latest": latest,
            "monthly": monthly,
            "source": "SimpleFIN (live) — written by scripts/simplefin/sync.py",
        })
    return new, updated, len(merged), earliest, latest, monthly


# ---------- profile balance updaters ----------

def update_checking_savings(by_last4, as_of):
    cs = load_json(CHECKING_PATH)
    if not cs:
        print(f"  skip {CHECKING_PATH.name} (not present)")
        return
    total = 0.0
    matched = 0
    for a in cs.get("accounts", []):
        l4 = a.get("last_four")
        d = by_last4.get(l4)
        if d and d["kind"] == "bank":
            a["balance"] = d["balance"]
            a["available_balance"] = d["available_balance"]
            a["balance_as_of"] = d["balance_as_of"]
            a["source"] = "SimpleFIN (live)"
            if d["balance"] is not None:
                total += d["balance"]
            matched += 1
    cs.pop("total_estimated_balance", None)
    cs["total_balance"] = round(total, 2)
    cs["balances_as_of"] = as_of
    cs["balance_source"] = "SimpleFIN (live) — see profile/transactions/ for activity"
    write_json(CHECKING_PATH, cs)
    print(f"  updated {CHECKING_PATH.name} ({matched} bank accounts, total ${total:,.2f})")


def update_credit_cards(by_last4, as_of):
    cards = load_json(CARDS_PATH)
    if not cards:
        print(f"  skip {CARDS_PATH.name} (not present)")
        return
    matched = 0
    for c in cards.get("cards", []):
        l4 = c.get("last_four")
        d = by_last4.get(l4)
        if d and d["kind"] == "credit_card":
            c["balance"] = d["balance"]
            c["balance_as_of"] = d["balance_as_of"]
            c["source"] = "SimpleFIN (live)"
            matched += 1
    cards["balances_as_of"] = as_of
    cards["balance_note"] = ("Balances are SimpleFIN-live; sign follows the bridge's convention "
                             "(negative typically = amount owed). Verify before treating as debt.")
    write_json(CARDS_PATH, cards)
    print(f"  updated {CARDS_PATH.name} ({matched} cards)")


def update_accounts_file(by_last4, as_of):
    acc = load_json(ACCOUNTS_PATH)
    if not acc:
        print(f"  skip {ACCOUNTS_PATH.name} (not present)")
        return
    bank_total, card_total, matched = 0.0, 0.0, 0
    for a in acc.get("bank_accounts", []):
        d = by_last4.get(a.get("account_last4"))
        if d and d["kind"] == "bank":
            a["balance"] = d["balance"]
            a["available_balance"] = d["available_balance"]
            a["balance_as_of"] = d["balance_as_of"]
            a["source"] = "SimpleFIN (live)"
            if d["balance"] is not None:
                bank_total += d["balance"]
            matched += 1
    for c in acc.get("credit_cards", []):
        d = by_last4.get(c.get("account_last4"))
        if d and d["kind"] == "credit_card":
            c["balance"] = d["balance"]
            c["balance_as_of"] = d["balance_as_of"]
            c["source"] = "SimpleFIN (live)"
            if d["balance"] is not None:
                card_total += d["balance"]
            matched += 1
    acc["bank_balances_as_of"] = as_of
    acc["total_bank_balance"] = round(bank_total, 2)
    acc["total_credit_card_balance"] = round(card_total, 2)
    write_json(ACCOUNTS_PATH, acc)
    print(f"  updated {ACCOUNTS_PATH.name} ({matched} accounts; bank ${bank_total:,.2f}, "
          f"cards ${card_total:,.2f})")
    return round(bank_total, 2), round(card_total, 2)


def update_business_accounts(by_last4, as_of):
    """Write live balances into profile/business/accounts.json (kept out of personal totals)."""
    biz = load_json(BUSINESS_ACCOUNTS_PATH)
    if not biz:
        print(f"  skip business/accounts.json (not present)")
        return None, None
    bank_total, card_total, matched = 0.0, 0.0, 0
    for a in biz.get("accounts", []):
        d = by_last4.get(a.get("last_four"))
        if d:
            a["balance"] = d["balance"]
            a["available_balance"] = d["available_balance"]
            a["balance_as_of"] = d["balance_as_of"]
            a["source"] = "SimpleFIN (live)"
            if d["balance"] is not None:
                if d["kind"] == "credit_card":
                    card_total += d["balance"]
                else:
                    bank_total += d["balance"]
            matched += 1
    biz["balances_as_of"] = as_of
    biz["total_business_bank_balance"] = round(bank_total, 2)
    biz["total_business_credit_card_balance"] = round(card_total, 2)
    write_json(BUSINESS_ACCOUNTS_PATH, biz)
    print(f"  updated business/accounts.json ({matched} accounts; bank ${bank_total:,.2f}, "
          f"cards ${card_total:,.2f})")
    return round(bank_total, 2), round(card_total, 2)


def update_freshness(slugs, bank_total, card_total, txn_total, earliest, latest, as_of):
    fresh = load_json(FRESHNESS_PATH, {})
    fresh.setdefault("api_sources", {})
    fresh["api_sources"]["simplefin"] = {
        "last_sync": as_of,
        "status": "active",
        "accounts_synced": slugs,
        "total_bank_balance": bank_total,
        "total_credit_card_balance": card_total,
        "transactions_total": txn_total,
        "history_earliest": earliest,
        "history_latest": latest,
    }
    km = fresh.setdefault("key_metrics", {})
    if bank_total is not None:
        km["total_bank_balance"] = bank_total
    if card_total is not None:
        km["total_credit_card_balance"] = card_total
    write_json(FRESHNESS_PATH, fresh)
    print(f"  updated {FRESHNESS_PATH.name} (api_sources.simplefin)")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write profile + transaction store")
    ap.add_argument("--full", action="store_true", help="Request MAX history (start-date = epoch 0)")
    ap.add_argument("--days", type=int, default=ROUTINE_DAYS_DEFAULT,
                    help=f"Trailing window in days (default {ROUTINE_DAYS_DEFAULT}); ignored if --full/--start")
    ap.add_argument("--start", help="Explicit start date YYYY-MM-DD (overrides --days/--full)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).astimezone()
    if args.start:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=now.tzinfo)
        start_epoch = int(start_dt.timestamp())
        window = f"from {args.start}"
    elif args.full:
        start_epoch = 0
        window = "MAX (everything the bridge has)"
    else:
        start_epoch = int((now - timedelta(days=args.days)).timestamp())
        window = f"trailing {args.days} days"

    print(f"Fetching SimpleFIN accounts + transactions ({window})...")
    try:
        client = get_simplefin_client()
        data = client.get_accounts(start_date=start_epoch, end_date=int(now.timestamp()), pending=True)
    except SimpleFINError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)

    PROBE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(PROBE_PATH, data)

    errors = data.get("errors") or []
    if errors:
        print(f"  bridge errors: {errors}")
    sf_accounts = data.get("accounts", [])
    if not sf_accounts:
        print("No accounts returned. Check the bridge / Access URL.")
        sys.exit(1)

    keys = load_json(KEYS_PATH, {})
    account_map = (keys.get("simplefin") or {}).get("account_map", {})
    profile_last4 = build_profile_last4_map()

    resolved = [resolve_account(a, account_map, profile_last4) for a in sf_accounts]
    sf_by_id = {a.get("id"): a for a in sf_accounts}
    as_of = now.isoformat(timespec="seconds")

    # --- report matching ---
    matched = [r for r in resolved if r["matched"]]
    unmatched = [r for r in resolved if not r["matched"]]
    print(f"\n=== Accounts ({len(resolved)} from bridge: {len(matched)} matched, {len(unmatched)} unmatched) ===")
    for r in resolved:
        tag = f"...{r['last4']} ({r['type'] or r['kind']})" if r["matched"] else "UNMATCHED"
        print(f"  {r['org'] or '?':22} {r['sf_name'][:30]:30} {r['currency'] or ''} "
              f"{r['balance'] if r['balance'] is not None else '?':>12}   {tag}")
    if unmatched:
        print("\n  ⚠ Unmatched accounts (will store txns under sfin_* slug but NOT touch profile balances).")
        print("    Pin them in profile/api-keys.json -> simplefin.account_map, e.g.:")
        for r in unmatched:
            print(f'      "{r["sfin_id"]}": {{ "last4": "____", "type": "checking|savings|credit_card", '
                  f'"label": "{r["sf_name"][:30]}" }}')

    # --- transaction merge (accumulate into yearly partitions + monthly rollups) ---
    print(f"\n=== Transactions (merge by id → yearly partitions; {'APPLY' if args.apply else 'dry-run'}) ===")
    txn_total = 0
    all_earliest, all_latest = [], []
    slugs = []
    results_by_slug = {}
    for r in resolved:
        sf = sf_by_id.get(r["sfin_id"], {})
        fetched = sf.get("transactions") or []
        new, updated, total, earliest, latest, monthly = merge_transactions(
            r["slug"], r, fetched, args.apply, as_of)
        txn_total += total
        slugs.append(r["slug"])
        results_by_slug[r["slug"]] = {"total": total, "monthly": monthly}
        if earliest:
            all_earliest.append(earliest)
        if latest:
            all_latest.append(latest)
        yrs = ",".join(sorted({mk[:4] for mk in monthly}, reverse=True)) or "-"
        print(f"  {r['slug']:22} fetched {len(fetched):>4}  → +{new} new, ~{updated} updated, "
              f"{total} total  [{earliest or '?'} … {latest or '?'}]  years={yrs}")

    hist_earliest = min(all_earliest) if all_earliest else None
    hist_latest = max(all_latest) if all_latest else None

    # by_last4 for profile balance updates (matched only)
    by_last4 = {r["last4"]: r for r in matched if r["last4"]}

    if not args.apply:
        bank_preview = round(sum(r["balance"] or 0 for r in matched if r["kind"] == "bank"), 2)
        card_preview = round(sum(r["balance"] or 0 for r in matched if r["kind"] == "credit_card"), 2)
        print(f"\nDry-run: bank balance would be ${bank_preview:,.2f}, "
              f"card balance ${card_preview:,.2f}, {txn_total} txns in store.")
        print(f"Wrote audit snapshot {PROBE_PATH.relative_to(ROOT)}.")
        print("Re-run with --apply to commit profile + transaction store.")
        return

    # --- apply: write profile balances + txn index + freshness ---
    print("\n=== Writing profile (preserving authored fields) ===")
    update_checking_savings(by_last4, as_of)
    update_credit_cards(by_last4, as_of)
    totals = update_accounts_file(by_last4, as_of)
    bank_total, card_total = totals if totals else (None, None)
    update_business_accounts(by_last4, as_of)

    # transactions index (cross-account summary + recent monthly rollups)
    def _acct_index(r):
        res = results_by_slug.get(r["slug"], {})
        monthly = res.get("monthly", {})
        years = sorted({mk[:4] for mk in monthly}, reverse=True)
        recent = dict(list(monthly.items())[:6])  # monthly is already newest-first
        return {
            "slug": r["slug"], "last4": r["last4"], "label": r["label"],
            "org": r["org"], "type": r["type"], "kind": r["kind"],
            "scope": r["scope"], "entity": r["entity"],
            "balance": r["balance"], "balance_as_of": r["balance_as_of"],
            "matched": r["matched"],
            "transaction_count": res.get("total", 0),
            "years": years,
            "dir": f"{r['slug']}/",
            "rollups_file": f"{r['slug']}/rollups.json",
            "recent_monthly": recent,
        }

    index = {
        "as_of": as_of,
        "source": "SimpleFIN (live) — written by scripts/simplefin/sync.py",
        "layout": ("Per account: transactions/<slug>/<year>.json (raw txns, dedup by id) + "
                   "transactions/<slug>/rollups.json (full monthly inflow/outflow/net). "
                   "This index carries the last 6 months per account for quick reads — "
                   "open a year partition only for line-item detail."),
        "history_earliest": hist_earliest,
        "history_latest": hist_latest,
        "transactions_total": txn_total,
        "accounts": [_acct_index(r) for r in resolved],
    }
    write_json(TXN_INDEX_PATH, index)
    print(f"  updated {TXN_INDEX_PATH.relative_to(ROOT)} ({len(resolved)} accounts, partitioned)")

    update_freshness(slugs, bank_total, card_total, txn_total, hist_earliest, hist_latest, as_of)

    print(f"\nDone. Bank ${bank_total or 0:,.2f} | Cards ${card_total or 0:,.2f} | "
          f"{txn_total} txns [{hist_earliest or '?'} … {hist_latest or '?'}]")
    if unmatched:
        print(f"⚠ {len(unmatched)} account(s) still unmatched — add them to account_map and re-run.")


if __name__ == "__main__":
    main()

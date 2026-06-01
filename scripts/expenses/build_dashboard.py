#!/usr/bin/env python3.10
"""Generate a self-contained LIGHT-MODE HTML budget dashboard from the DERIVED budget-data.json.
No external/CDN dependencies (bars rendered server-side) so it opens offline in any browser.
Output: reports/budget-dashboard.html  (DERIVED — regenerate via this script)."""
import json, os, html

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
def P(*a): return os.path.join(ROOT, *a)
D = json.load(open(P("profile", "expenses", "budget-data.json")))

def money(x, sign=False):
    s = f"${abs(x):,.0f}"
    if sign and x < 0: return f"-{s}"
    if sign and x > 0: return f"+{s}"
    return s

rr = D["runrate"]
net = rr["avg_monthly_operating_net"]
inc, spend = rr["avg_monthly_income"], rr["avg_monthly_spend"]
sav_in, sav_out, sav_net = rr["avg_monthly_savings_in"], rr["avg_monthly_savings_out"], rr["avg_monthly_savings_net"]
runrate_months = ", ".join(D["runrate_months_used"])

# ---- monthly trend (last 15 months) ----
mbt = D["monthly_by_type"]
months = sorted(mbt.keys())[-15:]
maxv = max([max(mbt[m].get("income", 0), mbt[m].get("spend", 0)) for m in months] + [1])
trend_rows = ""
for m in months:
    i = mbt[m].get("income", 0); s = mbt[m].get("spend", 0)
    n = i - s - mbt[m].get("tax", 0) - mbt[m].get("debt", 0)
    iw, sw = 100 * i / maxv, 100 * s / maxv
    ncls = "neg" if n < 0 else "pos"
    trend_rows += f"""
      <div class="trow">
        <div class="tlabel">{m}</div>
        <div class="tbars">
          <div class="tbar"><div class="fill inc" style="width:{iw:.1f}%"></div><span>{money(i)}</span></div>
          <div class="tbar"><div class="fill spd" style="width:{sw:.1f}%"></div><span>{money(s)}</span></div>
        </div>
        <div class="tnet {ncls}">{money(n, sign=True)}</div>
      </div>"""

# ---- spend by category bar chart (run-rate) ----
cats = [c for c in D["category_runrate"] if c["type"] in ("spend", "debt") and c["monthly_avg"] > 0]
cmax = max([c["monthly_avg"] for c in cats] + [1])
cat_rows = ""
for c in cats:
    w = 100 * c["monthly_avg"] / cmax
    cat_rows += f"""<div class="crow"><div class="cname">{html.escape(c['category'])}</div>
      <div class="cbarwrap"><div class="cbar" style="width:{w:.1f}%"></div></div>
      <div class="cval">{money(c['monthly_avg'])}</div></div>"""

# ---- COMPLETE category breakdown, grouped by type ----
TYPE_LABELS = [("spend", "Spending"), ("debt", "Debt / Lease"), ("tax", "Taxes (set-aside & payments)"),
               ("savings", "Savings / Investing"), ("income", "Income"),
               ("transfer", "Internal transfers (excluded from spend)")]
cb = D["category_breakdown"]
groups = ""
for tkey, tlabel in TYPE_LABELS:
    rows = [c for c in cb if c["type"] == tkey]
    if not rows: continue
    sub_mo = sum(c["monthly_avg"] for c in rows)
    trows = ""
    for c in rows:
        trows += (f"<tr><td>{html.escape(c['category'])}</td>"
                  f"<td class='r'>{money(c['monthly_avg'])}</td>"
                  f"<td class='r mut'>{money(c['all_time_total'])}</td>"
                  f"<td class='r mut'>{c['n']:,}</td></tr>")
    groups += (f"<div class='grp grp-{tkey}'><div class='grphdr'><span>{tlabel}</span>"
               f"<span class='grpsum'>{money(sub_mo)}/mo</span></div>"
               f"<table class='bt'><thead><tr><th>Category</th><th class='r'>Run-rate/mo</th>"
               f"<th class='r'>All-time</th><th class='r'>#</th></tr></thead><tbody>{trows}</tbody></table></div>")

# ---- top merchants ----
mer_rows = "".join(f"<tr><td>{html.escape(m['merchant'][:34])}</td><td class='r'>{money(m['total'])}</td></tr>"
                   for m in D["top_merchants"][:15])

# ---- flags (derived from the data, not hardcoded) ----
flags = []
if net < 0:
    flags.append(("<b>Operating shortfall</b> — spending exceeds income",
                  f"~{money(spend)}/mo spend vs ~{money(inc)}/mo income; the gap is funded by drawing down savings/investments."))
if sav_net < 0:
    flags.append(("<b>Net savings is negative</b> — drawing down, not building",
                  f"Contributing ~{money(sav_in)}/mo but withdrawing ~{money(sav_out)}/mo to cover bills."))
elif sav_in > 0:
    flags.append((f"Saving ~{money(sav_net)}/mo net", "Positive net flow into savings/investments."))
if D["needs_review"]:
    flags.append((f"{len(D['needs_review'])} merchant(s) need a category rule",
                  "Add them to profile/expenses/categories.json (payee_overrides) and re-run categorize.py."))
if not flags:
    flags.append(("Budget looks balanced", "No deficit, positive net savings, everything categorized."))
flag_html = "".join(f"<div class='flag'><div class='ftitle'>⚠ {t}</div><div class='fbody'>{b}</div></div>" for t, b in flags)
review_rows = "".join(f"<li><b>{html.escape(r['payee'])}</b> — {money(r['total_outflow'])} ({r['n']}×), <code>{html.escape(r['sample_desc'])}</code></li>"
                      for r in D["needs_review"]) or "<li>None — everything categorized.</li>"

# ---- headline alert (derived) ----
if net < 0:
    alert_html = (f'<div class="alert"><b>~{money(net)}/mo operating shortfall.</b> '
                  f'Spending (~{money(spend)}/mo) exceeds income (~{money(inc)}/mo); the gap is covered by '
                  f'drawing down savings/investments (net ~{money(sav_net, sign=True)}/mo).</div>')
else:
    alert_html = (f'<div class="alert" style="background:#dafbe1;border-color:#aceebb;color:#1a4d2e;">'
                  f'<b>Operating surplus ~{money(net)}/mo.</b> Income (~{money(inc)}/mo) covers spending '
                  f'(~{money(spend)}/mo); net ~{money(sav_net, sign=True)}/mo to savings/investments.</div>')

HTML = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Family Office — Budget Dashboard</title>
<style>
  :root {{ --bg:#f6f8fa; --card:#ffffff; --line:#d8dee4; --txt:#1f2328; --mut:#59636e;
           --inc:#1a7f37; --spd:#cf222e; --accent:#0969da; --warn:#9a6700; --chip:#eaeef2; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--txt); font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:26px; margin:0 0 4px; }}
  .sub {{ color:var(--mut); font-size:13px; margin-bottom:24px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:22px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; box-shadow:0 1px 2px rgba(31,35,40,.04); }}
  .kpi .lab {{ color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  .kpi .val {{ font-size:25px; font-weight:700; margin-top:6px; }}
  .val.neg {{ color:var(--spd); }} .val.pos {{ color:var(--inc); }}
  .alert {{ background:#fff8f0; border:1px solid #f0c38e; border-radius:12px; padding:16px 18px; margin-bottom:26px; color:#5c3b00; }}
  .alert b {{ color:var(--spd); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px 20px; margin-bottom:20px; box-shadow:0 1px 2px rgba(31,35,40,.04); }}
  .card h2 {{ font-size:15px; margin:0 0 14px; }}
  .legend span {{ font-size:12px; color:var(--mut); margin-right:16px; }}
  .dot {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:middle; }}
  .trow {{ display:grid; grid-template-columns:64px 1fr 78px; gap:10px; align-items:center; margin-bottom:7px; }}
  .tlabel {{ color:var(--mut); font-size:12px; }}
  .tbars {{ display:flex; flex-direction:column; gap:3px; }}
  .tbar {{ position:relative; height:13px; background:var(--chip); border-radius:3px; }}
  .tbar .fill {{ height:100%; border-radius:3px; }}
  .fill.inc {{ background:var(--inc); }} .fill.spd {{ background:var(--spd); }}
  .tbar span {{ position:absolute; right:6px; top:-1px; font-size:10px; color:var(--mut); }}
  .tnet {{ text-align:right; font-size:12px; font-weight:600; }}
  .tnet.neg {{ color:var(--spd); }} .tnet.pos {{ color:var(--inc); }}
  .crow {{ display:grid; grid-template-columns:180px 1fr 70px; gap:10px; align-items:center; margin-bottom:6px; }}
  .cname {{ font-size:13px; }} .cval {{ text-align:right; font-size:13px; color:var(--mut); }}
  .cbarwrap {{ background:var(--chip); border-radius:3px; height:15px; }}
  .cbar {{ height:100%; background:linear-gradient(90deg,#54aeff,var(--accent)); border-radius:3px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ text-align:left; color:var(--mut); font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:.03em; padding:4px 0; border-bottom:2px solid var(--line); }}
  td {{ padding:5px 0; border-bottom:1px solid var(--line); }}
  td.r, th.r {{ text-align:right; }} td.mut {{ color:var(--mut); }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  .grp {{ margin-bottom:18px; }}
  .grphdr {{ display:flex; justify-content:space-between; align-items:baseline; font-weight:700; font-size:14px;
             padding:6px 10px; border-radius:8px 8px 0 0; background:var(--chip); }}
  .grphdr .grpsum {{ font-size:13px; color:var(--mut); font-weight:600; }}
  .grp-spend .grphdr {{ background:#ffebe9; }} .grp-income .grphdr {{ background:#dafbe1; }}
  .grp-savings .grphdr {{ background:#ddf4ff; }} .grp-tax .grphdr {{ background:#fff1e5; }}
  .grp table {{ padding:0 10px; }}
  .flag {{ border-left:3px solid var(--warn); padding:8px 12px; margin-bottom:10px; background:#fff8f0; border-radius:0 8px 8px 0; }}
  .ftitle {{ font-size:13px; }} .fbody {{ font-size:12px; color:var(--mut); margin-top:2px; }}
  code {{ background:var(--chip); padding:1px 5px; border-radius:4px; font-size:12px; }}
  .foot {{ color:var(--mut); font-size:11px; margin-top:24px; line-height:1.6; }}
  @media(max-width:720px){{ .kpis{{grid-template-columns:repeat(2,1fr);}} .cols{{grid-template-columns:1fr;}} .crow{{grid-template-columns:120px 1fr 60px;}} }}
</style></head><body><div class="wrap">
  <h1>Budget Dashboard</h1>
  <div class="sub">Family Office · as of {D['as_of']} · run-rate from complete months ({runrate_months}) · live SimpleFIN + optional CSV history</div>

  <div class="kpis">
    <div class="kpi"><div class="lab">Avg income / mo</div><div class="val">{money(inc)}</div></div>
    <div class="kpi"><div class="lab">Avg spend / mo</div><div class="val">{money(spend)}</div></div>
    <div class="kpi"><div class="lab">Operating net / mo</div><div class="val {'neg' if net<0 else 'pos'}">{money(net, sign=True)}</div></div>
    <div class="kpi"><div class="lab">Net to savings/invest</div><div class="val {'neg' if sav_net<0 else 'pos'}">{money(sav_net, sign=True)}</div></div>
  </div>

  {alert_html}

  <div class="card">
    <h2>Income vs. Spend — last {len(months)} months</h2>
    <div class="legend"><span><i class="dot" style="background:var(--inc)"></i>Income</span><span><i class="dot" style="background:var(--spd)"></i>Spend</span><span>operating net at right</span></div>
    <div style="margin-top:12px">{trend_rows}</div>
  </div>

  <div class="card">
    <h2>Top spending categories — monthly run-rate</h2>
    {cat_rows}
  </div>

  <div class="card">
    <h2>All categories — full breakdown by type</h2>
    <div class="sub" style="margin:-6px 0 14px">Run-rate/mo = average over {runrate_months}. All-time = total across the full YYYY–YYYY history. # = transaction count.</div>
    {groups}
  </div>

  <div class="cols">
    <div class="card"><h2>Top merchants (all-time, YYYY–YYYY)</h2><table>{mer_rows}</table></div>
    <div class="card"><h2>Notes &amp; open items</h2>{flag_html}
      <div style="margin-top:8px; font-size:13px;">Needs categorization:</div>
      <ul style="margin:6px 0 0; padding-left:18px; font-size:12px; color:var(--mut);">{review_rows}</ul>
    </div>
  </div>

  <div class="foot">
    DERIVED artifact — regenerate with <code>python3.10 scripts/expenses/categorize.py &amp;&amp; python3.10 scripts/expenses/build_dashboard.py</code>.
    Categories authored in <code>profile/expenses/categories.json</code> (seeded from your Monarch history).
    Operating net = income − spend − tax − debt; internal transfers, credit-card payments, and savings/investment moves are excluded from spend and shown separately.
  </div>
</div></body></html>"""

out = P("reports", "budget-dashboard.html")
open(out, "w").write(HTML)
print(f"Wrote {os.path.relpath(out, ROOT)} ({len(HTML):,} bytes)")

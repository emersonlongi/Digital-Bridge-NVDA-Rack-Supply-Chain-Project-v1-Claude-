"""
Taiwan AI Supply-Chain Revenue Index
Pulls monthly revenue (MOPS filings via FinMind) for a basket of Taiwan-listed
AI-hardware suppliers, computes YoY / MoM growth and an equal-weighted index by
content bucket, and writes a self-contained dashboard to docs/.

Runs unattended in GitHub Actions. No user input required.
"""
import os, csv, json, datetime, urllib.request, urllib.parse
from collections import defaultdict

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
os.makedirs(DOCS, exist_ok=True)


def load_companies():
    path = os.path.join(HERE, "data", "companies.csv")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_revenue(stock_id, start_date):
    params = {"dataset": "TaiwanStockMonthRevenue", "data_id": stock_id, "start_date": start_date}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=40) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("data", []) or []


def prev_month(y, m):
    return (y - 1, 12) if m == 1 else (y, m - 1)


def pct(x):
    return None if x is None else round(x * 100, 1)


def main():
    companies = load_companies()
    start = (datetime.date.today() - datetime.timedelta(days=800)).isoformat()
    results, missing = [], []
    period_yoy = defaultdict(list)  # (year,month) -> [yoy across companies]

    for c in companies:
        sid = c["stock_id"].strip()
        try:
            rows = fetch_revenue(sid, start)
        except Exception as e:
            print(f"[WARN] {sid} {c['name']}: fetch failed ({e})")
            missing.append(c["name"]); continue
        rev = {}
        for r in rows:
            try:
                rev[(int(r["revenue_year"]), int(r["revenue_month"]))] = float(r["revenue"])
            except (KeyError, TypeError, ValueError):
                continue
        if not rev:
            print(f"[WARN] {sid} {c['name']}: no revenue rows")
            missing.append(c["name"]); continue

        periods = sorted(rev)
        ly, lm = periods[-1]
        latest = rev[(ly, lm)]
        yoy_base = rev.get((ly - 1, lm))
        mom_base = rev.get(prev_month(ly, lm))
        yoy = (latest / yoy_base - 1) if yoy_base else None
        mom = (latest / mom_base - 1) if mom_base else None
        results.append({
            "stock_id": sid, "name": c["name"], "bucket": c["bucket"],
            "period": f"{ly}-{lm:02d}", "revenue": latest, "yoy": pct(yoy), "mom": pct(mom),
        })
        for (yy, mm) in periods:
            base = rev.get((yy - 1, mm))
            if base:
                period_yoy[(yy, mm)].append(rev[(yy, mm)] / base - 1)
        print(f"[OK] {sid} {c['name']}: {ly}-{lm:02d} YoY={pct(yoy)}% MoM={pct(mom)}%")

    yoys = [r["yoy"] for r in results if r["yoy"] is not None]
    index_yoy = round(sum(yoys) / len(yoys), 1) if yoys else None

    by_bucket = defaultdict(list)
    for r in results:
        if r["yoy"] is not None:
            by_bucket[r["bucket"]].append(r["yoy"])
    buckets = [{"bucket": b, "yoy": round(sum(v) / len(v), 1), "n": len(v)}
               for b, v in sorted(by_bucket.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))]

    hist = sorted(period_yoy)[-13:]
    history = [{"period": f"{y}-{m:02d}",
                "yoy": round(sum(period_yoy[(y, m)]) / len(period_yoy[(y, m)]) * 100, 1)}
               for (y, m) in hist]

    data = {
        "as_of_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "latest_period": max((r["period"] for r in results), default=None),
        "index_yoy": index_yoy,
        "n_companies": len(results),
        "buckets": buckets,
        "companies": sorted(results, key=lambda r: (r["yoy"] is None, -(r["yoy"] or 0))),
        "history": history,
        "missing": missing,
    }

    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_html(data))
    print(f"[DONE] companies={len(results)} index_yoy={index_yoy} missing={missing}")


def render_html(d):
    def cls(v):
        return "pos" if (v or 0) >= 0 else "neg"

    bucket_rows = "".join(
        f'<tr><td>{b["bucket"]}</td><td class="num {cls(b["yoy"])}">{b["yoy"]:+.1f}%</td>'
        f'<td class="num dim">{b["n"]}</td></tr>' for b in d["buckets"]
    )
    def company_row(r):
        yoy = ("%+.1f%%" % r["yoy"]) if r["yoy"] is not None else "n/a"
        mom = ("%+.1f%%" % r["mom"]) if r["mom"] is not None else "n/a"
        return (f'<tr><td><span class="tk">{r["stock_id"]}</span>{r["name"]}</td>'
                f'<td class="dim">{r["bucket"]}</td>'
                f'<td class="num {cls(r["yoy"])}">{yoy}</td>'
                f'<td class="num {cls(r["mom"])}">{mom}</td></tr>')
    company_rows = "".join(company_row(r) for r in d["companies"])
    labels = json.dumps([h["period"] for h in d["history"]])
    series = json.dumps([h["yoy"] for h in d["history"]])
    idx = d["index_yoy"]
    idx_txt = f"{idx:+.1f}%" if idx is not None else "n/a"
    idx_cls = cls(idx)
    missing = ("Not reporting yet / unavailable this run: " + ", ".join(d["missing"])) if d["missing"] else ""

    tpl = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Taiwan AI Supply-Chain Revenue Index</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root{--bg:#0b0f17;--card:#121826;--line:#1f2937;--ink:#e6edf6;--dim:#8b97a8;--pos:#36d399;--neg:#f87272;--accent:#5b9dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--dim);margin:0 0 24px;font-size:13px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:720px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.kpi{font-size:44px;font-weight:700;letter-spacing:-1px}.kpi.pos{color:var(--pos)}.kpi.neg{color:var(--neg)}
.klabel{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.num{text-align:right;font-variant-numeric:tabular-nums}.pos{color:var(--pos)}.neg{color:var(--neg)}.dim{color:var(--dim)}
.tk{display:inline-block;background:#1c2638;color:var(--accent);border-radius:5px;padding:1px 6px;font-size:12px;margin-right:6px}
h2{font-size:15px;margin:28px 0 10px}.foot{color:var(--dim);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:16px}
.miss{color:var(--neg);font-size:12px;margin-top:8px}
.nav{display:flex;gap:8px;margin-bottom:22px}.nav a{color:var(--dim);text-decoration:none;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--line);border-radius:8px}.nav a.active{color:#fff;background:#1c2638;border-color:#2b3a52}
</style></head><body><div class="wrap">
<nav class="nav"><a href="index.html" class="active">Revenue Index</a><a href="supplychain.html">Winning-Content Map</a><a href="scoreboard.html">Live Scoreboard</a></nav>
<h1>Taiwan AI Supply-Chain Revenue Index</h1>
<p class="sub">Monthly revenue momentum across __NCOMP__ Taiwan-listed NVIDIA-supply-chain names &middot; latest period <b>__PERIOD__</b> &middot; updated __AS_OF__</p>
<div class="grid">
  <div class="card"><div class="klabel">Index &mdash; equal-weighted YoY revenue growth</div>
    <div class="kpi __IDXCLS__">__IDX__</div>
    <div class="dim" style="font-size:12px;margin-top:6px">Average of each company's year-over-year monthly revenue change</div></div>
  <div class="card"><div class="klabel">12-month trend</div><canvas id="c" height="150"></canvas></div>
</div>
<h2>By content bucket</h2>
<div class="card"><table><thead><tr><th>Bucket</th><th class="num">YoY</th><th class="num">#</th></tr></thead>
<tbody>__BUCKETS__</tbody></table></div>
<h2>By company</h2>
<div class="card"><table><thead><tr><th>Company</th><th>Bucket</th><th class="num">YoY</th><th class="num">MoM</th></tr></thead>
<tbody>__COMPANIES__</tbody></table>
<div class="miss">__MISSING__</div></div>
<div class="foot">
<b>Method:</b> equal-weighted mean of year-over-year monthly-revenue growth for the basket, overall and by content bucket. Equal weighting is deliberate &mdash; it captures whether the AI buildout is broadening across the supply chain rather than tracking only the largest names.<br>
<b>Source:</b> company monthly revenue filings (Taiwan MOPS) via the FinMind open API. Figures are as reported by the source and not independently audited.<br>
<b>Not investment advice.</b> Built as an open research tool.
</div>
</div>
<script>
const L=__LABELS__,D=__SERIES__;
new Chart(document.getElementById('c'),{type:'line',
 data:{labels:L,datasets:[{data:D,borderColor:'#5b9dff',backgroundColor:'rgba(91,157,255,.12)',fill:true,tension:.3,pointRadius:2}]},
 options:{plugins:{legend:{display:false}},scales:{
   y:{ticks:{color:'#8b97a8',callback:v=>v+'%'},grid:{color:'#1f2937'}},
   x:{ticks:{color:'#8b97a8',maxRotation:0,autoSkip:true},grid:{display:false}}}}});
</script></body></html>"""
    return (tpl.replace("__NCOMP__", str(d["n_companies"]))
               .replace("__PERIOD__", str(d["latest_period"]))
               .replace("__AS_OF__", d["as_of_utc"])
               .replace("__IDXCLS__", idx_cls)
               .replace("__IDX__", idx_txt)
               .replace("__BUCKETS__", bucket_rows)
               .replace("__COMPANIES__", company_rows)
               .replace("__MISSING__", missing)
               .replace("__LABELS__", labels)
               .replace("__SERIES__", series))


if __name__ == "__main__":
    main()

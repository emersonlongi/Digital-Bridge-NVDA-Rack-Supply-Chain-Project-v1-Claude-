"""
Layer 3 - Live winners scoreboard.
Pulls end-of-day prices for the public NVIDIA-supply-chain names from Stooq
(free, no API key), computes 1D / 1M / 1Y performance, and writes
docs/scoreboard.html. Runs unattended in GitHub Actions alongside build.py.
"""
import csv, io, time, datetime, urllib.request
from collections import defaultdict

DOCS = "docs"

# (stooq symbol, display ticker, name, content bucket)
BASKET = [
    ("nvda.us", "NVDA", "NVIDIA", "Compute / platform"),
    ("tsm.us",  "TSM",  "TSMC (ADR)", "Foundry / packaging"),
    ("mu.us",   "MU",   "Micron", "HBM / memory"),
    ("vrt.us",  "VRT",  "Vertiv", "Power + cooling"),
    ("aph.us",  "APH",  "Amphenol", "Copper / connectors"),
    ("tel.us",  "TEL",  "TE Connectivity", "Copper / connectors"),
    ("cohr.us", "COHR", "Coherent", "Optical"),
    ("lite.us", "LITE", "Lumentum", "Optical"),
    ("fn.us",   "FN",   "Fabrinet", "Optical"),
    ("alab.us", "ALAB", "Astera Labs", "Retimers / connectivity"),
    ("crdo.us", "CRDO", "Credo", "Retimers / connectivity"),
    ("mpwr.us", "MPWR", "Monolithic Power", "Power semis"),
    ("nvts.us", "NVTS", "Navitas", "Power semis (800V)"),
    ("on.us",   "ON",   "onsemi", "Power semis"),
]


def fetch_closes(symbol):
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        text = resp.read().decode("utf-8", "replace")
    closes = []
    for row in csv.DictReader(io.StringIO(text)):
        c = row.get("Close")
        try:
            closes.append(float(c))
        except (TypeError, ValueError):
            continue
    return closes  # oldest -> newest


def chg(now, then):
    return round((now / then - 1) * 100, 1) if (then and now) else None


def main():
    rows, missing = [], []
    for sym, tk, name, bucket in BASKET:
        try:
            closes = fetch_closes(sym)
        except Exception as e:
            print(f"[WARN] {tk}: fetch failed ({e})")
            missing.append(tk); time.sleep(0.3); continue
        if len(closes) < 2:
            print(f"[WARN] {tk}: insufficient data")
            missing.append(tk); time.sleep(0.3); continue
        last = closes[-1]
        d1 = chg(last, closes[-2])
        m1 = chg(last, closes[-22]) if len(closes) >= 22 else None
        y1 = chg(last, closes[-253]) if len(closes) >= 253 else None
        rows.append({"tk": tk, "name": name, "bucket": bucket,
                     "last": round(last, 2), "d1": d1, "m1": m1, "y1": y1})
        print(f"[OK] {tk}: {last:.2f}  1D={d1}  1M={m1}  1Y={y1}")
        time.sleep(0.3)

    m1s = [r["m1"] for r in rows if r["m1"] is not None]
    y1s = [r["y1"] for r in rows if r["y1"] is not None]
    data = {
        "as_of_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "n": len(rows),
        "avg_m1": round(sum(m1s) / len(m1s), 1) if m1s else None,
        "avg_y1": round(sum(y1s) / len(y1s), 1) if y1s else None,
        "rows": rows,
        "missing": missing,
    }
    import os
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "scoreboard.html"), "w", encoding="utf-8") as f:
        f.write(render_html(data))
    print(f"[DONE] names={len(rows)} avg_1M={data['avg_m1']} avg_1Y={data['avg_y1']} missing={missing}")


NAV = ('<nav class="nav"><a href="index.html">Revenue Index</a>'
       '<a href="supplychain.html">Winning-Content Map</a>'
       '<a href="scoreboard.html" class="active">Live Scoreboard</a></nav>')


def render_html(d):
    def c(v):
        return "pos" if (v or 0) >= 0 else "neg"

    def f(v):
        return "n/a" if v is None else f"{v:+.1f}%"

    by = defaultdict(list)
    for r in d["rows"]:
        by[r["bucket"]].append(r)
    body = ""
    for bucket in sorted(by):
        body += f'<tr class="grp"><td colspan="5">{bucket}</td></tr>'
        for r in by[bucket]:
            body += (f'<tr><td><span class="tk">{r["tk"]}</span>{r["name"]}</td>'
                     f'<td class="num">${r["last"]:,.2f}</td>'
                     f'<td class="num {c(r["d1"])}">{f(r["d1"])}</td>'
                     f'<td class="num {c(r["m1"])}">{f(r["m1"])}</td>'
                     f'<td class="num {c(r["y1"])}">{f(r["y1"])}</td></tr>')
    miss = ("Unavailable this run: " + ", ".join(d["missing"])) if d["missing"] else ""
    avg_m, avg_y = f(d["avg_m1"]), f(d["avg_y1"])
    cm, cy = c(d["avg_m1"]), c(d["avg_y1"])

    tpl = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live Scoreboard - NVIDIA AI Supply Chain</title>
<style>
:root{--bg:#0b0f17;--card:#121826;--line:#1f2937;--ink:#e6edf6;--dim:#8b97a8;--pos:#36d399;--neg:#f87272;--accent:#5b9dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:24px 20px 70px}
.nav{display:flex;gap:8px;margin-bottom:22px;flex-wrap:wrap}.nav a{color:var(--dim);text-decoration:none;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--line);border-radius:8px}.nav a.active{color:#fff;background:#1c2638;border-color:#2b3a52}
h1{font-size:23px;margin:0 0 6px}.sub{color:var(--dim);margin:0 0 22px;font-size:13px}
.kpis{display:flex;gap:14px;margin-bottom:22px;flex-wrap:wrap}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;flex:1;min-width:160px}
.kpi .l{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.05em}.kpi .v{font-size:26px;font-weight:700;margin-top:4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 18px 12px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:9px 8px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;text-align:right}th:first-child{text-align:left}
.num{text-align:right;font-variant-numeric:tabular-nums}.pos{color:var(--pos)}.neg{color:var(--neg)}
.grp td{color:var(--accent);font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid #243248;padding-top:16px}
.tk{display:inline-block;background:#1c2638;color:var(--accent);border-radius:5px;padding:1px 6px;font-size:12px;margin-right:6px}
.miss{color:var(--neg);font-size:12px;margin-top:10px}
.foot{color:var(--dim);font-size:12px;margin-top:24px;border-top:1px solid var(--line);padding-top:16px;line-height:1.7}
a.inline{color:var(--accent)}
</style></head><body><div class="wrap">
__NAV__
<h1>Live Scoreboard</h1>
<p class="sub">End-of-day prices for the public NVIDIA-supply-chain names, grouped by content bucket &middot; __N__ names &middot; updated __AS_OF__</p>
<div class="kpis">
  <div class="kpi"><div class="l">Basket avg &mdash; 1 month</div><div class="v __CM__">__AVGM__</div></div>
  <div class="kpi"><div class="l">Basket avg &mdash; 1 year</div><div class="v __CY__">__AVGY__</div></div>
</div>
<div class="card"><table><thead><tr><th>Company</th><th>Last</th><th>1D</th><th>1M</th><th>1Y</th></tr></thead>
<tbody>__BODY__</tbody></table><div class="miss">__MISS__</div></div>
<div class="foot">
<b>What this is:</b> the market-performance companion to the <a class="inline" href="index.html">revenue signal</a> and the <a class="inline" href="supplychain.html">content map</a> &mdash; the investable public names in one view, equal-weighted basket averages on top.<br>
<b>Source:</b> Stooq end-of-day prices (free). Prices are end-of-day, not real-time, and may lag one session.<br>
<b>Not investment advice.</b> Open research tool.
</div>
</div></body></html>"""
    return (tpl.replace("__NAV__", NAV).replace("__N__", str(d["n"]))
               .replace("__AS_OF__", d["as_of_utc"])
               .replace("__AVGM__", avg_m).replace("__AVGY__", avg_y)
               .replace("__CM__", cm).replace("__CY__", cy)
               .replace("__BODY__", body).replace("__MISS__", miss))


if __name__ == "__main__":
    main()

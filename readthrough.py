"""
Layer 5 - AI-Rack Read-Through (the alpha layer).
Turns the live Taiwan monthly-revenue signal into a forward read for a digital-
infrastructure investor-operator (e.g. DigitalBridge): a content-weighted AI-
buildout-pace gauge, demand + design reads, a public-name read-through, and
auto-generated takeaways. Built entirely on data already pulled (FinMind Taiwan
monthly revenue) - no new data sources. Runs in GitHub Actions with the rest.
"""
import os, json, datetime, urllib.request, urllib.parse
from collections import defaultdict

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
os.makedirs(DOCS, exist_ok=True)

ACCEL, DECEL = 3.0, -3.0   # inflection thresholds: pp change in YoY growth

# stock_id : (name, theme, signal weight, [US read-through tickers])
UNIVERSE = [
    ("6669", "Wiwynn",                "ODM / rack assembly",         1.00, ["NVDA"]),
    ("2382", "Quanta",                "ODM / rack assembly",         0.90, ["NVDA"]),
    ("3231", "Wistron",               "ODM / rack assembly",         0.70, ["NVDA"]),
    ("5274", "ASPEED",                "Server management (BMC)",     0.90, ["NVDA"]),
    ("3017", "Asia Vital Components", "Liquid cooling",              0.80, ["VRT"]),
    ("3324", "Auras",                 "Liquid cooling",              0.80, ["VRT"]),
    ("2383", "Elite Material",        "Substrate / CCL",             0.70, []),
    ("3037", "Unimicron",             "Substrate / CCL",             0.60, []),
    ("4966", "Lotes",                 "Interconnect / connectors",   0.60, ["APH", "TEL"]),
    ("3665", "BizLink",               "Interconnect / connectors",   0.50, ["APH", "TEL"]),
    ("2308", "Delta Electronics",     "Power delivery",              0.50, ["VRT", "MPWR", "NVTS", "ON"]),
    ("2301", "Lite-On",               "Power delivery",              0.40, ["VRT", "MPWR", "NVTS", "ON"]),
    ("2376", "Gigabyte",              "Boards & systems",            0.50, []),
    ("8210", "Chenbro",               "Boards & systems",            0.40, []),
    ("2330", "TSMC",                  "Foundry & EMS (diversified)", 0.25, ["TSM"]),
    ("2317", "Hon Hai (Foxconn)",     "Foundry & EMS (diversified)", 0.20, []),
]

THEME_MEANING = {
    "ODM / rack assembly":         "raw AI-rack assembly volume is being deployed faster",
    "Server management (BMC)":     "total AI-server unit volume is rising (a BMC ships in every server)",
    "Liquid cooling":              "the build is going liquid-cooled for high-density racks",
    "Substrate / CCL":             "higher layer-count, higher-power Rubin-class boards are ramping",
    "Interconnect / connectors":   "copper / connector content per rack is climbing",
    "Power delivery":              "the shift to higher-density / 800V power is accelerating",
    "Boards & systems":            "broad server board and chassis demand is rising",
    "Foundry & EMS (diversified)": "the broad electronics base is moving (a noisy AI proxy)",
}
CORE_THEMES = [t for t in THEME_MEANING if "diversified" not in t]

US_NAMES = {
    "NVDA": "NVIDIA", "VRT": "Vertiv", "APH": "Amphenol", "TEL": "TE Connectivity",
    "MPWR": "Monolithic Power", "NVTS": "Navitas", "ON": "onsemi", "TSM": "TSMC (ADR)",
}
NO_PROXY = "Coherent, Lumentum, Fabrinet, Astera Labs, Credo"


def fetch_revenue(stock_id, start_date):
    params = {"dataset": "TaiwanStockMonthRevenue", "data_id": stock_id, "start_date": start_date}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params))
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8")).get("data", []) or []


def yoy_series(rev):
    out = []
    for (y, m) in sorted(rev):
        base = rev.get((y - 1, m))
        if base:
            out.append(((y, m), rev[(y, m)] / base - 1))
    return out


def company_signal(rows):
    rev = {}
    for r in rows:
        try:
            rev[(int(r["revenue_year"]), int(r["revenue_month"]))] = float(r["revenue"])
        except (KeyError, TypeError, ValueError):
            continue
    ys = yoy_series(rev)
    if not ys:
        return None
    (py, pm), yoy = ys[-1]
    vals = [v for _, v in ys]
    infl = None
    if len(vals) >= 6:
        infl = sum(vals[-3:]) / 3 - sum(vals[-6:-3]) / 3
    elif len(vals) >= 2:
        infl = vals[-1] - vals[-2]
    return {"period": f"{py}-{pm:02d}", "yoy": yoy * 100,
            "infl": None if infl is None else infl * 100}


def direction(infl):
    if infl is None:
        return "steady"
    if infl >= ACCEL:
        return "accelerating"
    if infl <= DECEL:
        return "decelerating"
    return "steady"


def wavg(pairs):
    num = sum(v * w for v, w in pairs if v is not None)
    den = sum(w for v, w in pairs if v is not None)
    return (num / den) if den else None


def build_takeaways(o_yoy, o_dir, o_infl, themes):
    dword = {"accelerating": "accelerating", "steady": "holding steady", "decelerating": "cooling"}[o_dir]
    out = []
    if o_yoy is not None:
        infl_txt = f" ({o_infl:+.0f}pp vs the prior trend)" if o_infl is not None else ""
        out.append(f"The content-weighted build signal is running about {o_yoy:+.0f}% YoY and {dword}{infl_txt}.")
    core = [(t, themes[t]) for t in CORE_THEMES if t in themes and themes[t]["infl"] is not None]
    if core:
        lead_t, lead = max(core, key=lambda kv: kv[1]["infl"])
        out.append(f"Fastest acceleration is in {lead_t.lower()} ({lead['yoy']:+.0f}% YoY, "
                   f"{lead['infl']:+.0f}pp) \u2014 {THEME_MEANING[lead_t]}.")
        decel = [t for t, info in core if info["dir"] == "decelerating"]
        if decel:
            out.append(f"Watch {decel[0].lower()}: it's decelerating ({themes[decel[0]]['infl']:+.0f}pp), "
                       f"an early flag worth tracking before the US names report.")
    hot = [n for n, key in (("liquid cooling", "Liquid cooling"),
                            ("power delivery", "Power delivery"),
                            ("substrate", "Substrate / CCL"))
           if key in themes and themes[key]["dir"] == "accelerating"]
    if hot:
        verb = "is" if len(hot) == 1 else "are"
        out.append("Operator read (design): " + " and ".join(hot) +
                   f" {verb} accelerating \u2014 a signal to build for liquid cooling and higher power "
                   "density now, not next cycle.")
    if "ODM / rack assembly" in themes:
        odm = themes["ODM / rack assembly"]
        s = {"accelerating": "strong and accelerating", "steady": "steady", "decelerating": "softening"}[odm["dir"]]
        tail = "tailwind" if odm["dir"] != "decelerating" else "caution flag"
        out.append(f"Operator read (demand): rack-assembly revenue is {s} ({odm['yoy']:+.0f}% YoY) \u2014 a {tail} "
                   f"for AI data-center capacity demand into the next prints.")
    return out


def main():
    start = (datetime.date.today() - datetime.timedelta(days=1200)).isoformat()
    companies, missing = [], []
    for sid, name, theme, weight, us in UNIVERSE:
        try:
            sig = company_signal(fetch_revenue(sid, start))
        except Exception as e:
            print(f"[WARN] {sid} {name}: {e}"); sig = None
        if not sig:
            missing.append(name); print(f"[WARN] {sid} {name}: no signal"); continue
        companies.append({"sid": sid, "name": name, "theme": theme, "weight": weight, "us": us, **sig})
        print(f"[OK] {sid} {name}: YoY={sig['yoy']:.0f}% infl={None if sig['infl'] is None else round(sig['infl'])}")

    themes = {}
    for t in THEME_MEANING:
        members = [c for c in companies if c["theme"] == t]
        if members:
            t_infl = wavg([(c["infl"], c["weight"]) for c in members])
            themes[t] = {"yoy": wavg([(c["yoy"], c["weight"]) for c in members]),
                         "infl": t_infl, "dir": direction(t_infl), "members": members}

    overall_yoy = wavg([(c["yoy"], c["weight"]) for c in companies])
    overall_infl = wavg([(c["infl"], c["weight"]) for c in companies])
    overall_dir = direction(overall_infl)

    markets = []
    for tk, disp in US_NAMES.items():
        feeders = [t for t, info in themes.items() if any(tk in c["us"] for c in info["members"])]
        if not feeders:
            continue
        infl = wavg([(themes[t]["infl"], 1) for t in feeders])
        markets.append({"tk": tk, "name": disp, "feeders": feeders, "infl": infl, "dir": direction(infl)})
    markets.sort(key=lambda x: -(x["infl"] if x["infl"] is not None else -999))

    payload = {
        "as_of_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "overall_yoy": overall_yoy, "overall_infl": overall_infl, "overall_dir": overall_dir,
        "themes": themes, "markets": markets,
        "takeaways": build_takeaways(overall_yoy, overall_dir, overall_infl, themes),
        "missing": missing,
    }
    with open(os.path.join(DOCS, "readthrough.html"), "w", encoding="utf-8") as f:
        f.write(render_html(payload))
    mt = "n/a" if overall_yoy is None else f"{round(overall_yoy)}%"
    print(f"[DONE] momentum={mt} dir={overall_dir} themes={len(themes)} missing={missing}")


NAV = ('<nav class="nav"><a href="index.html">Revenue Index</a>'
       '<a href="supplychain.html">Winning-Content Map</a>'
       '<a href="scoreboard.html">Live Scoreboard</a>'
       '<a href="news.html">Supply-Chain News</a>'
       '<a href="readthrough.html" class="active">Read-Through</a></nav>')


def render_html(d):
    arrow = {"accelerating": "\u25B2", "steady": "\u2192", "decelerating": "\u25BC"}
    dcls = {"accelerating": "pos", "steady": "dim", "decelerating": "neg"}
    dlbl = {"accelerating": "Accelerating", "steady": "Holding steady", "decelerating": "Cooling"}

    def fy(v): return "n/a" if v is None else f"{v:+.0f}%"
    def fi(v): return "n/a" if v is None else f"{v:+.0f}pp"

    o_yoy, o_dir = d["overall_yoy"], d["overall_dir"]
    momentum = "n/a" if o_yoy is None else f"{o_yoy:+.0f}%"

    takeaways = "".join(f"<li>{t}</li>" for t in d["takeaways"]) or "<li>Signal unavailable this run.</li>"

    order = CORE_THEMES + [t for t in d["themes"] if t not in CORE_THEMES]
    trows = ""
    for t in order:
        if t not in d["themes"]:
            continue
        info = d["themes"][t]
        names = ", ".join(c["name"] for c in info["members"])
        ycls = "pos" if (info["yoy"] or 0) >= 0 else "neg"
        trows += (f'<tr><td>{t}<div class="dim sm">{names}</div></td>'
                  f'<td class="num {ycls}">{fy(info["yoy"])}</td>'
                  f'<td class="num {dcls[info["dir"]]}">{arrow[info["dir"]]} {fi(info["infl"])}</td></tr>')

    mrows = ""
    for m in d["markets"]:
        mrows += (f'<tr><td><span class="tk">{m["tk"]}</span>{m["name"]}</td>'
                  f'<td class="dim sm">{", ".join(m["feeders"])}</td>'
                  f'<td class="num {dcls[m["dir"]]}">{arrow[m["dir"]]} {m["dir"]}</td></tr>')

    tpl = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI-Rack Read-Through - NVIDIA Supply Chain</title>
<style>
:root{--bg:#0b0f17;--card:#121826;--line:#1f2937;--ink:#e6edf6;--dim:#8b97a8;--pos:#36d399;--neg:#f87272;--accent:#5b9dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:26px 20px 70px}
.nav{display:flex;gap:8px;margin-bottom:22px;flex-wrap:wrap}.nav a{color:var(--dim);text-decoration:none;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--line);border-radius:8px}.nav a.active{color:#fff;background:#1c2638;border-color:#2b3a52}
h1{font-size:23px;margin:0 0 6px}.sub{color:var(--dim);margin:0 0 22px;font-size:13px}
.hero{display:grid;grid-template-columns:1.1fr 1fr;gap:16px;margin-bottom:18px}@media(max-width:680px){.hero{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.klabel{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.big{font-size:46px;font-weight:800;letter-spacing:-1px;line-height:1}.big.pos{color:var(--pos)}.big.neg{color:var(--neg)}
.badge{display:inline-block;font-size:14px;font-weight:700;padding:5px 12px;border-radius:8px;margin-top:6px}
.badge.pos{background:rgba(54,211,153,.13);color:var(--pos)}.badge.neg{background:rgba(248,114,114,.13);color:var(--neg)}.badge.dim{background:#1c2638;color:var(--dim)}
.tk{display:inline-block;background:#1c2638;color:var(--accent);border-radius:5px;padding:1px 6px;font-size:12px;margin-right:6px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.05em;color:var(--accent);margin:26px 0 10px}
ul.take{margin:0;padding-left:18px}ul.take li{margin-bottom:9px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}th.num,.num{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}.neg{color:var(--neg)}.dim{color:var(--dim)}.sm{font-size:11px;margin-top:2px}
.foot{color:var(--dim);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:16px;line-height:1.7}
a.inline{color:var(--accent)}
</style></head><body><div class="wrap">
__NAV__
<h1>AI-Rack Read-Through</h1>
<p class="sub">Translating the live Taiwan monthly-revenue signal into a forward read on AI-infrastructure demand, design direction, and the public supply-chain names &middot; updated __ASOF__</p>

<div class="hero">
  <div class="card">
    <div class="klabel">AI-buildout pace &mdash; content-weighted revenue momentum</div>
    <div class="big __OCLS__">__MOM__</div>
    <div class="dim" style="font-size:12px;margin-top:8px">YoY monthly-revenue growth across the Taiwan supply chain, weighted by each name's AI-rack content and signal purity (not equal-weighted).</div>
  </div>
  <div class="card">
    <div class="klabel">Trend (inflection)</div>
    <span class="badge __OCLS__">__ARROW__ __DIRLBL__</span>
    <div class="dim" style="font-size:12px;margin-top:10px">Whether the growth <i>rate</i> itself is accelerating or rolling over &mdash; the second derivative, which tends to move the stocks before the level does.</div>
  </div>
</div>

<h2>Takeaways &mdash; what the signal says is being prioritized</h2>
<div class="card"><ul class="take">__TAKE__</ul></div>

<h2>By content theme</h2>
<div class="card"><table><thead><tr><th>Theme</th><th class="num">YoY</th><th class="num">Inflection</th></tr></thead>
<tbody>__THEMES__</tbody></table></div>

<h2>Public-name read-through</h2>
<div class="card"><table><thead><tr><th>Name</th><th>Fed by</th><th class="num">Signal</th></tr></thead>
<tbody>__MARKETS__</tbody></table>
<div class="dim sm" style="margin-top:10px">Direction inferred from the Taiwan names that share each company's content. Optical &amp; retimer names (__NOPROXY__) have no Taiwan proxy in this basket, so the signal doesn't speak to them. Prices live on the <a class="inline" href="scoreboard.html">scoreboard</a>.</div></div>

<div class="foot">
<b>Method:</b> for each Taiwan name we compute year-over-year monthly-revenue growth and its <i>inflection</i> (last three months' YoY vs the prior three). Names are weighted by an estimate of their AI-rack content and signal purity, so diversified giants don't drown out the cleaner AI reads. Themes map to the US names that share that content. The read-through is a leading indicator &mdash; Taiwan reports monthly, weeks before the US names report quarterly.<br>
<b>Weights and mappings are estimates</b> and the revenue is as reported by the source (Taiwan MOPS via FinMind), not independently audited.<br>
<b>Not investment advice.</b> A research signal, not a recommendation &mdash; it flags what to investigate, not what to trade.
</div>
</div></body></html>"""
    return (tpl.replace("__NAV__", NAV)
               .replace("__ASOF__", d["as_of_utc"])
               .replace("__OCLS__", dcls[o_dir])
               .replace("__MOM__", momentum)
               .replace("__ARROW__", arrow[o_dir])
               .replace("__DIRLBL__", dlbl[o_dir])
               .replace("__TAKE__", takeaways)
               .replace("__THEMES__", trows)
               .replace("__MARKETS__", mrows)
               .replace("__NOPROXY__", NO_PROXY))


if __name__ == "__main__":
    main()

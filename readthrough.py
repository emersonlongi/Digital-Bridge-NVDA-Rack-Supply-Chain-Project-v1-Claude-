"""
Layer 5 - AI-Rack Read-Through (the alpha layer).
Turns the live Taiwan monthly-revenue signal into a forward read for a digital-
infrastructure investor-operator (e.g. DigitalBridge): a content-weighted AI-
buildout-pace gauge, evidence-backed reads, a content-theme breakdown, the raw
company signal, and a public-name read-through.

Every claim is shown with the numbers behind it: latest YoY, the last-3-months
vs prior-3-months trajectory (the inflection = how the growth RATE is changing),
and the company-level drivers. Built only on data already pulled (FinMind Taiwan
monthly revenue) - no new sources. Runs in GitHub Actions with the rest.
"""
import os, datetime, urllib.request, urllib.parse, json

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
os.makedirs(DOCS, exist_ok=True)

ACCEL, DECEL = 3.0, -3.0   # inflection thresholds (pp change in YoY growth rate)

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
    "ODM / rack assembly":         "raw AI-rack assembly volume being deployed",
    "Server management (BMC)":     "total AI-server unit volume (a BMC ships in every server)",
    "Liquid cooling":              "the build going liquid-cooled for high-density racks",
    "Substrate / CCL":             "higher layer-count, higher-power Rubin-class boards ramping",
    "Interconnect / connectors":   "copper / connector content per rack",
    "Power delivery":              "the shift to higher-density / 800V power",
    "Boards & systems":            "broad server board and chassis demand",
    "Foundry & EMS (diversified)": "the broad electronics base (a noisy AI proxy)",
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
    (py, pm), _ = ys[-1]
    vals = [v for _, v in ys]
    latest = vals[-1]
    recent3 = sum(vals[-3:]) / len(vals[-3:])
    if len(vals) >= 6:
        prior3 = sum(vals[-6:-3]) / 3
    elif len(vals) > 3:
        prior3 = sum(vals[:-3]) / len(vals[:-3])
    else:
        prior3 = None
    if prior3 is not None:
        infl = recent3 - prior3
    elif len(vals) >= 2:
        infl = vals[-1] - vals[-2]
    else:
        infl = None
    return {"period": f"{py}-{pm:02d}", "yoy": latest * 100, "recent3": recent3 * 100,
            "prior3": None if prior3 is None else prior3 * 100,
            "infl": None if infl is None else infl * 100, "n": len(vals)}


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


def agg(members):
    return {"yoy":     wavg([(c["yoy"], c["weight"]) for c in members]),
            "recent3": wavg([(c["recent3"], c["weight"]) for c in members]),
            "prior3":  wavg([(c["prior3"], c["weight"]) for c in members]),
            "infl":    wavg([(c["infl"], c["weight"]) for c in members])}


def _fy(v): return "n/a" if v is None else f"{v:+.0f}%"
def _fp(v): return "n/a" if v is None else f"{v:+.0f}pp"


def build_reads(ov, odir, themes):
    dword = {"accelerating": "accelerating", "steady": "holding steady", "decelerating": "cooling"}[odir]
    reads = []
    reads.append({
        "claim": f"The AI-buildout signal is {dword}.",
        "ev": (f"Content-weighted revenue is running {_fy(ov['yoy'])} YoY. The last 3 months averaged "
               f"{_fy(ov['recent3'])} vs {_fy(ov['prior3'])} the prior 3 \u2014 a {_fp(ov['infl'])} "
               f"change in the growth rate itself."),
        "why": ("Taiwan reports monthly, weeks ahead of the US names' quarterly prints, so this "
                "rate-of-change is an early read on AI data-center demand."),
    })
    core = [(t, themes[t]) for t in CORE_THEMES if t in themes and themes[t]["infl"] is not None]
    if core:
        lt, li = max(core, key=lambda kv: kv[1]["infl"])
        drv = sorted(li["members"], key=lambda c: (c["yoy"] if c["yoy"] is not None else -1e9), reverse=True)[:2]
        reads.append({
            "claim": f"Fastest acceleration: {lt.lower()}.",
            "ev": (f"{_fy(li['yoy'])} YoY, inflection {_fp(li['infl'])} (last 3mo {_fy(li['recent3'])} "
                   f"vs prior {_fy(li['prior3'])}). Drivers: "
                   + ", ".join(f"{c['name']} {_fy(c['yoy'])}" for c in drv) + "."),
            "why": f"Reads as {THEME_MEANING[lt]} \u2014 speeding up.",
        })
        cooling = [(t, i) for t, i in core if i["dir"] == "decelerating"]
        if cooling:
            ct, ci = min(cooling, key=lambda kv: kv[1]["infl"])
            soft = sorted(ci["members"], key=lambda c: (c["infl"] if c["infl"] is not None else 1e9))[:2]
            reads.append({
                "claim": f"Cooling \u2014 watch {ct.lower()}.",
                "ev": (f"Still {_fy(ci['yoy'])} YoY, but inflection {_fp(ci['infl'])} (last 3mo "
                       f"{_fy(ci['recent3'])} vs prior {_fy(ci['prior3'])}). Softest: "
                       + ", ".join(f"{c['name']} {_fp(c['infl'])}" for c in soft) + "."),
                "why": (f"The growth rate is rolling over while the level is still high \u2014 {THEME_MEANING[ct]}, "
                        "losing pace. An early flag worth tracking before the US names report."),
            })
    hot = [t for t in ("Liquid cooling", "Power delivery", "Substrate / CCL")
           if t in themes and themes[t]["dir"] == "accelerating"]
    if hot:
        reads.append({
            "claim": "Operator read \u2014 design: build for density now.",
            "ev": "Accelerating: " + "; ".join(
                f"{t.lower()} ({_fy(themes[t]['yoy'])}, {_fp(themes[t]['infl'])})" for t in hot) + ".",
            "why": ("Cooling, power and substrate content rise together as racks get denser and hotter \u2014 "
                    "a signal to design for liquid cooling and higher-voltage power this cycle, not next."),
        })
    if "ODM / rack assembly" in themes:
        od = themes["ODM / rack assembly"]
        tail = "a tailwind" if od["dir"] != "decelerating" else "a caution flag"
        reads.append({
            "claim": "Operator read \u2014 demand: rack-assembly pace.",
            "ev": (f"{_fy(od['yoy'])} YoY, inflection {_fp(od['infl'])} (last 3mo {_fy(od['recent3'])} "
                   f"vs prior {_fy(od['prior3'])})."),
            "why": (f"Rack assembly is the rawest read on AI systems actually shipping \u2014 {tail} for "
                    "data-center capacity demand into the next prints."),
        })
    return reads


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
            a = agg(members)
            themes[t] = {**a, "dir": direction(a["infl"]), "members": members, "meaning": THEME_MEANING[t]}

    a = agg(companies)
    overall_dir = direction(a["infl"])

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
        "overall": a, "overall_dir": overall_dir,
        "reads": build_reads(a, overall_dir, themes),
        "themes": themes, "companies": companies, "markets": markets, "missing": missing,
    }
    with open(os.path.join(DOCS, "readthrough.html"), "w", encoding="utf-8") as f:
        f.write(render_html(payload))
    mt = "n/a" if a["yoy"] is None else f"{round(a['yoy'])}%"
    print(f"[DONE] momentum={mt} dir={overall_dir} themes={len(themes)} reads={len(payload['reads'])} missing={missing}")


NAV = '<div id="nav"></div><script src="nav.js"></script>'


def render_html(d):
    arrow = {"accelerating": "\u25B2", "steady": "\u2192", "decelerating": "\u25BC"}
    dcls = {"accelerating": "pos", "steady": "dim", "decelerating": "neg"}
    dlbl = {"accelerating": "Accelerating", "steady": "Holding steady", "decelerating": "Cooling"}

    def fy(v): return "n/a" if v is None else f"{v:+.0f}%"
    def fp(v): return "n/a" if v is None else f"{v:+.0f}pp"
    def ycls(v): return "pos" if (v or 0) >= 0 else "neg"

    ov, odir = d["overall"], d["overall_dir"]
    momentum = fy(ov["yoy"])
    omath = f'last 3mo {fy(ov["recent3"])} &middot; prior 3mo {fy(ov["prior3"])} &middot; \u0394 {fp(ov["infl"])}'

    reads = "".join(
        f'<div class="read"><div class="claim">{r["claim"]}</div>'
        f'<div class="ev">{r["ev"]}</div><div class="why">{r["why"]}</div></div>'
        for r in d["reads"]) or '<div class="read"><div class="ev">Signal unavailable this run.</div></div>'

    order = CORE_THEMES + [t for t in d["themes"] if t not in CORE_THEMES]
    trows = ""
    for t in order:
        if t not in d["themes"]:
            continue
        info = d["themes"][t]
        chips = "".join(
            f'<span class="chip">{c["name"]} <b class="{ycls(c["yoy"])}">{fy(c["yoy"])}</b></span>'
            for c in sorted(info["members"], key=lambda c: (c["yoy"] if c["yoy"] is not None else -1e9), reverse=True))
        trows += (f'<tr><td>{t}'
                  f'<div class="sub">last 3mo {fy(info["recent3"])} vs prior 3mo {fy(info["prior3"])} '
                  f'&middot; signals {info["meaning"]}</div><div class="chips">{chips}</div></td>'
                  f'<td class="num {ycls(info["yoy"])}">{fy(info["yoy"])}</td>'
                  f'<td class="num {dcls[info["dir"]]}">{arrow[info["dir"]]} {fp(info["infl"])}</td></tr>')

    crows = ""
    for c in sorted(d["companies"], key=lambda c: -c["weight"]):
        cdir = direction(c["infl"])
        crows += (f'<tr><td><span class="tk">{c["sid"]}</span>{c["name"]}</td>'
                  f'<td class="dim sm">{c["theme"]}</td>'
                  f'<td class="num {ycls(c["yoy"])}">{fy(c["yoy"])}</td>'
                  f'<td class="num {dcls[cdir]}">{fp(c["infl"])}</td>'
                  f'<td class="num dim">{c["weight"]:.2f}</td></tr>')

    mrows = ""
    for m in d["markets"]:
        mrows += (f'<tr><td><span class="tk">{m["tk"]}</span>{m["name"]}</td>'
                  f'<td class="dim sm">{", ".join(m["feeders"])}</td>'
                  f'<td class="num {dcls[m["dir"]]}">{arrow[m["dir"]]} {m["dir"]}</td></tr>')

    miss = ""
    if d["missing"]:
        miss = f'<div class="dim sm" style="margin-top:10px">No signal this run: {", ".join(d["missing"])}.</div>'

    tpl = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI-Rack Read-Through - NVIDIA Supply Chain</title>
<style>
:root{--bg:#0b0f17;--card:#121826;--line:#1f2937;--ink:#e6edf6;--dim:#8b97a8;--pos:#36d399;--neg:#f87272;--accent:#5b9dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:26px 20px 70px}
.nav{display:flex;gap:8px;margin-bottom:22px;flex-wrap:wrap}.nav a{color:var(--dim);text-decoration:none;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--line);border-radius:8px}.nav a.active{color:#fff;background:#1c2638;border-color:#2b3a52}
h1{font-size:23px;margin:0 0 6px}.sub-h{color:var(--dim);margin:0 0 22px;font-size:13px}
.hero{display:grid;grid-template-columns:1.1fr 1fr;gap:16px;margin-bottom:8px}@media(max-width:680px){.hero{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.klabel{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.big{font-size:46px;font-weight:800;letter-spacing:-1px;line-height:1}.big.pos{color:var(--pos)}.big.neg{color:var(--neg)}
.badge{display:inline-block;font-size:14px;font-weight:700;padding:5px 12px;border-radius:8px;margin-top:4px}
.badge.pos{background:rgba(54,211,153,.13);color:var(--pos)}.badge.neg{background:rgba(248,114,114,.13);color:var(--neg)}.badge.dim{background:#1c2638;color:var(--dim)}
.mono{font-variant-numeric:tabular-nums;color:var(--ink);font-size:13px;margin-top:12px;background:#0e1422;border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.tk{display:inline-block;background:#1c2638;color:var(--accent);border-radius:5px;padding:1px 6px;font-size:12px;margin-right:6px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.05em;color:var(--accent);margin:28px 0 6px}.hint{color:var(--dim);font-size:12px;margin:0 0 12px}
.read{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.read .claim{font-weight:700;font-size:15px;margin-bottom:7px}
.read .ev{font-variant-numeric:tabular-nums;font-size:13px;background:#0e1422;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px}
.read .why{color:var(--dim);font-size:13px;line-height:1.55}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}th.num,.num{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}.neg{color:var(--neg)}.dim{color:var(--dim)}.sm{font-size:11px}
.sub{font-size:11.5px;color:var(--dim);margin-top:3px;line-height:1.5}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{font-size:11px;color:var(--dim);background:#0e1422;border:1px solid var(--line);border-radius:6px;padding:2px 7px}.chip b{font-weight:700}
.foot{color:var(--dim);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:16px;line-height:1.7}
a.inline{color:var(--accent)}
</style></head><body><div class="wrap">
__NAV__
<h1>AI-Rack Read-Through</h1>
<p class="sub-h">The live Taiwan monthly-revenue signal, read forward for AI-infrastructure demand, design direction, and the public supply-chain names &middot; updated __ASOF__</p>

<div class="hero">
  <div class="card">
    <div class="klabel">AI-buildout pace &mdash; content-weighted YoY</div>
    <div class="big __OCLS__">__MOM__</div>
    <div class="dim" style="font-size:12px;margin-top:8px">Monthly-revenue growth across the Taiwan supply chain, weighted by each name's AI-rack content and signal purity (not equal-weighted).</div>
  </div>
  <div class="card">
    <div class="klabel">Trend (the inflection)</div>
    <span class="badge __OCLS__">__ARROW__ __DIRLBL__</span>
    <div class="mono">__OMATH__</div>
    <div class="dim" style="font-size:12px;margin-top:8px">Whether the growth <i>rate</i> is speeding up or rolling over &mdash; last 3 months' YoY vs the prior 3. This tends to move the stocks before the level does.</div>
  </div>
</div>

<h2>Reads</h2>
<p class="hint">What the signal says &mdash; each with the numbers behind it, then what it means and why.</p>
__READS__

<h2>By content theme</h2>
<p class="hint">Content-weighted growth and inflection per theme, with the company drivers and what an acceleration there signals.</p>
<div class="card"><table><thead><tr><th>Theme &amp; drivers</th><th class="num">YoY</th><th class="num">Inflection</th></tr></thead>
<tbody>__THEMES__</tbody></table></div>

<h2>Raw signal &mdash; all names</h2>
<p class="hint">The underlying company data the reads are built from. Inflection = last-3-month avg YoY minus prior-3-month avg YoY. Weight = estimated AI-rack content &times; signal purity.</p>
<div class="card"><table><thead><tr><th>Company</th><th>Theme</th><th class="num">YoY</th><th class="num">Inflection</th><th class="num">Wt</th></tr></thead>
<tbody>__COMPANIES__</tbody></table>__MISS__</div>

<h2>Public-name read-through</h2>
<div class="card"><table><thead><tr><th>Name</th><th>Fed by</th><th class="num">Signal</th></tr></thead>
<tbody>__MARKETS__</tbody></table>
<div class="sub" style="margin-top:10px">Direction inferred from the Taiwan names that share each company's content. Optical &amp; retimer names (__NOPROXY__) have no Taiwan proxy in this basket, so the signal doesn't speak to them. Prices live on the <a class="inline" href="scoreboard.html">scoreboard</a>.</div></div>

<div class="foot">
<b>Method:</b> for each Taiwan name we compute year-over-year monthly-revenue growth and its <i>inflection</i> &mdash; the last three months' average YoY minus the prior three months'. A positive inflection means growth is accelerating; negative means it's cooling even if still positive. Names are content-weighted so diversified giants don't drown out the cleaner AI reads, then grouped into themes that map to the US names sharing that content. Taiwan reports monthly, weeks before the US names report quarterly &mdash; that lead is the edge.<br>
<b>Weights and mappings are estimates;</b> revenue is as reported by the source (Taiwan MOPS via FinMind), not independently audited.<br>
<b>Not investment advice</b> &mdash; a research signal that flags what to investigate, not what to trade.
</div>
</div></body></html>"""
    return (tpl.replace("__NAV__", NAV).replace("__ASOF__", d["as_of_utc"])
               .replace("__OCLS__", dcls[odir]).replace("__MOM__", momentum)
               .replace("__ARROW__", arrow[odir]).replace("__DIRLBL__", dlbl[odir])
               .replace("__OMATH__", omath).replace("__READS__", reads)
               .replace("__THEMES__", trows).replace("__COMPANIES__", crows)
               .replace("__MARKETS__", mrows).replace("__MISS__", miss)
               .replace("__NOPROXY__", NO_PROXY))


if __name__ == "__main__":
    main()

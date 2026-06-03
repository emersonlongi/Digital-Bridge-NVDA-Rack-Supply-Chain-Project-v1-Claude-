"""
Layer 6 - Grid Demand Pulse (the power-constraint signal).
Power, not chips, is the binding constraint on the AI buildout. This pulls
electricity DEMAND from the EIA API for the specific US balancing authorities
where AI data centers cluster (Dominion/N. Virginia, ERCOT, Georgia, Phoenix,
Oregon, California), aggregates daily -> monthly, and applies the same
inflection framing as the read-through: latest YoY, last-3-months vs prior-3
(how the growth RATE is changing), datacenter-intensity weighted.

The edge is the decomposition by datacenter grid + the second derivative, not
the raw source. Tailored for a digital-infrastructure operator (DigitalBridge):
where demand is hottest is where power is scarcest and siting value highest.
Runs in GitHub Actions alongside the other scripts. Needs EIA_API_KEY (free).
"""
import os, datetime, json, urllib.request, urllib.parse
from collections import defaultdict

BASE = "https://api.eia.gov/v2/electricity/rto/daily-region-data/data/"
KEY = os.environ.get("EIA_API_KEY", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
os.makedirs(DOCS, exist_ok=True)

ACCEL, DECEL = 2.0, -2.0   # pp change in YoY growth rate (grids move slower than revenue)

# EIA-930 balancing authority : (display, coverage, datacenter-intensity weight)
# Weight estimates how cleanly each grid's total demand reads as a datacenter
# signal (datacenter share x how concentrated the load is). Dominion is the
# purest; California is power-constrained so growth understates demand.
GRIDS = [
    ("DOM",  "Dominion",              "Northern Virginia - 'data center alley'", 1.00),
    ("ERCO", "ERCOT",                 "Texas",                                    0.70),
    ("SOCO", "Southern Company",      "Georgia / Southeast",                      0.60),
    ("AZPS", "Arizona Public Service","Phoenix metro",                            0.60),
    ("PACW", "PacifiCorp West",       "Oregon / Pacific NW",                      0.50),
    ("CISO", "California ISO",         "California",                              0.40),
]


def fetch_raw(respondent, start_date):
    params = [
        ("frequency", "daily"),
        ("data[0]", "value"),
        ("facets[respondent][]", respondent),
        ("facets[type][]", "D"),            # D = demand
        ("start", start_date),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
        ("offset", "0"),
        ("length", "5000"),
        ("api_key", KEY),
    ]
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    return j.get("response", {}).get("data", []) or []


def to_monthly(rows):
    """daily demand rows -> {(year, month): mean daily demand}."""
    buckets = defaultdict(list)
    for r in rows:
        p = str(r.get("period", ""))
        parts = p.split("-")
        if len(parts) < 2:
            continue
        try:
            y, m = int(parts[0]), int(parts[1])
            val = float(r.get("value"))
        except (ValueError, TypeError):
            continue
        buckets[(y, m)].append(val)
    return {k: sum(v) / len(v) for k, v in buckets.items() if v}


def yoy_series(rev):
    out = []
    for (y, m) in sorted(rev):
        base = rev.get((y - 1, m))
        if base:
            out.append(((y, m), rev[(y, m)] / base - 1))
    return out


def signal(monthly):
    ys = yoy_series(monthly)
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


def _fy(v): return "n/a" if v is None else f"{v:+.1f}%"
def _fp(v): return "n/a" if v is None else f"{v:+.1f}pp"


def build_reads(ov, odir, grids):
    dword = {"accelerating": "accelerating", "steady": "holding steady", "decelerating": "cooling"}[odir]
    reads = []
    reads.append({
        "claim": f"Power demand across datacenter grids is {dword}.",
        "ev": (f"Content-weighted demand is running {_fy(ov['yoy'])} YoY. The last 3 months averaged "
               f"{_fy(ov['recent3'])} vs {_fy(ov['prior3'])} the prior 3 \u2014 a {_fp(ov['infl'])} "
               f"change in the growth rate."),
        "why": ("Power, not chips, is the gating constraint on AI capacity \u2014 this is the arena a "
                "digital-infrastructure operator competes in. Accelerating demand means capacity is "
                "tightening and energized sites gain scarcity value."),
    })
    have = [g for g in grids if g["yoy"] is not None]
    if have:
        hot = max(have, key=lambda g: g["yoy"])
        reads.append({
            "claim": f"Fastest-growing grid: {hot['disp']} ({hot['cover']}).",
            "ev": (f"{_fy(hot['yoy'])} YoY, inflection {_fp(hot['infl'])} "
                   f"(last 3mo {_fy(hot['recent3'])} vs prior {_fy(hot['prior3'])})."),
            "why": ("This is where load is climbing fastest \u2014 so where power headroom is scarcest and "
                    "the value of an energized site or a live interconnection position is highest."),
        })
        cool = [g for g in have if g["dir"] == "decelerating"]
        if cool:
            c = min(cool, key=lambda g: (g["infl"] if g["infl"] is not None else 1e9))
            reads.append({
                "claim": f"Cooling \u2014 watch {c['disp']} ({c['cover']}).",
                "ev": (f"Still {_fy(c['yoy'])} YoY but inflection {_fp(c['infl'])} "
                       f"(last 3mo {_fy(c['recent3'])} vs prior {_fy(c['prior3'])})."),
                "why": ("In a hot datacenter grid, cooling demand growth often isn't weak demand \u2014 it's "
                        "the ceiling: grid headroom or interconnection queues throttling what can connect. "
                        "Worth watching as a sign power is becoming the hard limit there."),
            })
        if len(have) >= 2:
            lo = min(have, key=lambda g: g["yoy"])
            spread = hot["yoy"] - lo["yoy"]
            reads.append({
                "claim": "Where power is scarce, it gets priced.",
                "ev": (f"{hot['disp']} {_fy(hot['yoy'])} vs {lo['disp']} {_fy(lo['yoy'])} "
                       f"\u2014 a {spread:.0f}pp spread in demand growth across grids."),
                "why": ("Demand isn't uniform \u2014 it concentrates where land, power and fiber line up. "
                        "Whoever holds energized capacity or queue position in the hottest grids has "
                        "pricing power; that scarcity is the asset digital-infra deals underwrite."),
            })
    return reads


def main():
    start = (datetime.date.today() - datetime.timedelta(days=1200)).isoformat()
    grids, missing = [], []
    for code, disp, cover, weight in GRIDS:
        try:
            sig = signal(to_monthly(fetch_raw(code, start)))
        except Exception as e:
            print(f"[WARN] {code} {disp}: {e}"); sig = None
        if not sig:
            missing.append(disp); print(f"[WARN] {code} {disp}: no signal"); continue
        grids.append({"code": code, "disp": disp, "cover": cover, "weight": weight,
                      "dir": direction(sig["infl"]), **sig})
        print(f"[OK] {code} {disp}: YoY={sig['yoy']:.1f}% infl={None if sig['infl'] is None else round(sig['infl'],1)}")

    ov = {"yoy":     wavg([(g["yoy"], g["weight"]) for g in grids]),
          "recent3": wavg([(g["recent3"], g["weight"]) for g in grids]),
          "prior3":  wavg([(g["prior3"], g["weight"]) for g in grids]),
          "infl":    wavg([(g["infl"], g["weight"]) for g in grids])}
    odir = direction(ov["infl"])

    payload = {
        "as_of_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "overall": ov, "overall_dir": odir,
        "reads": build_reads(ov, odir, grids),
        "grids": grids, "missing": missing,
    }
    with open(os.path.join(DOCS, "power.html"), "w", encoding="utf-8") as f:
        f.write(render_html(payload))
    mt = "n/a" if ov["yoy"] is None else f"{round(ov['yoy'],1)}%"
    print(f"[DONE] pulse={mt} dir={odir} grids={len(grids)} reads={len(payload['reads'])} missing={missing}")


NAV = '<div id="nav"></div><script src="nav.js"></script>'


def render_html(d):
    arrow = {"accelerating": "\u25B2", "steady": "\u2192", "decelerating": "\u25BC"}
    dcls = {"accelerating": "pos", "steady": "dim", "decelerating": "neg"}
    dlbl = {"accelerating": "Accelerating", "steady": "Holding steady", "decelerating": "Cooling"}

    def fy(v): return "n/a" if v is None else f"{v:+.1f}%"
    def fp(v): return "n/a" if v is None else f"{v:+.1f}pp"
    def yc(v): return "pos" if (v or 0) >= 0 else "neg"

    ov, odir = d["overall"], d["overall_dir"]
    momentum = fy(ov["yoy"])
    omath = f'last 3mo {fy(ov["recent3"])} &middot; prior 3mo {fy(ov["prior3"])} &middot; \u0394 {fp(ov["infl"])}'

    reads = "".join(
        f'<div class="read"><div class="claim">{r["claim"]}</div>'
        f'<div class="ev">{r["ev"]}</div><div class="why">{r["why"]}</div></div>'
        for r in d["reads"]) or '<div class="read"><div class="ev">Signal unavailable this run.</div></div>'

    grows = ""
    for g in sorted(d["grids"], key=lambda g: -(g["yoy"] if g["yoy"] is not None else -1e9)):
        grows += (f'<tr><td><span class="tk">{g["code"]}</span>{g["disp"]}'
                  f'<div class="sub">{g["cover"]} &middot; last 3mo {fy(g["recent3"])} vs prior 3mo {fy(g["prior3"])} '
                  f'&middot; weight {g["weight"]:.2f}</div></td>'
                  f'<td class="num {yc(g["yoy"])}">{fy(g["yoy"])}</td>'
                  f'<td class="num {dcls[g["dir"]]}">{arrow[g["dir"]]} {fp(g["infl"])}</td></tr>')

    miss = ""
    if d["missing"]:
        miss = f'<div class="dim sm" style="margin-top:10px">No signal this run: {", ".join(d["missing"])}.</div>'

    tpl = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grid Demand Pulse - NVIDIA AI Supply Chain</title>
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
.foot{color:var(--dim);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:16px;line-height:1.7}
a.inline{color:var(--accent)}
</style></head><body><div class="wrap">
__NAV__
<h1>Grid Demand Pulse</h1>
<p class="sub-h">How fast electricity demand is growing in the US grids where AI data centers cluster &mdash; the binding constraint on the buildout, read forward &middot; updated __ASOF__</p>

<div class="hero">
  <div class="card">
    <div class="klabel">Datacenter-grid demand &mdash; content-weighted YoY</div>
    <div class="big __OCLS__">__MOM__</div>
    <div class="dim" style="font-size:12px;margin-top:8px">Electricity demand growth across the balancing authorities that host the major datacenter hubs, weighted by each grid's datacenter intensity (not equal-weighted).</div>
  </div>
  <div class="card">
    <div class="klabel">Trend (the inflection)</div>
    <span class="badge __OCLS__">__ARROW__ __DIRLBL__</span>
    <div class="mono">__OMATH__</div>
    <div class="dim" style="font-size:12px;margin-top:8px">Whether demand growth is speeding up or rolling over &mdash; last 3 months' YoY vs the prior 3. A roll-over in a hot grid can mean power is hitting its ceiling.</div>
  </div>
</div>

<h2>Reads</h2>
<p class="hint">What the signal says &mdash; each with the numbers behind it, then what it means and why, for an infrastructure operator.</p>
__READS__

<h2>By grid</h2>
<p class="hint">Demand growth and inflection per balancing authority, ranked by how fast load is climbing.</p>
<div class="card"><table><thead><tr><th>Grid &amp; coverage</th><th class="num">YoY</th><th class="num">Inflection</th></tr></thead>
<tbody>__GRIDS__</tbody></table>__MISS__</div>

<div class="foot">
<b>Method:</b> daily electricity demand for each balancing authority from the EIA API (Hourly Grid Monitor, EIA-930), averaged to monthly, then year-over-year growth and its <i>inflection</i> &mdash; last three months' average YoY minus the prior three. Grids are weighted by an estimate of their datacenter intensity. Pairs with the <a class="inline" href="readthrough.html">read-through</a> (the component/demand pulse from Taiwan): this is the power/capacity side of the same story.<br>
<b>This is total grid demand as a proxy for datacenter load,</b> not a direct datacenter meter &mdash; it's confounded by weather and economic growth. Year-over-year comparison controls for normal seasonality, but an unusually hot or cold year still moves it; read the cross-grid differences and the inflection, not the absolute level. Weights are estimates.<br>
<b>Not investment advice</b> &mdash; a research signal that flags where to look, not what to trade.
</div>
</div></body></html>"""
    return (tpl.replace("__NAV__", NAV).replace("__ASOF__", d["as_of_utc"])
               .replace("__OCLS__", dcls[odir]).replace("__MOM__", momentum)
               .replace("__ARROW__", arrow[odir]).replace("__DIRLBL__", dlbl[odir])
               .replace("__OMATH__", omath).replace("__READS__", reads)
               .replace("__GRIDS__", grows).replace("__MISS__", miss))


if __name__ == "__main__":
    main()

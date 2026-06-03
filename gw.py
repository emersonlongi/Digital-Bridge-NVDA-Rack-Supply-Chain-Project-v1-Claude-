"""
Layer 7 - Gigawatts in Transit (the cross-domain signal).
The one metric that lives on the bridge almost nobody covers: it translates the
Taiwan AI-rack component pulse into GIGAWATTS of datacenter capacity shipping
toward the grid, then compares that against how fast US datacenter grids are
actually energizing - the gap being the wave still coming.

Honesty model: the GROWTH and the energization GAP are units-independent and
solid (they're just revenue growth vs grid-demand growth). The ABSOLUTE GW level
rests on four stated, tunable assumptions shown on the page - read it as an
order-of-magnitude estimate and watch the trend. Uses data already pulled
(FinMind Taiwan revenue + EIA grid demand). Needs FINMIND_TOKEN and EIA_API_KEY.
"""
import os, datetime, json, urllib.request, urllib.parse
from collections import defaultdict

FINMIND_API = "https://api.finmindtrade.com/api/v4/data"
EIA_BASE = "https://api.eia.gov/v2/electricity/rto/daily-region-data/data/"
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
EIA_API_KEY = os.environ.get("EIA_API_KEY", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
os.makedirs(DOCS, exist_ok=True)

ACCEL, DECEL = 3.0, -3.0

# AI rack ODMs whose monthly revenue most directly tracks rack/system shipments
FEEDERS = [("6669", "Wiwynn"), ("2382", "Quanta"), ("3231", "Wistron")]

# --- stated assumptions (all estimates; shown on the page, tunable here) ---
AI_SHARE = 0.55             # est. share of these ODMs' revenue that is AI rack/server
ASP_PER_RACK_USD = 3_000_000  # est. revenue per AI rack-system (GB200/GB300 NVL-class)
KW_PER_RACK = 130           # est. power draw per current-gen AI rack
TWD_PER_USD = 32.0          # est. FX
REVENUE_TO_TWD = 1000.0     # FinMind revenue field -> TWD (MOPS reports thousands of TWD); calibrate via run log

# datacenter grids for the energization side (same as the Grid Demand Pulse)
GRIDS = [("DOM", 1.00), ("ERCO", 0.70), ("SOCO", 0.60),
         ("AZPS", 0.60), ("PACW", 0.50), ("CISO", 0.40)]


def fetch_revenue(stock_id, start_date):
    params = {"dataset": "TaiwanStockMonthRevenue", "data_id": stock_id, "start_date": start_date}
    req = urllib.request.Request(FINMIND_API + "?" + urllib.parse.urlencode(params))
    if FINMIND_TOKEN:
        req.add_header("Authorization", f"Bearer {FINMIND_TOKEN}")
    with urllib.request.urlopen(req, timeout=40) as r:
        rows = json.loads(r.read().decode("utf-8")).get("data", []) or []
    out = {}
    for x in rows:
        try:
            out[(int(x["revenue_year"]), int(x["revenue_month"]))] = float(x["revenue"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch_eia_yoy(respondent, start_date):
    params = [("frequency", "daily"), ("data[0]", "value"),
              ("facets[respondent][]", respondent), ("facets[type][]", "D"),
              ("start", start_date), ("sort[0][column]", "period"),
              ("sort[0][direction]", "asc"), ("offset", "0"), ("length", "5000"),
              ("api_key", EIA_API_KEY)]
    req = urllib.request.Request(EIA_BASE + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read().decode("utf-8")).get("response", {}).get("data", []) or []
    monthly = defaultdict(list)
    for x in rows:
        p = str(x.get("period", "")).split("-")
        if len(p) < 2:
            continue
        try:
            monthly[(int(p[0]), int(p[1]))].append(float(x.get("value")))
        except (ValueError, TypeError):
            continue
    rev = {k: sum(v) / len(v) for k, v in monthly.items() if v}
    s = signal_growth(rev)
    return s["yoy"] if s else None


def yoy_series(rev):
    out = []
    for (y, m) in sorted(rev):
        base = rev.get((y - 1, m))
        if base:
            out.append(((y, m), rev[(y, m)] / base - 1))
    return out


def signal_growth(rev):
    ys = yoy_series(rev)
    if not ys:
        return None
    vals = [v for _, v in ys]
    recent3 = sum(vals[-3:]) / len(vals[-3:])
    if len(vals) >= 6:
        prior3 = sum(vals[-6:-3]) / 3
    elif len(vals) > 3:
        prior3 = sum(vals[:-3]) / len(vals[:-3])
    else:
        prior3 = None
    infl = (recent3 - prior3) if prior3 is not None else (vals[-1] - vals[-2] if len(vals) >= 2 else None)
    return {"yoy": vals[-1] * 100, "recent3": recent3 * 100,
            "prior3": None if prior3 is None else prior3 * 100,
            "infl": None if infl is None else infl * 100}


def direction(infl):
    if infl is None:
        return "steady"
    if infl >= ACCEL:
        return "accelerating"
    if infl <= DECEL:
        return "decelerating"
    return "steady"


def rev_to_gw(rev_value):
    usd = (rev_value * REVENUE_TO_TWD) / TWD_PER_USD
    racks = (usd * AI_SHARE) / ASP_PER_RACK_USD
    return racks * KW_PER_RACK / 1_000_000.0   # kW -> GW


def wavg(pairs):
    num = sum(v * w for v, w in pairs if v is not None)
    den = sum(w for v, w in pairs if v is not None)
    return (num / den) if den else None


def _fy(v): return "n/a" if v is None else f"{v:+.0f}%"
def _fp(v): return "n/a" if v is None else f"{v:+.0f}pp"


def build_reads(q_gw, ttm_gw, comp, cdir, grid_yoy):
    dword = {"accelerating": "accelerating", "steady": "holding steady", "decelerating": "cooling"}[cdir]
    reads = []
    reads.append({
        "claim": f"~{q_gw:.1f} GW/quarter of AI rack capacity is shipping from the component pipeline, {dword}.",
        "ev": (f"An estimated {q_gw:.1f} GW over the last three months (~{ttm_gw:.0f} GW trailing twelve), "
               f"growing {_fy(comp['yoy'])} YoY with a {_fp(comp['infl'])} inflection. Derived from Wiwynn, "
               f"Quanta and Wistron revenue and the stated assumptions below."),
        "why": ("This is AI capacity heading for the grid before it shows up in any power statistic \u2014 the "
                "leading edge of what operators will have to house and power."),
    })
    if grid_yoy is not None and comp["yoy"] is not None:
        gap = comp["yoy"] - grid_yoy
        if gap >= 4:
            verb = "outrunning energization"
            why = ("Capacity is shipping faster than grids are energizing it \u2014 equipment stacking up behind "
                   "the power bottleneck, which is exactly where holding energized capacity or queue position pays.")
        elif gap <= -4:
            verb = "lagging energization"
            why = ("Grids are energizing faster than the component pipeline is growing \u2014 demand catching up to, "
                   "or outpacing, fresh supply; a sign of how tight live capacity already is.")
        else:
            verb = "keeping pace with energization"
            why = ("Shipments and grid energization are moving together \u2014 the buildout is flowing through to "
                   "live load rather than piling up or starving.")
        reads.append({
            "claim": f"The pipeline is {verb}.",
            "ev": (f"Component shipments +{comp['yoy']:.0f}% YoY vs datacenter-grid demand "
                   f"{_fy(grid_yoy)} YoY \u2014 a {gap:+.0f}pp gap."),
            "why": why,
        })
    reads.append({
        "claim": "The wave is " + ("still building." if cdir == "accelerating" else "cresting." if cdir == "decelerating" else "steady."),
        "ev": (f"The shipping run-rate's growth is {dword} \u2014 {_fp(comp['infl'])} inflection "
               f"(last 3mo {_fy(comp['recent3'])} vs prior {_fy(comp['prior3'])})."),
        "why": ("Whether the incoming demand wave is still building or starting to crest \u2014 the second "
                "derivative, which turns before the headline numbers do."),
    })
    return reads


def main():
    start = (datetime.date.today() - datetime.timedelta(days=1200)).isoformat()

    combined, present, per_name = defaultdict(float), defaultdict(int), []
    for sid, name in FEEDERS:
        try:
            rev = fetch_revenue(sid, start)
        except Exception as e:
            print(f"[WARN] {sid} {name}: {e}"); rev = {}
        s = signal_growth(rev)
        per_name.append({"sid": sid, "name": name, "yoy": s["yoy"] if s else None})
        for k, v in rev.items():
            combined[k] += v; present[k] += 1
        print(f"[OK] {sid} {name}: months={len(rev)} latestYoY={None if not s else round(s['yoy'])}")

    combined = {k: v for k, v in combined.items() if present[k] == len(FEEDERS)}
    comp = signal_growth(combined)
    months = sorted(combined)
    gw_by_month = {k: rev_to_gw(combined[k]) for k in months}
    q_gw = sum(gw_by_month[k] for k in months[-3:]) if len(months) >= 1 else 0.0
    ttm_gw = sum(gw_by_month[k] for k in months[-12:]) if len(months) >= 1 else 0.0
    if months:
        raw_latest = combined[months[-1]]
        print(f"[CHECK] latest combined revenue field = {raw_latest:,.0f}  -> latest-month GW = {gw_by_month[months[-1]]:.3f}  -> Q run-rate = {q_gw:.2f} GW")

    grid_yoy = None
    if EIA_API_KEY:
        vals = []
        for code, w in GRIDS:
            try:
                gy = fetch_eia_yoy(code, start)
            except Exception as e:
                print(f"[WARN] EIA {code}: {e}"); gy = None
            if gy is not None:
                vals.append((gy, w))
        grid_yoy = wavg(vals) if vals else None
        print(f"[OK] grid demand YoY (weighted) = {None if grid_yoy is None else round(grid_yoy,1)}")

    cdir = direction(comp["infl"]) if comp else "steady"
    payload = {
        "as_of_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "q_gw": q_gw, "ttm_gw": ttm_gw, "comp": comp or {"yoy": None, "recent3": None, "prior3": None, "infl": None},
        "cdir": cdir, "grid_yoy": grid_yoy, "per_name": per_name,
        "reads": build_reads(q_gw, ttm_gw, comp or {"yoy": None, "recent3": None, "prior3": None, "infl": None}, cdir, grid_yoy) if comp else [],
    }
    with open(os.path.join(DOCS, "gw.html"), "w", encoding="utf-8") as f:
        f.write(render_html(payload))
    print(f"[DONE] Q={q_gw:.1f}GW TTM={ttm_gw:.0f}GW dir={cdir} gridYoY={grid_yoy}")


NAV = '<div id="nav"></div><script src="nav.js"></script>'


def render_html(d):
    arrow = {"accelerating": "\u25B2", "steady": "\u2192", "decelerating": "\u25BC"}
    dcls = {"accelerating": "pos", "steady": "dim", "decelerating": "neg"}
    dlbl = {"accelerating": "Building", "steady": "Steady", "decelerating": "Cresting"}

    def fy(v): return "n/a" if v is None else f"{v:+.0f}%"
    def fp(v): return "n/a" if v is None else f"{v:+.0f}pp"

    comp, cdir = d["comp"], d["cdir"]
    omath = (f'Q run-rate {d["q_gw"]:.1f} GW &middot; trailing 12-mo ~{d["ttm_gw"]:.0f} GW &middot; '
             f'growth {fy(comp["yoy"])} YoY ({fp(comp["infl"])})')

    reads = "".join(
        f'<div class="read"><div class="claim">{r["claim"]}</div>'
        f'<div class="ev">{r["ev"]}</div><div class="why">{r["why"]}</div></div>'
        for r in d["reads"]) or '<div class="read"><div class="ev">Component signal unavailable this run.</div></div>'

    inputs = "".join(
        f'<tr><td><span class="tk">{p["sid"]}</span>{p["name"]}</td>'
        f'<td class="num {"pos" if (p["yoy"] or 0) >= 0 else "neg"}">{fy(p["yoy"])}</td></tr>'
        for p in d["per_name"])

    assumptions = (
        f'<tr><td>AI share of feeder revenue</td><td class="num">{AI_SHARE*100:.0f}%</td></tr>'
        f'<tr><td>Revenue per AI rack-system</td><td class="num">${ASP_PER_RACK_USD/1e6:.1f}M</td></tr>'
        f'<tr><td>Power per rack</td><td class="num">{KW_PER_RACK} kW</td></tr>'
        f'<tr><td>FX</td><td class="num">{TWD_PER_USD:.0f} TWD/USD</td></tr>')

    tpl = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gigawatts in Transit - NVIDIA AI Supply Chain</title>
<style>
:root{--bg:#0b0f17;--card:#121826;--line:#1f2937;--ink:#e6edf6;--dim:#8b97a8;--pos:#36d399;--neg:#f87272;--accent:#5b9dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:26px 20px 70px}
.nav{display:flex;gap:8px;margin-bottom:22px;flex-wrap:wrap}.nav a{color:var(--dim);text-decoration:none;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--line);border-radius:8px}.nav a.active{color:#fff;background:#1c2638;border-color:#2b3a52}
h1{font-size:23px;margin:0 0 6px}.sub-h{color:var(--dim);margin:0 0 22px;font-size:13px}
.hero{display:grid;grid-template-columns:1.1fr 1fr;gap:16px;margin-bottom:8px}@media(max-width:680px){.hero{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.klabel{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.big{font-size:46px;font-weight:800;letter-spacing:-1px;line-height:1}.big.pos{color:var(--pos)}.big.neg{color:var(--neg)}.big .u{font-size:20px;font-weight:700;color:var(--dim);margin-left:6px}
.badge{display:inline-block;font-size:14px;font-weight:700;padding:5px 12px;border-radius:8px;margin-top:4px}
.badge.pos{background:rgba(54,211,153,.13);color:var(--pos)}.badge.neg{background:rgba(248,114,114,.13);color:var(--neg)}.badge.dim{background:#1c2638;color:var(--dim)}
.mono{font-variant-numeric:tabular-nums;color:var(--ink);font-size:13px;margin-top:12px;background:#0e1422;border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.tk{display:inline-block;background:#1c2638;color:var(--accent);border-radius:5px;padding:1px 6px;font-size:12px;margin-right:6px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.05em;color:var(--accent);margin:28px 0 6px}.hint{color:var(--dim);font-size:12px;margin:0 0 12px}
.read{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.read .claim{font-weight:700;font-size:15px;margin-bottom:7px}
.read .ev{font-variant-numeric:tabular-nums;font-size:13px;background:#0e1422;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px}
.read .why{color:var(--dim);font-size:13px;line-height:1.55}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:680px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}th.num,.num{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}.neg{color:var(--neg)}.dim{color:var(--dim)}
.foot{color:var(--dim);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:16px;line-height:1.7}
a.inline{color:var(--accent)}
</style></head><body><div class="wrap">
__NAV__
<h1>Gigawatts in Transit</h1>
<p class="sub-h">The Taiwan component pulse translated into gigawatts of AI datacenter capacity shipping toward the grid &mdash; the incoming demand wave, before it shows up in any power statistic &middot; updated __ASOF__</p>

<div class="hero">
  <div class="card">
    <div class="klabel">AI capacity shipping &mdash; component-pipeline run-rate</div>
    <div class="big __OCLS__">__QGW__<span class="u">GW / qtr</span></div>
    <div class="dim" style="font-size:12px;margin-top:8px">Estimated from the AI-rack ODMs' monthly revenue (Wiwynn, Quanta, Wistron). The absolute level is an estimate built on the assumptions below &mdash; read the trend and the gap, not the decimal.</div>
  </div>
  <div class="card">
    <div class="klabel">The wave (run-rate growth)</div>
    <span class="badge __OCLS__">__ARROW__ __DIRLBL__</span>
    <div class="mono">__OMATH__</div>
    <div class="dim" style="font-size:12px;margin-top:8px">Growth and inflection are units-independent (just revenue growth), so this side is solid regardless of the absolute calibration.</div>
  </div>
</div>

<h2>Reads</h2>
<p class="hint">What the signal says &mdash; the numbers, then what it means and why, for an infrastructure operator.</p>
__READS__

<div class="grid2">
  <div>
    <h2>Conversion assumptions</h2>
    <p class="hint">How revenue becomes gigawatts. All estimates &mdash; tunable.</p>
    <div class="card"><table><tbody>__ASSUMP__</tbody></table></div>
  </div>
  <div>
    <h2>Pipeline inputs</h2>
    <p class="hint">The feeder ODMs and their latest revenue growth.</p>
    <div class="card"><table><thead><tr><th>Company</th><th class="num">YoY</th></tr></thead><tbody>__INPUTS__</tbody></table></div>
  </div>
</div>

<div class="foot">
<b>Method:</b> we sum the monthly revenue of the AI-rack ODMs (Wiwynn, Quanta, Wistron), take the estimated AI share, divide by an estimated revenue-per-rack to get rack count, and multiply by estimated power-per-rack to get gigawatts shipping. The <b>growth rate and inflection</b> equal the revenue growth, so they hold regardless of the conversion; the <b>absolute GW level</b> depends on the four assumptions above and should be read as order-of-magnitude. The energization gap compares this against datacenter-grid demand growth from the EIA (the <a class="inline" href="power.html">Grid Demand Pulse</a>). Pairs with the <a class="inline" href="readthrough.html">read-through</a>.<br>
<b>This is a derived estimate,</b> not a reported figure &mdash; revenue is blended (not purely AI racks) and the conversion factors are approximations. It exists to size and time the incoming wave, not to be precise to the gigawatt.<br>
<b>Not investment advice</b> &mdash; a research signal that frames magnitude and direction, not a recommendation.
</div>
</div></body></html>"""
    return (tpl.replace("__NAV__", NAV).replace("__ASOF__", d["as_of_utc"])
               .replace("__OCLS__", dcls[cdir]).replace("__QGW__", f'{d["q_gw"]:.1f}')
               .replace("__ARROW__", arrow[cdir]).replace("__DIRLBL__", dlbl[cdir])
               .replace("__OMATH__", omath).replace("__READS__", reads)
               .replace("__ASSUMP__", assumptions).replace("__INPUTS__", inputs))


if __name__ == "__main__":
    main()

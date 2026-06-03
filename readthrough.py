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
    hot = [n for n, key in ((

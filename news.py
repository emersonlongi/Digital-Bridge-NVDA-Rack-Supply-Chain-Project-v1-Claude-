"""
Layer 4 - Supply-chain news watcher.
Pulls recent, thesis-relevant headlines for NVIDIA's AI-rack supply chain from
Google News RSS (free, no API key), groups them by content theme, colour-codes
each by importance (with a wildcard tier for surprising items), and writes
docs/news.html. Runs unattended in GitHub Actions alongside the other scripts.
"""
import os, time, datetime, email.utils, html, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

DOCS = "docs"
GNEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
MAX_AGE_DAYS = 120
PER_THEME = 5

THEMES = [
    ("Roadmap & platform",
     ["NVIDIA Rubin GPU", "NVIDIA GB300 NVL72", "NVIDIA Vera Rubin"]),
    ("Memory - HBM",
     ["NVIDIA HBM4", "SK hynix HBM4", "Micron HBM NVIDIA"]),
    ("Optical & co-packaged optics",
     ["NVIDIA co-packaged optics", "silicon photonics data center", "Coherent Lumentum NVIDIA"]),
    ("Power - 800V HVDC",
     ["NVIDIA 800V data center power", "Navitas GaN data center", "Vertiv NVIDIA power"]),
    ("Liquid cooling",
     ["NVIDIA liquid cooling", "data center liquid cooling AI"]),
    ("Foundry & Taiwan supply chain",
     ["TSMC CoWoS NVIDIA", "NVIDIA AI server supply chain Taiwan"]),
]

# importance tagging (heuristic, keyword/source based)
HIGH_KW = ("mass production", "shipment", "ships", " order", "orders", "capacity",
           "guidance", "earnings", "acquisition", "acquire", "merger", "contract",
           "ramp", "backlog", "expansion", "billion", "million", "$", "sold out", "record")
WILD_KW = ("breakthrough", "unexpected", "surprise", "rumor", "reportedly", "leak",
           "shock", "scrap", "cancel", "delay", "halt", "first-ever", "world's first", "pivot")
TIER1 = ("Reuters", "Bloomberg", "Wall Street Journal", "Financial Times", "CNBC",
         "Nikkei", "The Information")


def classify(title, source):
    t = title.lower()
    if any(k in t for k in WILD_KW):
        return "wild"
    if any(k in t for k in HIGH_KW) or any(s in source for s in TIER1):
        return "high"
    return "normal"


def fetch_items(query):
    url = GNEWS.format(q=urllib.parse.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        dt = None
        try:
            dt = email.utils.parsedate_to_datetime(pub)
            if dt is not None and dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            dt = None
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)].strip()
        if title and link:
            out.append({"title": title, "link": link, "source": source, "dt": dt})
    return out


def fmt_abs(dt):
    """Absolute UTC timestamp - always correct no matter when the page is viewed."""
    if not dt:
        return ""
    return dt.strftime("%b ") + str(dt.day) + dt.strftime(", %H:%M")


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=MAX_AGE_DAYS)
    sections, total = [], 0
    for theme, queries in THEMES:
        items = []
        for q in queries:
            try:
                items.extend(fetch_items(q))
            except Exception as e:
                print(f"[WARN] {theme} / {q!r}: {e}")
            time.sleep(0.2)
        seen, uniq = set(), []
        for it in items:
            key = it["title"].lower()
            if key not in seen:
                seen.add(key)
                uniq.append(it)
        dated = [it for it in uniq if it["dt"] is not None and it["dt"] >= cutoff]
        dated.sort(key=lambda x: x["dt"], reverse=True)
        chosen = dated[:PER_THEME]
        total += len(chosen)
        sections.append((theme, chosen))
        print(f"[OK] {theme}: {len(chosen)} headlines")

    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "news.html"), "w", encoding="utf-8") as f:
        f.write(render_html(sections, now, total))
    print(f"[DONE] total headlines={total}")


NAV = '<div id="nav"></div><script src="nav.js"></script>'


def render_html(sections, now, total):
    blocks = ""
    for theme, items in sections:
        if items:
            rows = ""
            for it in items:
                cat = classify(it["title"], it["source"])
                tag = ('<span class="tag high">High</span>' if cat == "high"
                       else '<span class="tag wild">Wildcard</span>' if cat == "wild" else "")
                abs_str = fmt_abs(it["dt"])
                iso = it["dt"].isoformat() if it["dt"] else ""
                meta = " &middot; ".join(x for x in (html.escape(it["source"]), abs_str) if x)
                ago = f'<span class="ago" data-ts="{iso}"></span>' if iso else ""
                rows += (f'<a class="item {cat}" href="{html.escape(it["link"])}" target="_blank" rel="noopener">'
                         f'<span class="t">{html.escape(it["title"])}{tag}</span>'
                         f'<span class="m">{meta}{ago}</span></a>')
        else:
            rows = '<div class="empty">No recent headlines.</div>'
        blocks += f'<section class="theme"><h2>{html.escape(theme)}</h2>{rows}</section>'

    asof = now.strftime("%Y-%m-%d %H:%M UTC")
    tpl = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Supply-Chain News - NVIDIA AI Supply Chain</title>
<style>
:root{--bg:#0b0f17;--card:#121826;--line:#1f2937;--ink:#e6edf6;--dim:#8b97a8;--accent:#5b9dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:24px 20px 70px}
.nav{display:flex;gap:8px;margin-bottom:22px;flex-wrap:wrap}.nav a{color:var(--dim);text-decoration:none;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--line);border-radius:8px}.nav a.active{color:#fff;background:#1c2638;border-color:#2b3a52}
h1{font-size:23px;margin:0 0 6px}.sub{color:var(--dim);margin:0 0 16px;font-size:13px}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 22px;font-size:12px;color:var(--dim)}
.legend span{display:inline-flex;align-items:center}
.legend span::before{content:"";width:9px;height:9px;border-radius:2px;margin-right:6px;display:inline-block}
.legend .high::before{background:#f5a524}.legend .wild::before{background:#a78bfa}.legend .normal::before{background:#3a465c}
.theme{margin-bottom:26px}
.theme h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--accent);margin:0 0 10px;font-weight:700}
.item{display:flex;justify-content:space-between;gap:16px;align-items:baseline;text-decoration:none;color:var(--ink);background:var(--card);border:1px solid var(--line);border-left:3px solid var(--line);border-radius:10px;padding:11px 14px;margin-bottom:8px;transition:border-color .15s}
.item:hover{border-color:#2b3a52}
.item.high{border-left-color:#f5a524}.item.wild{border-left-color:#a78bfa}
.item .t{font-size:14px;line-height:1.45}
.item .m{color:var(--dim);font-size:12px;white-space:nowrap;flex-shrink:0}
.tag{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;padding:1px 6px;border-radius:4px;margin-left:8px;white-space:nowrap}
.tag.high{background:rgba(245,165,36,.16);color:#f5a524}.tag.wild{background:rgba(167,139,250,.16);color:#a78bfa}
.empty{color:var(--dim);font-size:13px;font-style:italic;padding:4px 2px}
.foot{color:var(--dim);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:16px;line-height:1.7}
a.inline{color:var(--accent)}
</style></head><body><div class="wrap">
__NAV__
<h1>Supply-Chain News</h1>
<p class="sub">Recent headlines across the NVIDIA AI-rack supply chain, grouped by the same content themes as the <a class="inline" href="supplychain.html">winning-content map</a> &middot; __TOTAL__ items &middot; updated __ASOF__</p>
<div class="legend"><span class="high">High importance</span><span class="wild">Wildcard / surprising</span><span class="normal">Standard</span></div>
__BLOCKS__
<div class="foot">
<b>What this is:</b> a live watch-list of news touching the parts of the stack this project tracks &mdash; roadmap, memory, optics, power, cooling, and the Taiwan supply chain. Pairs with the <a class="inline" href="index.html">revenue signal</a>, <a class="inline" href="scoreboard.html">price scoreboard</a>, and <a class="inline" href="readthrough.html">read-through</a>.<br>
<b>Colour coding</b> is a keyword/source heuristic: amber = likely-material (production, orders, capacity, $ figures, tier-1 wires), purple = surprising/unconfirmed (breakthroughs, delays, rumours). A guide, not a verdict.<br>
<b>Source:</b> auto-aggregated from Google News RSS, filtered to these themes. Headlines only &mdash; not analysis, not investment advice. Dates shown in UTC.
</div>
</div>
<script>
(function(){
  function ago(ms){
    var s=Math.max(0,(Date.now()-ms)/1000);
    if(s<3600)return Math.max(1,Math.floor(s/60))+"m ago";
    if(s<86400)return Math.floor(s/3600)+"h ago";
    if(s<86400*14)return Math.floor(s/86400)+"d ago";
    return Math.floor(s/(86400*7))+"w ago";
  }
  var els=document.querySelectorAll(".ago[data-ts]");
  for(var i=0;i<els.length;i++){
    var t=Date.parse(els[i].getAttribute("data-ts"));
    if(!isNaN(t))els[i].textContent=" \u00b7 "+ago(t);
  }
})();
</script>
</body></html>"""
    return (tpl.replace("__NAV__", NAV).replace("__TOTAL__", str(total))
               .replace("__ASOF__", asof).replace("__BLOCKS__", blocks))


if __name__ == "__main__":
    main()

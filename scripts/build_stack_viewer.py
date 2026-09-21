"""Build the Symphony building viewer (pilot): data/stack/symphony_viewer.html - one self-contained page.

The interface follows the developer viewers Kendall pointed at (18-19 Sep 2026): a render of the building, every unit
tinted by type on the facade, a FILTERS panel top-left (unit count, one button per type, a SQ.FT range, Hide All), and
a card for the unit tapped. What is ours, and what the developer's viewer does not have (Kendall, 19 Sep: "add everything"):

  per unit      the unit's own plan from the Revit model (rooms, inside dimensions), where it sits on the floor plate,
                the programme, the sheet's price / view, the type's unit card, a WhatsApp share
  per type      the Land Department register: launched, sold, left, and what the type actually settles at
  per building  every floor of the tower (offices 1-8, clubhouse 9, homes 10-34), the facts, construction progress,
                the history of the developer's sheets
  around it     nearest of each kind from the map's amenity layer, and the area's settled sales

Every figure carries its source on the page. Sizes not on a sheet are the model's and say so.

    python scripts/stack_overlay.py json && python scripts/build_stack_viewer.py
"""
import glob, json, math, os, re, sys, urllib.parse, urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "stack")
RENDER_SRC = os.path.join(OUT, "symphony_render_full.jpg")
SITE = (25.168, 55.308)                 # site anchor from the curated facts - site-level, pending Makani
PROGRESS = {"overall": 6, "completion": "Q2 2029", "source": "imtiaz.ae, read 19 Sep 2026"}
AMENITIES = ["Clubhouse", "Gym", "Yoga studio", "Sauna & steam", "Adult pool", "Kids' pool", "Kids' playground", "Observatory deck", "Outdoor dining", "BBQ area"]
KIND_NAME = {"school": "School", "clinic": "Clinic", "hospital": "Hospital", "metro": "Metro", "mall": "Mall", "supermarket": "Supermarket",
             "park": "Park", "beach": "Beach", "ev": "EV charging"}


def sheets():
    """Symphony units per sheet date, newest last: homes keyed by unit number, offices and retail as a list."""
    by_date = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "avail", "imtiaz_*.json"))):
        if f.endswith("_auto.json"):
            continue
        date = os.path.basename(f)[len("imtiaz_"):-len(".json")]
        d = json.load(open(f, encoding="utf-8"))
        for p in d.get("projects", []):
            if "ymphony" in p["p"]:
                row = lambda u: {"no": str(u[0]), "type": u[1], "sqft": u[2], "price": u[3], "view": u[4]}
                by_date[date] = {"plan": p.get("plan"), "completion": p.get("completion"),
                                 "units": {str(u[0]): row(u) for u in p["units"] if str(u[0]).isdigit()},
                                 "other": [row(u) for u in p["units"] if not str(u[0]).isdigit()]}
    return by_date


def around():
    am = json.load(open(os.path.join(ROOT, "data", "board", "amenities.json"), encoding="utf-8"))
    items = am if isinstance(am, list) else next(v for v in am.values() if isinstance(v, list))
    best = {}
    for a in items:
        dx = (a["lon"] - SITE[1]) * 111.32 * math.cos(math.radians(SITE[0])); dy = (a["lat"] - SITE[0]) * 110.57
        d = math.hypot(dx, dy)
        if a.get("k") and (a["k"] not in best or d < best[a["k"]][0]):
            best[a["k"]] = (d, a["n"], a.get("x") if isinstance(a.get("x"), str) else "")
    return [{"kind": KIND_NAME.get(k, k), "name": n, "note": x, "km": round(d, 1)} for k, (d, n, x) in sorted(best.items(), key=lambda kv: kv[1][0])]


def area():
    """The district's settled sales from the app's area page (client tier). None if it cannot be read."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts")); argv, sys.argv = sys.argv, ["x"]
        import demo_capture as dc
        sys.argv = argv
        t = urllib.request.urlopen(urllib.request.Request(dc.url("/area/Bukadra"), headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read().decode("utf-8", "replace")
        txt = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[\s\S]*?</\1>", " ", t)).split())
        g = lambda pat: (re.search(pat, txt) or [None, None])[1]
        return {"name": "Bukadra", "period": g(r"(\d{4}-\d\d-\d\d\s*\S\s*\d{4}-\d\d-\d\d)"), "sales": g(r"([\d,]+) settled sales"), "sqft": g(r"([\d,]+) ?/sqft"),
                "ticket": g(r"([\d.]+m) median ticket"), "offplan": g(r"(\d+) ?% off-plan"),
                "layouts": re.findall(r"(\d B/R) (\d+) sales ([\d.]+m)", txt)[:4]}
    except Exception as e:
        print("area page not read:", str(e)[:80]); return None


def main():
    from PIL import Image
    im = Image.open(RENDER_SRC).convert("RGB"); W, H = im.size
    im.resize((2400, round(H * 2400 / W)), Image.LANCZOS).save(os.path.join(OUT, "symphony_render.jpg"), quality=86)
    S = json.load(open(os.path.join(OUT, "symphony_units.json")))
    stack = S["units"]
    sh = sheets(); dates = sorted(sh); latest = dates[-1]
    for u in stack:
        u["status"] = "unlisted"
        for d in dates:
            if u["unit"] in sh[d]["units"]:
                u["sheet"] = dict(sh[d]["units"][u["unit"]], date=d); u["status"] = "available" if d == latest else "gone"
        u["sqft"] = round(u["sheet"]["sqft"]) if u.get("sheet") else u["sqft_est"]
    um = json.load(open(os.path.join(ROOT, "data", "board", "unitmix_goldensymphony.json"), encoding="utf-8"))["buildings_by_id"]["0"]
    register = [{"type": r["type"], "launched": r.get("launched"), "sold": r.get("sold") or 0, "left": r.get("remaining"), "median": r.get("median_aed"), "ask": r.get("ask_med")}
                for r in um["rows"] if r.get("launched") and r["type"] != "Na"]
    cur = json.load(open(os.path.join(ROOT, "data", "dev_meta", "curated", "goldensymphony.json"), encoding="utf-8"))["buildings"]["symphony"]
    offices = {}
    for o in sh[latest]["other"]:
        m = re.match(r"OFFICE-(\d)\d\d", o["no"])
        if m: offices.setdefault(m.group(1), []).append(o)
    data = {"building": "The Symphony by Imtiaz", "area": "Meydan Horizon", "w": W, "h": H, "latest": latest,
            "plan": next((sh[d]["plan"] for d in reversed(dates) if sh[d].get("plan")), None),
            "completion": next((sh[d]["completion"] for d in reversed(dates) if sh[d].get("completion")), None),
            "units": [u for u in stack if u["polys"]], "hidden": sum(1 for u in stack if not u["polys"]), "total": len(stack),
            "bands": S["bands"], "plates": S["plates"], "plate": S["plate"], "register": register, "register_asof": um.get("as_of"),
            "facts": cur["facts"], "status": cur["status"], "developer": cur["developer"], "progress": PROGRESS, "amenities": AMENITIES,
            "history": [{"date": d, "homes": sorted(sh[d]["units"]), "other": len(sh[d]["other"])} for d in dates],
            "offices": offices, "retail": [o for o in sh[latest]["other"] if o["no"].startswith("RETAIL")],
            "around": around(), "areastats": area()}
    html = TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False))
    open(os.path.join(OUT, "symphony_viewer.html"), "w", encoding="utf-8").write(html)
    print("viewer written: %d homes in view, latest sheet %s, available %s, register rows %d, around %d, area %s" % (
        len(data["units"]), latest, [u["unit"] for u in stack if u["status"] == "available"], len(register), len(data["around"]), bool(data["areastats"])))


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Symphony — unit viewer (pilot)</title>
<style>
  html,body{margin:0;height:100%;background:#0d1417;font-family:"Avenir Next","Segoe UI",system-ui,sans-serif;overflow:hidden;color:#fff}
  #bg{position:fixed;inset:-40px;background:url(symphony_render.jpg) center/cover;filter:blur(28px) brightness(.82) saturate(1.05)}
  #stage{position:fixed;inset:0}#stage svg{width:100%;height:100%;display:block}
  #shade{position:fixed;left:0;right:0;bottom:0;height:120px;background:linear-gradient(180deg,transparent,rgba(0,0,0,.45));pointer-events:none}
  .u{stroke:rgba(255,255,255,.55);stroke-width:1.2;cursor:pointer;transition:fill-opacity .25s,opacity .25s}
  .u:hover{fill-opacity:.78;stroke:#fff;stroke-width:2}.u.off{opacity:0;pointer-events:none}
  .u.avail{stroke:#F4D58D;stroke-width:3.2}.u.gone{stroke:rgba(255,255,255,.3)}.u.sel{stroke:#fff;stroke-width:4;fill-opacity:.9}
  .glass{background:linear-gradient(180deg,rgba(78,92,110,.88),rgba(104,116,132,.82));backdrop-filter:blur(6px);box-shadow:0 8px 28px rgba(0,0,0,.28);border-radius:12px}
  #panel{position:fixed;left:18px;top:18px;width:264px;box-sizing:border-box;padding:16px 20px 16px;max-height:calc(100% - 36px);overflow:auto}
  #panel h1{margin:0;text-align:center;font-size:13.5px;font-weight:600;letter-spacing:.04em}
  #count{text-align:center;font-size:17px;font-weight:600;margin:12px 0 16px}
  .tb{display:block;width:100%;border:0;border-radius:6px;padding:8px 0;margin:0 0 4px;font:500 15px/1.2 inherit;cursor:pointer;color:#2b2f36;transition:filter .15s,opacity .15s}
  .tb.dark{color:#fff}.tb.off{opacity:.38;filter:saturate(.4)}
  .grp{font-size:10.5px;letter-spacing:.1em;opacity:.7;margin:12px 0 6px;text-transform:uppercase}
  .sz{margin-top:18px;font-size:16px}.sz u{font-size:13.5px;margin-left:8px;text-underline-offset:3px}
  .range{position:relative;height:34px;margin:12px 6px 0}.range .track{position:absolute;left:0;right:0;top:15px;height:2px;background:rgba(255,255,255,.85)}
  .range input{position:absolute;left:-6px;width:calc(100% + 12px);top:4px;margin:0;background:none;pointer-events:none;-webkit-appearance:none;appearance:none;height:24px}
  .range input::-webkit-slider-thumb{-webkit-appearance:none;pointer-events:auto;width:28px;height:28px;border-radius:50%;background:#5a0d0d;border:0;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.4)}
  .range input::-moz-range-thumb{pointer-events:auto;width:28px;height:28px;border-radius:50%;background:#5a0d0d;border:0;cursor:pointer}
  .vals{display:flex;justify-content:space-between;font-size:16.5px;margin:2px 4px 12px}
  #hide{display:block;width:100%;border:0;border-radius:7px;padding:9px 0;background:#c9c7c5;color:#3a3d42;font:500 14.5px inherit;cursor:pointer}
  #only{display:flex;gap:8px;align-items:center;margin:10px 2px 0;font-size:13px;cursor:pointer}#only input{accent-color:#F4D58D;width:16px;height:16px}
  table.reg{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}table.reg td,table.reg th{padding:3px 2px;text-align:right;font-weight:400}
  table.reg th{opacity:.65;font-size:10.5px}table.reg td:first-child,table.reg th:first-child{text-align:left}
  .bar{height:4px;border-radius:2px;background:rgba(255,255,255,.22);overflow:hidden;margin-top:2px}.bar i{display:block;height:100%;background:#F4D58D}
  .src{font-size:10.5px;opacity:.6;line-height:1.4;margin-top:6px}
  #tab{position:fixed;left:112px;top:0;width:76px;height:22px;border-radius:0 0 10px 10px;background:rgba(88,100,116,.85);display:grid;place-items:center;cursor:pointer;color:#dfe3e8;font-size:15px;z-index:3}
  #card{position:fixed;right:22px;top:18px;width:372px;box-sizing:border-box;padding:18px 20px;display:none;max-height:calc(100% - 96px);overflow:auto;
        background:linear-gradient(180deg,rgba(40,50,62,.94),rgba(58,68,82,.92));backdrop-filter:blur(6px);box-shadow:0 8px 28px rgba(0,0,0,.35);border-radius:12px}
  #card h2{margin:0 0 2px;font:600 22px/1.2 inherit}#card .t{opacity:.8;font-size:13px;letter-spacing:.06em;text-transform:uppercase}
  #card .x{position:absolute;right:14px;top:10px;cursor:pointer;font-size:20px;opacity:.7}
  #card h3{margin:18px 0 8px;font:600 11.5px/1 inherit;letter-spacing:.1em;text-transform:uppercase;opacity:.75;border-top:1px solid rgba(255,255,255,.14);padding-top:14px}
  dl{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;margin:14px 0 0;font-size:14.5px}dt{opacity:.65}dd{margin:0;text-align:right;font-weight:500}
  .pill{display:inline-block;margin-top:10px;padding:4px 10px;border-radius:99px;font-size:12.5px;font-weight:600;letter-spacing:.04em}
  .pill.a{background:#F4D58D;color:#3a2c05}.pill.g{background:rgba(255,255,255,.16)}.pill.n{background:rgba(255,255,255,.10);font-weight:500}
  .plan{width:100%;border-radius:8px;background:#f6f3ec;display:block}
  .acts{display:flex;gap:8px;margin-top:14px}.acts a{flex:1;text-align:center;padding:9px 0;border-radius:7px;text-decoration:none;font-size:13.5px;font-weight:600}
  .acts .w{background:#25D366;color:#063}.acts .c{background:rgba(255,255,255,.14);color:#fff}
  .row{display:flex;justify-content:space-between;gap:10px;font-size:13.5px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.08)}.row span:last-child{opacity:.8;white-space:nowrap}
  .row small{opacity:.6}
  #about{position:fixed;left:50%;transform:translateX(-50%);top:14px;padding:9px 20px;border-radius:99px;font-size:14px;cursor:pointer;z-index:2}
  #foot{position:fixed;left:64px;bottom:20px;font-size:12px;line-height:1.5;text-shadow:0 1px 3px rgba(0,0,0,.7);max-width:600px}
  #north{position:fixed;left:26px;bottom:24px;font-size:11px;text-align:center;text-shadow:0 1px 3px rgba(0,0,0,.7)}
  #north i{display:block;width:0;height:0;margin:0 auto 2px;border:6px solid transparent;border-bottom:16px solid #e04a3a}
  #contact{position:fixed;right:22px;bottom:18px;padding:12px 22px;border-radius:99px;background:rgba(60,70,84,.88);font-size:16px;box-shadow:0 4px 16px rgba(0,0,0,.3)}
</style></head><body>
<div id="bg"></div><div id="stage"></div><div id="shade"></div>
<div id="tab">&#8963;</div>
<div id="about" class="glass">About the building</div>
<div id="panel" class="glass">
  <h1>FILTERS</h1><div id="count"></div><div id="types"></div>
  <div class="grp">Also in the tower</div><div id="others"></div>
  <div class="sz">Size <u>SQ.FT</u></div>
  <div class="range"><div class="track"></div><input id="lo" type="range"><input id="hi" type="range"></div>
  <div class="vals"><span id="vlo"></span><span id="vhi"></span></div>
  <button id="hide">Hide All</button>
  <label id="only"><input type="checkbox" id="onlyc"> <span id="onlyt"></span></label>
  <div class="grp">Sold so far</div><div id="reg"></div>
</div>
<div id="card"></div>
<div id="north"><i></i>N</div><div id="foot"></div><div id="contact">&#9711; Contact</div>
<script>
const D = /*DATA*/;
const TYPES = [["Master Suite","#d9c2e6",0],["1 BHK","#e8b987",0],["2 BHK","#3c4858",1],["3 BHK","#a9c9a0",0],["4 BHK","#8fd0c0",0],["4 BHK Duplex","#7ccfd3",0]].filter(t => D.units.some(u => u.type === t[0]));
const OTHERS = [["Office","#7f9bd1",0],["Clubhouse","#e9c45a",0]];
const COL = Object.fromEntries(TYPES.concat(OTHERS).map(t => [t[0], t[1]]));
const REGTYPE = {"Master Suite":"1 bedroom","1 BHK":"1 bedroom","2 BHK":"2 bedroom","3 BHK":"3 bedroom","4 BHK":"4 bedroom"};
const on = new Set(TYPES.concat(OTHERS).map(t => t[0]));
const fmt = n => Math.round(n).toLocaleString("en-US"), M = n => "AED " + (n / 1e6).toFixed(2) + "M";
const smax = Math.max(...D.units.map(u => u.sqft)); let lo = 0, hi = smax, only = false, sel = null;
const NS = "http://www.w3.org/2000/svg", $ = id => document.getElementById(id);
const svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", `0 0 ${D.w} ${D.h}`); svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
const img = document.createElementNS(NS, "image"); img.setAttribute("href", "symphony_render.jpg"); img.setAttribute("width", D.w); img.setAttribute("height", D.h); svg.appendChild(img);
function poly(o, p, cls, op) { const e = document.createElementNS(NS, "polygon"); e.setAttribute("points", p.pts.map(q => q.join(",")).join(" ")); e.setAttribute("fill", COL[o.type]);
  e.setAttribute("fill-opacity", op); e.setAttribute("class", "u " + cls); e.addEventListener("click", () => pick(o)); svg.appendChild(e); return e; }
D.bands.forEach(b => { b.band = true; b.els = b.polys.map(p => poly(b, p, "", ".34")); });
D.units.forEach(u => { u.els = u.polys.map(p => poly(u, p, u.status === "available" ? "avail" : u.status === "gone" ? "gone" : "", u.status === "available" ? ".62" : ".42")); });
D.units.filter(u => u.status === "available").forEach(u => u.els.forEach(e => svg.appendChild(e)));
$("stage").appendChild(svg);

function buttons(box, list) { list.forEach(([name, col, dark]) => { const b = document.createElement("button"); b.className = "tb" + (dark ? " dark" : ""); b.style.background = col; b.textContent = name; b.dataset.t = name;
  b.onclick = () => { on.has(name) ? on.delete(name) : on.add(name); b.classList.toggle("off", !on.has(name)); draw(); }; box.appendChild(b); }); }
buttons($("types"), TYPES); buttons($("others"), OTHERS);
const elo = $("lo"), ehi = $("hi"); [elo, ehi].forEach(e => { e.min = 0; e.max = smax; e.step = 1; }); elo.value = 0; ehi.value = smax;
elo.oninput = () => { lo = Math.min(+elo.value, hi - 50); elo.value = lo; draw(); }; ehi.oninput = () => { hi = Math.max(+ehi.value, lo + 50); ehi.value = hi; draw(); };
$("hide").onclick = () => { const all = on.size === 0; TYPES.concat(OTHERS).forEach(t => all ? on.add(t[0]) : on.delete(t[0])); document.querySelectorAll(".tb").forEach(b => b.classList.toggle("off", !on.has(b.dataset.t))); draw(); };
$("onlyc").onchange = e => { only = e.target.checked; draw(); };
$("onlyt").textContent = `On the ${D.latest} sheet only (${D.units.filter(u => u.status === "available").length})`;
$("tab").onclick = () => { const p = $("panel"); p.style.display = p.style.display === "none" ? "" : "none"; };
$("reg").innerHTML = `<table class="reg"><tr><th>type</th><th>sold</th><th>of</th><th>settles at</th></tr>` + D.register.map(r =>
  `<tr><td>${r.type}<div class="bar"><i style="width:${Math.round(100 * r.sold / r.launched)}%"></i></div></td><td>${r.sold}</td><td>${r.launched}</td><td>${r.median ? M(r.median) : "—"}</td></tr>`).join("") +
  `</table><div class="src">Dubai Land Department units register${D.register_asof ? ", " + D.register_asof : ""}. Counts by type, not by unit number: which homes are sold is not published.</div>`;

function shown(o) { if (!on.has(o.type)) return false; if (o.band) return !only; return o.sqft >= lo && o.sqft <= hi && (!only || o.status === "available"); }
function draw() { let n = 0; D.units.forEach(u => { const s = shown(u); if (s) n++; u.els.forEach(e => e.classList.toggle("off", !s)); });
  D.bands.forEach(b => b.els.forEach(e => e.classList.toggle("off", !shown(b))));
  $("count").textContent = n + " Units"; $("vlo").textContent = fmt(lo); $("vhi").textContent = fmt(hi); $("hide").textContent = on.size === 0 ? "Show All" : "Hide All"; }

const RC = {living:"#eadfc8", bedroom:"#cfdbe8", bath:"#d9d9d6", hall:"#dcebe4", balcony:"#e8dcef", corridor:"#eee"};
function planSVG(u) { if (!u.rooms.length) return ""; const xs = u.rooms.flatMap(r => [r.r[0], r.r[2]]), ys = u.rooms.flatMap(r => [r.r[1], r.r[3]]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys), pad = 500, w = x1 - x0 + 2 * pad, h = y1 - y0 + 2 * pad;
  const R = u.rooms.map(r => { const a = Math.min(r.r[0], r.r[2]), b = Math.max(r.r[0], r.r[2]), c = Math.min(r.r[1], r.r[3]), d = Math.max(r.r[1], r.r[3]);
    const X = a - x0 + pad, Y = y1 - d + pad, Wd = b - a, Hd = d - c, big = Wd > 2600 && Hd > 1900;
    return `<rect x="${X}" y="${Y}" width="${Wd}" height="${Hd}" fill="${RC[r.k] || "#eee"}" stroke="#3a3f47" stroke-width="70"/>` + (big ?
      `<text x="${X + Wd / 2}" y="${Y + Hd / 2 - 60}" font-size="${Math.min(520, Wd / 7)}" text-anchor="middle" fill="#2b2f36" font-weight="600">${r.n}</text>
       <text x="${X + Wd / 2}" y="${Y + Hd / 2 + 520}" font-size="${Math.min(430, Wd / 8)}" text-anchor="middle" fill="#5a606a">${(Wd / 1000).toFixed(1)} × ${(Hd / 1000).toFixed(1)} m</text>` : ""); }).join("");
  return `<svg class="plan" viewBox="0 0 ${w} ${h}" font-family="inherit">${R}</svg>`; }
function plateSVG(u) { const [P, PY] = D.plate, s = 1 / 100, W = 2 * P * s, H = 2 * PY * s;
  const B = D.plates[u.floor].map(b => { const a = Math.min(b[1], b[3]), c = Math.max(b[1], b[3]), d = Math.min(b[2], b[4]), e = Math.max(b[2], b[4]), me = b[0] === u.unit;
    return `<rect x="${(a + P) * s}" y="${(PY - e) * s}" width="${(c - a) * s}" height="${(e - d) * s}" fill="${me ? "#c41e3a" : "#e6e3dc"}" stroke="#3a3f47" stroke-width="2"/>
      <text x="${(a + c) / 2 * s + P * s}" y="${(PY - (d + e) / 2) * s + 5}" font-size="15" text-anchor="middle" fill="${me ? "#fff" : "#555"}" font-weight="${me ? 700 : 400}">${b[0].slice(-2)}</text>`; }).join("");
  return `<svg class="plan" viewBox="-30 -30 ${W + 60} ${H + 60}" font-family="inherit"><rect x="${(P - 7000) * s}" y="${(PY - 11000) * s}" width="140" height="220" fill="#cfcfcb" stroke="#3a3f47" stroke-width="2"/>
    <text x="${W / 2}" y="${H / 2 + 5}" font-size="14" text-anchor="middle" fill="#666">core</text>${B}<text x="${W / 2}" y="-10" font-size="14" text-anchor="middle" fill="#888">N ↑ · floor ${u.floor}</text></svg>`; }

function close_(o) { $("card").style.display = "none"; if (o && o.els) o.els.forEach(e => e.classList.remove("sel")); sel = null; }
function open_(html, o) { const c = $("card"); c.innerHTML = `<span class="x">&times;</span>` + html; c.style.display = "block"; c.scrollTop = 0; c.querySelector(".x").onclick = () => close_(o); }
function pick(o) { if (sel && sel.els) sel.els.forEach(e => e.classList.remove("sel")); sel = o; o.els.forEach(e => e.classList.add("sel")); o.band ? bandCard(o) : unitCard(o); }
function unitCard(u) { const s = u.sheet, p = u.programme || {}, reg = D.register.find(r => r.type === REGTYPE[u.type]);
  const pill = u.status === "available" ? `<span class="pill a">AVAILABLE · sheet of ${D.latest}</span>` : u.status === "gone" ? `<span class="pill g">was on the ${s.date} sheet · not on ${D.latest}</span>` : `<span class="pill n">not on the developer's sheet</span>`;
  const slug = {"1 BHK":"1br","Master Suite":"mastersuite_1br","2 BHK":"2br","3 BHK":"3br","4 BHK":"4br","4 BHK Duplex":"4br_duplex_lower"}[u.type];
  const msg = encodeURIComponent(`The Symphony by Imtiaz · unit ${u.unit} · ${u.type}, floor ${u.floor} · ${fmt(u.sqft)} sq ft` + (s ? ` · AED ${fmt(s.price)} · ${s.view}` : "") + ` · ${D.plan || ""} · completion ${D.completion || ""}`);
  open_(`<div class="t">${u.type} · floor ${u.floor}</div><h2>Unit ${u.unit}</h2>${pill}<dl>
    <dt>Size</dt><dd>${fmt(u.sqft)} sq ft${s ? "" : " <small>(model)</small>"}</dd>${s ? `<dt>Asking</dt><dd>AED ${fmt(s.price)}</dd><dt>View</dt><dd>${s.view}</dd>` : ""}
    <dt>Bedrooms</dt><dd>${p.bedrooms ?? "—"}</dd><dt>Bathrooms</dt><dd>${p.bathrooms ?? "—"}${p.powder ? " + powder" : ""}${p.maid ? " + maid's" : ""}</dd>
    <dt>Payment plan</dt><dd>${D.plan || "—"}</dd><dt>Completion</dt><dd>${D.completion || "—"}</dd></dl>
    ${reg ? `<h3>What this type settles at</h3><div class="row"><span>${reg.type}, Land Department register</span><span>${reg.median ? M(reg.median) : "—"}</span></div>
      <div class="row"><span>Sold so far</span><span>${reg.sold} of ${reg.launched} · ${reg.left} left</span></div>${s && reg.median ? `<div class="row"><span>This unit's asking price</span><span>${M(s.price)} <small>(${s.price > reg.median ? "+" : ""}${Math.round(100 * (s.price / reg.median - 1))}%)</small></span></div>` : ""}` : ""}
    <h3>The plan</h3>${planSVG(u)}<h3>Where it sits on the floor</h3>${plateSVG(u)}
    <div class="acts"><a class="w" target="_blank" href="https://wa.me/?text=${msg}">Send by WhatsApp</a>${slug ? `<a class="c" target="_blank" href="https://azimuth-2.digitalchemy.workers.dev/img/card_symphony_${slug}">Unit type card</a>` : ""}</div>
    <div class="src">${s ? "Size, asking price and view: the developer's availability sheet. " : "Size: DigitAlchemy's model of the floor plate (indicative). Price and view appear when the unit is on the developer's sheet. "}Plan and floor plate: DigitAlchemy® Revit model, scaled from the developer's floor-plan deck — indicative, not surveyed.</div>`, u); }
function bandCard(b) { if (b.type === "Clubhouse") return open_(`<div class="t">Floor 9</div><h2>Clubhouse &amp; gym</h2><h3>Amenities</h3>${D.amenities.map(a => `<div class="row"><span>${a}</span><span></span></div>`).join("")}<div class="src">Amenity list: imtiaz.ae. Floor 9 per the developer's floor-plan deck.</div>`, b);
  const os = D.offices[String(b.floor)] || [];
  open_(`<div class="t">Floor ${b.floor} · offices</div><h2>Office floor ${b.floor}</h2><span class="pill ${os.length ? "a" : "n"}">${os.length ? os.length + " on the " + D.latest + " sheet" : "none on the developer's sheet"}</span>
    ${os.length ? "<h3>Available</h3>" + os.map(o => `<div class="row"><span>${o.no}<br><small>${fmt(o.sqft)} sq ft · ${o.view}</small></span><span>AED ${fmt(o.price)}</span></div>`).join("") : ""}
    <div class="src">Floors 1–8 are offices (84 in all) per the developer's floor-plan deck. Availability: developer sheet of ${D.latest}.</div>`, b); }
$("about").onclick = () => { const a = D.areastats, pr = D.progress;
  open_(`<div class="t">${D.developer} · ${D.area}</div><h2>${D.building}</h2><span class="pill n">${D.status}</span>
    <h3>Construction</h3><div class="row"><span>Overall progress</span><span>${pr.overall}%</span></div><div class="bar"><i style="width:${pr.overall}%"></i></div><div class="src">${pr.source}. Developer's estimate: ${pr.completion}.</div>
    <h3>The building</h3>${D.facts.map(f => `<div class="row"><span><small>${f[0]}</small><br>${f[1]}</span><span></span></div>`).join("")}
    <h3>The developer's sheets</h3>${D.history.map(h => `<div class="row"><span>${h.date}<br><small>${h.homes.join(", ") || "no homes"}</small></span><span>${h.homes.length} homes · ${h.other} other</span></div>`).join("")}
    <h3>Around it</h3>${D.around.map(x => `<div class="row"><span>${x.kind} · ${x.name}${x.note ? `<br><small>${x.note}</small>` : ""}</span><span>${x.km} km</span></div>`).join("")}
    <div class="src">Nearest of each kind from the map's amenity layer, measured from the site anchor (site-level, not the front door).</div>
    ${a ? `<h3>The area · ${a.name}</h3><div class="row"><span>Settled sales${a.period ? " · " + a.period : ""}</span><span>${a.sales}</span></div><div class="row"><span>Median per sq ft</span><span>AED ${a.sqft}</span></div>
      <div class="row"><span>Median ticket</span><span>AED ${a.ticket}</span></div><div class="row"><span>Off-plan share</span><span>${a.offplan}%</span></div>${a.layouts.map(l => `<div class="row"><span>${l[0]} · ${l[1]} sales</span><span>AED ${l[2]}</span></div>`).join("")}
      <div class="src">Dubai Land Department, settled not asking. No rents or yield yet: nothing here is complete to let.</div>` : ""}`, null); };
$("foot").innerHTML = `${D.building} · ${D.area} — ${D.units.length} homes on the two faces in view (${D.hidden} more on the far side; ${D.total} in all), offices on floors 1–8, clubhouse on 9.<br>
  Render: Imtiaz Developments (imtiaz.ae). Unit stack: DigitAlchemy® model, indicative. Availability: developer sheet of ${D.latest}.`;
draw();
</script></body></html>
"""

if __name__ == "__main__":
    main()

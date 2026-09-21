"""The 2026 launch board — one self-contained page for Naj: every district ranked by what launched there, and every launch inside it.

Kendall, 21 Sep 2026: "let's build out an app, or a map, just a quick one, to share with Naj so she can get a full understanding
of it... maybe cards... you tell me what you think is best."

Cards in one HTML file, not a PDF per district and not a map: it opens by double-click on any phone, works offline, sends over
WhatsApp as one attachment, and it is searchable — which a stack of 24 PDFs is not. A map looks better and tells her less; she
knows where Al Furjan is, what she does not know is that Sobha launched 4,526 units there and that we can already draw it.

Reads the FULL register (3,039 projects), not the 45 district files (2,645) - the difference hid Bukadra, Liwan and Trump Tower.

    python scripts/build_launch_board.py        -> data/board/launch_board.html
"""
import collections, glob, io, json, os, re, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REG = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dld__dld_projects-open-api.json")
LIVE = ("NOT_STARTED", "ACTIVE", "PENDING", "CONDITIONAL_ACTIVATING")
slug = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())

# The register's developer_name is the LANDOWNER / master developer, not the brand that builds and sells. Checked: it gives
# "Dubai Properties" for Binghatti Aquarise and "Dubai Maritime City" for Breez by Danube. It is right only where the brand owns
# its own land (Sobha, DAMAC). So the board labels it "master" and never calls it the developer - the brand is in the project
# name, which is what a broker actually uses. English names below are read off the English project names on those same rows.
MASTER = {
    "شركة نخيل": "Nakheel", "شوبا": "Sobha", "مجموعة ميدان": "Meydan Group", "دبي للعقارات": "Dubai Properties",
    "اعمار العقارية": "Emaar Properties", "إعمار للتطوير": "Emaar Development", "مدينة دبي الملاحية": "Dubai Maritime City",
    "مؤسسه مدينه دبى للطيران": "Dubai Aviation City", "قرية جميرا": "Jumeirah Village", "ليوان": "Liwan",
    "دبي لاند ريزيدنسز": "Dubailand Residences", "دبي لاند": "Dubailand", "داماك كريسنت": "DAMAC Crescent",
    "داماك ميري": "DAMAC Meray", "مركز دبي للسلع المتعددة": "DMCC", "مدينة دبي الرياضية": "Dubai Sports City",
    "دبي هيلز استيت": "Dubai Hills Estate", "مراس العقارية": "Meraas", "الخليج التجاري": "Business Bay (Dubai Properties)",
    "تيكوم للإستثمارات": "TECOM", "سلطة دبي للمناطق الإقتصادية المتكاملة": "DIEZ", "الفرجان": "Al Furjan",
    "ذي لاجونز": "The Lagoons", "رمرام": "Remraam", "ميناء راشد العقارية": "Mina Rashid", "الاتحاد العقارية": "Union Properties",
    "دى اتش ايه ام": "DHAM free zone", "الياس و مصطفى كلداري": "Kaldari", "أتش أر أي": "HRE", "دار جلوبال": "Dar Global",
    "اراد": "Arada", "سيفين مايفير": "Seven Mayfair",
}


def master_en(ar):
    ar = (ar or "").strip()
    for k, v in MASTER.items():
        if k in ar:
            return v
    return ""


def english_names():
    """project_id -> English name. The raw register carries only the Arabic name; our district files carry project_name_en."""
    out = {}
    for p in glob.glob(os.path.join(ROOT, "data", "board", "projects_*.json")):
        for r in json.load(io.open(p, encoding="utf-8")).get("projects", []):
            n = (r.get("project_name_en") or "").strip()
            if n:
                out[r.get("project_id")] = n
    return out


def avail_now():
    """{project name (lower) -> units free} from the LATEST sheet each developer has sent. This is the only place we know a
    specific unit is free today; the register knows what launched, never what is left. 8 developers, ~46 projects."""
    best = {}
    for f in glob.glob(os.path.join(ROOT, "data", "avail", "*.json")):
        b = os.path.basename(f)
        m = re.match(r"([a-z]+)_(\d{4}-\d{2}-\d{2})", b)
        if not m or "_auto" in b:
            continue
        dev, dt = m.groups()
        if dev not in best or dt > best[dev][0]:
            best[dev] = (dt, f)
    out = {}
    for dev, (dt, f) in best.items():
        for p in json.load(io.open(f, encoding="utf-8")).get("projects", []):
            nm = (p.get("p") or "").strip()
            n = len(p.get("units") or [])
            if nm and n:
                out[nm.lower()] = {"n": n, "dev": dev.title(), "date": dt}
    return out


def area_intel():
    """What PULSE already knows about each area: what it sells for, how off-plan it is, what it yields."""
    d = json.load(io.open(os.path.join(ROOT, "public", "pulse.json"), encoding="utf-8"))
    return {a.get("area"): a for a in ((d.get("areaIntel") or {}).get("areas") or [])}


def models():
    ce = os.path.join(ROOT, "data", "ce")
    return {slug(d): d for d in os.listdir(ce)
            if os.path.isdir(os.path.join(ce, d)) and os.path.exists(os.path.join(ce, d, "buildings.geojson"))}


def build():
    rows = json.load(io.open(REG, encoding="utf-8"))["results"]
    en = english_names()
    ms = models()
    av = avail_now()
    ai = area_intel()
    alias = json.load(io.open(os.path.join(ROOT, "data", "dld", "area_alias.json"), encoding="utf-8"))["alias"]
    rev = collections.defaultdict(list)
    for market, area in alias.items():
        rev[area].append(market)
    pulse = json.load(io.open(os.path.join(ROOT, "public", "pulse.json"), encoding="utf-8"))
    sp = (pulse.get("transactions") or {}).get("offPlanSplit") or {}
    off, ready = sp.get("Off-Plan", 0), sp.get("Ready", 0)

    live = [r for r in rows if (r.get("project_start_date") or "")[:4] in ("2025", "2026")
            and r.get("project_status") in LIVE and (r.get("no_of_units") or 0) > 0]
    by = collections.defaultdict(list)
    for r in live:
        by[r.get("area_name_en") or "?"].append(r)

    districts = []
    for area, rs in by.items():
        mk = (rev.get(area) or [""])[0]
        cands = [slug(area)] + [slug(m) for m in rev.get(area, [])]
        model = next((ms[c] for c in cands if c in ms), None)
        rs.sort(key=lambda r: -(r.get("no_of_units") or 0))
        districts.append({
            "area": area, "market": mk.title(), "model": model,
            "units": sum(r["no_of_units"] for r in rs), "n": len(rs),
            "u26": sum(r["no_of_units"] for r in rs if (r.get("project_start_date") or "")[:4] == "2026"),
            "p": [{
                "name": en.get(r["project_id"]) or r.get("project_name") or "?",
                "m": master_en(r.get("developer_name")),
                "u": r["no_of_units"], "b": round(r.get("percent_completed") or 0),
                "end": (r.get("project_end_date") or "")[:7],
                "start": (r.get("project_start_date") or "")[:10],
                "esc": bool((r.get("escrow_agent_name") or "").strip()),
                "free": (av.get((en.get(r["project_id"]) or "").strip().lower()) or {}).get("n", 0),
                "fdev": (av.get((en.get(r["project_id"]) or "").strip().lower()) or {}).get("dev", ""),
                "fdate": (av.get((en.get(r["project_id"]) or "").strip().lower()) or {}).get("date", ""),
            } for r in rs[:40]],
        })
        k = ai.get(area) or {}
        districts[-1].update({
            "sqft": k.get("medianAedSqft"), "tick": k.get("medianTicketAed"), "sales": k.get("sales"),
            "opct": k.get("offPlanPct"), "yld": k.get("grossYieldPct"),
        })
    districts.sort(key=lambda d: -d["units"])
    for i, d in enumerate(districts, 1):
        d["rank"] = i

    data = {"generated": time.strftime("%d %b %Y"), "districts": districts,
            "total_units": sum(d["units"] for d in districts), "total_p": sum(d["n"] for d in districts),
            "u26": sum(d["u26"] for d in districts),
            "p26": sum(1 for d in districts for x in d["p"] if x["start"][:4] == "2026"),
            "offplan_pct": round(100.0 * off / max(1, off + ready), 1), "off": off, "ready": ready,
            "free_p": sum(1 for d in districts for x in d["p"] if x["free"]),
            "free_u": sum(x["free"] for d in districts for x in d["p"]),
            "modelled": sum(1 for d in districts[:24] if d["model"])}
    tpl = io.open(os.path.join(ROOT, "scripts", "launch_board_template.html"), encoding="utf-8").read()
    out = os.path.join(ROOT, "data", "board", "launch_board.html")
    io.open(out, "w", encoding="utf-8").write(tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))))
    print("%d districts, %d launches, %d units -> %s (%.1f MB)"
          % (len(districts), data["total_p"], data["total_units"], os.path.relpath(out, ROOT), os.path.getsize(out) / 1e6))
    return out


if __name__ == "__main__":
    build()

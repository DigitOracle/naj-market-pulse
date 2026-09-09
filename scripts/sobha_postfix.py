"""Post-pass over the Sobha harvest: sobharealty.com <title> tags are marketing taglines ('Living in Dubai | Sobha One'), so normalise
name (from the URL slug) and area (from the known-area list / the 'located within ...' sentence) in sobha_portfolio.json, every kit meta.json
and every NEW plan-pack meta.json. Pure local file rewrite - no network."""
import json, os, re, sys, glob
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "data", "plans", "harvest", "_work"))
from harvest_dev import area_from  # noqa: E402

OVERRIDE = {"sobha-verde": "Verde by Sobha", "golf-ridges": "Golf Ridges at Sobha One", "the-element": "The Element at Sobha One", "sobha-skyparks": "Sobha SkyParks",
            "sobha-seahaven": "Sobha SeaHaven", "uaq-downtown": "Downtown UAQ", "sky-edition": "SeaHaven Sky Edition", "the-s": "The S", "sobha-hartland-2": "Sobha Hartland II",
            "community-sobha-hartland-2": "Sobha Hartland II", "sobha-hartland-townhouses": "Sobha Hartland Townhouses", "sobha-hartland-greens": "Sobha Hartland Greens",
            "sobha-sanctuary-the-woods": "The Woods (Sobha Sanctuary)", "sobha-city": "Sobha City (Abu Dhabi)", "community-sobha-city": "Sobha City (Abu Dhabi)"}
TAGLINE = re.compile(r"luxury|premium|award|residences? in|living in|community in|apartments? in|villas? in|for sale|homes? in|signature|urban|waterfront|lagoon|golf-integrated|explore|discover|invest", re.I)


def slug_name(slug):
    if slug in OVERRIDE:
        return OVERRIDE[slug]
    s = slug.replace("community-", "")
    words = s.split("-")
    out = []
    for w in words:
        if w in ("uaq",):
            out.append("UAQ")
        elif w.isdigit():
            out.append(w)
        else:
            out.append(w.capitalize())
    n = " ".join(out)
    return n.replace("Skyvue", "Skyvue").replace("Skyscape", "Skyscape").replace("Seahaven", "SeaHaven").replace("Skyparks", "SkyParks")


def fix_area(p):
    loc = (p.get("facts") or {}).get("location") or ""
    blob = " ".join([loc, p.get("title", ""), p.get("description", ""), p["url"].replace("-", " ")])
    a = area_from(blob)
    cur = p.get("area") or ""
    if a:
        # prefer the more specific community name when the blob has it
        for pref in ("Sobha Hartland", "Sobha Siniya Island", "Siniya", "Dubai Harbour", "Motor City", "Sheikh Zayed Road", "Al Bahiya"):
            if re.search(pref, blob, re.I):
                a = {"Siniya": "Sobha Siniya Island, Umm Al Quwain"}.get(pref, pref)
                if pref == "Sobha Hartland" and re.search(r"Hartland (?:2|II)", blob):
                    a = "Sobha Hartland II"
                break
        return a
    if cur and not TAGLINE.search(cur):
        return cur
    return loc[:60] or None


def fix_mix(p):
    """Bedroom mix: floor-plan tabs / unit-type headings first (clean), page text only as a fallback; drop nav noise (villa/penthouse menu words)."""
    f = p.get("facts") or {}
    tabs = []
    for t in (f.get("mix") or []):
        if re.match(r"^(STUDIO|\d(?:\.5)?BR)$", t):
            tabs.append(t)
    for u in p.get("unit_types") or []:
        m = re.match(r"(\d(?:\.5)?)\s*(?:Bed(?:room)?|BR)", u.get("type", ""), re.I)
        if m and m.group(1) + "BR" not in tabs:
            tabs.append(m.group(1) + "BR")
        if re.search(r"studio", u.get("type", ""), re.I) and "STUDIO" not in tabs:
            tabs.append("STUDIO")
    if tabs:
        f["mix"] = sorted(tabs, key=lambda x: (x != "STUDIO", float(x.replace("BR", "")) if x != "STUDIO" else 0))
        return
    f["mix"] = [t for t in (f.get("mix") or []) if len(t) <= 10 and t not in ("villa", "penthouse", "retail", "office", "townhouse", "villament", "mansion", "duplex")
                or re.match(r"^\d", t)][:10]


def main():
    pf = os.path.join(ROOT, "data", "dev_meta", "sobha_portfolio.json")
    P = json.load(open(pf, encoding="utf-8"))
    names = {}
    for p in P["properties"]:
        slug = p["slug"]
        cur = p.get("name") or ""
        sw = [w for w in slug.replace("community-", "").split("-") if len(w) > 2]
        if TAGLINE.search(cur) or not all(w.lower() in cur.lower() for w in sw) or slug in OVERRIDE:
            p["name"] = slug_name(slug)
        p["area"] = fix_area(p)
        fix_mix(p)
        names[slug] = (p["name"], p["area"])
    json.dump(P, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n1 = n2 = 0
    for mp in glob.glob(os.path.join(ROOT, "data", "kits", "sobha", "site", "*", "meta.json")):
        slug = os.path.basename(os.path.dirname(mp))
        if slug in names:
            m = json.load(open(mp, encoding="utf-8")); m["project"], m["area"] = names[slug][0], names[slug][1] or ""
            json.dump(m, open(mp, "w", encoding="utf-8"), indent=1, ensure_ascii=False); n1 += 1
    for mp in glob.glob(os.path.join(ROOT, "data", "plans", "harvest", "sobha", "*", "meta.json")):
        m = json.load(open(mp, encoding="utf-8"))
        if "harvested 9 Sep 2026" not in m.get("source", ""):
            continue
        src = m["source"].split(": ")[-1].strip()
        hit = [s for s, p in ((q["slug"], q) for q in P["properties"]) if p["url"] == src]
        if hit:
            m["project"], m["area"] = names[hit[0]][0], names[hit[0]][1] or m.get("area", "")
            json.dump(m, open(mp, "w"), indent=1); n2 += 1
    print("portfolio", len(P["properties"]), "kit metas", n1, "pack metas", n2)
    for s, (n, a) in names.items():
        print(f"  {s:<32} {n:<34} {a}")


if __name__ == "__main__":
    main()

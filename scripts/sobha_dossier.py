"""Compose data/kits/sobha/SOBHA_PUBLIC_DOSSIER.md (< 1,500 words) from sobha_portfolio.json + the DLD register already on disk
+ the press releases / About / Leadership / Investor Relations pages cached on 9 Sep 2026 (data/dev_meta/_html/sobha/).
Only what the developer's own pages or the DLD open-data register state; anything else is written as 'n/s' (not stated)."""
import json, os, re, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
P = json.load(open(os.path.join(ROOT, "data", "dev_meta", "sobha_portfolio.json"), encoding="utf-8"))
D = json.load(open(os.path.join(ROOT, "data", "kits", "sobha", "SOBHA_DLD_projects.json"), encoding="utf-8"))
props = {p["slug"]: p for p in P["properties"]}

HEADLINE = [("community-sobha-hartland", "Sobha Hartland (community)"), ("community-sobha-hartland-2", "Sobha Hartland II (community)"), ("sobha-one", "Sobha One"),
            ("the-element", "The Element (Sobha One)"), ("golf-ridges", "Golf Ridges (Sobha One)"), ("sobha-central", "Sobha Central"), ("the-mirage", "The Mirage (Central)"),
            ("sobha-seahaven", "Sobha SeaHaven"), ("sky-edition", "SeaHaven Sky Edition"), ("sobha-skyparks", "Sobha SkyParks"), ("sobha-solis", "Sobha Solis"),
            ("sobha-orbis", "Sobha Orbis"), ("sobha-reserve", "Sobha Reserve"), ("community-sobha-siniya-island", "Sobha Siniya Island (community)"),
            ("skyscape", "Skyscape"), ("skyvue", "Skyvue"), ("sobha-elwood", "Sobha Elwood"), ("sobha-verde", "Verde by Sobha"),
            ("the-crest", "The Crest"), ("crest-grande", "Crest Grande"), ("creek-vistas", "Creek Vistas"), ("creek-vistas-grande", "Creek Vistas Grande"),
            ("creek-vistas-reserve", "Creek Vistas Reserve"), ("creek-vistas-heights", "Creek Vistas Heights"),
            ("310-riverside-crescent", "310 Riverside Crescent"), ("320-riverside-crescent", "320 Riverside Crescent"), ("330-riverside-crescent", "330 Riverside Crescent"),
            ("340-riverside-crescent", "340 Riverside Crescent"), ("350-riverside-crescent", "350 Riverside Crescent"), ("360-riverside-crescent", "360 Riverside Crescent"),
            ("sobha-estates", "Sobha Estates"), ("waves-opulence", "Waves Opulence"), ("sobha-aquacrest", "Sobha Aquacrest"),
            ("community-sobha-sanctuary", "Sobha Sanctuary (community)"), ("sobha-aquamont", "Sobha Aquamont (UAQ)")]

# DLD register (Arabic names) -> page slug; most specific first, with exclusions
DLD_RULES = [("ذا ايليمنت", None, "the-element"), ("شوبا ون", "ايليمنت", "sobha-one"), ("310", None, "310-riverside-crescent"), ("320", None, "320-riverside-crescent"),
             ("330", None, "330-riverside-crescent"), ("340", None, "340-riverside-crescent"), ("350", None, "350-riverside-crescent"), ("360", None, "360-riverside-crescent"),
             ("سكاي سكيب", None, "skyscape"), ("سكاي فيو", None, "skyvue"), ("شوبا ريزرف", None, "sobha-reserve"), ("شوبا أوربيس", None, "sobha-orbis"),
             ("شوبا سوليس", None, "sobha-solis"), ("فيردي", None, "sobha-verde"), ("شوبا استيتس", None, "sobha-estates"), ("إلوود", None, "sobha-elwood"),
             ("سيهافين البرج أ", None, "sobha-seahaven"), ("سيهيفين البرج ب", None, "sobha-seahaven"), ("سنترال فيز", None, "sobha-central"),
             ("ذا كرست", None, "the-crest"), ("كريست جراندي", None, "crest-grande"), ("كريك فيستا هايتس", None, "creek-vistas-heights"),
             ("كريك فيستا جراندي", None, "creek-vistas-grande"), ("كريك فيستاس ريزرف", None, "creek-vistas-reserve"), ("شوبا كريك فيستاس", "ريزرف", "creek-vistas"),
             ("ذا إس تاور", None, "the-s"), ("ويفز اوبيولينس", None, "waves-opulence"), ("ويفز جراندى", None, "waves-grande"), ("هارتلاند ويفز", "جراندى|اوبيولينس", "waves"),
             ("ون بارك افينيو", None, "one-park-avenue"), ("جرينز", None, "sobha-hartland-greens")]
dld = {}
for pr in D["projects"]:
    nm = pr.get("project_name", "")
    for key, excl, slug in DLD_RULES:
        if key in nm and not (excl and re.search(excl, nm)):
            dld.setdefault(slug, []).append(pr); break


def dcol(slug):
    rows = dld.get(slug)
    if not rows:
        return "-"
    out = []
    for d in rows:
        u = int(d.get("no_of_units") or 0)
        out.append(f"{u if u else 'n/s'}u·{float(d['percent_completed']):.0f}%·{(d.get('project_end_date') or 'n/s')[:7]}·{d['project_status'].lower().replace('_', '-')}")
    return " / ".join(out)


PARENT = {"sobha-hartland": "Sobha Hartland, MBR City", "sobha-hartland-2": "Sobha Hartland II, MBR City", "sobha-central": "Sobha Central, Sheikh Zayed Rd",
          "sobha-one": "Sobha One, Ras Al Khor", "seahaven": "SeaHaven, Dubai Harbour", "sobha-siniya-island": "Siniya Island, UAQ", "sobha-sanctuary": "Sobha Sanctuary, Dubai",
          "sobha-city": "Sobha City, Abu Dhabi", "downtown-uaq": "Downtown UAQ", "sobha-seahaven": "Dubai Harbour", "the-mirage": "Sobha Central, Sheikh Zayed Rd",
          "the-pinnacle": "Sobha Central, Sheikh Zayed Rd", "skyvue-altier": "Sobha Hartland II, MBR City", "sobha-aquamont": "Downtown UAQ"}


def location(p):
    segs = [s for s in p["url"].replace("https://sobharealty.com", "").split("/") if s]
    for s in segs[1:]:
        if s in PARENT:
            return PARENT[s]
    loc = (p["facts"].get("location") or "").strip()
    if loc and not re.search(r"features|offers|making|attractive|with beach", loc):
        loc = re.sub(r"\s*\(.*?\)", "", loc)
        return loc if len(loc) <= 40 else loc[:40].rsplit(" ", 1)[0]
    return (p.get("area") or "n/s")[:40]


def mixcol(p):
    f = p["facts"]
    br = [x for x in f["mix"] if re.match(r"^(STUDIO|\d)", x)]
    if not br and p.get("unit_types"):
        br = sorted({re.sub(r"\s*\(.*", "", u["type"]) for u in p["unit_types"]})
    if br:
        nums = [re.sub(r"BR$", "", x) for x in br if re.match(r"^\d", x)]
        return ("/".join(nums) + "BR") if nums and len(nums) == len(br) else ", ".join(br)[:50]
    other = [x for x in f["mix"] if re.match(r"^(villa|townhouse|penthouse|mansion|duplex)$", x, re.I)]
    return "/".join(other) or "n/s"


def row(slug, label):
    p = props.get(slug)
    if not p:
        if "skyparks" in slug:
            return f"| {label} | HTTP 403 (both URLs) | | | - | https://sobharealty.com/properties-in-dubai/sobha-skyparks |"
        return f"| {label} | page not captured | | | - | |"
    f = p["facts"]
    return f"| {label} | {location(p)} | {mixcol(p)} | {f['handover'] or 'n/s'} | {dcol(slug)} | {p['url']} |"


L = []
A = L.append
A("# Sobha Realty — Public-Source Dossier")
A("")
A("Compiled 9 Sep 2026 from sobharealty.com only (project pages, About, Leadership, Investor Relations, Press Releases) plus the DLD project register on disk (`SOBHA_DLD_projects.json`). No portals, no logins, 1 request/second, robots.txt honoured. Facts as the developer prints them; **n/s = not stated on the site**.")
A("")
A("## 1. Company facts (as the site states them)")
A("")
A("- **Founding:** Sobha Group founded 1976 by PNC Menon as an interior decoration firm in Oman; now a multinational group with developments in the UAE, Oman, India and the UK (About). 2026 is its 50th anniversary (press, 22 Jul 2026).")
A("- **Leadership page:** PNC Menon, Founder; **Ravi Menon, Chairman**, appointed to lead Sobha Group alongside his father; **Francis Alfred, Managing Director, Sobha Realty**.")
A("- **Backward Integration:** 'recognised as a Harvard case study for its pioneering backward integration in real estate' (Leadership page); design, engineering, construction and quality control in-house (press, 6 Apr 2026). Philosophy: 'The Art of Detail'.")
A("- **About-page counters:** ~8 Mn sq ft land area developed; ~3,000 employees (2024); ~10 % market share in Dubai.")
A("- **Listing status:** n/s. Investor Relations offers Financial Statements and Investor Updates behind a request form (H1 FY26, 5 Aug 2026; FY 2025, 21 Jan 2026). No exchange, ticker, ownership or revenue figure is printed. DLD register: SOBHA L.L.C, developer no. 966.")
A("- **ESG:** 2025 GRESB score 97, 4-Star, #1 in Asia in its peer group (press).")
A("- **Sobha Siniya Island, UAQ (community page):** natural island 50 min from Dubai, 30 from Sharjah, 10 from Al Marjan Island, 1.7 km bridge; resorts, mansions, villas, residences; 18-hole golf course; 46 % open green space; beach residences, marina residences, island villas.")
A("- **Sobha City, Abu Dhabi (press, 11 Apr 2026):** first Abu Dhabi project; Al Bahiya, E10/E12 corridor; ~38 million sq ft masterplan, first phase ~8 million sq ft; ~60 % open/green, 50,000+ trees, 18 km wellness loop, Par-3 course by Greg Norman Golf Course Design.")
A("")
A("## 2. 2026 launches, handovers and news (as announced)")
A("")
A("- **Handovers (22 Jul 2026):** 6,819 units across Dubai in 2026, ~AED 21.6 billion, the largest annual delivery to date; spans Sobha Hartland, Hartland II, Sobha Reserve, Sobha One and Verde by Sobha. 2025 sales AED 30 billion (+30 %). Pipeline: 16 UAE masterplans incl. Sobha Sanctuary (AED 50 billion, Dubai) and Sobha City (AED 40 billion, Abu Dhabi).")
A("- **The Mirage at Sobha Central (press, 10 Nov, year n/s):** 677 homes; after 1,500+ units sold at Sobha Central for AED 3.5 billion; buyers 26 % Indian, 15 % European. Masterplan: 250,000 sq ft green space, 175,000 sq ft offices, 160,000 sq ft retail incl. a mall.")
A("- **MoUs 2026:** Emirates NBD (6 Apr) and NBQ (1 Jul) off-plan mortgages; Project Management Institute (11 Aug); 10 universities (22 May).")
A("- **Blocked:** press releases for **Sobha SkyParks** ('its tallest creation') and **Sobha Aquacrest** ('second cluster of its AED 20 billion landmark') and both SkyParks project pages return HTTP 403; nothing is taken from them.")
A("")
A("## 3. Projects — what each developer page states")
A("")
A("**Units and payment plans are n/s on every project page** (they live in the brochures), so those columns are omitted. Mix = floor-plan tabs; DLD = units · % complete · registered end · status.")
A("")
A("| Project | Location | Mix | Handover | DLD register | URL |")
A("|---|---|---|---|---|---|")
for slug, label in HEADLINE:
    A(row(slug, label))
A("")
pp = [(p["name"], p["printed_price"]) for p in P["properties"] if p.get("printed_price")]
if pp:
    A("**Starting prices printed by the developer** (asterisked, 'subject to inventory availability'): " + "; ".join(f"{n} {v}" for n, v in pp) + ".")
    A("")
others = [p for p in P["properties"] if p["slug"] not in {s for s, _ in HEADLINE}]
if others:
    grp = {}
    for p in others:
        segs = [s for s in p["url"].replace("https://sobharealty.com", "").split("/") if s]
        grp.setdefault(PARENT.get(segs[1], "other") if len(segs) > 2 else "other", []).append(p)
    A(f"**Further pages captured ({len(others)}, same kit format, full records in `data/dev_meta/sobha_portfolio.json`):** " + "; ".join(f"{k}: {len(v)} sub-pages" for k, v in grp.items()) + ".")
    A("")
A("## 4. What the site does not publish")
A("")
A("- Unit counts, handover dates and payment plans are, with the few exceptions shown, **not printed on the project pages**; pages carry hero/gallery imagery, a floor-plan carousel (type, suite/balcony/total sq ft), FAQs and an enquiry form. Brochures saved under `data/kits/sobha/site/<slug>/` were not mined for the table.")
A("- No listing venue, ownership, revenue or profit figures beyond the press-release sales totals above. Siniya Island, Sobha City and Aquamont sit outside Dubai and have no DLD row.")
A("")
A("## 5. Sources")
A("")
A("Every URL fetched (status, yield) is logged in `data/kits/sobha/SOBHA_SOURCES.json`. Key pages: https://sobharealty.com/about · https://sobharealty.com/about/our-leadership-team · https://sobharealty.com/media-center/investor-relations · https://sobharealty.com/media-center/press-releases (nine releases) · https://sobharealty.com/sitemap.xml · the table URLs.")
md = "\n".join(L)
out = os.path.join(ROOT, "data", "kits", "sobha", "SOBHA_PUBLIC_DOSSIER.md")
open(out, "w", encoding="utf-8").write(md)
words = len(re.findall(r"\S+", re.sub(r"https?://\S+", "URL", md)))
print("written", out, "| words (each URL = 1):", words, "| rows captured:", sum(1 for s, _ in HEADLINE if s in props), "/", len(HEADLINE))

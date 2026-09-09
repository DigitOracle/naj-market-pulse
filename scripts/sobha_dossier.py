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
            ("the-element", "The Element at Sobha One"), ("golf-ridges", "Golf Ridges at Sobha One"), ("sobha-central", "Sobha Central"), ("the-mirage", "The Mirage"),
            ("the-pinnacle", "The Pinnacle"), ("the-eden", "The Eden"), ("the-serene", "The Serene"), ("the-tranquil", "The Tranquil"), ("the-horizon", "The Horizon"),
            ("sobha-seahaven", "Sobha SeaHaven"), ("sky-edition", "SeaHaven Sky Edition"), ("sobha-skyparks", "Sobha SkyParks"), ("sobha-solis", "Sobha Solis"),
            ("sobha-orbis", "Sobha Orbis"), ("sobha-reserve", "Sobha Reserve"), ("community-sobha-siniya-island", "Sobha Siniya Island (community)"),
            ("skyscape", "Skyscape"), ("skyvue", "Skyvue"), ("skyvue-altier", "Skyvue Altier"), ("sobha-elwood", "Sobha Elwood"), ("sobha-verde", "Verde by Sobha"),
            ("the-crest", "The Crest"), ("crest-grande", "Crest Grande"), ("creek-vistas", "Creek Vistas"), ("creek-vistas-grande", "Creek Vistas Grande"),
            ("creek-vistas-reserve", "Creek Vistas Reserve"), ("creek-vistas-heights", "Creek Vistas Heights"), ("riverside-crescent", "Riverside Crescent (cluster)"),
            ("310-riverside-crescent", "310 Riverside Crescent"), ("320-riverside-crescent", "320 Riverside Crescent"), ("330-riverside-crescent", "330 Riverside Crescent"),
            ("340-riverside-crescent", "340 Riverside Crescent"), ("350-riverside-crescent", "350 Riverside Crescent"), ("360-riverside-crescent", "360 Riverside Crescent"),
            ("sobha-estates", "Sobha Estates"), ("the-s", "The S"), ("waves", "Waves"), ("waves-grande", "Waves Grande"), ("waves-opulence", "Waves Opulence"),
            ("sobha-hartland-greens", "Hartland Greens"), ("one-park-avenue", "One Park Avenue"), ("sobha-aquacrest", "Sobha Aquacrest"),
            ("community-sobha-sanctuary", "Sobha Sanctuary (community)"), ("community-sobha-city", "Sobha City, Abu Dhabi (community)"), ("sobha-aquamont", "Sobha Aquamont (UAQ)")]

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
          "sobha-city": "Sobha City, Abu Dhabi", "downtown-uaq": "Downtown UAQ"}


def location(p):
    segs = [s for s in p["url"].replace("https://sobharealty.com", "").split("/") if s]
    for s in segs[1:-1]:
        if s in PARENT:
            return PARENT[s]
    loc = (p["facts"].get("location") or "").strip()
    if loc and not re.search(r"features|offers|making|attractive|with beach", loc):
        return re.sub(r"\s*\(.*?\)", "", loc)[:40]
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
A("Compiled 9 Sep 2026 from sobharealty.com only (project pages, About, Leadership, Investor Relations, Press Releases) plus the Dubai Land Department project register already on disk (`SOBHA_DLD_projects.json`). No portals, no logins, 1 request/second, robots.txt honoured. Facts are as the developer prints them; **n/s = not stated on the site**. Prices appear only where a developer page prints a starting price.")
A("")
A("## 1. Company facts (as the site states them)")
A("")
A("- **Founding:** Sobha Group was founded in 1976 by PNC Menon, a first-generation entrepreneur, as an interior decoration firm in Oman; today a multinational, multiproduct group with developments and investments in the UAE, Oman, India and the UK (About; press boilerplate). 2026 is the Group's 50th anniversary (press, 22 Jul 2026).")
A("- **Leadership (Leadership page):** PNC Menon, Founder; **Ravi Menon, Chairman**, appointed to lead Sobha Group alongside his father; **Francis Alfred, Managing Director, Sobha Realty**.")
A("- **Backward Integration:** the Group is 'recognised as a Harvard case study for its pioneering backward integration in real estate' (Leadership page); design, engineering, construction and quality control are managed in-house (press, 6 Apr 2026). Brand philosophy: 'The Art of Detail'.")
A("- **Scale counters (About page source):** ~8 Mn sq ft of land area developed; ~3,000 employees as of 2024; ~10 % market share in Dubai.")
A("- **Listing status:** n/s. The Investor Relations page publishes Financial Statements and Investor Updates behind a request form (H1 FY26 on 5 Aug 2026; FY 2025 on 21 Jan 2026; FY 2024 on 6 Feb 2025; Corporate Presentation 2024 on 13 Aug 2024). No exchange, ticker, ownership or revenue figure is printed. The DLD register names SOBHA L.L.C (developer no. 966) on the active projects.")
A("- **ESG:** 2025 GRESB Real Estate Assessment score 97 (from 72 three years earlier), 4-Star, #1 in Asia in its peer group (press).")
A("- **Sobha Siniya Island, Umm Al Quwain (community page):** natural island 50 minutes from Dubai, 30 from Sharjah, 10 from Al Marjan Island, connected by a 1.7 km bridge; resorts, mansions, villas and residences; 18-hole golf course; 46 % of the island open green space; beach residences, marina residences and island villas (sub-pages captured, see table).")
A("- **Sobha City, Abu Dhabi (press, 11 Apr 2026):** first Abu Dhabi project; Al Bahiya on the E10/E12 corridor near Zayed International Airport and Yas Island; ~38 million sq ft masterplan, initial phase ~8 million sq ft; ~60 % open and green space, 50,000+ trees, 18 km wellness loop, executive Par-3 course by Greg Norman Golf Course Design; schools, healthcare, mosques.")
A("")
A("## 2. 2026 launches, handovers and corporate news (as announced)")
A("")
A("- **Handovers (22 Jul 2026):** 6,819 units across Dubai to be handed over in 2026, sales value ~AED 21.6 billion, the company's largest annual delivery; spans Sobha Hartland, Sobha Hartland II, Sobha Reserve, Sobha One and Verde by Sobha. 2025 sales AED 30 billion (+30 % year on year). Pipeline: 16 UAE masterplans incl. Sobha Sanctuary (AED 50 billion, Dubai) and Sobha City (AED 40 billion, Abu Dhabi).")
A("- **The Mirage at Sobha Central (press dated 10 Nov, year n/s):** 677 homes; follows 1,500+ units sold at Sobha Central for AED 3.5 billion; buyers 26 % Indian, 15 % European. Sobha Central masterplan: 250,000 sq ft open green space, 175,000 sq ft leasable offices, 160,000 sq ft retail/dining incl. an integrated mall.")
A("- **Financing MoUs:** Emirates NBD (6 Apr 2026) and National Bank of Umm Al Qaiwain (1 Jul 2026), preferential mortgages for off-plan buyers across Sobha developments.")
A("- **Other 2026 MoUs:** Project Management Institute (11 Aug 2026); 10 universities (22 May 2026).")
A("- **Blocked:** the press releases for **Sobha SkyParks ('its tallest creation')** and **Sobha Aquacrest ('second cluster of its AED 20 billion landmark')** and both SkyParks project pages return HTTP 403 to a polite browser fetch; no facts are taken from them.")
A("")
A("## 3. Projects — what each developer page states")
A("")
A("Location as printed | units | bedroom mix (floor-plan tabs) | handover | payment plan | DLD register (units, % complete, registered end date, status) | URL.")
A("")
A("| Project | Location | Units | Mix | Handover | Payment | DLD register | URL |")
A("|---|---|---|---|---|---|---|---|")
for slug, label in HEADLINE:
    A(row(slug, label))
A("")
pp = [(p["name"], p["printed_price"]) for p in P["properties"] if p.get("printed_price")]
if pp:
    A("**Starting prices printed by the developer** (asterisked, 'subject to inventory availability'): " + "; ".join(f"{n} {v}" for n, v in pp) + ".")
    A("")
others = [p for p in P["properties"] if p["slug"] not in {s for s, _ in HEADLINE}]
if others:
    A(f"**Further pages captured ({len(others)}, same kit format):** " + "; ".join(p["name"] for p in others) + ".")
    A("")
A("## 4. What the site does not publish")
A("")
A("- Unit counts, handover dates and payment plans are, with few exceptions (Riverside Crescent 'Dec 2027', Skyscape 'Dec 2028'), **not printed on the project pages**; pages carry hero/gallery imagery, a floor-plan carousel (type, suite/balcony/total sq ft), FAQs and an enquiry form. Brochures saved under `data/kits/sobha/site/<slug>/` were not mined for the table.")
A("- No listing venue, ownership, revenue or profit figures beyond the press-release sales totals above; no corporate structure beyond the Group/Realty naming.")
A("- The DLD register supplies units, completion % and registered end dates where the project is registered (column 'DLD register'); Siniya Island, Sobha City and Aquamont are outside Dubai and have no DLD row.")
A("")
A("## 5. Sources")
A("")
A("Every URL fetched, with status and yield, is logged in `data/kits/sobha/SOBHA_SOURCES.json`. Key pages: https://sobharealty.com/about · https://sobharealty.com/about/our-leadership-team · https://sobharealty.com/media-center/investor-relations · https://sobharealty.com/media-center/press-releases (and the nine release URLs logged there) · https://sobharealty.com/sitemap.xml · the project URLs in the table.")
md = "\n".join(L)
out = os.path.join(ROOT, "data", "kits", "sobha", "SOBHA_PUBLIC_DOSSIER.md")
open(out, "w", encoding="utf-8").write(md)
words = len(re.findall(r"\S+", re.sub(r"https?://\S+", "URL", md)))
print("written", out, "| words (each URL = 1):", words, "| rows captured:", sum(1 for s, _ in HEADLINE if s in props), "/", len(HEADLINE))

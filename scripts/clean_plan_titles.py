"""Clean the harvested project titles in the plans index, so a plan can find its building.

Kendall, 22 Sep 2026: "clean the project titles."

`build_plans_index.py` takes a project's name from the developer's own page, and a developer's page is titled for search,
not for us: "Explore Arbor View Apartment In Arjan", "Bella Rose - Modern Living in AL Barsha South, Dubai", "SAMANA Avenue
- Apartments in Dubai Land Residence Complex", "Binghatti Aquarise Business Bay". The building page matches plans to a
building on the project name (`plansFor` in building_page.js), so every one of those misses.

Measured before this ran: of 168 harvested projects carrying 4,094 plans, **6** matched a named building on the raw title.
Cleaning the titles takes that to **39** - a six-fold lift for a text change, with no new harvesting.

What it does, in order, and only ever to the name:
  1. HTML entities decoded, whitespace squared up.
  2. Everything after a pipe or a dash-with-marketing-after-it dropped: "Clayton Residency | Urban Living" -> "Clayton Residency".
  3. A leading "Explore" / "Discover" / "Dream Home in" dropped.
  4. A trailing place dropped, whether joined by "at", "in", a comma or nothing at all: "ARLO at Dubai Creek Harbour",
     "Binghatti Haven Sports City", "Central Park Towers, DIFC, Dubai". Places come from data/dld/area_alias.json plus the
     district slugs plus the abbreviations the register never uses but a marketing page always does (JVC, JVT, DIFC, IMPZ).
  5. Trailing sales words dropped: "Project", "Apartments for Sale", "Studios & Apartments".
  6. Parentheticals dropped.

**The original is never lost**: it moves to `title`, and `name` becomes the cleaned form - which is also what the page prints
above the plan grid, so "THE PLANS - Explore Arbor View Apartment In Arjan" stops happening too.

Guards: a clean that empties the name, or cuts it below four characters, or removes more than two thirds of it, is refused
and the original stands. A compound that is genuinely the name - "Sobha Sanctuary The Willows" - survives, because nothing
in the place list matches it.

    python scripts/clean_plan_titles.py --dry     what it would change, and the match lift
    python scripts/clean_plan_titles.py --write   rewrite data/board/plans_index.json (keeps a .bak)
"""
import glob, html, json, os, re, shutil, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IDX = os.path.join(ROOT, "data", "board", "plans_index.json")

# places a marketing title tacks on. The register's own alias table, plus the short forms it never uses and a page always does.
EXTRA = ["jvc", "jvt", "jlt", "difc", "impz", "mbr city", "mohammed bin rashid city", "downtown dubai", "downtown",
         "dubai marina", "dubai creek harbour", "creek harbour", "dubai hills estate", "dubai hills", "business bay",
         "sports city", "production city", "studio city", "motor city", "silicon oasis", "discovery gardens",
         "palm jumeirah", "dubai islands", "deira", "al jaddaf", "al jaddaf waterfront", "arjan", "majan", "dubailand",
         "dubai land residence complex", "dubai land", "al barari", "al barsha", "al barsha south", "al warsan",
         "dubai design district", "arabian ranches iii", "arabian ranches", "town square", "damac hills", "the valley",
         "jumeirah village circle", "jumeirah village triangle", "jumeirah lake towers", "al furjan", "dubai south",
         "dubai maritime city", "sobha hartland", "meydan", "nad al sheba", "dubai", "uae", "sheffield"]
# Only phrases a page bolts on, never a bare noun: "Forest Villas" and "Palm Grove Villas" ARE the project names.
SALES = ["apartments for sale", "for sale", "studios & apartments", "studios and apartments",
         "villas & townhouses", "villas and townhouses", "waterfront residences", "spacious villas", "luxury apartments",
         "family apartments", "modern development", "modern living", "urban living", "active living",
         "premium apartments & homes", "design-lead living", "residences project", "project"]
# short forms that are unmistakably a district standing alone; every other place needs two words to strip uninvited
ABBR = {"jvc", "jvt", "jlt", "difc", "impz"}
LEAD = re.compile(r"^\s*(explore|discover|dream home in|introducing|welcome to)\s+", re.I)


def places():
    p = os.path.join(ROOT, "data", "dld", "area_alias.json")
    out = set(EXTRA)
    if os.path.exists(p):
        a = json.load(open(p, encoding="utf-8"))["alias"]
        out |= {k.lower() for k in a} | {v.lower() for v in a.values()}
    ce = os.path.join(ROOT, "data", "ce")
    if os.path.isdir(ce):
        out |= {re.sub(r"(?<=[a-z])(?=[A-Z])", " ", d).lower() for d in os.listdir(ce) if os.path.isdir(os.path.join(ce, d))}
    return sorted(out, key=len, reverse=True)                  # longest first: "dubai creek harbour" before "dubai"


PLACES = places()


def clean(raw):
    s = html.unescape(raw or "").replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*\|.*$", "", s)                             # "... | Design-Lead Living in ..."
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)                     # "The Woods (Sobha Sanctuary)"
    s = LEAD.sub("", s)
    # a dash followed by marketing, or by a place, is a suffix - a dash inside a name ("Bayz 101 - Tower A") is not
    m = re.match(r"^(.*?)\s*[—–-]\s*(.+)$", s)
    if m and (any(w in m.group(2).lower() for w in SALES) or any(p in m.group(2).lower() for p in PLACES)):
        s = m.group(1)
    for _ in range(3):                                         # peel repeatedly: "..., DIFC, Dubai"
        before = s
        for w in SALES:
            s = re.sub(r"[\s,—–-]+%s\b.*$" % re.escape(w), "", s, flags=re.I)
        for p in PLACES:
            # take a stranded noun with the place: "Arbor View Apartment In Arjan" -> "Arbor View", not "Arbor View Apartment"
            s = re.sub(r"[\s,]+(?:apartments?|villas?|townhouses?|residences?|homes?)?[\s,]*(?:at|in|near)\s+%s\b.*$"
                       % re.escape(p), "", s, flags=re.I)
            # A bare, uninvited place at the end only strips when it is two words or a known abbreviation - so
            # "Binghatti Haven Sports City" loses its district but "Address Grand Downtown" keeps its name. Never a
            # "The X" ending, which is a phase ("Sobha Sanctuary The Greens"), and never down to a one-word stub.
            if len(p.split()) > 1 or p in ABBR:
                if not re.search(r"\bthe\s+%s\s*$" % re.escape(p), s, flags=re.I):
                    cut = re.sub(r"[\s,]+%s\s*$" % re.escape(p), "", s, flags=re.I)
                    if len(cut.split()) >= 2:
                        s = cut
        s = re.sub(r"\s*[,—–-]\s*$", "", s).strip()
        if s == before:
            break
    s = re.sub(r"\s+", " ", s).strip(" ,-—–")
    if len(s) < 4 or len(s) < len(raw.strip()) / 3.0:          # refused: too little left to be a name
        return raw.strip()
    return s


def match_rate(projects):
    """How many of these project names find a named building. The same normalisation the page's matcher uses."""
    norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()
    B = set()
    for f in glob.glob(os.path.join(ROOT, "data", "board", "unitmix_*.json")):
        try:
            doc = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for r in (doc.get("buildings_by_id") or {}).values():
            if isinstance(r, dict) and r.get("name"):
                B.add(norm(r["name"]))
    n = 0
    for name in projects:
        c = norm(name)
        if c in B or any(min(len(b), len(c)) > 6 and (b.startswith(c) or c.startswith(b)) for b in B):
            n += 1
    return n, len(B)


if __name__ == "__main__":
    idx = json.load(open(IDX, encoding="utf-8"))
    rows, before, after = [], [], []
    for d in idx["developers"]:
        for p in d.get("projects") or []:
            raw = p.get("title") or p.get("name") or ""
            new = clean(raw)
            before.append(raw); after.append(new)
            if new != raw.strip():
                rows.append((d.get("key"), raw, new, len(p.get("plans") or [])))
    b, nb = match_rate(before); a, _ = match_rate(after)
    print("%d projects, %s plans, against %s named buildings" % (len(before), f"{sum(1 for _ in before):,}", f"{nb:,}"))
    print("titles rewritten: %d" % len(rows))
    print("match a named building:  before %d   after %d   (+%d)" % (b, a, a - b))
    print()
    for k, raw, new, n in sorted(rows, key=lambda r: -r[3])[:20]:
        print("   %-10s %-52s -> %-30s %4d plans" % (k, raw[:51], new[:29], n))
    if "--write" in sys.argv:
        if not os.path.exists(IDX + ".bak"):
            shutil.copy(IDX, IDX + ".bak")
        for d in idx["developers"]:
            for p in d.get("projects") or []:
                raw = p.get("title") or p.get("name") or ""
                new = clean(raw)
                if new != raw.strip():
                    p["title"] = raw.strip()                   # the harvested page title, kept
                    p["name"] = new                            # what the page prints and matches on
        idx["titles_cleaned"] = {"at": __import__("datetime").date.today().isoformat(), "n": len(rows),
                                 "note": "harvested page titles reduced to the project name; the original is in `title`. "
                                         "scripts/clean_plan_titles.py"}
        json.dump(idx, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print("\nwrote %s (%d titles, .bak kept)" % (os.path.relpath(IDX, ROOT), len(rows)))

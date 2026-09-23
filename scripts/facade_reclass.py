"""Re-class tall facades from the REGISTERS instead of from height alone.

Kendall, 22 Sep 2026, looking at the all-Dubai twin: "when we zoom in, some have facades, others do not?"

They all have one. The problem was what they were given. Measured across all 43 districts, 66,715 buildings:

    render   82.6%   painted plaster      stone 14.4%   concrete 2.0%   glass (3 classes) 0.9%

and 83.9% of every class was decided by `default:low` - a guess from height with nothing behind it. I told Kendall the fix
was to class more buildings from evidence: OpenStreetMap's building:material, Overture, and the developer-site harvest.
**Measured, that is a dead end and I was wrong about it.** Of the 2,452 buildings 20 m and over:

    an OSM record            1,807     of those, a material tag      40
    an Overture record       2,095     of those, a facade material   12
    ---------------------------------------------------------------------
    ceiling on material evidence                                     52  (2%)

and the developer portfolios - 600 projects, all with text - carry **zero** material signal; the copy is amenities and
location, never cladding.

What we DO hold for the same 2,452 buildings, from our own registers:

    a known USE (homes / office / hotel)   1,236  (50%)
    a known COMPLETION YEAR                  894  (36%)

That is twenty-four times the coverage of the material tags, and it is a far better prior than height. A 2020s Dubai
residential tower is a glass curtain wall; it is not the fair-faced concrete that 709 tall buildings (28.9%) are currently
given because `default:height>40` said so. Almas Tower - blue glass, famously - is classed `concrete` today. So is Upton
Dubai Tower 1.

**This is a better PRIOR, not evidence about any individual building**, and the `source` field says so on every row it
touches (`prior:*`), so nothing downstream can mistake it for a material fact. Rows already classed from OSM or Overture
are never overwritten: real evidence always wins.

    python scripts/facade_reclass.py --dry            what it would change, by district and class
    python scripts/facade_reclass.py --all            rewrite facade_v2.json in place (keeps a .bak)
"""
import collections, glob, json, os, shutil, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CE = os.path.join(ROOT, "data", "ce")
BOARD = os.path.join(ROOT, "data", "board")
TALL = 20.0                       # metres: below this the render default is right - they are villas and low-rise
GLASS_ERA = 2005                  # Dubai's tower stock goes curtain-wall from about here
VARIANTS = ("glassblue", "glassclear", "glassbronze")


def registers(slug):
    """{footprint id: (use, completion year)} from the floor stack and the unit mix."""
    out = {}
    sp = os.path.join(BOARD, "stack_%s.json" % slug)
    up = os.path.join(BOARD, "unitmix_%s.json" % slug)
    st = json.load(open(sp, encoding="utf-8"))["buildings_by_id"] if os.path.exists(sp) else {}
    um = json.load(open(up, encoding="utf-8"))["buildings_by_id"] if os.path.exists(up) else {}
    for i in set(st) | set(um):
        b, u = st.get(i) or {}, um.get(i) or {}
        use = (b.get("uses") or [None])[0]
        yr = ((b.get("project") or {}).get("end") or (u.get("dld") or {}).get("completion") or "")[:4]
        out[i] = (use, int(yr) if yr.isdigit() else None)
    return out


def reclass(v, use, year, idx):
    """The new class and why, or None to leave it alone.

    Only touches a tall building whose class came from a height default. Real evidence - an OSM material tag, an Overture
    facade - is never overwritten, and low-rise is never touched: plaster is the right answer for a villa.
    """
    if (v.get("h") or 0) < TALL:
        return None
    if not (v.get("source") or "").startswith("default"):
        return None                                        # OSM / Overture said something: leave it
    if v.get("class") in VARIANTS:
        return None                                        # already glass; the default got this one right
    if use == "office" or (year and year >= GLASS_ERA):
        return VARIANTS[idx % 3], "prior:%s%s" % ("office" if use == "office" else "built>=%d" % GLASS_ERA,
                                                  "" if not year else ",%d" % year)
    if use == "hotel" and year and year >= 1995:
        return "glassbronze", "prior:hotel,%d" % year
    if year and year < 1995:
        return "stone", "prior:built<1995,%d" % year
    return None                                            # no use and no year: the height default stands


def run(slugs, write):
    moved = collections.Counter(); per = collections.Counter(); total = tall = 0
    for slug in slugs:
        p = os.path.join(CE, slug, "facade_v2.json")
        if not os.path.exists(p):
            continue
        doc = json.load(open(p, encoding="utf-8"))
        reg = registers(slug)
        n = 0
        for i, v in doc["buildings"].items():
            total += 1
            if (v.get("h") or 0) >= TALL:
                tall += 1
            use, year = reg.get(i, (None, None))
            r = reclass(v, use, year, int(i))
            if not r:
                continue
            new, why = r
            moved["%s -> %s" % (v.get("class"), new)] += 1
            if write:
                v["class"], v["source"] = new, why
            n += 1
        per[slug] = n
        if write and n:
            if not os.path.exists(p + ".bak"):
                shutil.copy(p, p + ".bak")
            doc["reclassed"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": n,
                                "note": "tall height-defaults re-classed from the registers' use and completion year; "
                                        "a prior, not a material observation - see scripts/facade_reclass.py"}
            doc["counts"] = dict(collections.Counter(b.get("class") for b in doc["buildings"].values()))
            json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("%s buildings, %s of them 20 m and over" % (f"{total:,}", f"{tall:,}"))
    print("%s re-classed (%.0f%% of the tall stock)%s"
          % (f"{sum(moved.values()):,}", 100.0 * sum(moved.values()) / max(1, tall), "" if write else "  [dry run]"))
    for k, n in moved.most_common():
        print("   %-26s %s" % (k, f"{n:,}"))
    top = [x for x in per.most_common(8) if x[1]]
    if top:
        print("busiest districts:", ", ".join("%s %d" % (s, n) for s, n in top))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    slugs = args or sorted(d for d in os.listdir(CE)
                           if os.path.isdir(os.path.join(CE, d)) and os.path.exists(os.path.join(CE, d, "facade_v2.json")))
    run(slugs, write="--all" in sys.argv or "--write" in sys.argv)

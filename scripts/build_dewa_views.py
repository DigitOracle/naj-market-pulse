"""Two files from the DEWA register joins, for the app's screens (14 Sep 2026). Reads the lake; writes nothing else.

  data/board/building_activity.json        TWIN colour modes, no nationality: how fast newly handed-over towers fill,
                                           residents against businesses, move-ins in the last six months against the six
                                           before (judged against Dubai's own ratio). Buildings with at least 20 accounts.
  data/internal/community_resident_mix.json  Resident nationality by community, shown in the app to anyone Naj shares a link
                                           groups at 5% or more in communities with at least 500 residential accounts,
                                           regions with their countries at 1%+ (never a figure under 20 accounts), the
                                           filter bands, simplified community outlines. Never shown to clients, never linked to
                                           homes or listings, never pushed anywhere public (data/internal is not in git).

Usage: python scripts/build_dewa_views.py
"""
import datetime as dt, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import lake  # noqa: E402

TWIN_OUT = os.path.join(ROOT, "data", "board", "building_activity.json")
MIX_OUT = os.path.join(ROOT, "data", "internal", "community_resident_mix.json")
SOURCE = "Dubai Electricity and Water Authority (DEWA) customer register via Dubai Data: accounts current at the extract, move-ins to 4 Jan 2026"
HATTA_LON = 55.65                        # the Hatta exclave sits 60 km east; its outlines would squash the city on one map


def twin(con):
    rows = con.execute("""select duid, district, fill_band, fill_per_month, first_month, newly_handed_over, residents_band, residential_pct,
                                 activity_band, last6, prev6, last6_from, last6_to, prev6_from, prev6_to, city_ratio
                          from lk_building_dewa_activity order by duid""").fetchall()
    if not rows:
        raise SystemExit("lk_building_dewa_activity is empty - run register_joins.py building_activity first")
    r0 = rows[0]
    doc = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "source": SOURCE, "attribution": "Source: DEWA open data via Dubai Data",
           "window": {"last6": [r0[11], r0[12]], "prev6": [r0[13], r0[14]]}, "cityRatio": r0[15], "minAccounts": 20,
           "modes": {"fill": {"label": "Filling up: towers handed over since Jan 2024, residential move-ins a month in their first six months",
                              "bands": ["under 5 a month", "5-15 a month", "15-40 a month", "40+ a month"]},
                     "residents": {"label": "Residents against businesses (share of accounts)", "bands": ["mostly businesses", "mixed", "mostly residents"]},
                     "activity": {"label": "Residential move-ins, last six months against the six before, compared with Dubai",
                                  "bands": ["behind Dubai", "in line with Dubai", "ahead of Dubai"]}},
           "notes": ["DEWA keeps current accounts only: earlier move-ins who have since left are not counted, so the earlier six months run low; "
                     "each building is compared with Dubai's own ratio for that reason.",
                     "Handover is read as the first month with three residential move-ins.",
                     "Buildings with fewer than 20 accounts have no colour: a small building's move-in is one household's.",
                     "Coverage is partial: the Municipality's open entrance layer stops at 256 MiB, so many buildings have no DEWA address."],
           "buildings": {str(r[0]): {"district": r[1], "fill": r[2], "fillPerMonth": r[3], "opened": r[4] if r[5] else None, "residents": r[6],
                                     "residentialPct": r[7], "activity": r[8], "last6": r[9], "prev6": r[10]} for r in rows}}
    os.makedirs(os.path.dirname(TWIN_OUT), exist_ok=True)
    json.dump(doc, open(TWIN_OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), default=float)   # DuckDB rounds to Decimal
    return len(rows), os.path.getsize(TWIN_OUT)


def clean_name(n):
    """'DownTown Dubai' -> 'Downtown Dubai'; 'Arabian Ranches - 1' -> 'Arabian Ranches 1'; 'Jumeriah Beach Residence - JBR' ->
    'Jumeirah Beach Residence (JBR)'; 'AL' -> 'Al'."""
    n = re.sub(r"\s+", " ", n or "").strip().replace("Jumeriah", "Jumeirah")
    n = re.sub(r"\s*-\s*(\d+)$", r" \1", n)
    n = re.sub(r"\s*-\s*([A-Z]{2,5})$", r" (\1)", n)
    out = []
    for w in n.split(" "):
        if w == "AL":
            w = "Al"
        elif len(w) > 3 and w[:1].isupper() and not w.isupper() and any(c.isupper() for c in w[1:]):
            w = w[0] + w[1:].lower()
        out.append(w)
    return " ".join(out)


def official_name(n):
    """The Municipality writes names in capitals: 'AL BARSHA SOUTH FOURTH' -> 'Al Barsha South Fourth'."""
    return " ".join(w.capitalize() if w.isalpha() else w.title() for w in re.sub(r"\s+", " ", n or "").strip().split(" "))


def community_names(con):
    """comm_num -> {label, official, known}: the master developments holding 15%+ of a community's sales since 2015 (up to three,
    two in the label), else the official name. lk_community_names comes from register_joins.py community."""
    known = {}
    for c, m, share in con.execute("""select comm_num, master_project, share_pct from lk_community_names where share_pct >= 15
                                      order by comm_num, share_pct desc""").fetchall():
        known.setdefault(int(c), [])
        if len(known[int(c)]) < 3:
            known[int(c)].append(clean_name(m))
    out = {}
    for c, name in con.execute("select try_cast(comm_num as bigint), name_en from dm_community").fetchall():
        if c is None:
            continue
        off = official_name(name)
        k = [x for x in known.get(int(c), []) if x.lower() != off.lower()]
        out[int(c)] = {"label": " · ".join(k[:2]) if k else off, "official": off, "known": k}
    return out


def mix(con):
    mixes = con.execute("""select comm_num, community, accounts_rounded, no_nationality_pct, nationality, share_pct, rank
                           from lk_community_resident_mix order by comm_num, rank""").fetchall()
    bands = con.execute("select comm_num, nationality, band_min from lk_community_resident_bands where band_min > 0").fetchall()
    geo = {int(c): (lon, lat, ring) for c, lon, lat, ring in
           con.execute("select try_cast(comm_num as bigint), lon, lat, ring_json from dm_community").fetchall() if c is not None}
    comms = {}
    for c, name, acc, nonat, nat, share, rank in mixes:
        e = comms.setdefault(c, {"comm": c, "name": name, "accounts": acc, "noNationalityPct": nonat, "mix": [], "other": 0, "bands": {}})
        if rank == 99:
            e["other"] = share
        else:
            e["mix"].append([nat, share])
    for c, nat, b in bands:
        if c in comms:
            comms[c]["bands"][nat] = b
    # 15 Sep: regions, each with its countries (Kendall: "continents, then a further breakdown")
    for c, region, rpct, others, nat, npct in con.execute("""select comm_num, region, region_pct, others_pct, country, country_pct
                                                            from lk_community_resident_regions
                                                            order by comm_num, region_rank, country_rank""").fetchall():
        if c not in comms:
            continue
        regs = comms[c].setdefault("regions", [])
        if not regs or regs[-1]["name"] != region:
            regs.append({"name": region, "pct": rpct, "countries": [], "others": others})
        if nat:
            regs[-1]["countries"].append([nat, npct])
    names = community_names(con)
    reach = {}
    for e in comms.values():
        for nat in e["bands"]:
            reach[nat] = reach.get(nat, 0) + 1
        nm = names.get(int(e["comm"]), {})
        e["label"], e["official"], e["known"] = nm.get("label") or official_name(e["name"]), nm.get("official") or official_name(e["name"]), nm.get("known", [])
        g = geo.get(e["comm"])
        if g:
            e["lon"], e["lat"] = round(g[0], 5), round(g[1], 5)
            e["onMap"] = g[0] <= HATTA_LON
    outlines = {}
    for c, (lon, lat, ring) in geo.items():
        if lon > HATTA_LON or not ring:
            continue
        pts, out = json.loads(ring), []
        for x, y in pts:
            p = [round(x, 4), round(y, 4)]
            if not out or p != out[-1]:
                out.append(p)
        outlines[str(c)] = out
    doc = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "source": SOURCE,
           "audience": "Anyone Naj shares an app link with. Kendall's decision, 22 Sep 2026: the nationality "
                       "layer is part of the client conversation, not an internal-only view. It is safe to show because it is "
                       "aggregate and floored - community level, a community needs 500+ residential accounts to appear at all, "
                       "a nationality needs a 5% share, shares are banded and rounded, and no account counts leave the Worker. "
                       "Nobody can be identified from it. Never linked to a named home or listing.",
           "rules": {"minResidentialAccounts": 500, "minSharePct": 5, "shares": "whole percent, rounded", "accounts": "rounded to the nearest 100",
                     "filterBands": [5, 10, 20, 40], "regionCountryMinPct": 1, "regionMinAccounts": 20},
           "notes": ["Nationality of the DEWA account holder, not every resident; accounts current at the extract.",
                     "noNationalityPct: residential accounts in the community with no nationality recorded (excluded from the shares).",
                     "regions: each region's share of accounts with a nationality, with its countries at 1% or more; 'others' is the "
                     "rest of that region, unnamed. Nothing under 20 accounts is shown: smaller countries stay in 'others', and "
                     "smaller regions, or a remainder small enough to work out by subtraction, count in Rest of the world.",
                     "A second passport counts where it was issued (Saint Kitts and Nevis, Dominica, Grenada, Antigua under "
                     "Americas; Vanuatu under Oceania). Arab world = Arab League members, North Africa included. Rest of the "
                     "world = Israel and the register's non-country entries (United Nations, NATO and similar)."],
           "nationalities": [n for n, _ in sorted(reach.items(), key=lambda kv: (-kv[1], kv[0]))],
           "communities": sorted(comms.values(), key=lambda e: e["label"] or ""),
           "names": {str(c): {"label": v["label"], "official": v["official"]} for c, v in names.items() if str(c) in outlines},
           "outlines": outlines}
    os.makedirs(os.path.dirname(MIX_OUT), exist_ok=True)
    json.dump(doc, open(MIX_OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), default=float)   # DuckDB rounds to Decimal
    return len(comms), len(doc["nationalities"]), os.path.getsize(MIX_OUT)


PREVIEW_OUT = os.path.join(ROOT, "data", "internal", "dewa_views.html")


def preview(con):
    """A page that opens on this laptop while the app screens are built: the resident mix with its filter and map, and the
    building colours as a list. It holds the internal data, so it lives in data/internal and is never published."""
    mix_doc = json.load(open(MIX_OUT, encoding="utf-8"))
    twin_doc = json.load(open(TWIN_OUT, encoding="utf-8"))
    names = dict(con.execute("select duid, display_name from lk_building_dewa_activity where display_name is not null").fetchall())
    for k, v in twin_doc["buildings"].items():
        v["name"] = names.get(k)
    page = open(os.path.join(HERE, "dewa_views_template.html"), encoding="utf-8").read()
    data = json.dumps({"mix": mix_doc, "twin": twin_doc}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    open(PREVIEW_OUT, "w", encoding="utf-8").write(page.replace("__DATA__", data))
    return os.path.getsize(PREVIEW_OUT)


def main():
    con = lake.connect(read_only=True)
    n, size = twin(con)
    print("twin colours: %d buildings -> %s (%d KB)" % (n, os.path.relpath(TWIN_OUT, ROOT), size // 1024))
    c, g, size = mix(con)
    print("resident mix (internal): %d communities, %d nationalities in the filter -> %s (%d KB)" % (c, g, os.path.relpath(MIX_OUT, ROOT), size // 1024))
    size = preview(con)
    print("laptop page (internal): %s (%d KB)" % (os.path.relpath(PREVIEW_OUT, ROOT), size // 1024))


if __name__ == "__main__":
    main()

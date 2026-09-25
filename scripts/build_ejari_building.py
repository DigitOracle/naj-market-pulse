"""How many homes in this building have a tenancy running - the first thing the twin can say about occupancy.

  python scripts/build_ejari_building.py                # every district, writes data/board/tenancy_<slug>.json
  python scripts/build_ejari_building.py businessbay    # one
  python scripts/build_ejari_building.py --push         # and publish to KV tenancy_<slug>

Kendall, 25 Sep 2026, looking at The Palm Tower's sold block: "this does not tell me if there's any one bedroom two
bedrooms available." Nothing can, from the sales register - it records completed transactions. But Ejari records
TENANCIES, with start and end dates, so a building can at least say how many of its homes are let right now. That is
not availability and it is a great deal more than a turnover multiple.

WHAT IT PUBLISHES, per building, per type:

    "at least 312 of 430 homes have a tenancy running on 9 Sep 2026"

FIVE THINGS THAT WOULD MAKE THAT FIGURE A LIE, and each is handled rather than noted:

1. **AT LEAST, always.** Only ~15% of Ejari contract lines carry a project number, so most projects bind by NAME. A
   contract registered without the project name never reaches its tower. Princess Tower shows 153 live against 771
   registered units; that is a naming gap, not an empty building. Every figure is a floor, never a total, and the
   word "at least" is in the rendered string and not only in a footnote.

2. **A MULTI-BUILDING PROJECT HAS ONE NUMBER AND IT IS NOT ANY ONE BUILDING'S.** Ejari has no unit identity - no
   property id, no unit number, no Makani, no parcel - so "DAMAC TOWERS BY PARAMOUNT" carries a single count for
   every tower under that name. Dividing it would be invention. Where a project reaches more than one of our
   footprints the record is marked `scope: "project"` with the building count, so the page can say "across the four
   towers of this project" rather than attributing it to the one you are looking at.

3. **live_props IS NOT A HOME COUNT.** The cut carries live_contracts and live_props (no_of_prop summed). Measured
   across every named residential project: the ratio is 1.00 at the median AND at p90 - one contract, one home - but
   34 rows exceed 2.0 and the worst is LUNA RESIDENCE at 7,980 properties per contract, which is a bulk registration
   covering a whole scheme. So the count is live_contracts, and any project whose ratio exceeds 2 is flagged
   `bulk_registration` and publishes no figure at all. A hotel registering 27,359 rooms on one contract is not 27,359
   tenancies.

4. **MORE TENANCIES THAN UNITS MEANS THE UNIT COUNT IS WRONG, NOT THAT THE BUILDING IS OVER-LET.** 22 projects are in
   that state. Iris Bay has 1,644 live against 202 registered - an office tower with sub-let space. Those publish the
   tenancy count and NO percentage, because a percentage over 100 invites the reader to decide which number is broken.

5. **THE DATE IS PART OF THE NUMBER.** The export is 9 Sep. "Live today" would be a claim the data cannot support, so
   `as_at` travels with every record and the rendered sentence names the date.

AND THE CEILING, which no amount of joining changes: **not let is not for sale.** An owner-occupied home has no
Ejari contract and is not on the market. The honest reading is "N have a tenancy running; the rest are owner-occupied,
vacant or unregistered, and we cannot tell which" - which is the DDA session's sentence, kept verbatim in `read_as`.

THE BIND reuses nkey() from build_unit_mix.py - the same normaliser the rent join already uses, so a building that
gets its median rent from a project gets its tenancy count from the same project or from neither. A second spelling
of "which project is this" would drift from the first within a week.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_unit_mix import nkey  # noqa: E402  - the same project normaliser the rent join uses
from build_avail_index import env_token, push  # noqa: E402

BOARD = os.path.join(ROOT, "data", "board")
DLD = os.path.join(ROOT, "data", "dld")
BULK_MAX = 2.0          # live_props / live_contracts above this is a bulk registration, not a home count

# Ejari's label -> the type name our unit mix uses. Residential only: a shop is not a home and is counted apart.
HOME_TYPE = {
    "Flat / Studio": "Studio", "Studio / Studio": "Studio",
    "Flat / 1bed room+Hall": "1 bedroom", "Villa / 1bed room+Hall": "1 bedroom",
    "Flat / 2 bed rooms+hall": "2 bedroom", "Villa / 2 bed rooms+hall": "2 bedroom",
    "Flat / 3 bed rooms+hall": "3 bedroom", "Villa / 3 bed rooms+hall": "3 bedroom",
    "Flat / 4 bed rooms+hall": "4 bedroom", "Villa / 4 bed rooms+hall": "4 bedroom",
    "Flat / 5 bed rooms+hall": "5 bedroom", "Villa / 5 bed rooms+hall": "5 bedroom",
    "Villa / 6 bed rooms+hall": "6 bedroom",
}


def districts():
    return sorted(os.path.basename(p)[11:-5] for p in
                  __import__("glob").glob(os.path.join(DLD, "ejari_live_*.json")))


def load(slug):
    try:
        E = json.load(open(os.path.join(DLD, "ejari_live_%s.json" % slug), encoding="utf-8"))
        U = json.load(open(os.path.join(BOARD, "unitmix_%s.json" % slug), encoding="utf-8"))
    except Exception:
        return None, None
    return E, U


def project_key(b):
    """What project this building belongs to: the register's own name for it, else the building's name."""
    p = ((b.get("dld") or {}).get("project") or "").strip()
    return nkey(p) if p else nkey(b.get("name") or "")


def run(slug):
    E, U = load(slug)
    if not E or not U:
        return None
    by = U.get("buildings_by_id") or {}

    # index the cut by normalised project name, never binding the unnamed bucket
    proj = {}
    for pr in E.get("projects") or []:
        nm = pr.get("project") or ""
        if not nm or nm == "(no project name)":
            continue
        proj.setdefault(nkey(nm), []).append(pr)

    # how many of OUR footprints each project reaches - decided here, because only we hold the building side
    reach = collections.Counter()
    keyed = {}
    for i, b in by.items():
        k = project_key(b)
        if k and k in proj:
            reach[k] += 1
            keyed[i] = k

    # how much of this district's Ejari even CAN reach a building - the single number that says whether the
    # per-building figures below are worth showing at all
    live_all = live_named = 0
    for pr in E.get("projects") or []:
        n = sum(int(v.get("live_contracts") or 0) for v in (pr.get("by_type") or {}).values())
        live_all += n
        if (pr.get("project") or "") != "(no project name)":
            live_named += n

    out, flags = {}, collections.Counter()
    for i, k in keyed.items():
        b = by[i]
        rows = proj[k]
        homes, comm, bulk = collections.Counter(), 0, False
        for pr in rows:
            for label, v in (pr.get("by_type") or {}).items():
                lc = int(v.get("live_contracts") or 0)
                lp = float(v.get("live_props") or 0)
                if lc <= 0:
                    continue
                if lp / lc > BULK_MAX:
                    bulk = True          # one contract standing for a whole scheme is not a set of tenancies
                    continue
                t = HOME_TYPE.get(label)
                if t:
                    homes[t] += lc
                elif (v.get("usage") or "") != "Residential":
                    comm += lc
        live = sum(homes.values())
        if not live and not comm:
            continue

        # NO DENOMINATOR. Measured across the estate, only 42.3% of live contracts reach one of our buildings -
        # 40.5% are in the unnamed bucket and can never bind - and coverage runs from 99.7% (sobhaheartland) to 4%
        # (dubaiinvestmentparkfirst). Setting this count against the unit count would read as an empty tower in one
        # district and a full one next door, for reasons no reader can see. The count stands alone.
        rec = {
            "live": live, "by_type": dict(homes), "commercial_live": comm,
            "at_least": True,                       # a contract registered without the project name never arrives
            "as_at": E.get("as_at"),
            "scope": "project" if reach[k] > 1 else "building",
            "project": rows[0].get("project"),
            "buildings_in_project": reach[k],
        }
        if bulk:
            rec["bulk_registration"] = True
            flags["bulk registration present"] += 1
        if reach[k] > 1:
            flags["project covers several buildings"] += 1
        out[str(i)] = rec

    # a project-scope figure is attributed to every building it covers, so summing the records multiplies it.
    # Count each project once - the same fact as "never divide a shared number", from the other direction.
    _seen, bound = set(), 0
    for r in out.values():
        if r.get("scope") == "project":
            if r.get("project") in _seen:
                continue
            _seen.add(r.get("project"))
        bound += r["live"] + r.get("commercial_live", 0)
    doc = {
        "district": slug, "as_at": E.get("as_at"), "source": E.get("source"),
        "buildings": len(out),
        "coverage": {
            "live_contracts_in_district": live_all,
            "under_a_named_project": live_named,
            "reaching_one_of_our_buildings": bound,
            "share_named": round(live_named / live_all, 3) if live_all else None,
            "share_bound": round(bound / live_all, 3) if live_all else None,
            "read_as": "share_bound is how much of this district's live tenancy data reaches a building at all. "
                       "Estate-wide it is 0.42. Below about 0.5 a per-building count is so incomplete that showing "
                       "it beside a unit count would mislead, which is why no record here carries a denominator.",
        },
        "read_as": E.get("read_as"),
        "limits": ("AT LEAST, never a total: only ~15%% of Ejari lines carry a project number, so most bind by name "
                   "and a contract registered without it never reaches its building. A project covering several "
                   "buildings carries ONE figure - scope:'project' - and must never be divided. live_props is not "
                   "used: the count is distinct live contracts, and a project registering more than %.0f properties "
                   "per contract is flagged and publishes nothing. 'Live on %s' is not 'live today'. NO RECORD "
                   "CARRIES A DENOMINATOR: only 42%% of live contracts estate-wide reach a building, unevenly by "
                   "district, so this count must never be rendered as a share of a building's homes."
                   % (BULK_MAX, E.get("as_at"))),
        "counts": dict(flags),
        "buildings_by_id": out,
    }
    json.dump(doc, open(os.path.join(BOARD, "tenancy_%s.json" % slug), "w", encoding="utf-8"), ensure_ascii=False)
    return doc


def main(slugs, do_push):
    slugs = slugs or districts()
    tok = env_token("INGEST_TOKEN") if do_push else None
    tot = bp = 0
    for s in slugs:
        d = run(s)
        if not d:
            continue
        tot += d["buildings"]
        bp += d["counts"].get("project covers several buildings", 0)
        print("%-26s %5d buildings  %s" % (s, d["buildings"],
              "  ".join("%s %d" % (k, v) for k, v in sorted(d["counts"].items())) or "-"))
        if do_push:
            print("     tenancy_%s -> %s" % (s, push("tenancy_" + s, d, tok).get("ok")))
    print("\n%d buildings carry a tenancy figure; %d of them are a project-level number covering more than one" % (tot, bp))


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if not a.startswith("-")], "--push" in sys.argv)

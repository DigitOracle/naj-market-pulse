"""Bind harvested plan projects to the DLD register, so a plan finds its building by ID and never by name again.

Kendall, 22 Sep 2026. The plans section reaches 4% of buildings. Three sessions spent the day proving why, and the answer
is not the one any of us started with:

    reaches a plot on the map today   27 projects    346 plans   <- the id join lands these
    parcel exists, no plot drawn      37 projects    903 plans   <- needs a new footprint binding
    no register project at all       104 projects  2,845 plans   <- harvesting, or selling ahead of registration

This script owns the FIRST HOP of that chain: harvested project name -> DLD project_name_en -> property_id -> parcel_key.
Everything downstream (parcel_key -> plot -> footprint) belongs to other lanes and is deliberately not done here.

WHY NAME MATCHING AT ALL, when the lesson of the day was "use the id": because the harvest has no id. A developer's web
page gives us a title and a PDF, never a property_id. This is the one join in the chain that CANNOT be an id lookup, so it
is the one place worth doing carefully - and then never doing again, because the output is ids.

Three rules, in order of confidence, and every row records which one fired:

  exact       normalised strings equal.
  prefix      one name starts the other, both over 8 characters. "Binghatti Aquarise" / "Binghatti Aquarise Tower".
  contains    our name appears as whole words inside the register's. The register keeps the developer prefix that a
              marketing page strips: "Crest Grande" is registered as "Sobha Hartland Crest Grande".

`contains` is the loose one and it is guarded. Measured without a guard it matched Emaar's **Boulevard Heights** to
**Samana** Boulevard Heights - a different developer's building, 60 plans, silently wrong. So a containment match is
refused when the words the register adds name any developer other than this project's own. That one guard is the
difference between 1,604 plans (one of them wrong) and 1,544 plans (all of them right), and the 60 lost plans are the
correct price.

    python scripts/bind_plans.py            report, write nothing
    python scripts/bind_plans.py --write    write data/board/plans_bind.json
"""
import collections, datetime, glob, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOARD = os.path.join(ROOT, "data", "board")
OUT = os.path.join(BOARD, "plans_bind.json")
MIN_PREFIX, MIN_CONTAINS = 8, 10        # below these, a shared word is coincidence rather than identity

# ---- PAIRS MEASURED WRONG ON A LIVE PAGE (added 22 Sep 2026) ------------------------------------------------------
# Five name-shape guards were written for floor plans in one day - emirate, developer agreement, exact_only,
# one-word-after-normalising, conflicting phase numbers - and every one was the right idea and cost legitimate
# matches; one would have taken plans from 21 buildings, at least four of them correct. The reason is structural: a
# rule that fires while a page renders sees one building, has no memory, and has no way to be TOLD about a specific
# pair. These were each seen wrong on a real page. Being told once is enough, and a refusal here outranks any rule
# that later concludes otherwise - including a future rule nobody has written yet.
#
# (harvested plan project, register project) - compared on the normalised name, so case and punctuation do not matter.
KNOWN_WRONG = [
    ("Boulevard Heights", "SAMANA Boulevard Heights"),          # EMAAR's plans on SAMANA's tower
    ("ARLO at Dubai Creek Harbour", "Dubai Creek Tower"),
    ("ARLO at Dubai Creek Harbour", "The Dubai Creek Residences"),
    ("Golf Grand", "Golfville Block A"),                        # reached by PREFIX, and they are different buildings
    ("Golf Grand at Dubai Hills Estate", "Golfville Block A"),
    ("The Crest", "The Crestmark"),                             # prefix again: one name is not the start of the other
    ("310 Riverside Crescent", "The Crescent A"),
    ("310 Riverside Crescent", "The Crescent B"),
    ("310 Riverside Crescent", "The Crescent C"),
]
_WRONG = {(re.sub(r"[^a-z0-9]+", " ", a.lower()).strip(), re.sub(r"[^a-z0-9]+", " ", b.lower()).strip()) for a, b in KNOWN_WRONG}


def known_wrong(plan_name, register_name):
    n = lambda s: re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()
    return (n(plan_name), n(register_name)) in _WRONG

# Areas that are not in Dubai. The developers we harvest sell across the UAE and their sites do not partition by emirate,
# so 1,254 plans over 22 projects - Sobha Siniya Island above all, which is in Umm Al Quwain - arrived in a Dubai index
# and were being counted as a Dubai coverage gap. They are not a gap. **No Dubai Land Department register will ever hold
# them**, so no harvesting, no crosswalk and no parcel geometry can bind them, and leaving them in the denominator makes
# our own coverage look 17 points worse than it is while pointing effort at work that cannot succeed.
NOT_DUBAI = ("siniya", "umm al quwain", "abu dhabi", "ras al khaimah", "sharjah", "ajman", "fujairah")

# Which emirate an area string names. Order matters: the longer, more specific keys are tested first, and anything
# unrecognised stays Dubai, because every harvest we run is a Dubai harvest that occasionally catches something else.
EMIRATE = [("siniya", "Umm Al Quwain"), ("umm al quwain", "Umm Al Quwain"), ("abu dhabi", "Abu Dhabi"),
           ("ras al khaimah", "Ras Al Khaimah"), ("sharjah", "Sharjah"), ("ajman", "Ajman"), ("fujairah", "Fujairah")]


def emirate_of(area):
    """The emirate an area belongs to, defaulting to Dubai.

    This exists because a name alone cannot tell you. "Bayside" is a Sobha Siniya Island tower in Umm Al Quwain and also
    reads perfectly as a Dubai Marina building - and the building page, matching projects to buildings by name
    containment, served its 69 floor plans to a Dubai Marina building until the emirate was known. Delphine, Pristine and
    Aquamarine did the same on three more buildings. A buyer saw another building's layouts in another emirate,
    presented as that building's, which is worse than holding no plans at all because it looks like an answer.

    So the emirate is written onto the project as a FIELD, not left to be re-inferred from the area string by every
    consumer. The twin's page guard reads it in preference to its own regex.
    """
    a = (area or "").lower()
    for key, name in EMIRATE:
        if key in a:
            return name
    return "Dubai"


def stamp_index(path, R):
    """Write `emirate` and `exact_only` onto every project in the plans index. Returns (emirates, exact_only count).

    **`exact_only` is a warning to anyone matching this project's name by substring.** The building page matches a
    project to a building by two-way name containment, and a short or common name wins that comparison against
    buildings it has nothing to do with. Measured live, five Dubai buildings were being served another developer's
    plans that way - Emaar's Creek Horizon carrying Sobha's The Horizon, Emaar's Grande carrying Sobha's Creek Vistas
    Grande - and the emirate field cannot help, because both sides are in Dubai.

    A name earns the flag if either is true:
      * it is ONE token. "Waves", "Grande", "May", "JUNE", "Caya" are project names, and as substrings they match
        almost anything. Emaar really did register a project called May.
      * it appears inside more than one project in the citywide register. "Waves" sits inside six.

    The flag is advisory and deliberately says nothing about what to do instead - the display surface decides whether
    that means exact-only, developer-must-agree, or don't show plans at all.
    """
    idx = json.load(open(path, encoding="utf-8"))
    names = list(R)
    seen, strict = collections.Counter(), 0
    for d in idx["developers"]:
        for p in d.get("projects") or []:
            e = emirate_of(p.get("area"))
            p["emirate"] = e
            seen[e] += 1
            c = norm(p.get("name"))
            hits = sum(1 for n in names if " " + c + " " in " " + n + " ") if c else 0
            p["name_tokens"] = len(c.split())
            p["register_collisions"] = hits
            p["exact_only"] = bool(c) and (len(c.split()) == 1 or hits > 1)
            strict += 1 if p["exact_only"] else 0
    idx["emirates"] = dict(seen)
    idx["exact_only_projects"] = strict
    json.dump(idx, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return seen, strict

# Brands the register writes into a project name. A containment match may never cross one of these.
BRANDS = {"samana", "danube", "azizi", "damac", "nakheel", "meraas", "omniyat", "select", "tiger", "deyaar", "object1",
          "imtiaz", "ellington", "binghatti", "sobha", "emaar", "arada", "wasl", "dugasta", "reportage", "mag", "aldar"}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def register():
    """{normalised name: {props, parcels, slugs, units, unregistered}} for every project in Dubai.

    Prefers `project_index.json` - the citywide cut, 3,685 projects over 83 areas - and falls back to the per-district
    key_bridge files only if it is missing.

    **The per-district files are a trap and this is why the fallback is a fallback.** They exist for the 41 districts on
    the twin's rail; the register covers 219 areas. 112,468 properties (44%) sit in an area with no cut at all, so a
    project outside the rail is invisible to any matcher reading them - SOBHA ONE is registered in Ras Al Khor Industrial
    First and simply is not in those files at any spelling. An absent district and an absent project look identical to a
    name lookup, which is how that got mistaken for a string problem twice.

    A name is deliberately NOT collapsed across areas. Project names are not unique in Dubai: "Pinnacle" is Binghatti
    Pinnacle in Al Jadaf, Vitalia by Pinnacle on Palm Jumeirah and MARINA PINNACLE in Marsa Dubai. Keeping every area
    means an ambiguous bind is visible in the row rather than silently resolved to whichever one sorted first.
    """
    R = collections.defaultdict(lambda: {"props": set(), "parcels": set(), "slugs": set(), "units": 0,
                                         "no_property_row": False})
    idx = os.path.join(BOARD, "project_index.json")
    if os.path.exists(idx):
        doc = json.load(open(idx, encoding="utf-8"))
        for e in doc["index"]:
            # name_variants holds the exact register spellings; match on all of them, because the two registers disagree
            # on whitespace ("Binghatti Haven " in units, "Binghatti Haven" in buildings) and on hyphenation
            for nm in {e.get("name")} | set(e.get("name_variants") or []):
                n = norm(nm)
                if not n:
                    continue
                R[n]["props"] |= {str(x) for x in (e.get("property_ids") or [])}
                R[n]["parcels"] |= {str(x) for x in (e.get("parcel_keys") or [])}
                R[n]["slugs"] |= set(e.get("areas") or [])
                R[n]["units"] = max(R[n]["units"], e.get("units") or 0)
                # The units register names this project and the building register has issued no property row for it.
                # **That is all this flag says.** Whether it means selling ahead of registration or simply a register
                # lag is not something these two tables can settle, so nothing downstream should phrase it as intent.
                if not e.get("properties"):
                    R[n]["no_property_row"] = True
        return R
    for f in sorted(glob.glob(os.path.join(BOARD, "key_bridge_*.json"))):
        rows = json.load(open(f, encoding="utf-8")).get("buildings_list")
        if not rows:                       # the key_bridge_pairs_* files have another shape; skipped, not an error
            continue
        slug = os.path.basename(f)[len("key_bridge_"):-len(".json")]
        for r in rows:
            n = norm(r.get("project_name_en"))
            if not n:
                continue
            R[n]["props"].add(str(r["property_id"]))
            R[n]["slugs"].add(slug)
            if r.get("parcel_key"):
                R[n]["parcels"].add(str(r["parcel_key"]).strip())
    return R


def resolve(c, dev, R, keys):
    """The register name this project is, and the rule that found it - or None."""
    if not c:
        return None
    if c in R:
        return c, "exact"
    for k in keys:
        if min(len(k), len(c)) > MIN_PREFIX and (k.startswith(c) or c.startswith(k)):
            return k, "prefix"
    if len(c) > MIN_CONTAINS:
        for k in keys:
            if " " + c + " " not in " " + k + " ":
                continue
            # refuse when the register's extra words name a DIFFERENT developer - the Samana/Emaar trap
            extra = set((" " + k + " ").replace(" " + c + " ", " ").split())
            if (extra & BRANDS) - {dev}:
                continue
            return k, "contains"
    return None


GENERIC = {"the", "by", "at", "in", "residences", "residence", "tower", "towers", "building", "dubai", "block"}


def buildings():
    """{parcel_key: [{district, i, name, bldgs}]} - the last hop, parcel to a specific footprint.

    plots.json carries `i` (the footprint index, which keys unitmix_<slug>.buildings_by_id), `pid` and `bldgs` as of
    v225, so a parcel now reaches one building rather than stopping at the plot.
    """
    p = os.path.join(BOARD, "plots.json")
    if not os.path.exists(p):
        return {}
    doc = json.load(open(p, encoding="utf-8"))
    feats = doc["features"] if isinstance(doc, dict) and "features" in doc else doc
    U, out = {}, collections.defaultdict(list)
    for f in glob.glob(os.path.join(BOARD, "unitmix_*.json")):
        U[os.path.basename(f)[len("unitmix_"):-len(".json")]] = \
            json.load(open(f, encoding="utf-8")).get("buildings_by_id") or {}
    for f in feats:
        x = f.get("properties") or f
        if x.get("i") is None:
            continue
        rec = (U.get(x.get("district")) or {}).get(str(x["i"])) or {}
        row = {"district": x.get("district"), "i": x["i"], "pid": x.get("pid"),
               "name": rec.get("name"), "bldgs": x.get("bldgs")}
        v = str(x.get("parcel") or "")
        for k in {v, v[:-3] if v.endswith(".00") else v}:
            if k:
                out[k].append(row)
    return out


def corroborates(project, building):
    """Does the building's own registered name agree with the project name?

    **This check exists because the id chain is not self-validating, which was a surprise.** parcel -> plot -> footprint
    index is all ids, no string comparison anywhere - and measured against 25 bound projects it still puts 5 of them on
    the wrong building: "The Serene" lands on Al Waha 17, "Binghatti Haven" on The Community-Sports Arena, "SAMANA
    Barari Heights" on Al Rabia Tower. The ids are faithful; the BINDING underneath them (reg_bindings/tx_bindings,
    which decides which footprint a register building sits on) is itself approximate, so going id-first inherits that
    layer's error instead of escaping it.

    So the name is not the weak alternative to the id here - it is the only independent check ON the id, and it is used
    that way: a bind is published when the ids agree AND the names do not contradict.
    """
    a, b = norm(project), norm(building)
    if not b:
        return None                                  # unnamed building: nothing to check against, not a contradiction
    return bool(a in b or b in a or (set(a.split()) & set(b.split()) - GENERIC))


def main():
    R = register()
    B = buildings()
    keys = list(R)
    idx = json.load(open(os.path.join(BOARD, "plans_index.json"), encoding="utf-8"))
    out, how, unbound = {}, collections.Counter(), collections.Counter()
    bound_plans = total_plans = total_proj = 0
    off_plans = off_proj = 0
    at_building = at_building_plans = bad_plans = 0
    elsewhere, contradicted = {}, {}
    for d in idx["developers"]:
        dev = norm(d.get("key"))
        for p in d.get("projects") or []:
            n = len(p.get("plans") or [])
            total_plans += n
            total_proj += 1
            em = emirate_of(p.get("area"))
            if em != "Dubai":                            # another emirate: out of scope, not a miss
                off_plans += n
                off_proj += 1
                elsewhere[p.get("name")] = {"developer": d.get("key"), "area": p.get("area"),
                                            "emirate": em, "plans": n}
                continue
            hit = resolve(norm(p.get("name")), dev, R, keys)
            if not hit:
                unbound[d.get("key")] += n
                continue
            k, rule = hit
            how[rule] += 1
            bound_plans += n
            out[p.get("name")] = {"developer": d.get("key"), "register_name": k, "rule": rule, "plans": n,
                                  "property_ids": sorted(R[k]["props"]), "parcel_keys": sorted(R[k]["parcels"]),
                                  "areas": sorted(R[k]["slugs"]), "units": R[k]["units"],
                                  # the units register names it and the building register has issued no property row.
                                  # Report it in those words. It is NOT evidence of selling ahead of registration:
                                  # an earlier index produced 238 of these and 223 were an artefact of joining the two
                                  # registers on an untrimmed name, which manufactured a phantom twin for every project
                                  # whose two spellings differed by a trailing space. The real count is 15 citywide.
                                  "no_property_row": R[k]["no_property_row"]}
            # the last hop: parcel -> plot feature -> footprint index, published only when the building's own name
            # does not contradict the project's. See corroborates() for why an all-id chain still needs that check.
            cands = [b for pk in R[k]["parcels"] for b in B.get(pk, [])]
            for b in cands:
                agree = corroborates(p.get("name"), b.get("name"))
                row = dict(b, corroborated=agree)
                if agree is False:
                    contradicted[p.get("name")] = row
                    bad_plans += n
                else:
                    out[p.get("name")]["building"] = row
                    at_building += 1
                    at_building_plans += n
                break
    dubai_plans = total_plans - off_plans
    print("harvested        %s plans over %d projects" % (f"{total_plans:,}", total_proj))
    print("not in Dubai     %s plans over %d projects   (Siniya Island, Abu Dhabi, UAQ - out of scope)"
          % (f"{off_plans:,}", off_proj))
    print("DUBAI            %s plans" % f"{dubai_plans:,}")
    print("  bound          %s  (%.0f%% of Dubai)   %d projects" % (f"{bound_plans:,}",
                                                                    100.0 * bound_plans / max(1, dubai_plans), len(out)))
    print("  unbound        %s" % f"{dubai_plans - bound_plans:,}")
    print("  at a building  %s  (%d projects, by id via plots.json)" % (f"{at_building_plans:,}", at_building))
    print("  REFUSED        %s  (%d projects: the ids agree, the building's own name does not)"
          % (f"{bad_plans:,}", len(contradicted)))
    print("by rule:", ", ".join("%s %d" % x for x in how.most_common()))
    print("unbound plans by developer:", ", ".join("%s %s" % (k, f"{v:,}") for k, v in unbound.most_common(6)))
    for nm, b in sorted(contradicted.items(), key=lambda x: x[0]):
        print("   refused: %-24s -> %s #%s \"%s\"" % (nm[:23], b["district"], b["i"], (b.get("name") or "")[:30]))
    # A refusal that was MEASURED on a live page outranks every rule above, and is written into the file as a row
    # rather than left as an absence - so a reader downstream can tell "never considered" from "considered, and no".
    refused_by_hand = {}
    for _nm in [k for k in out if known_wrong(k, (out[k] or {}).get("register_name"))]:
        refused_by_hand[_nm] = {"register_name": out[_nm].get("register_name"), "rule": out[_nm].get("rule"),
                                "plans": out[_nm].get("plans"), "developer": out[_nm].get("developer"),
                                "why": "seen wrong on a live page: these are different buildings"}
        bound_plans -= int(out[_nm].get("plans") or 0)
        how[out[_nm].get("rule")] -= 1
        del out[_nm]
    if refused_by_hand:
        print("  REFUSED BY HAND %d project(s) measured wrong on a live page:" % len(refused_by_hand))
        for _nm, _r in sorted(refused_by_hand.items()):
            print("     %-34s -> %-34s (%s, %s plans)" % (_nm[:34], str(_r["register_name"])[:34], _r["rule"], _r["plans"]))

    if "--write" in sys.argv:
        doc = {"generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
               "refused_by_hand": refused_by_hand,
               "bound": len(out), "bound_plans": bound_plans, "total_plans": total_plans,
               "dubai_plans": dubai_plans, "not_in_dubai_plans": off_plans, "not_in_dubai": elsewhere,
               "at_building": at_building, "at_building_plans": at_building_plans,
               "refused_contradicted": contradicted,
               "coverage_pct_of_dubai": round(100.0 * bound_plans / max(1, dubai_plans), 1), "by_rule": dict(how),
               "note": "Harvested plan project -> DLD register, by name, ONCE, so everything downstream can use ids. "
                       "`rule` says how much to trust the row: exact > prefix > contains, and a `contains` row never "
                       "crosses a developer brand. Many property_ids is normal for a villa community (Sobha Sanctuary: "
                       "375 plots, one property each) - that is the project, not an ambiguity. See scripts/bind_plans.py.",
               "projects": out}
        json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\nwrote %s" % os.path.relpath(OUT, ROOT))
        seen, strict = stamp_index(os.path.join(BOARD, "plans_index.json"), R)
        print("stamped plans_index.json: %s"
              % ", ".join("%s %d" % (k, v) for k, v in seen.most_common()))
        print("  exact_only (name too generic to match by substring): %d projects" % strict)


if __name__ == "__main__":
    main()

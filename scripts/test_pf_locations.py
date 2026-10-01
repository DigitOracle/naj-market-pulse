"""pf_listings.py location bindings (villa / townhouse clusters) and the one-owner rule - pure functions, no network, no lake.

Each case is one that went wrong or could go wrong on DAMAC Hills, 1 Oct 2026. The negative controls show the checks can fail:
the first spelling rule collapsed doubled letters across the whole joined name, so 'Golf Vita A' ('golfvitaa') became 'Golf
Vita' and three locations claimed one register entry.

  python scripts/test_pf_locations.py
"""
import os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pf_listings as P  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


CW = ("damac", "hills")
COMM = P.norm_name("Damac Hills")


def reg_of(entries):
    reg = {}
    for name, key, src in entries:
        reg.setdefault(P.strip_community(P.norm_name(name), COMM), []).append({"name": name, "key": key, "num": None, "src": src})
    return reg


REG = reg_of([("DAMAC HILLS - CARSON", "damachills:1003", "beds_left"),
              ("DAMAC HILLS - PICCADILLY GREEN", "dld:damachillspiccadillygreen", "beds_left"),
              ("DAMAC HILLS - GOLF VITA", "damachills:8", "beds_left"),
              ("DAMAC Hills - Golf Vita", "damachills:8", "verified_anchor"),
              ("DAMAC HILLS - BROOKFIELD-1", "dld:damachillsbrookfield1", "beds_left"),
              ("DAMAC HILLS - BROOKFIELD-2", "dld:damachillsbrookfield2", "beds_left"),
              ("DAMAC HILLS-VENETO", "dld:damachillsveneto", "beds_left"),
              ("DAMAC HILLS - THE FLORA", "dld:damachillstheflora", "beds_left"),
              ("DAMAC HILLS - THE TRUMP ESTATES 2", "dld:damachillsthetrumpestates2", "beds_left")])

# ---- names
b, why = P.match_location("Carson", REG, COMM, CW)
check(b and b["key"] == "damachills:1003" and b["method"] == "pf_location_name", "Carson = DAMAC HILLS - CARSON (community name stripped)")
b, why = P.match_location("Veneto at Damac Hills", REG, COMM, CW)
check(b and b["key"] == "dld:damachillsveneto", "'Veneto at Damac Hills' = 'DAMAC HILLS-VENETO' (community name at the back)")
b, why = P.match_location("Flora", REG, COMM, CW)
check(b and b["key"] == "dld:damachillstheflora", "'Flora' = 'THE FLORA' ('the' is generic)")
b, why = P.match_location("Picadilly Green", REG, COMM, CW)
check(b and b["method"] == "pf_location_spelling" and b["confidence"] < 0.9, "'Picadilly' / 'PICCADILLY': bound as a spelling variant, lower confidence")
b, why = P.match_location("Golf Vita", REG, COMM, CW)
check(b and b["key"] == "damachills:8" and b["register_source"] == "beds_left", "Golf Vita: the DLD project wins over the anchor of the same key")
b, why = P.match_location("Golf Vita A", REG, COMM, CW)
check(b is None, "'Golf Vita A' is NOT 'Golf Vita' (a tower letter is not a doubled letter)")
b, why = P.match_location("Brookfield", REG, COMM, CW)
check(b is None and "BROOKFIELD-1" in why and "BROOKFIELD-2" in why, "'Brookfield' vs BROOKFIELD-1/-2: review, never a guess")
b, why = P.match_location("Trump Estates", REG, COMM, CW)
check(b is None and "TRUMP ESTATES 2" in why, "'Trump Estates' vs 'THE TRUMP ESTATES 2': review")
b, why = P.match_location("Akoya Park", REG, COMM, CW)
check(b is None and why == "no register name", "a name the register does not have: review, 'no register name'")
# negative control: the first rule (collapse across the joined name) would have bound Golf Vita A - the test above can fail
old_spelling = lambda s: re.sub(r"(.)\1+", r"\1", s)
check(old_spelling(P.strip_community(P.norm_name("Golf Vita A"), COMM)) == old_spelling("golfvita"),
      "NEGATIVE CONTROL: the old joined-name collapse does merge 'Golf Vita A' into 'Golf Vita'")

# ---- one owner per listing
def listing(*tails):
    tree = [{"type": "CITY", "slug": "dubai"}, {"type": "COMMUNITY", "slug": "damac-hills"}]
    tree += [{"type": "SUBCOMMUNITY", "slug": t} for t in tails]
    return {"location_tree": tree, "location": {"type": "SUBCOMMUNITY", "slug": tails[-1]}}

ss, ss3 = "damac-hills-silver-springs", "damac-hills-silver-springs-silver-springs-3"
p = listing(ss, ss3)
check(P.owned_elsewhere(p, ss, {ss, ss3}) == ss3, "a Silver Springs 3 advert on the Silver Springs page belongs to bound child Silver Springs 3")
check(P.owned_elsewhere(p, ss3, {ss, ss3}) is None, "... and is counted on the Silver Springs 3 page")
check(P.owned_elsewhere(p, ss, {ss}) is None, "child not bound: the parent keeps the advert")
check(P.owned_elsewhere(listing(ss), ss, {ss, ss3}) is None, "a parent-only advert stays with the parent")
tower = {"location_tree": [{"type": "COMMUNITY", "slug": "business-bay"}, {"type": "TOWER", "slug": "business-bay-the-opus"}],
         "location": {"type": "TOWER", "slug": "business-bay-the-opus"}}
check(P.owned_elsewhere(tower, "business-bay-the-opus", {"business-bay-the-opus", "business-bay-other"}) is None,
      "a tower advert (Business Bay / JVC shape) is never moved: the rule is a no-op there")
# negative control: with the child bound, dropping the rule would count the Silver Springs 3 advert twice
both = [t for t in (ss, ss3) if t in P.location_tails(p)]
check(len(both) == 2, "NEGATIVE CONTROL: the advert's tree names both bound locations, so without the rule it would be counted twice")

# ---- district keys
check(P.key_in_district("dld:damachillscarson", "damachills", ["dld:damachillscarson"]), "a dld: key of the district's beds_left belongs to it")
check(not P.key_in_district("dld:damachillscarson", "businessbay", ["dld:businessbayx"]), "... and not to another district")
check(P.key_in_district("businessbay:12", "businessbay", []), "a district-prefixed key belongs to its district")

# ---- coverage
P.register_projects = lambda d: ({"k1": "A", "k2": "B", "k3": "C", "k4": "D"}, "2026-09-30")
cov = P.coverage_block("nodistrict", [{"building_slug": "x", "key": "k1"}, {"building_slug": "y", "key": "k2"}, {"building_slug": "z", "key": "nodistrict:9"}],
                       [{"key": "k1"}], 10)
check(cov["register_total"] == 4 and cov["register_bound"] == 2 and cov["register_with_adverts"] == 1, "coverage: 2 of 4 bound, 1 with adverts")
check(cov["bound_locations_outside_register"] == 1 and cov["say"] == "covers 2 of 4 DLD projects", "coverage: an anchor-keyed tower is counted outside the register")
check(cov["unbound_register"] == ["C", "D"], "coverage: the unbound register names are listed")

print("\n%d failed" % len(FAILS))
sys.exit(1 if FAILS else 0)

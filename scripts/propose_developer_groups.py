"""Propose which DLD register entities belong to the same developer, for a HUMAN to accept or reject.

Kendall, reading a building card that said "DAMAC STAR PROPERTIES (L L C) - 12 projects": "they have
only delivered 12 projects?" No - DAMAC is 18 entities in the register and 146 projects between them.
Scoring one registered company and labelling it with a brand name is a true figure attached to a claim
it does not support.

There is NO WAY TO DO THIS AUTOMATICALLY AND HONESTLY, which is why this proposes rather than decides:

  * The register holds no parent-company id. master_developer_number looks exactly like one and is the
    master developer of the COMMUNITY - DAMAC Properties Co points at master 555, which resolves to
    EMAAR PROPERTIES. Grouping on it would file DAMAC's projects under Emaar.
  * developer_dna.json links only the fifteen board developers. DAMAC is not one of them.
  * So the only remaining signal is the NAME, and name clustering is the trap this codebase has been
    caught by repeatedly. "DAMAC" is a safe token; "DUBAI" is not - Dubai Hills Estate, Dubai
    Properties and Dubai South are different companies that share a city.

So: propose on the name, but never trust a token that could be a place or a common word, and put the
evidence next to every row so the decision is made by someone who can check it. Output goes to
data/identity/developer_group_proposals.csv in the same shape as developer_group_review.csv, and
nothing is written to developer_group_decisions.json - that file is filled by a person.

  python scripts/propose_developer_groups.py [--min N]
"""
import collections
import csv
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import duckdb  # noqa: E402

OUT = os.path.join(ROOT, "data", "identity", "developer_group_proposals.csv")
DNA = os.path.join(ROOT, "data", "dev_meta", "developer_dna.json")
DECISIONS = os.path.join(ROOT, "data", "identity", "developer_group_decisions.json")

# A token that could be a place, a legal form or a common word is NOT evidence of a shared owner. These
# are the ones that would quietly merge unrelated companies, so they are proposed only as "review".
UNSAFE = {
    "DUBAI", "AL", "EMIRATES", "EMIRATE", "UNITED", "ARABIAN", "ARABIA", "GULF", "MIDDLE", "EAST",
    "THE", "NEW", "FIRST", "SECOND", "THIRD", "GRAND", "ROYAL", "GOLDEN", "GREEN", "BLUE", "WHITE",
    "STAR", "SUN", "MOON", "CITY", "TOWN", "PALM", "MARINA", "CREEK", "HARBOUR", "BAY", "ISLAND",
    "REAL", "PROPERTY", "PROPERTIES", "DEVELOPMENT", "DEVELOPMENTS", "DEVELOPER", "DEVELOPERS",
    "INVESTMENT", "INVESTMENTS", "HOLDING", "HOLDINGS", "GROUP", "INTERNATIONAL", "GLOBAL", "PRIME",
    "ELITE", "LUXURY", "HOMES", "HOUSE", "LAND", "LANDS", "ESTATE", "ESTATES", "PROJECT", "PROJECTS",
    "ONE", "TWO", "SKY", "SEA", "OASIS", "PEARL", "DIAMOND", "CROWN", "IMPERIAL", "NATIONAL",
    "DISTRICT", "COMMUNITY", "VILLAGE", "HILLS", "PARK", "GARDEN", "GARDENS", "HEIGHTS", "VIEWS",
}


def place_words():
    """Every word appearing in a Dubai AREA name, read from the data rather than guessed at.

    The first run put JUMEIRAH in the SAFE bucket - twelve entities, a confident-looking 34 projects -
    and they are Jumeirah Golf Estates, Jumeirah Hills, Jumeirah Park, Jumeirah Village, Jumeirah
    Islands. Nakheel communities sharing a place name, not one developer. A hand-written blocklist would
    have missed it and the next one like it; the area names are already on disk and say so exactly.
    """
    words = set()
    try:
        con = duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)
        for (a,) in con.execute("select distinct AREA_EN from transactions where AREA_EN is not null").fetchall():
            for w in re.split(r"[^A-Za-z]+", a or ""):
                if len(w) > 2:
                    words.add(w.upper())
        con.close()
    except Exception as e:
        print("  (no area names available, so place-checking is off: %s)" % e)
    return words
LEGAL = re.compile(r"\b(l\.?l\.?c|f\.?z\.?[ce]|p\.?j\.?s\.?c|s\.?o\.?c|w\.?l\.?l|ltd|limited|co|company|br|branch|of)\b", re.I)


def token(name):
    """The leading brand word, or "" when it is one we must not trust on its own."""
    t = LEGAL.sub(" ", str(name or ""))
    t = re.sub(r"[^A-Za-z& ]", " ", t)
    words = [w.upper() for w in t.split() if len(w) > 1]
    return words[0] if words else ""


def main():
    minimum = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 2
    projs = sorted(__import__("glob").glob(os.path.join(ROOT, "data", "registers", "projects", "projects_*.csv")))
    devs = sorted(__import__("glob").glob(os.path.join(ROOT, "data", "registers", "developers", "developers_*.csv")))
    if not projs or not devs:
        print("FAIL: registers not on disk"); return 2
    con = duckdb.connect()
    rows = con.execute("""
        select cast(cast(d.developer_number as double) as bigint) dn,
               any_value(d.developer_name_en) nm,
               count(p.project_number) total,
               sum(case when p.project_status = 'FINISHED' then 1 else 0 end) finished
        from read_csv_auto(?) d
        left join read_csv_auto(?) p
          on cast(p.developer_number as bigint) = cast(cast(d.developer_number as double) as bigint)
        where d.developer_name_en is not null
        group by 1
    """, [devs[-1], projs[-1]]).fetchall()
    con.close()

    # entities already spoken for by the fifteen board developers: proposing them again would invite a
    # decision that contradicts one already made in developer_dna.json
    spoken = {}
    try:
        with open(DNA, encoding="utf-8") as f:
            for brand, rec in json.load(f)["developers"].items():
                for l in (rec.get("dld_entity_links") or []):
                    if l.get("developer_number") is not None:
                        spoken[int(l["developer_number"])] = brand
    except Exception:
        pass

    PLACES = place_words()
    by_token = collections.defaultdict(list)
    for dn, nm, total, finished in rows:
        tk = token(nm)
        if tk:
            by_token[tk].append((dn, nm, total or 0, finished or 0))

    proposals = []
    for tk, members in sorted(by_token.items(), key=lambda kv: -sum(m[2] for m in kv[1])):
        if len(members) < minimum:
            continue
        projects = sum(m[2] for m in members)
        if projects == 0:
            continue
        claimed = {spoken[m[0]] for m in members if m[0] in spoken}
        # NO SAFE/UNSAFE BUCKET. The first cut called a token distinctive or generic and was wrong in
        # BOTH directions: JUMEIRAH went to "safe" with twelve entities that are Nakheel communities
        # sharing a place name, and when the place check was added it demoted DAMAC, EMAAR and SOBHA -
        # brands big enough to have a community named AFTER them. Two opposite wrong answers from the
        # same attempt to automate a judgement is the tell. So every signal is reported as a FLAG on
        # the row and the ranking is by size alone; the one-second human call is the point of the file.
        flags = []
        if tk in PLACES:
            flags.append("token also appears in a Dubai area name (may be a place, or a community named after the brand)")
        if tk in UNSAFE:
            flags.append("generic word or legal form")
        if len(tk) <= 3:
            flags.append("very short token")
        if claimed:
            flags.append("already linked to " + ", ".join(sorted(claimed)) + " in developer_dna.json")
        why = "; ".join(flags) if flags else "no warning signals"
        for dn, nm, total, finished in sorted(members, key=lambda m: -m[2]):
            proposals.append({
                "group": tk, "developer_number": dn, "developer_name_en": nm,
                "method": "name token (proposal, not a decision)",
                "group_projects": projects, "group_entities": len(members),
                "evidence": "%d registered projects, %d finished. Group: %d projects across %d entities. %s"
                            % (total, finished, projects, len(members), why),
            })

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "group_projects", "group_entities", "developer_number",
                                          "developer_name_en", "method", "evidence"])
        w.writeheader()
        for r in sorted(proposals, key=lambda x: (-x["group_projects"], x["group"], -1)):
            w.writerow(r)

    try:
        with open(DECISIONS, encoding="utf-8") as f:
            n_dec = len(json.load(f).get("decisions") or [])
    except Exception:
        n_dec = 0
    groups = {}
    for r in proposals:
        groups.setdefault(r["group"], r)
    print("proposals -> %s" % OUT)
    print("  %d entities in %d candidate groups, ranked by combined projects" % (len(proposals), len(groups)))
    print("  decisions already recorded in developer_group_decisions.json: %d" % n_dec)
    print()
    print("  %-16s %3s %5s  %s" % ("group", "ent", "projs", "flags"))
    for r in sorted(groups.values(), key=lambda x: -x["group_projects"])[:14]:
        flag = r["evidence"].split(". ", 2)[-1]
        print("  %-16s %3d %5d  %s" % (r["group"], r["group_entities"], r["group_projects"], flag[:70]))
    print()
    print("  Every row carries its flags; none of them decides anything. Accepting DAMAC and rejecting")
    print("  JUMEIRAH is a one-second call for someone who knows Dubai and is not one this can make.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

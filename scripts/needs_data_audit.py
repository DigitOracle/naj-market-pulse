"""Which 'needs_data' questions are marked against a BELIEF about the data rather than a check of it?

Q002 sat at needs_data for nine days because the obvious source (the DED commerce registry) was the wrong one,
and the right one - the DHA facility register - was already behind 1,812 clinic pins. Nobody had looked at it
from that angle. Rings' point: if one question was wrong that way, others will be.

This does NOT decide anything. It matches each needs_data question's own keywords against every table and
column name on the lake and prints the candidates, so a person can check the few that look live instead of
re-reading forty-seven. A name match is a lead, not an answer - `dsc_housing_unit` looked like it answered Q094
and turned out to be four columns with no fee, no building and no location.
"""
import sys, os, io, json, re
from collections import defaultdict
R = r"C:\Dev\naj-market-pulse"
sys.path.insert(0, os.path.join(R, "scripts"))
import lake

STOP = set("""the a an and or of for is are was were do does did can could to in on at by with from what which who
whom whose how many much when where why any some this that these those it its near nearby around close closest
i we you they me my our your their there here be been being have has had will would should shall may might must
per each every all both few more most other another such no nor not only own same so than too very just also
building buildings property properties unit units place places get got make made take taken see seen know known
like about into over under again further then once here""".split())


def words(q):
    txt = " ".join([q.get("question", "")] + (q.get("keys") or []) + (q.get("aliases") or []))
    return {w for w in re.findall(r"[a-z]{4,}", txt.lower()) if w not in STOP}


con = lake.connect()
cols = defaultdict(set)
for t, c in con.execute("select table_name, column_name from duckdb_columns()").fetchall():
    cols[t].add(c.lower())
print("lake tables: %d" % len(cols))

b = json.load(io.open(os.path.join(R, "questions", "bank.json"), encoding="utf-8"))
nd = [q for q in b["questions"] if q.get("status") == "needs_data"]
print("needs_data questions: %d\n" % len(nd))

rows = []
for q in nd:
    ws = words(q)
    if not ws:
        continue
    hits = []
    for t, cs in cols.items():
        tn = t.lower()
        # A table name match is worth much more than a column name match: a column called "type" matches
        # everything and means nothing.
        score = sum(3 for w in ws if w in tn) + sum(1 for w in ws if any(w in c for c in cs))
        if score >= 3:
            hits.append((score, t))
    hits.sort(reverse=True)
    if hits:
        rows.append((hits[0][0], q, hits[:4]))

rows.sort(key=lambda r: -r[0])
print("%-6s %-58s %s" % ("score", "question", "candidate tables on the lake"))
print("-" * 150)
for score, q, hits in rows:
    print("%-6d %-58s %s" % (score, (q["id"] + " " + q["question"])[:58],
                             ", ".join("%s(%d)" % (t, s) for s, t in hits)))
print("\n%d of %d needs_data questions have a lake table whose NAME echoes their own keywords." % (len(rows), len(nd)))
print("That is a lead list, not a result. Each one still needs the Q094 test: does the table actually carry the")
print("column the question asks for, and does its key reach a building?")

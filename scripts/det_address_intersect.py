"""Intersect the DDA session's det_address parcel list against our own parcel universe.

The DDA session called the list 'idstr-normalised'. It is not, in OUR sense: the first number below is
not the intersection, it is how much of the list our own key function can speak to at all.

24 Sep 2026, keys.py changed twice and this was re-run after each. 469f2fb taught the canonical key to read
a DOT as the community-plot separator, and f4a65cf moved sub-parcel truncation out to parent_parcel_key
after the first version had folded it in. Canonical parses now 28,765 distinct keys against 28,711 before
either change, refusals 2,653 against 3,387: the 738 dot-separated strings ('0117.645') moved from refused
to parsed, and the 2 sub-parcel strings ('4238153.2', '27490.40') went back to refused, which is right -
a sub-parcel is a different parcel, not another spelling of its parent. Still refused, deliberately: spaces
round the separator ('106 - 230', 1,417 of them), slashes ('0214/550'), doubled hyphens ('0621--0') and
letter prefixes ('TP010103', 'C-001-005').

NOT ONE CONCLUSION MOVED ACROSS EITHER CHANGE, which is the point of re-running rather than assuming. 100%
of their parcels already ours and 0 new, 20,308 reaching a DLD property, 3,783 plots under exactly one
building, 429 placeable, 32 both. The numbers that move are parse counts; the numbers that matter are not
sensitive to them, because the parcels were already ours by a second route.

A count read from lk_parcel_keys before its next rebuild is one out: dm_address_parcel still shows 28,766
distinct keys and still carries the one key the folded rule merged.
"""
import sys, os, json, io, re
from collections import Counter
R = r"C:\Dev\naj-market-pulse"
sys.path.insert(0, os.path.join(R, "scripts"))
import lake
from keys import parcel_key

raw = json.load(io.open(os.path.join(R, "data", "board", "_det_address_parcels.json"), encoding="utf-8"))
print("their list, raw strings      %7d" % len(raw))

strict, failed = {}, []
for s in raw:
    k = parcel_key(s)
    if k is None:
        failed.append(s)
    else:
        strict.setdefault(k, s)
print("parse with keys.parcel_key   %7d distinct keys, from %d strings" % (len(strict), len(raw) - len(failed)))
print("refuse to parse              %7d strings" % len(failed))

# What SHAPE do the refusals take? Grouped, because a fix is per-shape, not per-string.
def shape(s):
    t = re.sub(r"\d", "9", s)
    t = re.sub(r"9+", "9", t)
    return t
print("\n  refusal shapes (top 12):")
for sh, n in Counter(shape(s) for s in failed).most_common(12):
    ex = next(s for s in failed if shape(s) == sh)
    print("    %-16s %6d   e.g. %r" % (sh, n, ex))

# A LOOSER parse, to measure what a widened normaliser would recover. Kept separate and never
# merged into keys.py here: widening the canonical key is a decision with consequences across
# every join in the lake, not a cleanup to slip into an intersection script.
def loose(s):
    t = str(s).strip().strip(") (")
    t = re.sub(r"\s+", "", t)
    t = t.replace(".", "-").replace("--", "-")
    m = re.match(r"^(\d{1,4})-(\d{1,5})$", t)
    if m and int(m.group(2)) < 10000:
        return int(m.group(1)) * 10000 + int(m.group(2))
    return parcel_key(t)

loose_keys = {}
for s in raw:
    k = loose(s)
    if k is not None:
        loose_keys.setdefault(k, s)
print("\nparse with a WIDENED rule    %7d distinct keys  (+%d over canonical)"
      % (len(loose_keys), len(loose_keys) - len(strict)))

con = lake.connect()
ours = {r[0] for r in con.execute("select distinct parcel_key from lk_parcel_keys where parcel_key is not null").fetchall()}
by_src = {}
for src, in con.execute("select distinct source from lk_parcel_keys").fetchall():
    by_src[src] = {r[0] for r in con.execute(
        "select distinct parcel_key from lk_parcel_keys where source=? and parcel_key is not null", [src]).fetchall()}
print("\nour lk_parcel_keys universe  %7d distinct keys" % len(ours))
for s in sorted(by_src, key=lambda k: -len(by_src[k])):
    print("    %-20s %7d" % (s, len(by_src[s])))

for label, ks in (("canonical", set(strict)), ("widened", set(loose_keys))):
    print("\n== INTERSECTION, %s parse (%d keys) ==" % (label, len(ks)))
    hit = ks & ours
    print("  in our universe at all      %7d  (%.1f%% of theirs)" % (len(hit), 100.0 * len(hit) / max(1, len(ks))))
    print("  NEW to us                   %7d" % len(ks - ours))
    for s in sorted(by_src, key=lambda k: -len(by_src[k])):
        n = len(ks & by_src[s])
        print("    already via %-18s %7d  (%.1f%% of theirs)" % (s, n, 100.0 * n / max(1, len(ks))))
    print("  PLACEABLE (source='plot')   %7d  (%.1f%% of theirs)"
          % (len(ks & by_src.get("plot", set())), 100.0 * len(ks & by_src.get("plot", set())) / max(1, len(ks))))

json.dump(sorted(loose_keys), io.open(os.path.join(
    r"C:\Users\kwils\AppData\Local\Temp\claude\C--Dev-naj-market-pulse\19068de3-2d8e-4b29-b274-9def17bceb44\scratchpad",
    "det_keys_widened.json"), "w"), indent=0)


# ---------------------------------------------------------------------------
# What a VIDEO can actually say. Two claims, two different ceilings, and the
# second one - the one that sells - is nearly empty.
#
#   "there is a pharmacy on this plot"  needs only a parcel key
#   "a pharmacy 200 m away"             needs a POSITION for the amenity's parcel
#
con.execute("create or replace temp table det_pk as select * from (values %s) t(pk)"
            % ",".join("(%d)" % k for k in sorted(loose_keys)))

print("\n-- DOES THE PARCEL REACH A BUILDING? --")
print(con.execute("""
 select 'reaches a DLD property (lk_d_parcel)' what, count(distinct d.pk) n
   from det_pk d join lk_d_parcel p on p.parcel_key = d.pk
  union all
 select 'reaches a DM building (building_parcel_dm)', count(distinct d.pk)
   from det_pk d join lk_parcel_keys k on k.parcel_key=d.pk and k.source='building_parcel_dm'
  union all
 select 'is one of our PLACEABLE plots', count(distinct d.pk)
   from det_pk d join lk_parcel_keys k on k.parcel_key=d.pk and k.source='plot'
""").fetchdf().to_string(index=False))

# Parcel grain, which is the whole argument. A plot with five buildings on it cannot carry a
# sentence with the word "tower" in it, however good the licence data is.
print("\n-- PARCEL GRAIN --")
print(con.execute("""
 select case when p.dm_buildings is null then '(unknown)'
             when p.dm_buildings = 1 then '1 building  - a claim can name it'
             when p.dm_buildings between 2 and 4 then '2-4 buildings - one of them'
             else '5+ buildings - plot-level only' end grain,
        count(distinct d.pk) plots
   from det_pk d join lk_d_parcel p on p.parcel_key=d.pk
  group by 1 order by 2 desc
""").fetchdf().to_string(index=False))

print("\n-- THE PLACEABLE ONES, BY AREA (the only rows a distance claim can use) --")
print(con.execute("""
 select coalesce(p.area_name_en,'(not in lk_d_parcel)') area, count(distinct d.pk) plots
   from det_pk d
   join lk_parcel_keys k on k.parcel_key=d.pk and k.source='plot'
   left join lk_d_parcel p on p.parcel_key=d.pk
  group by 1 order by 2 desc limit 20
""").fetchdf().to_string(index=False))

# BOTH at once is the number that decides whether a video sentence exists at all.
print("\n-- PLACEABLE *AND* SINGLE-BUILDING (supports both claims in one sentence) --")
print(con.execute("""
 select count(distinct d.pk) n
   from det_pk d
   join lk_parcel_keys k on k.parcel_key=d.pk and k.source='plot'
   join lk_d_parcel p on p.parcel_key=d.pk and p.dm_buildings = 1
""").fetchdf().to_string(index=False))

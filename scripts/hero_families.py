"""hero_families.py -- DigitAlchemy(R) / Digital Abbot
Merge the parallel reference research (data/ce/<slug>/research/*.json, one file per film cluster, written by the research
agents on 15 Sep) into ONE per-sub-community family table for scripts/hero_all.py:

  data/ce/<slug>/hero_families.json
    {"<sub-community>": {"type": apartment|townhouse|villa|clubhouse, "look": "akoya_hero"|"carson_podium"|...,
                         "storeys_total": <family default>, "podium_levels": <family default>, "storeys_vary": bool,
                         "under_construction": bool, "buildings": [<research entries>], "villa": {...}, "sources": [...], "notes"}}

Rules of the merge (all visible in the file so a wrong call can be argued with):
  - "mixed" with building entries -> apartment (the townhouses sit inside the blocks); "mixed" without -> villa
  - family storeys_total = median of the buildings' storeys_total; podium_levels = most common value, never 0
    (podium 0 = no separate parking podium, but the hero grammar still needs a ground level for the lobby -> 1)
  - storeys_vary = the buildings differ by more than 2 storeys (Artesia A-D 20-27): hero_all then trusts the register's
    per-footprint storeys for an unnamed footprint instead of the family median
  - under_construction = every building's completion year is after 2026 (Golf Greens, Golf Gate 2)
  - Carson keeps the carson_podium look (the footprint on record is the whole plot; see facade_refs.json)

    python scripts/hero_families.py damachills
"""
import glob, json, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")
SPECIAL_LOOK = {"Carson": "carson_podium"}


def key(name):
    n = re.sub(r"\(.*?\)", "", name).strip()
    n = re.sub(r"^\s*DAMAC\s*HILLS\s*-?\s*", "", n, flags=re.I).strip(" -")
    return " ".join(re.sub(r"-(\d)", r" \1", n).title().split())


def year(s):
    m = re.search(r"(20\d\d)", str(s or ""))
    return int(m.group(1)) if m else None


def main():
    slug = sys.argv[1]
    out = {}; files = sorted(glob.glob(os.path.join(CE, slug, "research", "*.json")))
    for fp in files:
        d = json.load(open(fp, encoding="utf-8"))
        for raw, e in d.get("sub_communities", {}).items():
            k = key(raw); blds = [b for b in (e.get("buildings") or []) if b]
            t = e.get("type") or "unknown"
            if t in ("mixed", "unknown"): t = "apartment" if any(b.get("storeys_total") for b in blds) else "villa"
            fam = {"type": t, "cluster": d.get("cluster") or "/".join(d.get("clusters", [])), "buildings": blds, "villa": e.get("villa") or {},
                   "notes": e.get("notes", ""), "research_file": os.path.basename(fp)}
            srcs = []
            for b in blds: srcs += b.get("sources", [])
            srcs += (e.get("villa") or {}).get("sources", [])
            fam["sources"] = list(dict.fromkeys(srcs))[:6]
            if t == "apartment":
                st = [int(b["storeys_total"]) for b in blds if b.get("storeys_total")]
                pods = [int(b["podium_levels"]) for b in blds if b.get("podium_levels") is not None]
                fam["storeys_total"] = int(statistics.median(st)) if st else None
                fam["podium_levels"] = max(1, statistics.mode(pods)) if pods else None
                fam["podium_note"] = "research says no separate parking podium (townhouse duplexes in the base); 1 ground level kept for the lobby" if pods and min(pods) == 0 else ""
                fam["storeys_vary"] = bool(st) and (max(st) - min(st) > 2)
                yrs = [year(b.get("completed")) for b in blds]; yrs = [y for y in yrs if y]
                fam["under_construction"] = bool(yrs) and min(yrs) > 2026
                fam["look"] = SPECIAL_LOOK.get(k, "akoya_hero")
            else:
                v = fam["villa"]; fam["storeys_total"] = int(v.get("storeys") or 2); fam["look"] = "villa"
                fam["terraced"] = bool(v.get("terraced")) or t == "townhouse"
            out[k] = fam
    json.dump(out, open(os.path.join(CE, slug, "hero_families.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{slug}: {len(out)} families from {len(files)} research files -> data/ce/{slug}/hero_families.json")
    for k, f in sorted(out.items()):
        print(f"  {k:22s} {f['type']:10s} storeys {f.get('storeys_total')!s:4s} podium {f.get('podium_levels')!s:4s} "
              f"{'VARY ' if f.get('storeys_vary') else ''}{'U/C ' if f.get('under_construction') else ''}{f['look']}  ({len(f['buildings'])} buildings researched)")


if __name__ == "__main__":
    main()

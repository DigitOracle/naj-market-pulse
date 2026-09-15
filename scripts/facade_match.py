"""facade_match.py -- DigitAlchemy(R) / Digital Abbot
Per-building facade overrides from photo references (Kendall, 14 Sep: "source pics from online for these buildings and match them").

Reads data/ce/<slug>/facade_refs.json (named buildings -> a look matched to photos, plus per-building extras), resolves each name
to footprint indices through the truth store (building.display_name / project_name / official_name, district = slug) unless the
entry lists "footprints" itself, and writes data/ce/<slug>/facade_match.json:
  {"<footprint index>": {"name", "look", "cga": {rule attr: value}, "unreal": {walls, slabs, vision}}}
scripts/ce_lod3_datasmith.py --attr-file applies the "cga" part per shape; da_apply_pbr.py applies the "unreal" part per building.

    python scripts/facade_match.py <slug>
"""
import json, os, sys
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")


def main():
    slug = sys.argv[1]
    refs = json.load(open(os.path.join(ROOT, "data", "ce", slug, "facade_refs.json"), encoding="utf-8"))
    con = duckdb.connect(DB, read_only=True)
    out = {}; report = []
    for name, entry in refs["buildings"].items():
        look = refs["looks"][entry["look"]]
        fps = entry.get("footprints")
        if fps is None:
            fps = [r[0] for r in con.execute(
                "select footprint_i from building where district = ? and (display_name ilike ? or project_name ilike ? or official_name ilike ?)",
                [slug] + [f"%{name}%"] * 3).fetchall() if r[0] is not None]
        cga = {**look.get("cga", {}), **entry.get("cga", {})}
        for fi in fps:
            out[str(int(fi))] = {"name": name, "look": entry["look"], "cga": cga, "unreal": look.get("unreal", {})}
        report.append(f"{name}: {len(fps)} footprint(s) {sorted(int(f) for f in fps)[:8]}")
    rules = refs.get("district_rules", [])
    if rules:
        feats = json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]
        for rule in rules:
            look = refs["looks"][rule["look"]]; n = 0
            for fi, f in enumerate(feats):
                try: h = float(f["properties"].get("bHeight") or 0)
                except (TypeError, ValueError): h = 0.0
                if str(fi) in out or not (rule.get("height_min_m", 0) <= h <= rule.get("height_max_m", 1e9)): continue
                out[str(fi)] = {"name": "", "look": rule["look"], "cga": dict(look.get("cga", {})), "unreal": look.get("unreal", {}), "by": "district rule"}; n += 1
            report.append(f"district rule {rule['look']} {rule.get('height_min_m')}-{rule.get('height_max_m')} m: {n} more footprint(s)")
    json.dump(out, open(os.path.join(ROOT, "data", "ce", slug, "facade_match.json"), "w", encoding="utf-8"), indent=1)
    print(f"{slug}: {len(out)} footprints matched to {len(refs['buildings'])} named buildings")
    for line in report: print("  " + line)


if __name__ == "__main__":
    main()

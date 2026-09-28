"""Check every district's v5 local-frame build against what it is meant to reproduce, and list what to rebuild.

A v5 build is right when all three hold:
  1. buildings in the GLB == features in the geojson
  2. it was built with the district's LIVE configuration (scripts/district_lod_config.json) - a two-tier
     district rebuilt at uniform LOD 3 has the right building count and is the wrong product
  3. its triangles match the live CityEngine build (glb_v4_verify.json) within 1%, where that build is
     current - the check that actually caught (2) on 28 Sep

Where the live build predates the district's current inputs (Ellington appends, reviewed heights), (3) can
differ legitimately; those are reported as STALE-REF, not as failures, with the reason.

  python scripts/verify_v5.py                 table, then the rebuild list
  python scripts/verify_v5.py --list          the rebuild list only, one slug per line (for the runner)
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")


def main():
    cfg = json.load(open(os.path.join(HERE, "district_lod_config.json"), encoding="utf-8"))["districts"]
    slugs = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(CE, "*", "buildings.geojson")))
    rows, rebuild = [], []
    for s in slugs:
        gj = os.path.join(CE, s, "buildings.geojson")
        g = len(json.load(open(gj, encoding="utf-8"))["features"])
        want = cfg.get(s, {})
        want_lod, want_th = want.get("lod", 3), want.get("tall_h")
        op = os.path.join(CE, s, "origin_v5.json")
        glb = os.path.join(CE, "_glb", "sky_%s_v5_0.glb" % s)
        if not (os.path.exists(op) and os.path.exists(glb)):
            rows.append((s, "MISSING", "no v5 build")); rebuild.append(s); continue
        o = json.load(open(op, encoding="utf-8"))
        # a v5 build older than its own geojson is out of date regardless of how it compares
        if os.path.getmtime(glb) < os.path.getmtime(gj):
            rows.append((s, "OUTDATED", "v5 GLB is older than buildings.geojson")); rebuild.append(s); continue
        if o["buildings"] != g:
            rows.append((s, "COUNT", "%d of %d buildings" % (o["buildings"], g))); rebuild.append(s); continue
        got_th = o.get("tall_h")
        if o.get("lod") != want_lod or (got_th is None) != (want_th is None) or \
                (want_th is not None and abs(float(got_th) - float(want_th)) > 1e-6):
            rows.append((s, "CONFIG", "built LOD %s tall %s, live is LOD %s tall %s" % (o.get("lod"), got_th, want_lod, want_th)))
            rebuild.append(s); continue
        vp = os.path.join(CE, s, "glb_v4_verify.json")
        live = os.path.join(CE, "_glb", "sky_%s_v4_0.glb" % s)
        if not os.path.exists(vp):
            rows.append((s, "OK", "no live build to compare")); continue
        ce_tris = json.load(open(vp, encoding="utf-8")).get("triangles") or 0
        r = o["triangles"] / float(ce_tris) if ce_tris else 0.0
        if abs(r - 1) <= 0.01:
            rows.append((s, "OK", "tris %d vs live %d, %.4f" % (o["triangles"], ce_tris, r)))
        elif os.path.exists(live) and os.path.getmtime(live) < os.path.getmtime(gj):
            rows.append((s, "STALE-REF", "tris %.4f of live, but the live build predates this geojson" % r))
        else:
            rows.append((s, "DIFFERS", "tris %d vs live %d, %.4f - live build is current, so this is real" % (o["triangles"], ce_tris, r)))
            rebuild.append(s)
    if "--list" in sys.argv:
        print("\n".join(rebuild)); return 0
    for s, st, why in rows:
        print("  %-26s %-9s %s" % (s, st, why))
    c = {}
    for _, st, _ in rows:
        c[st] = c.get(st, 0) + 1
    print("\n  %s" % "  ".join("%s %d" % kv for kv in sorted(c.items())))
    print("  rebuild (%d): %s" % (len(rebuild), " ".join(rebuild) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

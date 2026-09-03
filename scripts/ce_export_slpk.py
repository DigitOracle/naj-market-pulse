"""Export district scenes from CityEngine to Scene Layer Packages (SLPK).

Lane: CE scene -> SLPK -> hosted scene layer on ArcGIS Online -> Maps SDK for
JavaScript SceneView with native callout labels (see agol_publish_scene.py and
data/board/preview/sceneview.html).  data/board/SCENELAYER_LANE.md is the guide.

CE 2025.1 must be running with the external Python bridge (gateway 127.0.0.1:25333).
Run with the Python that has the `cityengine` module (system `python`, 3.12).

Usage:  python scripts/ce_export_slpk.py [slug ...]      # default dubaimarina
        python scripts/ce_export_slpk.py --all           # the six v3 districts
Output: data/ce/_slpk/<slug>.slpk  (+ CE export log next to it)
        data/ce/_slpk/_export_summary.json  (sizes / shape counts, feeds the manifest)

What it does
  1. takes the CE lock ONCE for the whole batch (data/ce/.ce_lock; polls 20 s, waits
     up to 30 min) and releases it when done - it never calls gateway.shutdown(),
     so the CityEngine session other agents share stays up
  2. opens each /najma/scenes/<slug>.cej in turn
  3. picks the buildings shape layer, ranks shapes by OID (getObjectsFrom() is NOT
     import order, but shape OIDs are time-ordered UUIDs assigned at import, so OID
     rank recovers SHP feature order - verified 3 Sep 2026)
  4. NAMES ARE LEFT ALONE when they already carry a footprint index.  ce_batch (v3)
     names shapes "b<i>_<facadeclass>_s<status>"; that name travels into the SLPK's
     `name` field, so the viewer joins on it and gets the status for free.  Renaming
     to a bare "b<i>" here would clobber the facade agent's scene, so we only rename
     (and only then save the scene) when the names do NOT parse to an index.
  5. exports with SPKMeshExportModelSettings: Global scene, one feature per shape,
     object attributes (bHeight/status/levels from the SHP) carried through

Join key contract for the viewer: footprint index i = the digits of the leading
"b<i>" token of the shape name.  In the SLPK, OID-1 == that same index whenever the
export order is OID order (which it is, since we hand ce.export the OID-ranked list).
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
OUT = os.path.join(CEDIR, "_slpk")
LOCK = os.path.join(CEDIR, ".ce_lock")
LOCK_OWNER = "ce_export_slpk.py (scene layer lane)"

# the districts with a v3 textured massing
ALL_SLUGS = ["businessbay", "dubaimarina", "burjkhalifa", "palmjumeirah",
             "jumeirahvillagecircle", "palmdeira"]

args = [a for a in sys.argv[1:] if not a.startswith("-")]
SLUGS = ALL_SLUGS if "--all" in sys.argv else (args or ["dubaimarina"])
NAME_RE = re.compile(r"^b(\d+)(?:_|$)")


def scene_path(slug):
    return "/najma/scenes/%s.cej" % slug


def acquire_lock(timeout_s=30 * 60, poll_s=20):
    waited = 0
    while os.path.exists(LOCK):
        try:
            holder = open(LOCK, encoding="utf-8", errors="replace").read().strip()
        except OSError:
            holder = "?"
        if waited >= timeout_s:
            sys.exit("CE lock still held by [%s] after %ds - giving up" % (holder, timeout_s))
        print("CE lock held by [%s] - waiting %ds (%ds so far)" % (holder, poll_s, waited), flush=True)
        time.sleep(poll_s)
        waited += poll_s
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write("%s pid=%d %s\n" % (LOCK_OWNER, os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S")))
    print("CE lock acquired:", LOCK_OWNER, flush=True)


def release_lock():
    try:
        if os.path.exists(LOCK):
            owner = open(LOCK, encoding="utf-8", errors="replace").read()
            if LOCK_OWNER in owner:
                os.remove(LOCK)
                print("CE lock released")
    except OSError as e:
        print("lock release:", e)


def rank_by_oid(ce, shapes):
    try:
        return sorted(shapes, key=lambda s: str(ce.getOID(s)))
    except Exception as e:
        print("  getOID failed (%s) - keeping getObjectsFrom order" % str(e)[:60])
        return list(shapes)


def get_names(ce, shapes):
    try:
        n = ce.getName(shapes)
        if isinstance(n, (list, tuple)) and len(n) == len(shapes):
            return [str(x) for x in n]
    except Exception:
        pass
    return [str(ce.getName(s)) for s in shapes]


def pick_layer(ce, nfeat):
    """Same choice the massing batch makes: the shape layer whose count matches the
    footprints, else one named *building*, else the biggest."""
    cands = []
    for L in ce.getObjectsFrom(ce.scene, ce.isShapeLayer):
        shp = ce.getObjectsFrom(L, ce.isShape)
        cands.append((str(ce.getName(L)), shp))
        print("  layer '%s': %d shapes" % (cands[-1][0], len(shp)))
    pick = ([c for c in cands if len(c[1]) == nfeat]
            or [c for c in cands if "building" in c[0].lower()]
            or sorted(cands, key=lambda c: -len(c[1])))
    return pick[0] if pick and pick[0][1] else (None, [])


def export_one(ce, SPKMeshExportModelSettings, slug):
    scene = scene_path(slug)
    gj = os.path.join(CEDIR, slug, "buildings.geojson")
    if not os.path.exists(gj):
        print("  %s: no buildings.geojson - skipped" % slug)
        return {"slug": slug, "skipped": "no buildings.geojson"}
    feats = json.load(open(gj, encoding="utf-8"))["features"]

    print("=== %s: %d footprints, scene %s" % (slug, len(feats), scene), flush=True)
    try:
        ce.openFile(scene)
    except Exception as e:
        print("  %s: cannot open scene (%s) - skipped" % (slug, str(e)[:100]))
        return {"slug": slug, "skipped": "scene will not open"}
    try:
        ce.waitForUIIdle()
    except Exception:
        time.sleep(2)

    layer_name, shapes = pick_layer(ce, len(feats))
    if not shapes:
        print("  %s: no shapes in scene - skipped" % slug)
        return {"slug": slug, "skipped": "no shapes"}
    ranked = rank_by_oid(ce, shapes)
    n = len(ranked)
    print("  using layer '%s' (%d shapes) vs %d features" % (layer_name, n, len(feats)), flush=True)

    # --- naming: keep what the massing batch put there ---------------------------
    t0 = time.time()
    names = get_names(ce, ranked)
    parsed = [NAME_RE.match(nm) for nm in names]
    good = sum(1 for m in parsed if m)
    idx = [int(m.group(1)) for m in parsed if m]
    conforming = good == n and len(set(idx)) == n
    renamed = False
    if conforming:
        print("  names already index-bearing (%d/%d parse to b<i>, e.g. %r) "
              "- left untouched, scene NOT saved" % (good, n, names[0]), flush=True)
        key_index = idx
    else:
        # only now do we touch the scene; prefer the batch's verified shape->feature map
        smap = os.path.join(CEDIR, slug, "shape_map_v3.json")
        mapping = list(range(n))
        if os.path.exists(smap):
            try:
                m = json.load(open(smap, encoding="utf-8")).get("shape_to_feature")
                if isinstance(m, list) and len(m) == n:
                    mapping = m
                    print("  using shape_map_v3.json for the shape -> footprint mapping")
            except Exception as e:
                print("  shape_map_v3.json unreadable:", str(e)[:80])
        print("  names do not carry an index (%d/%d) - renaming to b<i>" % (good, n), flush=True)
        for s, fi in zip(ranked, mapping):
            ce.setName(s, "b%d" % fi)
        key_index = mapping
        renamed = True
    print("  names settled in %.1fs" % (time.time() - t0), flush=True)

    # rule wiring - normally already set by the massing batch; keep it idempotent
    try:
        rf = ce.getRuleFile(ranked[0])
    except Exception:
        rf = None
    if not rf:
        ce.setRuleFile(ranked, "/najma/rules/najma.cga")
        ce.setStartRule(ranked, "Lot")
        print("  rule file assigned")
    for attr in ("bHeight", "status", "levels"):
        try:
            ce.setAttributeSource(ranked, "/ce/rule/" + attr, "OBJECT")
        except Exception:
            pass

    # --- export ------------------------------------------------------------------
    slpk = os.path.join(OUT, slug + ".slpk")
    for fn in os.listdir(OUT):  # CE names the package <base>_<layerIdx>_<layerName>.slpk
        if fn.startswith(slug) and fn.endswith(".slpk"):
            os.remove(os.path.join(OUT, fn))

    st = SPKMeshExportModelSettings()
    st.setOutputPath(OUT)
    st.setBaseName(slug)
    st.setSceneType(SPKMeshExportModelSettings.GLOBAL)            # required for ArcGIS Online web scenes
    st.setFeatureGranularity(SPKMeshExportModelSettings.FEATURE_PER_SHAPE)
    st.setExportGeometry(SPKMeshExportModelSettings.MODEL_GEOMETRY_FALLBACK)
    st.setFileSize(SPKMeshExportModelSettings.MIDSIZE_FILE)
    st.setEmitReports(True)
    st.setIgnoreLayers(False)
    st.setExistingFiles(SPKMeshExportModelSettings.OVERWRITE)
    st.setWriteLog(True)
    print("  exporting SLPK ->", slpk, flush=True)
    t0 = time.time()
    ce.export(ranked, st)
    written = None
    for _ in range(180):
        cands = [fn for fn in os.listdir(OUT) if fn.startswith(slug) and fn.endswith(".slpk")]
        if cands:
            p = os.path.join(OUT, cands[0])
            sz = os.path.getsize(p)
            time.sleep(2)
            if sz > 0 and os.path.getsize(p) == sz:
                written = p
                break
        time.sleep(1)
    took = time.time() - t0

    if renamed:
        try:
            ce.saveFile(scene)
            print("  scene saved (names were rewritten)")
        except Exception as e:
            print("  saveFile:", str(e)[:80])

    if not written:
        print("  %s: export finished but no .slpk written - check the export log in %s" % (slug, OUT))
        return {"slug": slug, "skipped": "no slpk written"}
    if written != slpk:
        os.replace(written, slpk)
    mb = os.path.getsize(slpk) / 1e6
    print("  SLPK: %s %.1f MB, %d shapes, %.0fs" % (slpk, mb, n, took), flush=True)
    return {"slug": slug, "slpk": slpk, "bytes": os.path.getsize(slpk), "mb": round(mb, 3),
            "shapes": n, "footprints": len(feats), "layer": layer_name,
            "names_kept": conforming, "name_example": names[0] if names else None,
            "min_index": min(key_index) if key_index else None,
            "max_index": max(key_index) if key_index else None,
            "export_s": round(took, 1)}


def main():
    os.makedirs(OUT, exist_ok=True)
    from cityengine import CE, SPKMeshExportModelSettings  # noqa: E402  (needs the bridge)

    ce = CE()
    results = []
    for slug in SLUGS:
        try:
            results.append(export_one(ce, SPKMeshExportModelSettings, slug))
        except Exception as e:
            print("  %s: FAILED %s: %s" % (slug, type(e).__name__, str(e)[:200]))
            results.append({"slug": slug, "skipped": "%s: %s" % (type(e).__name__, str(e)[:200])})

    summary = os.path.join(OUT, "_export_summary.json")
    with open(summary, "w", encoding="utf-8") as f:
        json.dump({"exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results}, f, indent=2)
    print("\nsummary ->", summary)
    for r in results:
        if "slpk" in r:
            print("  %-24s %8.2f MB  %6d shapes  names %s"
                  % (r["slug"], r["mb"], r["shapes"], "kept" if r["names_kept"] else "rewritten"))
        else:
            print("  %-24s SKIPPED: %s" % (r["slug"], r.get("skipped")))
    print("\nnext: propy scripts/agol_publish_scene.py <slpk> --title \"Najma - <District> massing\"")


if __name__ == "__main__":
    acquire_lock()
    try:
        main()
    finally:
        release_lock()

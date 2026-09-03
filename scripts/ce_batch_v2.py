"""CityEngine batch v2 — per-building district massing with rules/najma_v2.cga.

For each slug: open /najma/scenes/<slug>.cej (already imported by ce_batch.py), map its shapes to the
buildings.geojson feature indices (order check by centroid, full nearest match if order drifted), name
shapes "b<i>_<class>", push facade class + variant as object attrs, assign najma_v2.cga, generate,
export glTF with per-building meshes (meshGranularity AS_GENERATED) to data/ce/_glb/sky_<slug>_v2_0.glb,
and collect the CGA reports through the export callback scripts/ce_report_v2.py into
data/ce/<slug>/report_v2.csv (+ report_v2.json). Verifies the GLB (mesh count vs shape count, size,
triangles, materials) into data/ce/<slug>/glb_v2_verify.json.

Size budget: --budget-mb (default 4). With --fit (default on) the batch walks the LOD ladder
  (LOD 2, bandEvery 1) -> (1, 1) -> (1, 2) -> (1, 3) -> (1, 5) -> (0, 1)
and keeps the first export under budget; every attempt's size is printed. --lod / --band-every pin one
tier (no ladder). The scene is saved only after a generation with zero failed shapes.

CityEngine lock protocol: data/ce/.ce_lock is created (with this agent's name) before the first bridge
call and removed at exit; if it exists we wait (20 s polls, up to 20 min). CE 2025.1 must be running
with the Python bridge on 25333. dubaimarina is the approved proof — refuse unless --allow-marina.

Usage:  python scripts/ce_batch_v2.py businessbay [burjkhalifa palmjumeirah] [--lod N] [--band-every N]
                                     [--budget-mb 4] [--no-fit] [--no-save] [--verify-only] [--palette]

--v3: textured lane. Uses rules/najma_v3.cga (ESRI.lib facade textures), names shapes "b<i>_<class>_s<status>" so the
viewer reads status from the name, writes sky_<slug>_v3_0.glb / report_v3.* / glb_v3_verify.json, single tier (LOD 1, no
LOD ladder - the texture carries the floors), budget default 40 MB for the RAW merged file (scripts/glb_pack_v3.mjs
does the WebP + meshopt compression afterwards), and the scene is NOT saved unless --save is given.
"""
import atexit, csv, datetime, json, math, os, shutil, struct, sys, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce"); GLB = os.path.join(CEDIR, "_glb"); RULES = os.path.join(ROOT, "rules")
LOCK = os.path.join(CEDIR, ".ce_lock"); LOCK_NAME = "ce_batch_v2 (cga facade agent) pid %d" % os.getpid()
SCRIPT_WS = "/najma/scripts/ce_report_v2.py"
LADDER = [(1, 1), (1, 2), (1, 3), (1, 5), (0, 1)]          # viewer ladder; --hero prepends the full LOD 2 facade tier
STATUS_HEX = {"existing": "#39434F", "construction": "#3E8A7E", "pipeline": "#C5A56A"}

args = sys.argv[1:]
def opt(name, default=None, cast=str):
    if name in args:
        i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return cast(v)
    return default
def flag(name):
    if name in args: args.remove(name); return True
    return False

VER = "v3" if flag("--v3") else "v2"                 # v3 = textured rule + status in the shape name
SAVE_V3 = flag("--save")
PIN_LOD = opt("--lod", None, int); PIN_BAND = opt("--band-every", None, int); BUDGET = opt("--budget-mb", 40.0 if VER == "v3" else 4.0, float)
FIT = not flag("--no-fit"); SAVE = not flag("--no-save"); VERIFY_ONLY = flag("--verify-only"); PALETTE = flag("--palette")
ALLOW_MARINA = flag("--allow-marina"); SNAP = not flag("--no-snapshot")
flag_nomerge = flag("--no-merge")                     # keep CE's raw one-mesh-per-leaf file (debug)
GRAN = opt("--granularity", "AS_GENERATED").upper()   # AS_GENERATED = one mesh per generated leaf | PER_MATERIAL = merged per material
if flag("--hero"): LADDER = [(2, 1)] + LADDER
SLUGS = [a for a in args if not a.startswith("--")] or ["businessbay"]
if PIN_LOD is not None or PIN_BAND is not None:
    FIT = False; LADDER = [(PIN_LOD if PIN_LOD is not None else 1, PIN_BAND if PIN_BAND is not None else 1)]
elif VER == "v3":
    FIT = False; LADDER = [(1, 1)]                     # textured: one tier, bands are in the texture
RULE_WS = f"/najma/rules/najma_{VER}.cga"; LOCK_NAME = f"ce_batch_{VER} (cga facade agent) pid {os.getpid()}"
if VER == "v3" and not SAVE_V3: SAVE = False
log_lines = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); log_lines.append(s)


# ------------------------------------------------------------------ colour check (offline)
def hx(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
def lin(c): return tuple(((v / 255 + 0.055) / 1.055) ** 2.4 if v / 255 > 0.04045 else v / 255 / 12.92 for v in c)
def nearest_status(rgb):
    out = {}
    for sp, f in (("srgb", lambda x: x), ("linear", lin)):
        ds = sorted((math.dist(f(rgb), f(hx(v))), k) for k, v in STATUS_HEX.items()); out[sp] = (ds[0][1], round(ds[0][0] / ds[1][0], 2))
    return out

def palette_check():
    """Every colour literal in najma_v2.cga must classify to its own status family with margin <= 0.8."""
    import re
    src = open(os.path.join(RULES, f"najma_{VER}.cga"), encoding="utf-8").read()
    bad = 0
    for m in re.finditer(r'col_\w+\(st\)\s*=\s*case st == "construction" : "(#[0-9A-Fa-f]{6})" case st == "pipeline" : "(#[0-9A-Fa-f]{6})" else : "(#[0-9A-Fa-f]{6})"', src):
        for fam, h in zip(("construction", "pipeline", "existing"), m.groups()):
            r = nearest_status(hx(h)); ok = all(k == fam and v <= 0.8 for k, v in r.values())
            bad += 0 if ok else 1
            log(f"  {h} -> {fam:12} srgb {r['srgb']}  linear {r['linear']}  {'ok' if ok else 'FAIL'}")
    log("palette:", "all colours classify to their own family" if not bad else f"{bad} FAIL")
    return bad == 0


# ------------------------------------------------------------------ GLB verification (offline)
def verify_glb(path, n_shapes=None, classes=None):
    b = open(path, "rb").read()
    ln = struct.unpack("<I", b[12:16])[0]; g = json.loads(b[20:20 + ln])
    tris = verts = prims = 0; names = []
    for m in g["meshes"]:
        names.append(m.get("name", ""))
        for p in m["primitives"]:
            prims += 1; n = g["accessors"][p["attributes"]["POSITION"]]["count"]; verts += n
            tris += g["accessors"][p["indices"]]["count"] // 3 if "indices" in p else n // 3
    mats = []
    for mt in g.get("materials", []):
        f = mt.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        srgb = tuple(int(round(255 * (c ** (1 / 2.2)))) for c in f[:3])  # CE writes gamma-2.2 linear factors
        mats.append({"name": mt.get("name"), "hex": "#%02X%02X%02X" % srgb, "alpha": round(f[3], 2), "family": nearest_status(srgb)["linear"][0]})
    fam = {}
    for mt in mats: fam[mt["family"]] = fam.get(mt["family"], 0) + 1
    cls = {}
    for nm in names:
        c = nm.split("_")[1] if "_" in nm else "(none)"; cls[c] = cls.get(c, 0) + 1
    roots = g["scenes"][0]["nodes"] if g.get("scenes") else []
    def meshes_under(i, acc):
        nd = g["nodes"][i]
        if "mesh" in nd: acc.append(nd["mesh"])
        for c in nd.get("children", []): meshes_under(c, acc)
        return acc
    per_root = [len(meshes_under(r, [])) for r in roots]
    root_names = []
    for r in roots:
        ms = meshes_under(r, []); root_names.append(g["nodes"][r].get("name") or (g["meshes"][ms[0]].get("name", "") if ms else ""))
    uniq_b = len({nm.split("_")[0] for nm in root_names if nm.startswith("b")})
    rep = {"file": os.path.relpath(path, ROOT), "bytes": len(b), "mb": round(len(b) / 1048576, 3), "meshes": len(g["meshes"]), "nodes": len(g.get("nodes", [])),
           "buildings": len(roots), "buildings_match_shapes": (len(roots) == n_shapes) if n_shapes else None, "unique_b_ids": uniq_b,
           "meshes_per_building": {"min": min(per_root) if per_root else 0, "max": max(per_root) if per_root else 0, "mean": round(sum(per_root) / max(len(per_root), 1), 1)},
           "primitives": prims, "triangles": tris, "vertices": verts, "materials": len(mats), "material_families": fam, "materials_detail": mats[:40],
           "mesh_named_b": sum(1 for nm in names if nm.startswith("b")), "classes_in_names": cls, "shapes": n_shapes,
           "meshes_match_shapes": (len(g["meshes"]) == n_shapes) if n_shapes else None, "bytes_per_tri": round(len(b) / max(tris, 1), 1),
           "textures": len(g.get("textures", [])), "images": len(g.get("images", [])),
           "image_mb": round(sum(g["bufferViews"][im["bufferView"]]["byteLength"] for im in g.get("images", []) if "bufferView" in im) / 1048576, 3),
           "textured_materials": sum(1 for mt in g.get("materials", []) if "baseColorTexture" in mt.get("pbrMetallicRoughness", {})),
           "status_in_names": {s: sum(1 for nm in names if nm.endswith("_s" + s)) for s in ("existing", "construction", "pipeline")}}
    return rep


# ------------------------------------------------------------------ lock
def acquire_lock(max_wait=20 * 60, poll=20):
    t0 = time.time()
    while os.path.exists(LOCK):
        holder = open(LOCK, encoding="utf-8", errors="replace").read().strip()
        if time.time() - t0 > max_wait:
            sys.exit(f"CE lock held by '{holder}' for > {max_wait // 60} min — giving up, nothing touched")
        log(f"  CE lock held by '{holder}' — waiting {poll}s ({int(time.time() - t0)}s so far)"); time.sleep(poll)
    open(LOCK, "w", encoding="utf-8").write(f"{LOCK_NAME} {datetime.datetime.now().isoformat(timespec='seconds')}\n")
    atexit.register(release_lock)
    log("  CE lock acquired:", LOCK_NAME)

def release_lock():
    try:
        if os.path.exists(LOCK) and LOCK_NAME in open(LOCK, encoding="utf-8", errors="replace").read():
            os.remove(LOCK); print("  CE lock released")
    except Exception as e:
        print("  lock release:", e)


# ------------------------------------------------------------------ helpers
def feature_centroids_utm(feats):
    import pyproj
    tr = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
    out = []
    for f in feats:
        g = f["geometry"]; ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
        xs, ys = zip(*[tr(x, y) for x, y in ring[:-1] or ring])
        out.append((sum(xs) / len(xs), -sum(ys) / len(ys)))  # scene frame: x = easting, z = -northing
    return out

def shape_centroid(ce, shape):
    v = ce.getVertices(shape); xs = v[0::3]; zs = v[2::3]
    return (sum(xs) / len(xs), sum(zs) / len(zs))

def rank_by_oid(ce, shapes):
    """getObjectsFrom() does not return import order, but shape OIDs are time-ordered UUIDs assigned at import,
    so ranking by OID recovers the SHP feature order (same trick as ce_export_slpk.py, verified 3 Sep 2026)."""
    try:
        return sorted(shapes, key=lambda s: str(ce.getOID(s)))
    except Exception as e:
        log("  getOID failed (%s) — keeping getObjectsFrom order" % str(e)[:60]); return list(shapes)

def map_shapes_to_features(ce, shapes, feats):
    """Returns list feature_index per shape. Checks import order on a sample; falls back to full nearest match."""
    fc = feature_centroids_utm(feats); n = len(shapes)
    sample = sorted(set([0, n // 4, n // 2, 3 * n // 4, n - 1] + list(range(0, n, max(1, n // 25)))))
    sc = {i: shape_centroid(ce, shapes[i]) for i in sample}
    off = (sum(sc[i][0] - fc[i][0] for i in sample) / len(sample), sum(sc[i][1] - fc[i][1] for i in sample) / len(sample)) if n == len(feats) else (0, 0)
    if n == len(feats):
        res = [math.hypot(sc[i][0] - off[0] - fc[i][0], sc[i][1] - off[1] - fc[i][1]) for i in sample]
        log(f"  order check: {len(sample)} samples, frame offset ({off[0]:.1f}, {off[1]:.1f}) m, residual max {max(res):.2f} m")
        if max(res) < 3.0:
            return list(range(n)), "identity"
    log("  order differs from feature order (or counts differ) — matching every shape by centroid")
    allc = [shape_centroid(ce, s) for s in shapes]
    off = (sum(c[0] for c in allc) / n - sum(c[0] for c in fc) / len(fc), sum(c[1] for c in allc) / n - sum(c[1] for c in fc) / len(fc))
    mapping = []
    for c in allc:
        x, z = c[0] - off[0], c[1] - off[1]
        j = min(range(len(fc)), key=lambda k: (fc[k][0] - x) ** 2 + (fc[k][1] - z) ** 2)
        mapping.append(j)
    dup = len(mapping) - len(set(mapping))
    log(f"  centroid match done, {dup} duplicate feature hits")
    return mapping, "centroid"

def export_log_status(log_path):
    """Parse CE's export .log: (ok, failed, total) over the 'Initial shapes:' block."""
    ok = failed = 0
    try:
        for line in open(log_path, encoding="utf-8", errors="replace"):
            s = line.strip()
            if not s or not s[0].isdigit(): continue
            parts = s.split()
            if len(parts) >= 3 and parts[1] == ":":
                if parts[2] == "OK": ok += 1
                else: failed += 1
    except Exception:
        pass
    return ok, failed, ok + failed


# ------------------------------------------------------------------ main per-slug run
def run_slug(ce, GLTFExportModelSettings, ScriptExportModelSettings, slug):
    T = {"start": time.time()}
    gj = os.path.join(CEDIR, slug, "buildings.geojson")
    fac_p = os.path.join(CEDIR, slug, "facade_v2.json")
    feats = json.load(open(gj, encoding="utf-8"))["features"]
    if not os.path.exists(fac_p):
        sys.path.insert(0, HERE); import facade_classes; facade_classes.run(slug)
    facade = json.load(open(fac_p, encoding="utf-8"))["buildings"]
    scene = f"/najma/scenes/{slug}.cej"
    log(f"=== {slug}: {len(feats)} footprints, scene {scene}")
    ce.openFile(scene)
    try: ce.waitForUIIdle()
    except Exception: time.sleep(2)
    layers = ce.getObjectsFrom(ce.scene, ce.isShapeLayer)
    cands = []
    for L in layers:
        shp = ce.getObjectsFrom(L, ce.isShape); nm = str(ce.getName(L)); cands.append((nm, shp)); log(f"  layer '{nm}': {len(shp)} shapes")
    pick = [c for c in cands if len(c[1]) == len(feats)] or [c for c in cands if "building" in c[0].lower()] or sorted(cands, key=lambda c: -len(c[1]))
    if not pick or not pick[0][1]:
        log("  no shapes — skipped"); return None
    layer_name, shapes = pick[0]; n = len(shapes)
    log(f"  using layer '{layer_name}' ({n} shapes) vs {len(feats)} features")
    shapes = rank_by_oid(ce, shapes)
    mapping, how = map_shapes_to_features(ce, shapes, feats); T["mapped"] = time.time()

    # names + object attrs (grouped to keep bridge calls low)
    by_cls, by_var, by_h, by_lv = {}, {}, {}, {}
    for s, fi in zip(shapes, mapping):
        rec = facade.get(str(fi), {"class": "auto", "variant": fi % 3}); c = rec["class"]; v = int(rec.get("variant", fi % 3))
        pr = feats[fi]["properties"]
        st = str(pr.get("status") or "existing").lower()
        ce.setName(s, f"b{fi}_{c}_s{st}" if VER == "v3" else f"b{fi}_{c}")   # v3: status travels in the name (textures carry no status colour)
        by_cls.setdefault(c, []).append(s); by_var.setdefault(v, []).append(s)
        # bHeight / levels are OBJECT-sourced, and the scene's objects still carry whatever the original
        # SHP import baked in — so heights improved in buildings.geojson (overture/wikidata backfill) only
        # reach the rule if we push them here, exactly the way fclass/fvar are pushed. Grouped by value to
        # keep the number of bridge calls down.
        try:
            h = float(pr.get("bHeight") or 0)
        except (TypeError, ValueError):
            h = 0.0
        if h > 0: by_h.setdefault(round(h, 1), []).append(s)
        lv = str(pr.get("levels") or "").strip()
        if lv: by_lv.setdefault(lv, []).append(s)
    for c, lst in by_cls.items(): ce.setAttribute(lst, "fclass", c)
    for v, lst in by_var.items(): ce.setAttribute(lst, "fvar", v)
    for h, lst in by_h.items(): ce.setAttribute(lst, "bHeight", h)
    for lv, lst in by_lv.items(): ce.setAttribute(lst, "levels", lv)
    log(f"  named {n} shapes (mapping: {how}); classes " + ", ".join(f"{c}={len(l)}" for c, l in sorted(by_cls.items())))
    log(f"  heights pushed: {len(by_h)} distinct values, max {max(by_h) if by_h else 0} m; levels {len(by_lv)} distinct")
    T["named"] = time.time()
    ce.setRuleFile(shapes, RULE_WS); ce.setStartRule(shapes, "Lot")
    for a in ("bHeight", "status", "levels", "fclass", "fvar", "pctComplete"):
        try: ce.setAttributeSource(shapes, "/ce/rule/" + a, "OBJECT")
        except Exception as e: log(f"  attr source {a}: {str(e).splitlines()[0][:80]}")
    json.dump({"slug": slug, "mapping": how, "layer": layer_name, "shape_to_feature": mapping}, open(os.path.join(CEDIR, slug, f"shape_map_{VER}.json"), "w"))

    # LOD ladder
    out_glb = os.path.join(GLB, f"sky_{slug}_{VER}_0.glb"); out_log = os.path.join(GLB, f"sky_{slug}_{VER}.log")
    csv_p = os.path.join(CEDIR, slug, f"report_{VER}.csv"); json_p = os.path.join(CEDIR, slug, f"report_{VER}.json")
    target = os.path.join(ce.toFSPath("/najma/scripts"), "ce_report_v2_target.json")
    attempts = []; chosen = None
    for lod, band in LADDER:
        for p in [out_log, csv_p, json_p, csv_p + ".err"] + [os.path.join(GLB, f) for f in os.listdir(GLB) if f.startswith(f"sky_{slug}_{VER}_") and f.endswith(".glb")]:
            if os.path.exists(p): os.remove(p)   # incl. _1/_2.. parts a previous oversized attempt split off
        ce.setAttribute(shapes, "/ce/rule/LOD", lod); ce.setAttribute(shapes, "/ce/rule/bandEvery", band)
        for a in ("LOD", "bandEvery"):
            try: ce.setAttributeSource(shapes, "/ce/rule/" + a, "USER")
            except Exception: pass
        t0 = time.time(); ce.generateModels(shapes); tg = time.time() - t0
        json.dump({"csv": csv_p, "json": json_p, "slug": slug, "lod": lod, "bandEvery": band}, open(target, "w"))
        s = GLTFExportModelSettings()
        s.setOutputPath(GLB); s.setBaseName(f"sky_{slug}_{VER}"); s.setMeshGranularity(GRAN)
        s.setOutputFormat(GLTFExportModelSettings.GLTF_GLB_WITH_SINGLE_BUFFER); s.setIncludeMaterials(True); s.setWriteLog(True)
        s.setExistingFiles(GLTFExportModelSettings.OVERWRITE)
        try: s.setTerrainLayers(GLTFExportModelSettings.TERRAIN_NONE)
        except Exception: pass
        try: s.setScript(SCRIPT_WS)
        except Exception as e: log("  setScript:", e)
        t0 = time.time(); ce.export(shapes, s); te = time.time() - t0
        time.sleep(1)
        ok, failed, total = export_log_status(out_log)
        size = os.path.getsize(out_glb) if os.path.exists(out_glb) else 0
        rep_ok = os.path.exists(csv_p)
        if not rep_ok:  # callback path fallback: project-relative, then a separate script-only export pass
            for alt in ("scripts/ce_report_v2.py",):
                try:
                    s2 = ScriptExportModelSettings(); s2.setScript(alt); ce.export(shapes, s2); time.sleep(1)
                    if os.path.exists(csv_p): rep_ok = True; log(f"  reports via ScriptExportModelSettings('{alt}')"); break
                except Exception as e:
                    log(f"  script export '{alt}': {str(e).splitlines()[0][:100]}")
        raw_mb = round(size / 1048576, 3); merged = None
        if size and GRAN == "AS_GENERATED" and not flag_nomerge:
            try:
                sys.path.insert(0, HERE); from glb_merge_per_building import merge as glb_merge
                merged = glb_merge(out_glb); size = os.path.getsize(out_glb)
            except Exception as e:
                log("  merge per building failed:", str(e)[:120])
        v = verify_glb(out_glb, n) if size else {"bytes": 0}
        a = {"lod": lod, "bandEvery": band, "granularity": GRAN, "generate_s": round(tg, 1), "export_s": round(te, 1), "mb": round(size / 1048576, 3), "raw_mb": raw_mb,
             "leaf_meshes_raw": merged["leaf_meshes_in"] if merged else None, "triangles": v.get("triangles"), "images": merged.get("images") if merged else v.get("images"),
             "image_mb": round(merged["image_bytes"] / 1048576, 3) if merged else v.get("image_mb"),
             "meshes": v.get("meshes"), "buildings": v.get("buildings"), "shapes_ok": ok, "shapes_failed": failed, "reports_csv": rep_ok}
        attempts.append(a)
        log(f"  LOD {lod} bandEvery {band} {GRAN}: gen {tg:.1f}s, export {te:.1f}s, raw {raw_mb} MB" + (f" ({merged['leaf_meshes_in']} leaf meshes) -> merged {a['mb']} MB" if merged else f" = {a['mb']} MB")
            + f", {v.get('triangles')} tris, buildings {v.get('buildings')}/{n}, meshes {v.get('meshes')}, shapes ok {ok} failed {failed}, reports {'yes' if rep_ok else 'NO'}"
            + (f", {merged['images']} images ({merged['image_bytes'] / 1048576:.2f} MB, {merged['images_in']} before dedupe), {merged['materials']} materials" if merged else ""))
        if failed == 0 and size and (not FIT or size <= BUDGET * 1048576):
            chosen = a; break
        if failed and not FIT:
            break
    T["exported"] = time.time()
    if chosen is None:
        log(f"  no tier met the {BUDGET} MB budget with zero failures — last attempt kept on disk, scene NOT saved")
    elif SAVE:
        try: ce.saveFile(scene); log(f"  scene saved with najma_{VER}.cga assigned")
        except Exception as e: log("  save:", str(e).splitlines()[0][:100])
    if SNAP and size:
        try:
            v3 = ce.get3DViews()[0]; ce.setSelection([]); v3.frame(shapes)
            try: ce.waitForUIIdle()
            except Exception: time.sleep(2)
            v3.snapshot(os.path.join(GLB, f"snap_{slug}_{VER}.png"), 1600, 1000)
        except Exception as e:
            log("  snapshot:", str(e)[:80])

    # verification + report summary
    ver = verify_glb(out_glb, n) if os.path.exists(out_glb) else {}
    ver.update({"slug": slug, "attempts": attempts, "chosen": chosen, "budget_mb": BUDGET, "mapping": how, "timings_s": {
        "map": round(T["mapped"] - T["start"], 1), "name_attrs": round(T["named"] - T["mapped"], 1), "generate_export": round(T["exported"] - T["named"], 1), "total": round(time.time() - T["start"], 1)},
        "generated": datetime.datetime.now().isoformat(timespec="seconds")})
    if os.path.exists(csv_p):
        rows = list(csv.DictReader(open(csv_p, encoding="utf-8", errors="replace")))
        gfa = sum(float(r["gfa_m2"] or 0) for r in rows); st = sum(int(r["storeys"] or 0) for r in rows)
        ver["report"] = {"rows": len(rows), "gfa_m2_total": round(gfa), "storeys_total": st,
                         "top5_gfa": sorted(({"shape": r["shape"], "gfa_m2": round(float(r["gfa_m2"] or 0)), "storeys": r["storeys"], "height_m": r["height_m"]} for r in rows), key=lambda r: -r["gfa_m2"])[:5]}
        log(f"  reports: {len(rows)} rows, GFA total {gfa:,.0f} m2, storeys {st}; top: " + "; ".join(f"{r['shape']} {r['gfa_m2']:,} m2/{r['storeys']} fl" for r in ver["report"]["top5_gfa"][:3]))
    json.dump(ver, open(os.path.join(CEDIR, slug, f"glb_{VER}_verify.json"), "w"), indent=1)
    log(f"  verify: {ver.get('buildings')} building root nodes / {n} shapes match={ver.get('buildings_match_shapes')} ({ver.get('unique_b_ids')} unique b-ids), {ver.get('meshes')} meshes "
        f"(per building {ver.get('meshes_per_building')}), {ver.get('mb')} MB, {ver.get('triangles')} tris, "
        f"{ver.get('materials')} materials {ver.get('material_families')}, classes {ver.get('classes_in_names')}")
    return ver


def main():
    if PALETTE:
        palette_check(); return
    if VERIFY_ONLY:
        for slug in SLUGS:
            p = os.path.join(GLB, f"sky_{slug}_{VER}_0.glb")
            if os.path.exists(p):
                n = len(json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"])
                v = verify_glb(p, n); log(json.dumps({k: v[k] for k in v if k != "materials_detail"}, indent=1))
            else: log(slug, "no v2 GLB")
        return
    for slug in SLUGS:
        if slug == "dubaimarina" and not ALLOW_MARINA:
            sys.exit("dubaimarina is the approved proof — pass --allow-marina to touch it")
        if not os.path.exists(os.path.join(CEDIR, slug, "buildings.geojson")):
            sys.exit(f"{slug}: no data/ce/{slug}/buildings.geojson")
    if not palette_check():
        sys.exit(f"palette check failed — fix rules/najma_{VER}.cga colours before generating")
    acquire_lock()
    from cityengine import CE, GLTFExportModelSettings, ScriptExportModelSettings  # noqa: E402  (bridge connect = first bridge call)
    ce = CE(); ws = ce.toFSPath("/"); proj = os.path.join(ws, "najma")
    log("  connected; workspace", ws)
    # stage rules + callback script (repo = SSOT)
    for root, _, fns in os.walk(RULES):
        rel = os.path.relpath(root, RULES); dst = os.path.join(proj, "rules") if rel == "." else os.path.join(proj, "rules", rel)
        os.makedirs(dst, exist_ok=True)
        for fn in fns:
            if fn.endswith(".cga"): shutil.copy2(os.path.join(root, fn), os.path.join(dst, fn))
    os.makedirs(os.path.join(proj, "scripts"), exist_ok=True)
    shutil.copy2(os.path.join(HERE, "ce_report_v2.py"), os.path.join(proj, "scripts", "ce_report_v2.py"))
    try: ce.refreshWorkspace()
    except Exception: pass
    info = ce.getRuleFileInfo(RULE_WS)  # compiles the rule — raises on CGA errors before any scene is touched
    rules = [r.get("name") if isinstance(r, dict) else str(r) for r in (info.get("rules", []) if isinstance(info, dict) else [])]
    log(f"  najma_{VER}.cga compiled: {len(rules)} rules" + (f" (start: {[r for r in rules if r in ('Lot',)]})" if rules else ""))
    results = {}
    for slug in SLUGS:
        try:
            results[slug] = run_slug(ce, GLTFExportModelSettings, ScriptExportModelSettings, slug)
        except Exception as e:
            log(f"  {slug} FAILED: {str(e).splitlines()[0][:200]}")
            import traceback; traceback.print_exc()
    release_lock()
    log("\nsummary:")
    for slug, v in results.items():
        if v: log(f"  {slug}: {v.get('mb')} MB, {v.get('buildings')} buildings/{v.get('shapes')} shapes, {v.get('meshes')} meshes, chosen {v.get('chosen')}, total {v['timings_s']['total']}s")
    open(os.path.join(GLB, f"ce_batch_{VER}_last.log"), "w", encoding="utf-8").write("\n".join(log_lines))


if __name__ == "__main__":
    main()

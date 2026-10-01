"""LAB (Blocks) - QA of the LOD 100 Blocks payloads Rings writes tonight. Read-only on everything it checks.

(a) data/ce/<slug>/blocks.json  (scripts/build_blocks.py: FeatureCollection; buildings {k:"b", i, h, hs?, n?, a?}, streets {k:"s"})
    * footprint count and ids vs data/ce/<slug>/buildings.geojson: every i present once, none extra, and block i IS footprint i
      (its polygon's centroid within 1 m of footprint i's) - the twin's b<i> is the same index (shape_map_v4/v3 "identity");
    * heights vs data/board/bldgfacts_<slug>.json height_m: |h - height_m| / height_m > 20 % flagged;
    * the same against the LIVE twin, https://azimuth-2.digitalchemy.workers.dev/img/bldgfacts_<slug> (curl - the worker 403s
      python urllib's user agent - with retries; cached under data/lab/blocks/live/ for an hour);
    * towers at 12 m: block h == 12 but bldgfacts (local or live) >= 20 m or >= 6 storeys, register storeys (anchors' levels)
      >= 6, heights_register >= 20 m, a tower-ish name, or the type hint says tower;
    * missing / extra footprints, duplicate ids, meta.buildings vs the features, implausible heights (<= 0, < 2 m, > 830 m).
(b) data/blocks_city/<slug>/blocks.json  (beyond-51 districts: DM community polygons + OSM)
    * the community polygon from data/raw_downloads/dda/prod/dm__dm_community-open-api.kml (COMM_NUM / CNAME_E), matched from
      the payload's meta (comm_num / community / communities) or the slug; blocks whose centroid falls outside it (25 m slack);
    * building counts vs the registers: DM building_summary_information (community_no; permits not Expired / Cancelled /
      demolished) and DLD dld__buildings (area_name_en, matched by normalised name);
    * implausible heights, duplicate ids.

Writes ONLY data/lab/blocks/qa_<slug>.json, data/lab/blocks/QA_SUMMARY.md (the text of data/lab/blocks/_summary_head.md, if
present, goes on top), data/lab/blocks/_qa_state.json, data/lab/blocks/live/, data/lab/blocks/_registers_by_community.json.

  python scripts/lab_blocks_qa.py                one pass: QA every blocks.json whose mtime changed since its last QA
  python scripts/lab_blocks_qa.py --force        one pass, everything
  python scripts/lab_blocks_qa.py --loop         poll every 12 min; stop when every district is QA'd and nothing has changed
                                                 for 30 min, or after 6 h
Research use only.
"""
import csv, datetime, json, math, os, re, subprocess, sys, time, traceback
import xml.etree.ElementTree as ET
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "lab", "blocks"); LIVE = os.path.join(OUT, "live")
os.makedirs(LIVE, exist_ok=True)
CE = os.path.join(DATA, "ce"); CITY = os.path.join(DATA, "blocks_city")
WORKER = "https://azimuth-2.digitalchemy.workers.dev"
KML = os.path.join(DATA, "raw_downloads", "dda", "prod", "dm__dm_community-open-api.kml")
DLD = os.path.join(DATA, "raw_downloads", "dd", "dld__buildings__2026-09-25.csv")
DM_GLOB_DIR = os.path.join(DATA, "raw_downloads"); DM_PREFIX = "building_summary_information_2026-08-31_"
STATE = os.path.join(OUT, "_qa_state.json"); SUMMARY = os.path.join(OUT, "QA_SUMMARY.md"); HEAD = os.path.join(OUT, "_summary_head.md")
REG_CACHE = os.path.join(OUT, "_registers_by_community.json")
TOL = 0.20; TALL_CHECK_M = 20.0; CENT_TOL_M = 1.0; LIVE_MAX_AGE = 3600; POLL_S = 12 * 60; STABLE_S = 30 * 60; MAX_S = 6 * 3600
RX_TOWER = re.compile(r"\btowers?\b", re.I)
RX_NOT_TOWER = re.compile(r"\b(water|clock|cooling|telecom|radio|observation|control)\s+tower\b", re.I)
M_LAT = 110850.0; M_LON = 101200.0          # metres per degree at ~25.1 N
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def jload(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def jdump(o, p, **kw):
    tmp = p + ".tmp"
    json.dump(o, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, **kw)
    os.replace(tmp, p)


def num(v):
    try:
        f = float(str(v).strip())
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def ring_centroid(ring):
    """Area centroid of a lon/lat ring (planar - fine at this scale), and its area in m2."""
    a = cx = cy = 0.0
    x0, y0 = ring[0]
    for k in range(len(ring) - 1):
        x1, y1 = (ring[k][0] - x0) * M_LON, (ring[k][1] - y0) * M_LAT
        x2, y2 = (ring[k + 1][0] - x0) * M_LON, (ring[k + 1][1] - y0) * M_LAT
        c = x1 * y2 - x2 * y1
        a += c; cx += (x1 + x2) * c; cy += (y1 + y2) * c
    if abs(a) < 1e-9:
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys)), 0.0
    return (x0 + cx / (3 * a) / M_LON, y0 + cy / (3 * a) / M_LAT), abs(a) / 2


def geom_centroid(g):
    """(lon, lat), area m2 of a Polygon / MultiPolygon (outer rings, area-weighted), or (None, 0)."""
    if not g: return None, 0.0
    polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates") if g.get("type") == "MultiPolygon" else []
    tot = sx = sy = 0.0; first = None
    for poly in polys:
        if not poly or len(poly[0]) < 3: continue
        (x, y), a = ring_centroid(poly[0])
        first = first or (x, y)
        tot += a; sx += x * a; sy += y * a
    if tot > 0: return (sx / tot, sy / tot), tot
    return first, 0.0


def dist_m(p, q):
    return math.hypot((p[0] - q[0]) * M_LON, (p[1] - q[1]) * M_LAT)


def valid_rings(f):
    """build_blocks.py's own test: a footprint draws only when some ring survives clean_ring (>= 4 points after dedupe)."""
    g = f.get("geometry") or {}
    polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates") if g.get("type") == "MultiPolygon" else []
    for poly in polys:
        for r in poly:
            out = []
            for c in r:
                p = [round(float(c[0]), 6), round(float(c[1]), 6)]
                if not out or p != out[-1]: out.append(p)
            if len(out) >= 2 and out[0] != out[-1]: out.append(out[0])
            if len(out) >= 4: return True
    return False


HINT_TYPES = {"villa", "townhouse", "lowrise_apt", "tower", "warehouse", "mall", "retail", "school", "mosque", "other"}


def differs(typical, hint):
    """typical_<x> (the heights lane) vs this lane's hint: only a real type conflict counts - typical_small and other
    size rules are not types, and villa / townhouse are one family (same typical height band)."""
    if typical not in HINT_TYPES: return False
    if {typical, hint} <= {"villa", "townhouse"}: return False
    return typical != hint


# ------------------------------------------------------------------ the live twin
def live_bldgfacts(slug, log=print):
    dst = os.path.join(LIVE, "bldgfacts_%s.json" % slug)
    if os.path.exists(dst) and time.time() - os.path.getmtime(dst) < LIVE_MAX_AGE:
        return jload(dst), "cached"
    tmp = dst + ".dl"
    for attempt in range(4):
        try:
            r = subprocess.run(["curl", "-s", "-f", "-m", "120", "--compressed", "--retry", "2", "--retry-delay", "5", "-o", tmp,
                                "-w", "%{http_code}", WORKER + "/img/bldgfacts_" + slug], capture_output=True, text=True, timeout=400)
            code = (r.stdout or "").strip()
            if r.returncode == 0 and code == "200":
                raw = open(tmp, "rb").read()
                if raw[:2] == b"\x1f\x8b":
                    import gzip; raw = gzip.decompress(raw)
                j = json.loads(raw.decode("utf-8"))
                jdump(j, dst, separators=(",", ":")); os.remove(tmp)
                return j, "fetched"
            if code == "404":
                return None, "404"
            log("  live bldgfacts_%s: curl rc %s http %s (attempt %d)" % (slug, r.returncode, code, attempt + 1))
        except Exception as e:
            log("  live bldgfacts_%s: %s (attempt %d)" % (slug, e, attempt + 1))
        time.sleep(10 * (attempt + 1))
    if os.path.exists(dst):
        return jload(dst), "stale-cache"
    return None, "unreachable"


# ------------------------------------------------------------------ (a) a district of the twin
def flag(flags, check, sev, ids, detail=None, note=None):
    if not ids and not detail: return
    f = {"check": check, "severity": sev, "n": len(ids) if ids else len(detail or [])}
    if ids: f["ids"] = sorted(ids, key=lambda v: (not isinstance(v, int), v if isinstance(v, int) else 0))[:5000]
    if detail: f["detail"] = detail[:60]
    if note: f["note"] = note
    flags.append(f)


def qa_ce(slug, log=print):
    p = os.path.join(CE, slug, "blocks.json")
    blk = jload(p)
    if not blk:
        return {"slug": slug, "kind": "ce", "status": "unreadable", "flags": [{"check": "unreadable", "severity": "high", "n": 1}]}
    meta = blk.get("meta") or {}
    B = [f for f in blk.get("features") or [] if (f.get("properties") or {}).get("k") == "b"]
    S = [f for f in blk.get("features") or [] if (f.get("properties") or {}).get("k") == "s"]
    fp = jload(os.path.join(CE, slug, "buildings.geojson"))["features"]
    n = len(fp)
    drawable = {i for i, f in enumerate(fp) if valid_rings(f)}
    bf = (jload(os.path.join(DATA, "board", "bldgfacts_%s.json" % slug), {}) or {}).get("buildings_by_id") or {}
    live, live_how = live_bldgfacts(slug, log)
    lbf = (live or {}).get("buildings_by_id") or {}
    anch = jload(os.path.join(DATA, "names", "anchors_%s.json" % slug), {}) or {}
    a_by_i = {}
    for a in anch.get("anchors") or []:
        if a.get("i") is not None and a["i"] not in a_by_i: a_by_i[a["i"]] = a
    hreg = (jload(os.path.join(CE, slug, "heights_register.json"), {}) or {}).get("heights") or {}
    th = (jload(os.path.join(OUT, "type_hints_%s.json" % slug), {}) or {}).get("types") or {}
    sm = jload(os.path.join(CE, slug, "shape_map_v4.json")) or jload(os.path.join(CE, slug, "shape_map_v3.json")) or {}

    flags = []
    ids = []; bad_id = []
    for f in B:
        i = f["properties"].get("i")
        if isinstance(i, bool) or not isinstance(i, int): bad_id.append(str(i)); continue
        ids.append(i)
    c = Counter(ids)
    dup = [i for i, k in c.items() if k > 1]
    idset = set(ids)
    extra = [i for i in idset if i < 0 or i >= n]
    missing = [i for i in range(n) if i not in idset]
    miss_draw = [i for i in missing if i in drawable]; miss_nogeom = [i for i in missing if i not in drawable]
    flag(flags, "missing_footprint", "high", miss_draw, note="footprint i has drawable geometry in buildings.geojson but no block")
    flag(flags, "missing_footprint_no_geometry", "info", miss_nogeom, note="footprint has no drawable ring - build_blocks skips it by design")
    flag(flags, "extra_block", "high", extra + [x for x in bad_id], note="block i not a footprint index of buildings.geojson")
    flag(flags, "duplicate_id", "high", dup)

    # block i IS footprint i: same place
    shifted = []
    fp_cent = {}
    for f in B:
        i = f["properties"].get("i")
        if not isinstance(i, int) or not (0 <= i < n): continue
        cb, _ = geom_centroid(f.get("geometry"))
        if i not in fp_cent: fp_cent[i] = geom_centroid(fp[i].get("geometry"))
        cf, _ = fp_cent[i]
        if cb and cf:
            d = dist_m(cb, cf)
            if d > CENT_TOL_M: shifted.append({"i": i, "offset_m": round(d, 1)})
    flag(flags, "id_geometry_mismatch", "high", [s["i"] for s in shifted], sorted(shifted, key=lambda s: -s["offset_m"]),
         note="block i's polygon is not footprint i's (centroid > 1 m apart): an index shift would put names/heights on the wrong building")
    # The twin names each mesh b<footprint i> (ce_batch_v2 setName uses the MAPPED feature index): shape_map's shape_to_feature
    # is in CityEngine scene order, so only its SET of feature indexes matters - the twin's ids are exactly those b<fi>.
    # (Fixed 30 Sep 23:58: an earlier pass compared scene order with i and falsely flagged palmdeira, whose map is "centroid".)
    stf = sm.get("shape_to_feature") if isinstance(sm, dict) else None
    twin_map = "absent" if not isinstance(stf, list) else "b<footprint i> (%s scene order)" % (sm.get("mapping") or "?")
    if isinstance(stf, list):
        tw = {int(x) for x in stf if isinstance(x, (int, float))}
        flag(flags, "not_in_twin", "medium", sorted(idset - tw),
             note="block b<i> the twin has no mesh for (footprint added after the twin build)")
        flag(flags, "in_twin_not_in_blocks", "medium", sorted(i for i in tw - idset if 0 <= i),
             note="twin mesh b<i> with no block")
        if len(stf) != n:
            flag(flags, "twin_shape_count", "info", [], [{"twin_shapes": len(stf), "footprints": n}],
                 note="the twin (shape_map_v4/v3) was built from a different footprint count")

    # heights
    diffs, diffs_live, t12, implaus = [], [], [], []
    hs_count = Counter(); h12 = 0
    for f in B:
        pr = f["properties"]; i = pr.get("i")
        if not isinstance(i, int): continue
        h = num(pr.get("h"))
        hs_count[pr.get("hs") or "(none)"] += 1
        if h is None or h <= 0 or h < 2.0 or h > 830:
            implaus.append({"i": i, "h": pr.get("h"), "hs": pr.get("hs")})
            continue
        b = bf.get(str(i)) or {}; hf = num(b.get("height_m"))
        if hf and hf > 0 and abs(h - hf) / hf > TOL:
            diffs.append({"i": i, "h": h, "bldgfacts_h": hf, "hs": pr.get("hs"), "ratio": round(h / hf, 2), "name": pr.get("n") or b.get("name")})
        lb = lbf.get(str(i)) or {}; hl = num(lb.get("height_m"))
        if hl and hl > 0 and abs(h - hl) / hl > TOL:
            diffs_live.append({"i": i, "h": h, "live_h": hl, "hs": pr.get("hs"), "ratio": round(h / hl, 2)})
        # (02:45: generalised from "exactly 12 m" - the heights lane now fills unknowns with community medians / typical_*,
        # so a tall building can be drawn at 11.7 m or 8 m instead: any block under 20 m with tall evidence is checked)
        if abs(h - 12.0) < 0.05:
            h12 += 1
        if h < TALL_CHECK_M:
            # evidence as heights (storeys x 3.2 m): strong = a measured / registered source says 20 m+ AND the block is under
            # 60 % of it (a 6-storey building drawn at 19.2 m is consistent, not a defect)
            why, ev = [], []
            if hf and hf >= 20: why.append("bldgfacts %.0f m" % hf); ev.append(hf)
            if hl and hl >= 20 and hl != hf: why.append("live %.0f m" % hl); ev.append(hl)
            st = num(b.get("storeys")) or num(lb.get("storeys"))
            if st and st >= 6: why.append("bldgfacts %d storeys" % st); ev.append(st * 3.2)
            a = a_by_i.get(i) or {}
            lv = num(a.get("levels"))
            if lv and lv >= 6: why.append("register %d storeys" % lv); ev.append(lv * 3.2)
            rh = num(hreg.get(str(i)))
            if rh and rh >= 20: why.append("heights_register %.0f m" % rh); ev.append(rh)
            nm = " / ".join(x for x in {pr.get("n") or "", a.get("name") or "", b.get("name") or "",
                                         (fp[i].get("properties") or {}).get("name") or "" if 0 <= i < n else ""} if x)
            named = bool(nm and RX_TOWER.search(nm) and not RX_NOT_TOWER.search(nm))
            if named: why.append("name '%s'" % nm[:60])
            t = (th.get(str(i)) or {})
            if t.get("type") == "tower": why.append("type hint tower (%s/%s)" % (t.get("src"), t.get("conf")))
            strong = bool(ev) and max(ev) >= 20 and h < 0.6 * max(ev)
            soft = not ev and (named or t.get("type") == "tower") and h <= 12.5
            if strong or soft:
                t12.append({"i": i, "h": h, "why": why, "evidence_m": round(max(ev), 1) if ev else None, "name": nm[:80] or None,
                            "hs": pr.get("hs"), "strong": strong})
    # the coordinator's register_lifts_<slug>.json (30 Sep 23:55): register heights the v4 massing already carries but the
    # stale bldgfacts (24 Sep) still shows as 12 m - the explanation, and the fix, for most measured 12 m towers
    lifts = (jload(os.path.join(OUT, "register_lifts_%s.json" % slug), {}) or {}).get("lifts") or {}
    for x in t12:
        lf = lifts.get(str(x["i"]))
        if lf: x["register_lift_m"] = lf.get("height_m")
    strong = [x for x in t12 if x["strong"]]; weak = [x for x in t12 if not x["strong"]]
    flag(flags, "tower_at_12m", "high", [x["i"] for x in strong], strong,
         note="block drawn under 20 m (12 m placeholder, community median or typical_*) but a measured / registered height or storey count says 20 m+ / 6+ storeys")
    flag(flags, "tower_at_12m_soft", "medium", [x["i"] for x in weak], weak,
         note="block drawn under 20 m; only a name or the type hint says tower (no measured height)")
    # a bldgfacts height of exactly 12.0 is the pipeline placeholder: a block that differs from it by a measured source is an
    # improvement, not a conflict - reported apart, at info
    sup = [d for d in diffs if abs(d["bldgfacts_h"] - 12.0) < 0.05 and d.get("hs") not in ("unknown", "default12", None)]
    real = [d for d in diffs if d not in sup]
    big = sorted(real, key=lambda d: -abs(math.log(d["ratio"])) if d["ratio"] > 0 else 0)
    flag(flags, "height_vs_bldgfacts_gt20pct", "medium", [d["i"] for d in real], big,
         note="block h differs > 20 % from bldgfacts height_m, where bldgfacts has a real (non-12 m) height")
    flag(flags, "bldgfacts_placeholder_superseded", "info", [d["i"] for d in sup],
         sorted(sup, key=lambda d: -d["h"]), note="bldgfacts says the 12 m placeholder; the block carries a sourced height instead")
    diffs = real
    local_ids = {d["i"] for d in diffs} | {d["i"] for d in sup}
    live_only = [d for d in diffs_live if d["i"] not in local_ids and abs(d["live_h"] - 12.0) >= 0.05]
    flag(flags, "height_vs_live_bldgfacts_gt20pct", "medium" if live else "info", [d["i"] for d in live_only],
         sorted(live_only, key=lambda d: -abs(math.log(d["ratio"])) if d["ratio"] > 0 else 0),
         note="block h differs > 20 % from the LIVE twin's bldgfacts (real height) but not from the local board file")
    flag(flags, "implausible_height", "high", [x["i"] for x in implaus], implaus)
    if meta.get("buildings") is not None and meta.get("buildings") != len(B):
        flag(flags, "meta_count_mismatch", "low", [], [{"meta_buildings": meta.get("buildings"), "features": len(B)}])
    drift = [k for k, v in bf.items() if k in lbf and num(v.get("height_m")) != num(lbf[k].get("height_m"))] if live else []
    flag(flags, "local_vs_live_bldgfacts_drift", "info", [int(k) for k in drift],
         note="data/board/bldgfacts_%s.json height_m differs from the live twin's for these" % slug)
    # 02:50 - district-wide fills (community_median): one median for every unknown block, so in a tower district a 40 m2
    # guardhouse becomes a 90 m needle, and in JVC a G+4 block becomes a 6 m bungalow
    needles, flat, tall_other = [], [], []
    cm_h = Counter()
    for f in B:
        pr = f["properties"]; hs_ = str(pr.get("hs") or "")
        if not hs_.startswith(("community_median", "district_median")): continue
        h = num(pr.get("h")) or 0; cm_h[round(h, 1)] += 1
        _, area = geom_centroid(f.get("geometry"))
        t = (th.get(str(pr.get("i"))) or {}).get("type")
        if h >= 25 and area < 200:
            needles.append({"i": pr["i"], "h": h, "area_m2": round(area), "type_hint": t})
        elif h >= 25 and t == "other":
            tall_other.append({"i": pr["i"], "h": h, "area_m2": round(area), "type_hint": t})
        elif h < 9 and t in ("tower", "lowrise_apt", "mall", "school"):
            flat.append({"i": pr["i"], "h": h, "area_m2": round(area), "type_hint": t})
    flag(flags, "median_fill_needle", "high", [x["i"] for x in needles], sorted(needles, key=lambda x: x["area_m2"]),
         note="community_median of 25 m+ on a footprint under 200 m2: a guardhouse / shed / kiosk drawn as a tower")
    flag(flags, "median_fill_tall_on_other", "medium", [x["i"] for x in tall_other], sorted(tall_other, key=lambda x: x["area_m2"]),
         note="community_median of 25 m+ on a 200 m2+ footprint the type hints call 'other' (podium, car park, service block?)")
    flag(flags, "median_fill_flattens_block", "medium", [x["i"] for x in flat], flat,
         note="community_median under 9 m on a footprint typed tower / lowrise_apt / mall / school")
    tall = sorted(({"i": f["properties"]["i"], "h": f["properties"]["h"], "n": f["properties"].get("n")} for f in B
                   if (num(f["properties"].get("h")) or 0) > 300), key=lambda x: -x["h"])
    flag(flags, "over_300m_review", "info", [x["i"] for x in tall], tall)
    # typical_* heights vs the type hints (the heights agent's use of this lane's output)
    typ_mis, typ_low, pending = [], [], []
    typ_conf = Counter()
    for f in B:
        pr = f["properties"]; hs = str(pr.get("hs") or "")
        t = th.get(str(pr.get("i"))) or {}
        if hs.startswith("typical_"):
            want = hs[len("typical_"):]
            typ_conf["%s/%s" % (hs, t.get("conf"))] += 1
            if th and t.get("type") and differs(want, t.get("type")): typ_mis.append({"i": pr["i"], "hs": hs, "type_hint": t.get("type")})
            if t.get("conf") == "low": typ_low.append({"i": pr["i"], "hs": hs, "type_hint_src": t.get("src")})
        elif hs in ("unknown", "default12") and t.get("type") in ("villa", "townhouse", "warehouse") and t.get("conf") in ("high", "medium"):
            pending.append(pr["i"])
    flag(flags, "typical_height_vs_type_hint", "low", [x["i"] for x in typ_mis], typ_mis,
         note="the block's typical_<type> height names a different type than the current type hint (hints re-issued since the build?)")
    flag(flags, "typical_height_on_low_conf_hint", "low", [x["i"] for x in typ_low], typ_low)
    flag(flags, "type_hint_not_yet_applied", "info", pending,
         note="12 m placeholder block whose type hint (medium/high) is villa / townhouse / warehouse: a rebuild with the hints would give it a typical height")

    sev = Counter(f["severity"] for f in flags)
    status = "FAIL" if sev.get("high") else "WARN" if sev.get("medium") else "OK"
    return {
        "slug": slug, "kind": "ce", "qa_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "blocks_file": os.path.relpath(p, ROOT).replace("\\", "/"), "blocks_mtime": datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds"),
        "blocks_generated": meta.get("generated"), "schema": "v1+hs" if any("hs" in f["properties"] for f in B) else "v1 (no hs)",
        "counts": {"blocks": len(B), "footprints": n, "drawable_footprints": len(drawable), "streets": len(S), "missing": len(miss_draw),
                   "missing_no_geometry": len(miss_nogeom), "extra": len(extra) + len(bad_id), "duplicates": len(dup),
                   "id_geometry_mismatch": len(shifted), "h_12m": h12, "tower_at_12m": len(strong), "tower_at_12m_explained_by_register_lifts": sum(1 for x in strong if x.get("register_lift_m")),
                   "tower_at_12m_soft": len(weak), "median_fill": sum(cm_h.values()), "median_fill_needles": len(needles), "median_fill_tall_on_other": len(tall_other), "median_fill_flat": len(flat),
                   "height_diff_gt20pct": len(diffs), "height_diff_live_only_gt20pct": len(live_only), "bldgfacts_placeholder_superseded": len(sup), "implausible": len(implaus),
                   "typical_heights": sum(typ_conf.values()), "type_hint_not_yet_applied": len(pending), "bldgfacts_rows": len(bf), "live_bldgfacts_rows": len(lbf), "local_vs_live_drift": len(drift)},
        "height_sources": dict(hs_count.most_common()), "twin_id_map": twin_map, "live_bldgfacts": live_how,
        "type_hints": bool(th), "typical_by_hint_conf": dict(typ_conf.most_common()), "median_fill_heights": dict(cm_h.most_common(4)), "flags": flags, "status": status,
    }


# ------------------------------------------------------------------ (b) beyond-51 districts
def norm(s):
    s = (s or "").upper().replace("&", " AND ")
    s = re.sub(r"\bIND\.?\b", "INDUSTRIAL", s)
    s = re.sub(r"\bFIRST\b", "1", s); s = re.sub(r"\bSECOND\b", "2", s); s = re.sub(r"\bTHIRD\b", "3", s)
    s = re.sub(r"\bFOURTH\b", "4", s); s = re.sub(r"\bFIFTH\b", "5", s); s = re.sub(r"\bSIXTH\b", "6", s)
    s = re.sub(r"\bAL\s+", "AL", s)
    s = s.replace("THANAYAH", "THANYAH").replace("YELAYISS", "YALAYIS").replace("JEBEL", "JABAL").replace("QOUZE", "QUOZ")
    return re.sub(r"[^A-Z0-9]", "", s)


_KML = None
def communities():
    """{comm_num: {"name", "community_e", "polys": [[ring lon/lat], ...]}} from the DM community KML."""
    global _KML
    if _KML is not None: return _KML
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    out = {}
    for pm in ET.parse(KML).getroot().iter("{http://www.opengis.net/kml/2.2}Placemark"):
        sd = {s.get("name"): (s.text or "").strip() for s in pm.iter("{http://www.opengis.net/kml/2.2}SimpleData")}
        cn = sd.get("COMM_NUM")
        if not cn: continue
        rings = []
        for pg in pm.iter("{http://www.opengis.net/kml/2.2}Polygon"):
            ob = pg.find("k:outerBoundaryIs/k:LinearRing/k:coordinates", ns)
            if ob is None or not ob.text: continue
            rings.append([tuple(map(float, t.split(",")[:2])) for t in ob.text.split()])
        e = out.setdefault(str(int(float(cn))), {"name": sd.get("CNAME_E"), "community_e": sd.get("COMMUNITY_E"), "polys": []})
        e["polys"] += rings
    _KML = out
    return out


def pip(pt, ring):
    x, y = pt; inside = False; j = len(ring) - 1
    for k in range(len(ring)):
        xi, yi = ring[k]; xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi: inside = not inside
        j = k
    return inside


def dist_to_ring_m(pt, ring):
    best = 1e18
    px, py = pt[0] * M_LON, pt[1] * M_LAT
    for k in range(len(ring) - 1):
        ax, ay = ring[k][0] * M_LON, ring[k][1] * M_LAT; bx, by = ring[k + 1][0] * M_LON, ring[k + 1][1] * M_LAT
        dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
        best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
    return best


def registers():
    """Per-community building counts from the DM permits register and the DLD buildings register (cached to disk).
    DM: rows (= distinct building_id) and distinct parcel_id, over the statuses the city build's own meta uses (New / Permit
    Delivered / Approved). A plot can carry several permitted buildings and a building several annexes, so the honest band for
    a footprint count is roughly [parcels, building rows]."""
    j = jload(REG_CACHE)
    if j and j.get("v") == 2: return j
    csv.field_size_limit(10 ** 9)
    dm_files = sorted(os.path.join(DM_GLOB_DIR, f) for f in os.listdir(DM_GLOB_DIR) if f.startswith(DM_PREFIX) and f.endswith(".csv"))
    live = {"New", "Permit Delivered", "Approved"}
    dm = {}; par = {}
    for fpath in dm_files:
        for row in csv.DictReader(open(fpath, encoding="utf-8-sig", errors="replace")):
            if (row.get("building_status_english") or "").strip() not in live: continue
            cn = num(row.get("community_no"))
            if cn is None: continue
            k = str(int(cn))
            e = dm.setdefault(k, {"name": (row.get("community_name_english") or "").strip(), "buildings": 0, "types": Counter()})
            e["buildings"] += 1; e["types"][(row.get("building_type_english") or "").strip()] += 1
            par.setdefault(k, set()).add(row.get("parcel_id"))
            if not e["name"]: e["name"] = (row.get("community_name_english") or "").strip()
    for k, e in dm.items():
        e["types"] = dict(e["types"].most_common()); e["parcels"] = len(par.get(k) or ())
    dld = Counter()
    for row in csv.DictReader(open(DLD, encoding="utf-8-sig", errors="replace")):
        dld[(row.get("area_name_en") or "").strip()] += 1
    j = {"v": 2, "built": datetime.datetime.now().isoformat(timespec="seconds"), "dm_files": [os.path.basename(f) for f in dm_files],
         "dm_note": "DM building_summary_information, statuses New / Permit Delivered / Approved: buildings = rows (distinct building_id), parcels = distinct parcel_id",
         "dm": dm, "dld": dict(dld), "dld_note": "rows of dld__buildings__2026-09-25.csv per area_name_en (includes off-plan)"}
    jdump(j, REG_CACHE, indent=0)
    return j


_CE_INDEX = None
def ce_index():
    """[(slug, [minx, miny, maxx, maxy])] of the twin districts' footprints, for the double-draw check."""
    global _CE_INDEX
    if _CE_INDEX is not None: return _CE_INDEX
    out = []
    for s in sorted(os.listdir(CE)):
        fp = os.path.join(CE, s, "buildings.geojson")
        if not os.path.exists(fp): continue
        lo = [999.0, 999.0, -999.0, -999.0]
        for f in jload(fp)["features"]:
            g = f.get("geometry") or {}
            polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates") or []
            for poly in polys:
                for x, y in (poly[0] if poly else []):
                    lo[0] = min(lo[0], x); lo[1] = min(lo[1], y); lo[2] = max(lo[2], x); lo[3] = max(lo[3], y)
        out.append((s, lo))
    _CE_INDEX = out
    return out


def ce_polys_near(bbox):
    """shapely polygons (lon/lat) of every twin footprint in the districts whose extent meets bbox."""
    from shapely.geometry import shape
    res = []
    for s, b in ce_index():
        if b[0] > bbox[2] or b[2] < bbox[0] or b[1] > bbox[3] or b[3] < bbox[1]: continue
        for i, f in enumerate(jload(os.path.join(CE, s, "buildings.geojson"))["features"]):
            try:
                g = shape(f["geometry"])
                if not g.is_valid: g = g.buffer(0)
                if not g.is_empty: res.append((g, s, i))
            except Exception:
                pass
    return res


def ring_area_m2(ring):
    return ring_centroid(list(ring))[1]


def qa_city(slug, log=print):
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    p = os.path.join(CITY, slug, "blocks.json")
    blk = jload(p)
    if not blk:
        return {"slug": slug, "kind": "city", "status": "unreadable", "flags": [{"check": "unreadable", "severity": "high", "n": 1}]}
    meta = dict(blk.get("meta") or {})
    mj = jload(os.path.join(CITY, slug, "meta.json"), {}) or {}
    meta.update({k: v for k, v in mj.items() if k not in meta or meta.get(k) in (None, "")})
    B = [f for f in blk.get("features") or [] if (f.get("properties") or {}).get("k", "b") == "b"
         and (f.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")]
    comms = communities()
    cns = []
    for key in ("comm_num", "COMM_NUM", "community_no"):
        if meta.get(key) not in (None, ""):
            cns = [str(int(float(meta[key])))]; break
    if not cns and isinstance(meta.get("communities"), list):
        cns = [str(int(float(x))) for x in meta["communities"]]
    how = "meta.comm_num" if cns else "slug"
    if not cns:
        nm = norm(meta.get("name") or slug.replace("_rest", ""))
        cns = [k for k, v in comms.items() if norm(v["name"]) == nm][:1]
    flags = []
    polys = [r for k in cns for r in (comms.get(k) or {}).get("polys", [])]
    if not polys:
        flag(flags, "community_not_found", "high", [], [{"slug": slug, "comm_num": cns, "matched_by": how}])
    # the build's own boundary.geojson vs the KML polygon: same community, same shape?
    bnd = jload(os.path.join(CITY, slug, "boundary.geojson"))
    bnd_area = kml_area = None
    if bnd and polys:
        try:
            bnd_area = sum(ring_area_m2(pl[0]) for ft in bnd.get("features") or [] for pl in
                           ([ft["geometry"]["coordinates"]] if ft["geometry"]["type"] == "Polygon" else ft["geometry"]["coordinates"]))
            kml_area = sum(ring_area_m2(r) for r in polys)
            if kml_area and abs(bnd_area - kml_area) / kml_area > 0.02:
                flag(flags, "boundary_differs_from_kml", "medium", [], [{"boundary_km2": round(bnd_area / 1e6, 3), "kml_km2": round(kml_area / 1e6, 3)}])
        except Exception as e:
            flag(flags, "boundary_unreadable", "low", [], [{"error": str(e)[:120]}])
    outside, far, implaus, ids, cents = [], [], [], [], []
    for f in B:
        pr = f["properties"]; i = pr.get("i", pr.get("id"))
        ids.append(i)
        c, area = geom_centroid(f["geometry"])
        cents.append((i, c, f))
        if polys and c and not any(pip(c, r) for r in polys):
            d = min(dist_to_ring_m(c, r) for r in polys)
            if d > 25: (far if d > 250 else outside).append({"i": i, "dist_m": round(d)})
        h = num(pr.get("h"))
        if h is None or h <= 0 or h < 2 or h > 830 or (h > 150 and area and area < 60):
            implaus.append({"i": i, "h": pr.get("h"), "hs": pr.get("hs"), "area_m2": round(area or 0)})
    c = Counter(ids); dup = [i for i, k in c.items() if k > 1 and i is not None]
    flag(flags, "outside_community", "medium", [x["i"] for x in outside], sorted(outside, key=lambda x: -x["dist_m"]),
         note="block centroid 25-250 m outside the DM community polygon (KML)")
    flag(flags, "far_outside_community", "high", [x["i"] for x in far], sorted(far, key=lambda x: -x["dist_m"]),
         note="block centroid more than 250 m outside the DM community polygon (KML)")
    flag(flags, "implausible_height", "high", [x["i"] for x in implaus if x["i"] is not None], implaus)
    flag(flags, "duplicate_id", "high", dup)
    # double draw: a city block standing on a twin-district footprint
    dd = []
    bb = meta.get("bbox")
    if B and bb:
        near = ce_polys_near(bb)
        if near:
            tr = STRtree([g for g, _, _ in near])
            for i, cc, f in cents:
                try:
                    g = shape(f["geometry"])
                    if not g.is_valid: g = g.buffer(0)
                except Exception:
                    continue
                for k in tr.query(g):
                    G, s2, j2 = near[int(k)]
                    inter = g.intersection(G).area
                    if inter > 0 and inter / min(g.area, G.area) >= 0.5:
                        dd.append({"i": i, "ce": "%s/b%d" % (s2, j2), "overlap": round(inter / min(g.area, G.area), 2)}); break
    flag(flags, "double_draw_with_twin_district", "high", [x["i"] for x in dd], dd,
         note="city block overlaps a data/ce footprint by >= 50 % of the smaller: both layers would draw it")
    reg = registers()
    dme = [reg["dm"].get(k) for k in cns if reg["dm"].get(k)]
    dm_b = sum(e["buildings"] for e in dme) if dme else None
    dm_p = sum(e["parcels"] for e in dme) if dme else None
    names = [norm((comms.get(k) or {}).get("name")) for k in cns]
    dld_n = sum(v for k, v in reg["dld"].items() if norm(k) in names) if names else 0
    excl = int(meta.get("excluded_in_existing_districts") or 0)
    twin_n = 0
    if slug.endswith("_rest"):                                  # the rest of a community whose main part is a twin district
        tb = jload(os.path.join(CE, slug[:-5], "blocks.json"), {}) or {}
        twin_n = sum(1 for f in tb.get("features") or [] if (f.get("properties") or {}).get("k") == "b")
    nb = len(B) + max(excl, twin_n)                             # the community's buildings, counting those a twin district draws
    if dm_p and nb < 0.5 * dm_p:
        flag(flags, "count_below_dm_parcels", "medium", [], [{"blocks_incl_twin": nb, "dm_parcels": dm_p, "dm_buildings": dm_b}],
             note="fewer than half as many footprints as DM permitted plots: footprints likely missing")
    fps = meta.get("footprint_sources") or {}
    ml = sum(v for k_, v in fps.items() if "microsoft" in k_.lower() or k_.lower().startswith("ml"))
    ml_share = round(ml / max(1, sum(fps.values())), 2) if fps else None
    if dm_b and nb > 3 * dm_b and nb > 50:
        thin = (dm_p or 0) < 100             # free zones / government land are permitted outside DM: the register barely covers them
        flag(flags, "count_above_dm_buildings", "info" if thin else "medium", [],
             [{"blocks_incl_twin": nb, "dm_parcels": dm_p, "dm_buildings": dm_b, "ml_footprint_share": ml_share}],
             note=("DM register covers < 100 plots here (free zone / other permitting authority): count not comparable" if thin else
                   "more than 3x as many footprints as DM permitted buildings: sheds / farm structures / ML detections, or a boundary problem"))
    if not dme and len(B) > 50:
        flag(flags, "no_dm_register_rows", "info", [], [{"comm_num": cns, "blocks": len(B)}])
    # this lane's own city type hints: still aligned with this blocks.json? and the typical_* heights built from them
    th_doc = jload(os.path.join(OUT, "city", "type_hints_%s.json" % slug)) or {}
    th = th_doc.get("types") or {}
    if th_doc and th_doc.get("blocks_buildings") != len(B):
        flag(flags, "type_hints_stale", "medium", [], [{"hints_for_buildings": th_doc.get("blocks_buildings"), "blocks_now": len(B),
                                                         "hints_blocks_mtime": th_doc.get("blocks_mtime")}],
             note="city type hints were keyed to a blocks.json with a different building count: the index i may have shifted; re-run hints")
    typ_mis, pending = [], []
    for f in B:
        pr = f["properties"]; hs_ = str(pr.get("hs") or ""); t = th.get(str(pr.get("i"))) or {}
        if hs_.startswith("typical_") and th and t.get("type") and differs(hs_[len("typical_"):], t.get("type")):
            typ_mis.append({"i": pr.get("i"), "hs": hs_, "type_hint": t.get("type")})
        elif hs_ in ("default12", "unknown") and t.get("type") in ("villa", "townhouse", "warehouse") and t.get("conf") in ("high", "medium"):
            pending.append(pr.get("i"))
    flag(flags, "typical_height_vs_type_hint", "low", [x["i"] for x in typ_mis], typ_mis)
    flag(flags, "type_hint_not_yet_applied", "info", pending,
         note="default 12 m block whose city type hint (medium/high) is villa / townhouse / warehouse")
    needles, flat, tall_other = [], [], []
    for f in B:
        pr = f["properties"]; hs_ = str(pr.get("hs") or "")
        if not hs_.startswith(("community_median", "district_median")): continue
        h = num(pr.get("h")) or 0
        _, area = geom_centroid(f.get("geometry"))
        t = (th.get(str(pr.get("i"))) or {}).get("type")
        if h >= 25 and area < 200:
            needles.append({"i": pr.get("i"), "h": h, "area_m2": round(area), "type_hint": t})
        elif h >= 25 and t == "other":
            tall_other.append({"i": pr.get("i"), "h": h, "area_m2": round(area), "type_hint": t})
        elif h < 9 and t in ("tower", "lowrise_apt", "mall", "school"):
            flat.append({"i": pr.get("i"), "h": h, "area_m2": round(area), "type_hint": t})
    flag(flags, "median_fill_needle", "high", [x["i"] for x in needles], sorted(needles, key=lambda x: x["area_m2"]),
         note="community_median of 25 m+ on a footprint under 200 m2: a shed / kiosk drawn as a tower")
    flag(flags, "median_fill_tall_on_other", "medium", [x["i"] for x in tall_other], sorted(tall_other, key=lambda x: x["area_m2"]))
    flag(flags, "median_fill_flattens_block", "medium", [x["i"] for x in flat], flat)
    hs = Counter(str((f["properties"] or {}).get("hs") or "(none)") for f in B)
    hv = sorted(num(f["properties"].get("h")) or 0 for f in B)
    sev = Counter(f["severity"] for f in flags)
    return {
        "slug": slug, "kind": "city", "qa_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "blocks_file": os.path.relpath(p, ROOT).replace("\\", "/"), "blocks_mtime": datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds"),
        "communities": [{"comm_num": k, "name": (comms.get(k) or {}).get("name")} for k in cns], "community_matched_by": how,
        "counts": {"blocks": len(B), "excluded_in_existing_districts": excl, "twin_district_blocks": twin_n or None, "outside_25_250m": len(outside), "outside_gt250m": len(far),
                   "implausible": len(implaus), "duplicates": len(dup), "double_draw": len(dd),
                   "dm_buildings": dm_b, "dm_parcels": dm_p, "dm_types": dme[0]["types"] if dme else None,
                   "dld_buildings": dld_n or None, "blocks_per_dm_building": round(nb / dm_b, 2) if dm_b else None,
                   "blocks_per_dm_parcel": round(nb / dm_p, 2) if dm_p else None, "blocks_per_dld_building": round(nb / dld_n, 2) if dld_n else None,
                   "ml_footprint_share": ml_share, "median_fill_needles": len(needles), "median_fill_tall_on_other": len(tall_other), "median_fill_flat": len(flat), "type_hints": bool(th), "type_hint_not_yet_applied": len(pending),
                   "typical_heights": sum(1 for f in B if str(f["properties"].get("hs") or "").startswith("typical_")), "median_h": hv[len(hv) // 2] if hv else None, "boundary_km2": round(bnd_area / 1e6, 3) if bnd_area else None},
        "height_sources": dict(hs.most_common()), "flags": flags,
        "status": "FAIL" if sev.get("high") else "WARN" if sev.get("medium") else "OK",
    }


# ------------------------------------------------------------------ passes + summary
def targets():
    t = []
    if os.path.isdir(CE):
        t += [("ce", s, os.path.join(CE, s, "blocks.json")) for s in sorted(os.listdir(CE)) if os.path.exists(os.path.join(CE, s, "blocks.json"))]
    if os.path.isdir(CITY):
        t += [("city", s, os.path.join(CITY, s, "blocks.json")) for s in sorted(os.listdir(CITY)) if os.path.exists(os.path.join(CITY, s, "blocks.json"))]
    return t


def one_pass(force=False, log=print):
    st = jload(STATE, {}) or {}
    changed = []
    for kind, slug, p in targets():
        key = "%s/%s" % (kind, slug)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        thp = os.path.join(OUT, "type_hints_%s.json" % slug) if kind == "ce" else os.path.join(OUT, "city", "type_hints_%s.json" % slug)
        thm = os.path.getmtime(thp) if os.path.exists(thp) else None
        if not force and st.get(key, {}).get("mtime") == mt and st.get(key, {}).get("th_mtime") == thm                 and os.path.exists(os.path.join(OUT, "qa_%s%s.json" % ("city_" if kind == "city" else "", slug))):
            continue
        if time.time() - mt < 20:                     # still being written: next pass
            continue
        try:
            r = qa_ce(slug, log) if kind == "ce" else qa_city(slug, log)
        except Exception as e:
            traceback.print_exc()
            r = {"slug": slug, "kind": kind, "status": "QA-ERROR", "error": str(e)[:300], "flags": []}
        if os.path.getmtime(p) != mt:                 # rewritten under us: retry next pass
            continue
        jdump(r, os.path.join(OUT, "qa_%s%s.json" % ("city_" if kind == "city" else "", slug)), indent=1)
        prev = st.get(key, {})
        st[key] = {"mtime": mt, "th_mtime": thm, "qa_at": time.time(), "status": r.get("status"), "runs": prev.get("runs", 0) + 1}
        if prev.get("mtime") != mt:                   # a new blocks.json (not just new type hints) resets the 30 min stability clock
            changed.append((key, r.get("status")))
        log("  QA %-34s %s %s" % (key, r.get("status"), json.dumps({k: v for k, v in (r.get("counts") or {}).items()
                                                                  if k in ("blocks", "footprints", "missing", "extra", "tower_at_12m", "height_diff_gt20pct", "outside_gt250m")})))
    st["_last_pass"] = time.time()
    if changed: st["_last_change"] = time.time()
    jdump(st, STATE, indent=1)
    write_summary(st)
    return changed


def write_summary(st):
    head = open(HEAD, encoding="utf-8").read().rstrip() + "\n\n" if os.path.exists(HEAD) else ""
    rows_ce, rows_city = [], []
    for kind, slug, p in targets():
        r = jload(os.path.join(OUT, "qa_%s%s.json" % ("city_" if kind == "city" else "", slug)))
        if not r: continue
        c = r.get("counts") or {}
        if kind == "ce":
            hs_ = r.get("height_sources") or {}
            unk = sum(v for k_, v in hs_.items() if k_ in ("unknown", "default12", "(none)"))
            rows_ce.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s / %s | %s | %s |" % (
                slug, c.get("blocks", "-"), c.get("footprints", "-"), c.get("missing", "-"), c.get("extra", "-"),
                "%s%s (+%s soft)" % (c.get("tower_at_12m", "-"), (" [%d in register_lifts]" % c["tower_at_12m_explained_by_register_lifts"])
                                     if c.get("tower_at_12m_explained_by_register_lifts") else "", c.get("tower_at_12m_soft", 0)),
                c.get("height_diff_gt20pct", "-"), c.get("id_geometry_mismatch", "-"),
                "%s / %s" % (c.get("median_fill_needles", "-"), c.get("median_fill_flat", "-")),
                unk, c.get("typical_heights", "-"), c.get("type_hint_not_yet_applied", "-"),
                (r.get("blocks_mtime") or "")[5:16].replace("T", " "), r.get("status")))
        else:
            hs_ = r.get("height_sources") or {}
            dflt = sum(v for k_, v in hs_.items() if k_ in ("default12", "unknown"))
            rows_city.append("| %s | %s | %s | %s / %s | %s | %s / %s | %s | %s | %s | %s%% | %s / %s | %s |" % (
                slug, c.get("blocks", "-"), ", ".join("%s %s" % (x["comm_num"], x["name"]) for x in r.get("communities") or []) or "?",
                c.get("dm_parcels", "-"), c.get("dm_buildings", "-"), c.get("dld_buildings", "-"), c.get("outside_25_250m", "-"),
                c.get("outside_gt250m", "-"), c.get("double_draw", "-"), c.get("implausible", "-"),
                "%s / %s" % (c.get("median_fill_needles", "-"), c.get("median_fill_flat", "-")),
                round(100.0 * dflt / c["blocks"]) if c.get("blocks") else "-",
                ("yes" if c.get("type_hints") else "not yet"), c.get("type_hint_not_yet_applied", "-"), r.get("status")))
    tot = Counter()
    for kind, slug, p in targets():
        r = jload(os.path.join(OUT, "qa_%s%s.json" % ("city_" if kind == "city" else "", slug))) or {}
        tot[r.get("status")] += 1
    txt = head + "## Rolling QA table (scripts/lab_blocks_qa.py)\n\nLast pass %s. Status counts: %s. Per-district detail with ids: `qa_<slug>.json` " \
        "(city districts: `qa_city_<slug>.json`). FAIL = any high-severity flag (missing/extra/duplicate/shifted ids, a measured-tall " \
        "building at 12 m, implausible height, a city block outside its community or double-drawn with a twin district); WARN = " \
        "medium only (>20 %% height differences vs a real bldgfacts height, name-only 12 m towers, not-in-twin ids, register-count " \
        "outliers). The ids and details are in the per-district JSON.\n\n" % (
            datetime.datetime.fromtimestamp(st.get("_last_pass", time.time())).strftime("%Y-%m-%d %H:%M"), dict(tot))
    txt += "### Twin districts (data/ce/<slug>/blocks.json)\n\n| district | blocks | footprints | missing | extra | 12 m-towers (any tall building drawn < 20 m) | >20% height diffs (vs bldgfacts) | id/geometry shifts | median-fill needles / flattened | 12 m unknown / typical_* / hint not yet applied | blocks mtime | status |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    txt += "\n".join(rows_ce) + "\n"
    txt += "\n### Beyond-51 districts (data/blocks_city/<slug>/blocks.json)\n\n"
    if rows_city:
        txt += ("Register counts are sanity bands, not truth: DM rows are permits (a villa plot carries several), DM parcels undercount "
                "multi-building plots, DLD areas are matched by name. A `_rest` slug is compared together with its twin district.\n\n"
                "| district | blocks | DM community | DM parcels / building rows | DLD buildings | outside 25-250 m / >250 m | double-draw with twin | implausible h | median-fill needles / flattened | 12 m default | type hints / hint not yet applied | status |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows_city) + "\n")
    else:
        txt += "None on disk yet (data/blocks_city/ %s).\n" % ("exists, empty" if os.path.isdir(CITY) else "does not exist")
    # one machine-readable list for the heights agent: every twin block at 12 m that a measured / registered source says is tall
    t12 = []
    for kind, slug, p in targets():
        if kind != "ce": continue
        r = jload(os.path.join(OUT, "qa_%s.json" % slug)) or {}
        for f in r.get("flags") or []:
            if f.get("check") in ("tower_at_12m", "tower_at_12m_soft"):
                for d in f.get("detail") or []:
                    t12.append({"slug": slug, "i": d["i"], "strength": "measured" if f["check"] == "tower_at_12m" else "name/type only",
                                "why": d.get("why"), "name": d.get("name"), "hs": d.get("hs"), "register_lift_m": d.get("register_lift_m"),
                                "blocks_mtime": r.get("blocks_mtime")})
    jdump({"generated": datetime.datetime.now().isoformat(timespec="seconds"), "research_only": True,
           "what": "twin blocks drawn under 20 m (12 m placeholder, community median or typical_*) where bldgfacts / live twin / DLD register storeys / heights_register (or only a name / "
                   "type hint: strength 'name/type only') say 20 m+ or 6+ storeys. Detail capped at 60 per district per check; full ids "
                   "in qa_<slug>.json.", "n": len(t12), "rows": t12}, os.path.join(OUT, "QA_TOWERS_AT_12M.json"), indent=1)
    # and one for the median-fill needles: every block a district-wide median raised to 25 m+ on a footprint under 200 m2
    nd = {}
    for kind, slug, p in targets():
        r = jload(os.path.join(OUT, "qa_%s%s.json" % ("city_" if kind == "city" else "", slug))) or {}
        for f in r.get("flags") or []:
            if f.get("check") == "median_fill_needle":
                nd["%s/%s" % (kind, slug)] = {"n": f.get("n"), "ids": f.get("ids"), "examples": (f.get("detail") or [])[:5],
                                              "blocks_mtime": r.get("blocks_mtime")}
    jdump({"generated": datetime.datetime.now().isoformat(timespec="seconds"), "research_only": True,
           "what": "blocks whose hs is community_median and h >= 25 m on a footprint under 200 m2 (guardhouses, kiosks, sheds drawn as "
                   "towers). Key = kind/slug; ids = block i.", "n": sum(v["n"] or 0 for v in nd.values()), "districts": nd},
          os.path.join(OUT, "QA_MEDIAN_NEEDLES.json"), indent=1)
    tmp = SUMMARY + ".tmp"
    open(tmp, "w", encoding="utf-8").write(txt)
    os.replace(tmp, SUMMARY)


def main():
    force = "--force" in sys.argv
    if "--loop" not in sys.argv:
        one_pass(force); return
    t0 = time.time()
    one_pass(force)
    while time.time() - t0 < MAX_S:
        time.sleep(POLL_S)
        ch = one_pass(False, log=lambda x: print(x, flush=True))
        st = jload(STATE, {}) or {}
        done = all(("%s/%s" % (k, s)) in st for k, s, _ in targets())
        quiet = time.time() - st.get("_last_change", t0) >= STABLE_S
        print("%s pass: %d re-QA'd, all QA'd=%s, quiet=%s" % (datetime.datetime.now().strftime("%H:%M"), len(ch), done, quiet), flush=True)
        city_seen = os.path.isdir(CITY) and any(k == "city" for k, _, _ in targets())
        if done and quiet and os.path.exists(os.path.join(OUT, "_typehints_done")) and os.path.exists(os.path.join(OUT, "_city_hints_done")) and city_seen:
            print("stable for 30 min - stopping", flush=True); break


if __name__ == "__main__":
    main()

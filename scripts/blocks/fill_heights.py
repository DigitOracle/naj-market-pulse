"""Write data/ce/<slug>/blocks_heights.json for every district: better-than-default heights per footprint index.

Scratchpad script (not in the repo). Run: python fill_heights.py [slug ...]
"""
import csv, json, os, re, sys, glob, collections
import duckdb
from shapely import wkb as swkb
from shapely.geometry import shape, Point
from shapely.strtree import STRtree
from shapely.ops import transform
from shapely.validation import make_valid
from pyproj import Transformer

ROOT = r"C:\Dev\naj-market-pulse"
DATA = os.path.join(ROOT, "data")
HERE = os.path.dirname(os.path.abspath(__file__))
TO = Transformer.from_crs(4326, 32640, always_xy=True).transform
DEFAULT_H = 12.0
TALL_OK = {"burjkhalifa", "dubaimarina"}
TYPICAL = {"villa": 8.0, "townhouse": 8.0, "warehouse": 10.0}


def floors_to_m(n, rule_prefix):
    n = int(n)
    if n <= 3:
        return round(n * 3.5, 1), "%s*3.5" % rule_prefix
    return round(n * 3.4 + 4, 1), "%s*3.4+4" % rule_prefix


def pnum(v):
    if v is None:
        return None
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", str(v).replace(",", "."))
    return float(m.group(1)) if m else None


def fix(g):
    if not g.is_valid:
        g = make_valid(g)
    return g


# ---------- global sources ----------
def load_overture():
    c = duckdb.connect()
    out = []
    for fn, kind in (("ov_buildings.parquet", "b"), ("ov_parts.parquet", "p")):
        rows = c.sql("select id, height, num_floors, ST_AsWKB(geometry) from '%s' where height is not null or num_floors is not null"
                     % os.path.join(HERE, fn).replace("\\", "/")).fetchall()
        for gid, h, nf, wk in rows:
            try:
                g = fix(transform(TO, swkb.loads(bytes(wk))))
            except Exception:
                continue
            if g.is_empty or g.area <= 0:
                continue
            out.append((kind, gid, h, nf, g))
    return out


def load_osm():
    d = json.load(open(os.path.join(HERE, "osm_heights.json"), encoding="utf-8"))
    out = []
    from shapely.geometry import Polygon
    for e in d["elements"]:
        t = e.get("tags") or {}
        h, lv = pnum(t.get("height")), pnum(t.get("building:levels"))
        if not h and not lv:
            continue
        polys = []
        if e["type"] == "way" and e.get("geometry"):
            pts = [TO(p["lon"], p["lat"]) for p in e["geometry"]]
            if len(pts) >= 4:
                polys.append(Polygon(pts))
        elif e["type"] == "relation":
            for m in e.get("members") or []:
                if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) >= 4:
                    polys.append(Polygon([TO(p["lon"], p["lat"]) for p in m["geometry"]]))
        for pg in polys:
            try:
                pg = fix(pg)
            except Exception:
                continue
            if pg.is_empty or pg.area <= 0:
                continue
            kind = "p" if "building:part" in t and "building" not in t else "b"
            out.append((kind, "%s/%s" % (e["type"], e["id"]), h, int(lv) if lv else None, pg))
    return out


def load_dm(ids):
    csv.field_size_limit(10 ** 8)
    res = {}
    for fn in glob.glob(os.path.join(DATA, "raw_downloads", "building_summary_information_2026-08-31_*.csv")):
        for row in csv.DictReader(open(fn, encoding="utf-8")):
            bid = row.get("building_id")
            if bid not in ids:
                continue
            h = pnum(row.get("building_height")) or 0.0
            tf = pnum(row.get("typical_floors_count"))
            fl = row.get("building_floor_height") or ""
            cur = res.setdefault(bid, {"h": 0.0, "tf": None, "fl": fl, "status": row.get("building_status_english")})
            if h > cur["h"]:
                cur["h"], cur["fl"] = h, fl
            if tf and (cur["tf"] or 0) < tf:
                cur["tf"] = tf
    return res


def storeys_from_floorstring(s):
    # "1B+  G  +10  +1P  +1R" -> above-ground storeys: G + M + typical + P (podium) ; roof excluded
    if not s or "G" not in s:
        return None
    n = 1
    for num, tag in re.findall(r"\+\s*(\d*)\s*([A-Za-z]*)", s):
        k = int(num) if num else 1
        tag = tag.upper()
        if tag in ("", "M", "P", "F"):
            n += k
    return n


def match(fp, tree, items, area_fp):
    """Return list of (kind, id, h, nf, iou, how) matches for one footprint polygon."""
    out = []
    c_fp = fp.representative_point()
    for j in tree.query(fp):
        kind, gid, h, nf, g = items[j]
        try:
            inter = fp.intersection(g).area
        except Exception:
            continue
        if inter <= 0:
            continue
        union = area_fp + g.area - inter
        iou = inter / union if union > 0 else 0
        how = None
        if iou >= 0.3:
            how = "iou%.2f" % iou
        elif kind == "p" and g.representative_point().within(fp):
            how = "part_in"
        elif g.representative_point().within(fp) and g.area >= 0.3 * area_fp:
            how = "centroid_in"
        elif c_fp.within(g) and g.area <= 3.0 * area_fp:
            how = "fp_centroid_in"
        if how:
            out.append((kind, gid, h, nf, iou, how))
    return out


def best(ms, field):
    """Pick a value: building-part max height (towers) else the highest-IoU building."""
    if field == "h":
        parts = [m for m in ms if m[0] == "p" and m[2]]
        blds = sorted([m for m in ms if m[0] == "b" and m[2]], key=lambda m: -m[4])
        if parts:
            pm = max(parts, key=lambda m: m[2])
            if not blds or pm[2] >= blds[0][2]:
                return pm[2], pm
        return (blds[0][2], blds[0]) if blds else (None, None)
    parts = [m for m in ms if m[0] == "p" and m[3]]
    blds = sorted([m for m in ms if m[0] == "b" and m[3]], key=lambda m: -m[4])
    if parts:
        pm = max(parts, key=lambda m: m[3])
        if not blds or pm[3] >= blds[0][3]:
            return pm[3], pm
    return (blds[0][3], blds[0]) if blds else (None, None)


def lj(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def run(slugs, OV, OSM):
    ov_tree = STRtree([x[4] for x in OV]); osm_tree = STRtree([x[4] for x in OSM])
    REG = lj(os.path.join(DATA, "identity", "official", "dld", "reg_bindings.json"), {}) or {}
    # DM ids across all stacks
    stacks = {s: (lj(os.path.join(DATA, "board", "stack_%s.json" % s), {}) or {}).get("buildings_by_id", {}) for s in slugs}
    ids = {str(v.get("dm")) for st in stacks.values() for v in st.values() if v.get("dm")}
    DM = load_dm(ids)
    report = []
    review = {}
    for slug in slugs:
        gp = os.path.join(DATA, "ce", slug, "buildings.geojson")
        feats = json.load(open(gp, encoding="utf-8"))["features"]
        anch = lj(os.path.join(DATA, "names", "anchors_%s.json" % slug), {}) or {}
        fps_h = {r[0]: r[3] for r in (anch.get("fps") or []) if len(r) > 3 and r[3]}
        by_i = {}
        for a in anch.get("anchors") or []:
            if a.get("i") is not None and a["i"] not in by_i:
                by_i[a["i"]] = a
        bf = ((lj(os.path.join(DATA, "board", "bldgfacts_%s.json" % slug), {}) or {}).get("buildings_by_id") or {})
        reg = REG.get(slug, {}) if isinstance(REG.get(slug), dict) else {}
        st = stacks.get(slug, {})
        dm_share = collections.Counter(str(v.get("dm")) for v in st.values() if v.get("dm"))
        rep = {}
        for rp in ("report_v4.csv", "report_v3.csv"):
            p = os.path.join(DATA, "ce", slug, rp)
            if os.path.exists(p):
                for row in csv.DictReader(open(p, encoding="utf-8")):
                    m = re.match(r"b(\d+)_", row.get("shape") or "")
                    if m and row.get("height_m"):
                        rep.setdefault(int(m.group(1)), (float(row["height_m"]), rp[:-4]))
                break
        th = (lj(os.path.join(DATA, "lab", "blocks", "type_hints_%s.json" % slug), {}) or {}).get("types") or {}
        out, outl, cnt, rev = {}, [], collections.Counter(), []
        n = before12 = after12 = 0
        for i, f in enumerate(feats):
            geom = f.get("geometry")
            if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            n += 1
            a = by_i.get(i) or {}
            bh = (f.get("properties") or {}).get("bHeight")
            bfh = (bf.get(str(i)) or {}).get("height_m")
            try:
                bfh = float(bfh) if bfh else None
            except (TypeError, ValueError):
                bfh = None
            # the build_blocks.py chain (without the overlay): bldgfacts, anchor, fps, bHeight, 12
            if bfh and bfh > 0:
                cur, cur_src = bfh, "bldgfacts"
            elif a.get("h"):
                cur, cur_src = float(a["h"]), "anchor"
            elif fps_h.get(i):
                cur, cur_src = float(fps_h[i]), "fps"
            elif bh:
                cur, cur_src = float(bh), "bHeight"
            else:
                cur, cur_src = DEFAULT_H, "default"
            is12 = abs(cur - DEFAULT_H) < 0.05
            if is12:
                before12 += 1
            # which footprints may be replaced
            anc_h = float(a["h"]) if a.get("h") else None
            # the twin's own roof height is never lowered: any non-12 anchor height protects the footprint
            protected = (cur_src == "anchor" and not is12) or (anc_h is not None and abs(anc_h - DEFAULT_H) > 0.05)
            suspect_low = (not protected) and (not is12) and cur < 20 and cur_src in ("fps", "bHeight")
            try:
                fp = fix(transform(TO, shape(geom)))
            except Exception:
                fp = None
            afp = fp.area if fp is not None else 0.0
            if protected and is12 and afp and afp < 150 and anc_h > 30:
                outl.append({"i": i, "h": anc_h, "src": "anchor", "why": "%.0f m on a %.0f m2 footprint - binding suspect, skipped" % (anc_h, afp)})
                after12 += 1
                continue
            if protected and is12:
                # bldgfacts' 12 m placeholder would hide the twin's own non-12 roof height: carry the anchor height
                out[str(i)] = {"h": round(anc_h, 1), "src": "anchor_twin (over bldgfacts 12 m placeholder)"}
                cnt["anchor_twin"] += 1
                continue
            if protected or (not is12 and not suspect_low):
                continue
            if fp is None:
                if is12: after12 += 1
                continue
            cands = []   # (h, src, measured?)
            b = bf.get(str(i)) or {}
            bh_m = b.get("height_m")
            if bh_m and abs(float(bh_m) - DEFAULT_H) > 0.05 and abs(float(bh_m) - cur) > 0.05:
                cands.append((float(bh_m), "bldgfacts:%s" % (b.get("facts_source") or "?"), True))
            om = match(fp, ov_tree, OV, afp) if afp > 0 else []
            sm = match(fp, osm_tree, OSM, afp) if afp > 0 else []
            h, m = best(om, "h")
            if h: cands.append((float(h), "overture_height(%s)" % m[5], True))
            h, m = best(sm, "h")
            if h: cands.append((float(h), "osm_height(%s)" % m[5], True))
            dmid = str((st.get(str(i)) or {}).get("dm") or "")
            d = DM.get(dmid) if dmid else None
            shared = dm_share.get(dmid, 0) if dmid else 0
            shtag = "(plot record shared by %d footprints)" % shared if shared > 1 else ""
            if d and d["h"] > 0:
                cands.append((float(d["h"]), "dm_permit_height" + shtag, True))
            nf, m = best(om, "nf")
            if nf:
                hh, rule = floors_to_m(nf, "overture_floors"); cands.append((hh, rule, False))
            nf, m = best(sm, "nf")
            if nf:
                hh, rule = floors_to_m(nf, "osm_levels"); cands.append((hh, rule, False))
            r = reg.get(str(i))
            if r:
                fl = r.get("floors") or r.get("floors_max")
                if fl:
                    hh, rule = floors_to_m(int(float(fl)), "dld_floors"); cands.append((hh, rule, False))
            if d:
                sf = storeys_from_floorstring(d["fl"])
                if sf:
                    hh, rule = floors_to_m(sf, "dm_storeys"); cands.append((hh, rule + shtag, False))
            if i in rep and abs(rep[i][0] - DEFAULT_H) > 0.05 and abs(rep[i][0] - cur) > 0.05:
                cands.append((rep[i][0], "ce_%s_massed" % rep[i][1], False))
            chosen = None
            for hh, src, meas in cands:
                if hh < 3.0:
                    outl.append({"i": i, "h": hh, "src": src, "why": "under 3 m - skipped"}); continue
                if hh > 450 and slug not in TALL_OK:
                    outl.append({"i": i, "h": hh, "src": src, "why": "over 450 m outside Burj Khalifa/Marina - skipped"}); continue
                if hh > 30 and afp < 150:
                    outl.append({"i": i, "h": hh, "src": src, "why": "%.0f m on a %.0f m2 footprint - skipped" % (hh, afp)}); continue
                chosen = (hh, src, meas); break
            if suspect_low:
                # only override a non-12 bHeight/fps when a MEASURED/recorded source says it is clearly taller
                if not chosen or chosen[1].startswith(("ce_", "typical")):
                    continue
                if not (chosen[0] >= 2 * cur and chosen[0] >= 25):
                    continue
                out[str(i)] = {"h": round(chosen[0], 1), "src": chosen[1] + "; replaces %s %.1f" % (cur_src, cur)}
                cnt[chosen[1].split("(")[0].split(":")[0] + "*"] += 1
                continue
            if not chosen:
                t = th.get(str(i)) or {}
                if t.get("conf") in ("medium", "high"):
                    if t.get("type") in TYPICAL:
                        chosen = (TYPICAL[t["type"]], "typical_%s" % t["type"], False)
                    elif t.get("type") == "tower":
                        rev.append(i)
            if chosen:
                out[str(i)] = {"h": round(chosen[0], 1), "src": chosen[1]}
                cnt[chosen[1].split("(")[0].split(":")[0]] += 1
            else:
                after12 += 1
        # footprints at 12 before that stay 12: those not in candidates path are counted above
        p = os.path.join(DATA, "ce", slug, "blocks_heights.json")
        json.dump(dict(sorted(out.items(), key=lambda kv: int(kv[0]))), open(p, "w", encoding="utf-8"), separators=(",", ":"))
        tall = [(k, v["h"]) for k, v in out.items() if v["h"] > 300]
        report.append({"slug": slug, "n": n, "before12": before12, "after12": after12, "written": len(out),
                       "sources": dict(cnt.most_common()), "outliers": outl, "towers_for_review": rev, "over300": tall})
        print("%-26s n=%5d  12m %5d (%3.0f%%) -> %5d (%3.0f%%)  wrote %5d  %s  outl=%d" % (
            slug, n, before12, 100.0 * before12 / max(n, 1), after12, 100.0 * after12 / max(n, 1), len(out), dict(cnt.most_common()), len(outl)))
    json.dump(report, open(os.path.join(HERE, "report.json"), "w"), indent=1)


if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(s for s in os.listdir(os.path.join(DATA, "ce")) if os.path.exists(os.path.join(DATA, "ce", s, "buildings.geojson")))
    OV = load_overture(); OSM = load_osm()
    print("overture items", len(OV), "osm items", len(OSM))
    run(slugs, OV, OSM)

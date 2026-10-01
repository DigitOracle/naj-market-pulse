"""Stage 2: write the height overlays from stage 1 (links.pkl). Scratch script.

  python hts_write.py city     -> data/blocks_city/<slug>/heights_overlay.json (replaces this script's own file each run)
  python hts_write.py ce       -> MERGES into data/ce/<slug>/blocks_heights.json (run fill_heights.py first; this is last)

Order per footprint (only where the footprint has no measured height; a measured one is never overwritten):
  1. register height (DM building_height, else DM storeys / DLD floors formula) -> src "register_<how>"
  2. city only: type hints (data/lab/blocks/city/type_hints_<slug>.json), villa/townhouse 8 m, warehouse 10 m,
     conf medium/high only -> src "typical_<type>" (ce: fill_heights.py already writes these)
  3. community median of the DM register (dm_register_check.median_h) -> src "community_median", ONLY where the type
     hints (when the district has them) do not call the footprint villa, townhouse or warehouse.
Flags: > 450 m outside Downtown (burjkhalifa) and Marina, and < 3 m, are left out and listed.
"""
import json, os, sys, glob, pickle, subprocess, collections, statistics, datetime
sys.stdout.reconfigure(encoding="utf-8")
REPO = r"C:\Dev\naj-market-pulse"
D = os.path.join(REPO, "data")
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "city_cache")
PLACEHOLDER = {"unknown", "default12"}
TALL_OK = ("burjkhalifa", "dubaimarina", "marsadubai")
LOWTYPES = {"villa", "townhouse", "warehouse"}
TYP_H = {"villa": 8.0, "townhouse": 8.0, "warehouse": 10.0}
MEASURED_THEIRS = ("overture_height", "osm_height", "dm_permit_height")  # their measured sources
NOW = datetime.datetime.now().isoformat(timespec="seconds")

S = pickle.load(open(os.path.join(HERE, "links.pkl"), "rb"))
LINKS, FPM = S["links"], S["fps_meta"]
DMREG = json.load(open(os.path.join(CACHE, "dm_register_stats.json"), encoding="utf-8"))
LL_CITY = collections.defaultdict(dict)
for _f in FPM:
    if _f["set"] == "city":
        LL_CITY[_f["slug"]][_f["i"]] = _f["ll"]
COMM_OF = {(f["set"], f["slug"], f["i"]): f.get("comm") for f in FPM}


def reg_src(src):
    base = src.split("(")[0]
    tail = src[len(base):]
    return "register_" + base.replace("dm_building_height", "dm_height") + tail


def is_measured_mine(src):
    return src.startswith("dm_building_height")


def nudge(h):
    # build_blocks.py treats exactly 12.0 with no levels as the placeholder; a real 12.0 is written as 12.01
    return 12.01 if abs(h - 12.0) < 1e-9 else h


def flag(h, slug):
    if h < 3:
        return "under_3m"
    if h > 450 and not any(t in slug for t in TALL_OK):
        return "over_450m_outside_downtown_marina"
    return None


def load_hints(path):
    if not os.path.exists(path):
        return None
    try:
        d = json.load(open(path, encoding="utf-8"))
        return {int(k): v for k, v in (d.get("types") or {}).items()}
    except Exception:
        return None


def median_for(comm):
    r = DMREG.get(str(comm)) if comm is not None else None
    return (r or {}).get("median_h"), (r or {}).get("with_height")


def by_slug(setname):
    m = collections.defaultdict(list)
    for l in LINKS:
        if l["set"] == setname and l["h"] is not None:
            m[l["slug"]].append(l)
    return m


# ------------------------------------------------------------------ city
def run_city():
    reg = by_slug("city")
    rep = {"generated": NOW, "communities": {}, "flags": [], "sample": []}
    tot = collections.Counter()
    for p in sorted(glob.glob(os.path.join(D, "blocks_city", "*", "blocks.json"))):
        slug = os.path.basename(os.path.dirname(p))
        fc = json.load(open(p, encoding="utf-8"))
        meta = json.load(open(os.path.join(os.path.dirname(p), "meta.json"), encoding="utf-8"))
        med = (meta.get("dm_register_check") or {}).get("median_h")
        hints = load_hints(os.path.join(D, "lab", "blocks", "city", "type_hints_%s.json" % meta.get("dm_slug", slug))) or \
            load_hints(os.path.join(D, "lab", "blocks", "city", "type_hints_%s.json" % slug))
        cur = {}
        cen = {}
        for f in fc["features"]:
            pr = f["properties"]
            if pr.get("k") != "b":
                continue
            # the builder's own height, before any overlay (an earlier overlay run is undone by its hs prefix)
            cur[pr["i"]] = (pr["h"], pr["hs"])
        ov = {}
        c = collections.Counter()
        base_hs = {}
        # the pre-overlay source: hs values written from an overlay are register_/typical_hint/community_median
        prev_ov_p = os.path.join(os.path.dirname(p), "heights_overlay.json")
        prev_ov = json.load(open(prev_ov_p, encoding="utf-8")) if os.path.exists(prev_ov_p) else {}
        for i, (h, hs) in cur.items():
            if str(i) in prev_ov and hs == prev_ov[str(i)].get("src"):
                hs = prev_ov[str(i)].get("base_hs", "default12")
            base_hs[i] = hs
        ll = LL_CITY.get(slug, {})
        # 1. register
        for l in reg.get(slug, []):
            i = l["i"]
            b = base_hs.get(i)
            if b is None or not (b in PLACEHOLDER or b.startswith("typical_")):
                c["register_not_needed_measured"] += 1
                continue
            fl = flag(l["h"], slug)
            if fl:
                rep["flags"].append({"set": "city", "slug": slug, "i": i, "h": l["h"], "src": l["src"], "flag": fl, "parcel": l["parcel"]})
                c["flagged"] += 1
                continue
            ov[i] = {"h": round(nudge(l["h"]), 2), "src": reg_src(l["src"]), "parcel": l["parcel"], "via": l["via"], "base_hs": b}
            c["register"] += 1
            if len(rep["sample"]) < 400 and (len(rep["sample"]) < 40 or hash((slug, i)) % 7 == 0):
                rep["sample"].append({"set": "city", "slug": slug, "i": i, "ll": [round(v, 6) for v in l["ll"]], "h": ov[i]["h"],
                                      "src": ov[i]["src"], "via": l["via"], "parcel": l["parcel"], "det": l["det"], "was": cur[i]})
        # 2. type hints (medium/high), placeholders only
        if hints:
            for i, b in base_hs.items():
                if i in ov or b not in PLACEHOLDER:
                    continue
                t = hints.get(i) or {}
                if t.get("type") in TYP_H and t.get("conf") in ("medium", "high"):
                    ov[i] = {"h": TYP_H[t["type"]], "src": "typical_" + t["type"], "base_hs": b}
                    c["typical_hint"] += 1
        # 3. community median, placeholders only, never on a villa / townhouse / warehouse hint
        if med:
            for i, b in base_hs.items():
                if i in ov or b not in PLACEHOLDER:
                    continue
                t = (hints or {}).get(i) or {}
                if t.get("type") in LOWTYPES:
                    c["median_skipped_lowtype"] += 1
                    continue
                ov[i] = {"h": round(nudge(float(med)), 2), "src": "community_median", "base_hs": b}
                c["community_median"] += 1
        for i in ov:
            if i in ll:
                ov[i]["c"] = [round(ll[i][0], 6), round(ll[i][1], 6)]
        n = len(cur)
        ph0 = sum(1 for b in base_hs.values() if b in PLACEHOLDER)
        ph_reg = ph0 - sum(1 for i, v in ov.items() if base_hs[i] in PLACEHOLDER and (v["src"].startswith("register_") or v["src"].startswith("typical_")))
        ph_med = ph_reg - c["community_median"]
        rep["communities"][slug] = {"buildings": n, "placeholder_before": ph0, "after_register_and_hints": ph_reg, "after_median": ph_med,
                                    "median_h": med, "hints": bool(hints), **c}
        tot.update(c); tot["buildings"] += n; tot["placeholder_before"] += ph0; tot["after_register_and_hints"] += ph_reg; tot["after_median"] += ph_med
        outp = os.path.join(os.path.dirname(p), "heights_overlay.json")
        json.dump({str(k): ov[k] for k in sorted(ov)}, open(outp + ".tmp", "w", encoding="utf-8"), separators=(",", ":"))
        os.replace(outp + ".tmp", outp)
    rep["totals"] = dict(tot)
    json.dump(rep, open(os.path.join(HERE, "city_write_report.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(rep["totals"], indent=1))


# ------------------------------------------------------------------ ce
def rank_theirs(src):
    s = src or ""
    if s.startswith("typical_"):
        return 0
    if s.startswith("overture_height") or s.startswith("osm_height"):
        return 3
    if s.startswith("dm_permit_height"):
        return 2 if "shared by" in s else 3
    if s.startswith("anchor"):
        return 2
    return 1  # floors formulas


def run_ce():
    reg = by_slug("ce")
    pre = os.path.join(HERE, "pre_merge_ce")
    os.makedirs(pre, exist_ok=True)
    rep = {"generated": NOW, "districts": {}, "flags": [], "review": [], "sample": [], "measured_conflicts": []}
    tot = collections.Counter()
    slugs = sorted(s for s in os.listdir(os.path.join(D, "ce")) if not s.startswith("_") and os.path.exists(os.path.join(D, "ce", s, "buildings.geojson")))
    for slug in slugs:
        ovp = os.path.join(D, "ce", slug, "blocks_heights.json")
        theirs = json.load(open(ovp, encoding="utf-8")) if os.path.exists(ovp) else {}
        # an earlier run of this script leaves register_/community_median entries: drop them, recompute from scratch
        theirs = {k: v for k, v in theirs.items() if not str((v or {}).get("src", "")).startswith(("register_", "community_median"))}
        # current state WITHOUT my entries: build to scratch with their overlay only (build reads the file on disk,
        # so write their-only overlay first if mine were in it)
        disk = json.load(open(ovp, encoding="utf-8")) if os.path.exists(ovp) else {}
        if disk != theirs and os.path.exists(ovp) and "--dry" not in sys.argv:
            json.dump(theirs, open(ovp, "w", encoding="utf-8"), separators=(",", ":"))
        outp = os.path.join(pre, slug + ".json")
        subprocess.run([sys.executable, os.path.join(REPO, "scripts", "build_blocks.py"), slug, "--out", outp], check=True,
                       capture_output=True)
        fc = json.load(open(outp, encoding="utf-8"))
        cur = {f["properties"]["i"]: (f["properties"]["h"], f["properties"]["hs"]) for f in fc["features"] if f["properties"].get("k") == "b"}
        hints = load_hints(os.path.join(D, "lab", "blocks", "type_hints_%s.json" % slug))
        merged = dict(theirs)
        c = collections.Counter()
        for l in reg.get(slug, []):
            i = l["i"]
            k = str(i)
            if i not in cur:
                continue
            h0, hs0 = cur[i]
            fl = flag(l["h"], slug)
            if fl:
                rep["flags"].append({"set": "ce", "slug": slug, "i": i, "h": l["h"], "src": l["src"], "flag": fl, "parcel": l["parcel"], "name": l["n"] or l["reg_name"]})
                c["flagged"] += 1
                continue
            mine = {"h": round(nudge(l["h"]), 2), "src": reg_src(l["src"])}
            if k in theirs:
                t = theirs[k]
                if str(t.get("src", "")).startswith("typical_"):
                    merged[k] = mine; c["register_over_typical"] += 1
                else:
                    th = float(t.get("h") or 0)
                    diff = abs(mine["h"] - th) / max(th, 1e-6)
                    if is_measured_mine(l["src"]) and diff > 0.20:
                        if 3 > rank_theirs(t.get("src")):
                            merged[k] = mine; c["register_over_theirs_review"] += 1; kept = "register"
                        else:
                            c["theirs_kept_review"] += 1; kept = "theirs"
                        rep["review"].append({"slug": slug, "i": i, "name": l["n"] or l["reg_name"], "theirs": t, "register": mine,
                                              "diff_pct": round(100 * diff), "kept": kept, "parcel": l["parcel"]})
                    else:
                        c["theirs_kept"] += 1
            elif hs0 in PLACEHOLDER:
                merged[k] = mine; c["register_on_placeholder"] += 1
            else:
                c["not_written_measured"] += 1
                diff = abs(mine["h"] - h0) / max(h0, 1e-6)
                if diff > 0.2:
                    rep["measured_conflicts"].append({"slug": slug, "i": i, "name": l["n"] or l["reg_name"], "current": [h0, hs0],
                                                      "register": mine, "diff_pct": round(100 * diff), "parcel": l["parcel"]})
            if k in merged and merged[k] is mine and len(rep["sample"]) < 400 and (len(rep["sample"]) < 40 or hash((slug, i)) % 5 == 0):
                rep["sample"].append({"set": "ce", "slug": slug, "i": i, "name": l["n"] or l["reg_name"], "ll": [round(v, 6) for v in l["ll"]],
                                      "h": mine["h"], "src": mine["src"], "via": l["via"], "parcel": l["parcel"], "det": l["det"], "was": [h0, hs0]})
        # register lifts (data/lab/blocks/register_lifts_<slug>.json): the heights register the twin already shows while
        # bldgfacts still says 12 m; they win over no entry, typical_*, and the register entries written above
        lp = os.path.join(D, "lab", "blocks", "register_lifts_%s.json" % slug)
        if os.path.exists(lp):
            from shapely.geometry import shape as _shape
            from shapely.ops import transform as _tr
            import pyproj as _pp
            _to = _pp.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
            gj = json.load(open(os.path.join(D, "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]
            for k2, v in (json.load(open(lp, encoding="utf-8")).get("lifts") or {}).items():
                hv = float(v.get("height_m") or 0)
                if hv <= 0:
                    continue
                ex = merged.get(k2)
                exs = str((ex or {}).get("src", ""))
                if ex and not exs.startswith(("typical_", "register_")):
                    c["lift_theirs_kept"] += 1
                    rep["review"].append({"slug": slug, "i": int(k2), "theirs": ex, "lift": hv, "kept": "theirs"})
                    continue
                if ex and exs.startswith("register_") and abs(float(ex["h"]) - hv) / hv > 0.2:
                    rep["review"].append({"slug": slug, "i": int(k2), "register": ex, "lift": hv, "kept": "lift"})
                merged[k2] = {"h": round(nudge(hv), 2), "src": "register_lift"}
                c["register_lift"] += 1
                try:
                    area = _tr(_to, _shape(gj[int(k2)]["geometry"])).area
                except Exception:
                    area = None
                rep.setdefault("lifts", []).append({"slug": slug, "i": int(k2), "h": hv, "footprint_m2": round(area or 0, 1),
                                                    "under_150m2": bool(area is not None and area < 150), "was": cur.get(int(k2))})
        # community median for what is still a placeholder
        for i, (h0, hs0) in cur.items():
            k = str(i)
            if k in merged or hs0 not in PLACEHOLDER:
                continue
            t = (hints or {}).get(i) or {}
            if t.get("type") in LOWTYPES:
                c["median_skipped_lowtype"] += 1
                continue
            med, nwh = median_for(COMM_OF.get(("ce", slug, i)))
            if not med:
                c["median_none"] += 1
                continue
            merged[k] = {"h": round(nudge(float(med)), 2), "src": "community_median"}
            c["community_median"] += 1
        n = len(cur)
        ph0 = sum(1 for (_, hs) in cur.values() if hs in PLACEHOLDER)
        ph_reg = ph0 - sum(1 for kk, vv in merged.items() if str(vv.get("src", "")).startswith("register_") and cur.get(int(kk), (0, ""))[1] in PLACEHOLDER)
        ph_med = ph_reg - c["community_median"]
        rep["districts"][slug] = {"buildings": n, "placeholder_before_merge": ph0, "after_register": ph_reg, "after_median": ph_med,
                                  "hints": bool(hints), **c}
        tot.update(c); tot["buildings"] += n; tot["placeholder_before_merge"] += ph0; tot["after_register"] += ph_reg; tot["after_median"] += ph_med
        # last write: re-read the file in case it changed under us, then write the merge
        if "--dry" not in sys.argv:
            json.dump(dict(sorted(merged.items(), key=lambda kv: int(kv[0]))), open(ovp + ".tmp", "w", encoding="utf-8"), separators=(",", ":"))
            os.replace(ovp + ".tmp", ovp)
        print("%-28s n=%5d ph %5d -> reg %5d -> med %5d  %s" % (slug, n, ph0, ph_reg, ph_med, dict(c)), flush=True)
    rep["totals"] = dict(tot)
    json.dump(rep, open(os.path.join(HERE, "ce_write_report%s.json" % ("_dry" if "--dry" in sys.argv else "")), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(rep["totals"], indent=1))


if __name__ == "__main__":
    {"city": run_city, "ce": run_ce}[sys.argv[1]]()

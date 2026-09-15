"""hero_all.py -- DigitAlchemy(R) / Digital Abbot
Hero-grade facade attributes for EVERY footprint of a district (Kendall, 15 Sep: "I need this task for every building in
Damac Hills, running in parallel" - the Golden Building treatment, real floor counts, real facade family, podium and
entrance, per building, not just the 33 photo-matched blocks).

Per footprint, in a process pool:
  identity   truth store building (display_name, storeys) + sub_community_building (nearest sub-community within its
             card radius), else the nearest sub-community centroid within radius + 150 m, else "unbound"
  family     data/ce/<slug>/hero_families.json (per sub-community, from the parallel reference research: type,
             storeys, podium levels, facade notes, sources) -> a look from facade_refs.json, plus per-building
             overrides when a named building is listed there
  massing    apartment blocks: storeys_total (research > register storeys) split into podium + residential floors
             -> bHeight = podium x hPodiumFloorH + floors x floorH; villas: levels = family storeys (G+1 = 2)
  geometry   footprint area, oriented long / short axes (UTM 40N) -> rows vs detached villas are left to the rule
             (rowMinAspect), but the numbers go in the report so a wrong call is visible
Output  data/ce/<slug>/facade_hero.json    {"<fi>": {"name", "sub", "family", "look", "cga": {...}, "unreal": {...}, "by"}}
        data/ce/<slug>/facade_hero_report.md   coverage per sub-community / family / evidence
Same shape as facade_match.json, so scripts/ce_lod3_datasmith.py --attr-file applies it unchanged.

    python scripts/hero_all.py damachills [--workers N] [--families data/ce/damachills/hero_families.json]
"""
import json, math, os, re, sys, time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb"); CE = os.path.join(ROOT, "data", "ce")

FLOOR_H, POD_FLOOR_H = 3.4, 4.0          # must match najma_v4.cga floorH / hPodiumFloorH
DEFAULT_POD = {"le10": 1, "gt10": 2}     # Akoya blocks: one podium level up to 10 storeys, two above (Loreto, Promenade 2B, Golf Gate 2)


def clean(name):
    n = name or ""
    n = re.sub(r"^\s*DAMAC\s*HILLS\s*-?\s*", "", n, flags=re.I).strip(" -")
    n = re.sub(r"-(\d)", r" \1", n).title()
    return " ".join(n.split())


def load_inputs(slug, families_p):
    import duckdb
    feats = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    refs = json.load(open(os.path.join(CE, slug, "facade_refs.json"), encoding="utf-8"))
    fam = json.load(open(families_p, encoding="utf-8")) if families_p and os.path.exists(families_p) else {}
    con = duckdb.connect(DB, read_only=True)
    bld = {r[0]: {"name": r[1], "storeys": r[2], "height_m": r[3], "lat": r[4], "lon": r[5], "kind": r[6], "src": r[7]}
           for r in con.execute("select footprint_i, display_name, storeys, height_m, lat, lon, kind, name_source from building "
                                "where district = ? and footprint_i is not null", [slug]).fetchall()}
    bound = {}
    for fi, sn, d in con.execute("select footprint_i, sub_name, dist_m from sub_community_building where district = ? order by footprint_i, dist_m", [slug]).fetchall():
        if fi not in bound: bound[fi] = (clean(sn), d)
    subs = [{"name": clean(r[0]), "lat": r[1], "lon": r[2], "radius_m": r[3] or 160.0}
            for r in con.execute("select name, lat, lon, radius_m from sub_community where district = ? and lat is not null", [slug]).fetchall()]
    return feats, refs, fam, bld, bound, subs


# ---------------------------------------------------------------- per-footprint worker (module-level for the pool)
_G = {}
def _init(feats, refs, fam, bld, bound, subs):
    import pyproj
    from shapely.geometry import shape
    _G.update(feats=feats, refs=refs, fam=fam, bld=bld, bound=bound, subs=subs, shape=shape,
              tr=pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True))


def geom_metrics(fi):
    from shapely.ops import transform
    g0 = _G["shape"](_G["feats"][fi]["geometry"]); c = g0.centroid          # centroid in degrees (the distance checks need lon/lat)
    g = transform(lambda x, y: _G["tr"].transform(x, y), g0)                   # metres for area / axes
    mrr = g.minimum_rotated_rectangle; xs, ys = mrr.exterior.coords.xy
    e1 = math.hypot(xs[1] - xs[0], ys[1] - ys[0]); e2 = math.hypot(xs[2] - xs[1], ys[2] - ys[1])
    long_, short = max(e1, e2), max(0.1, min(e1, e2))
    return {"area_m2": round(g.area, 1), "long_m": round(long_, 1), "short_m": round(short, 1), "aspect": round(long_ / short, 2), "lon": c.x, "lat": c.y}


def nearest_sub(lon, lat):
    best = None
    for s in _G["subs"]:
        d = math.hypot((lat - s["lat"]) * 111320, (lon - s["lon"]) * 100800)
        if best is None or d < best[1]: best = (s, d)
    if best and best[1] <= max(1000.0, best[0]["radius_m"] + 150): return best[0]["name"], round(best[1], 1), "nearest centroid"   # 15 Sep: 382 villas sat outside radius+150; 1 km still lands inside DAMAC Hills
    return None, (round(best[1], 1) if best else None), "unbound"


def family_for(sub, name, storeys, kind):
    fam = _G["fam"].get(sub or "", {})
    t = fam.get("type")
    if not t:
        t = "apartment" if (storeys or 0) >= 4 or kind == "tower" else "villa"
        src = "default (register storeys / kind)"
    else:
        src = "hero_families.json"
    return fam, t, src


def match_named(fam, name):
    """A research entry for this exact building (e.g. 'Orchid B' vs the register's 'DAMAC HILLS - ORCHID B')."""
    if not name: return None
    norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower().replace("tower", ""))   # 'Loreto 1 - A' == 'Loreto 1A' == 'Loreto Tower 1A'
    n = norm(clean(name))
    for b in fam.get("buildings", []) or []:
        bn = norm(b.get("name") or "")
        if bn and (bn == n or n.endswith(bn) or bn.endswith(n)): return b
    return None


def work(fi):
    f = _G["feats"][fi]; pr = f["properties"]; refs = _G["refs"]; looks = refs["looks"]
    b = _G["bld"].get(fi, {}); name = b.get("name") or pr.get("name") or ""
    gm = geom_metrics(fi)
    lon, lat = (b.get("lon") or gm["lon"]), (b.get("lat") or gm["lat"])
    if fi in _G["bound"]: sub, dist, how = _G["bound"][fi][0], _G["bound"][fi][1], "truth store binding"
    else: sub, dist, how = nearest_sub(gm["lon"], gm["lat"])
    # 15 Sep: the register's name beats the geographic binding when the named family's centroid is within 600 m (Loreto 1A/1B/2B were
    # bound to Lilac, Golf Horizon to Golf Panorama); a name whose family sits > 600 m away is a register mis-name (fi 8 'Golf Vita'
    # standing among the Golf Town blocks, 1.2 km from Golf Vita) and is kept as a flagged conflict, geography wins.
    name_conflict = ""
    if name:
        cn = clean(name).lower(); hits = [k for k in _G["fam"] if k.lower() in cn]
        if hits:
            k = max(hits, key=len); sc = next((x for x in _G["subs"] if x["name"] == k), None)
            dk = math.hypot((gm["lat"] - sc["lat"]) * 111320, (gm["lon"] - sc["lon"]) * 100800) if sc else 0.0
            if dk <= 600:
                if k != sub: how = f"register name ({sub or 'unbound'} by geography)"
                sub, dist = k, round(dk, 1)
            else: name_conflict = f"named '{clean(name)}' but {k} is {dk:.0f} m away; geography kept"
    storeys_reg = int(b.get("storeys") or 0); kind = b.get("kind") or ""
    try: lv = int(float(pr.get("levels") or 0))
    except ValueError: lv = 0
    fam, ftype, fsrc = family_for(sub, name, storeys_reg, kind)
    rec = {"name": clean(name) if name else "", "sub": sub or "", "bind": how, "bind_m": dist, "family": ftype, "family_src": fsrc,
           "geom": gm, "register_storeys": storeys_reg, "osm_levels": lv or None, "conflict": name_conflict}
    cga, unreal, evidence = {}, {}, []

    # explicit per-footprint entries in facade_refs.json win (e.g. the clubhouse pinned to footprint 3)
    pinned = next(((nm, e) for nm, e in refs["buildings"].items() if fi in (e.get("footprints") or [])), None)
    if pinned:
        nm, e = pinned; look = looks[e["look"]]
        cga = {**look.get("cga", {}), **e.get("cga", {})}; unreal = look.get("unreal", {})
        rec.update(look=e["look"], name=nm, by="facade_refs pinned footprint"); evidence.append("facade_refs.json")
    elif ftype == "apartment" and not (storeys_reg < 4 and not name and gm["area_m2"] < 1200):
        named = match_named(fam, name)
        # storeys: the researched building itself > the register when the family's towers differ (Artesia A-D 20-27 storeys and
        # the footprint is unnamed) > the family default > the register > OSM levels
        podium_only = (storeys_reg < 4 and lv == 0 and bool(name) and not named)   # 'Artesia' / 'Golf Promenade' at 12 m = the podium plot, not a tower
        if named and named.get("storeys_total"): st = named["storeys_total"]
        elif lv >= 4: st = lv                                       # OSM mapped the standing building (fi 480/481: 13 levels, not the unbuilt Golf Greens 35)
        elif fam.get("storeys_vary") and storeys_reg >= 4: st = storeys_reg
        elif podium_only: st = fam.get("podium_levels") or DEFAULT_POD["le10"]
        else: st = fam.get("storeys_total") or storeys_reg or lv or 9
        pod = (named or {}).get("podium_levels")
        if pod is None: pod = fam.get("podium_levels")
        if pod is None: pod = DEFAULT_POD["gt10"] if st > 10 else DEFAULT_POD["le10"]
        pod = int(pod); floors = 0 if podium_only else max(1, int(st) - pod)
        if podium_only: pod = int(st)
        h = round(pod * POD_FLOOR_H + floors * FLOOR_H, 1)
        look_name = fam.get("look") or "akoya_hero"
        # Carson: the footprint on record is the whole podium plot; the 33-floor towers come from the photoreal layer
        if look_name == "carson_podium" or (sub == "Carson" and gm["area_m2"] > 8000): look_name = "carson_podium"
        look = looks.get(look_name, looks["akoya_hero"])
        cga = dict(look.get("cga", {})); unreal = dict(look.get("unreal", {}))
        if look_name != "carson_podium":
            cga.update(bHeight=h, podiumLevels=pod, levels=str(int(st)))
        # the refs file's own per-name overrides (Loreto 35 m / 2 podium etc.) still apply on top
        for nm, e in refs["buildings"].items():
            if not podium_only and nm.lower() in (name or "").lower() and e.get("look") == look_name:
                cga.update(e.get("cga", {})); evidence.append(f"facade_refs '{nm}'")
        if fam.get("under_construction") and lv == 0 and not podium_only:   # Golf Greens 1/2: rising, not standing - teal, cut at pctComplete
            cga.update(status="construction", pctComplete=float(fam.get("pct_complete", 60)))
        rec.update(look=look_name, storeys_total=int(st), podium_levels=pod, res_floors=floors, height_m=cga.get("bHeight", h),
                   by=("research building" if named else "OSM levels" if lv >= 4 else "podium plot (named, 12 m)" if podium_only
                       else "register storeys (family varies)" if (fam.get("storeys_vary") and storeys_reg >= 4)
                       else "research family" if fam else "register storeys"))
        if named: evidence += named.get("sources", [])[:3]
        elif fam: evidence += fam.get("sources", [])[:2]
    elif ftype == "clubhouse":
        look = looks.get("clubhouse_sandstone"); cga = dict(look.get("cga", {})); unreal = dict(look.get("unreal", {}))
        rec.update(look="clubhouse_sandstone", by="research family")
    else:   # villa / townhouse: the villa branch of najma_v4.cga with the family's storeys and cladding
        if ftype == "apartment": ftype = "townhouse"; rec["family"] = ftype; rec["family_src"] += " (low-rise footprint inside an apartment sub-community)"
        v = fam.get("villa", {}) if fam else {}
        st = int(v.get("storeys") or (lv if 0 < lv <= 3 else 0) or 2)
        cga = {"lowStyle": "villa", "levels": str(st), "bHeight": round(st * 3.5, 1)}
        walls = (v.get("walls") or "").lower()
        cga["fclass"] = "stone" if ("stone" in walls or "sand" in walls or "beige" in walls) and "white" not in walls else "render"
        if ftype == "townhouse" or v.get("terraced") or fam.get("terraced"): cga["rowMinAspect"] = 1.8; cga["rowMinLen"] = 18   # rows split sooner
        unreal = {"walls": "white" if cga["fclass"] == "render" else "sandstone", "slabs": "white", "vision": "clear_glass"}
        rec.update(look="villa_" + cga["fclass"], storeys_total=st, by=("research family" if v else "district default G+1"))
        if v: evidence += v.get("sources", [])[:2]
    rec.update(cga=cga, unreal=unreal, evidence=evidence[:4])
    return fi, rec


def main():
    args = sys.argv[1:]
    def opt(n, d):
        if n in args: i = args.index(n); v = args[i + 1]; del args[i:i + 2]; return v
        return d
    workers = int(opt("--workers", max(2, (os.cpu_count() or 4) - 2)))
    slug = [a for a in args if not a.startswith("--")][0]
    families_p = opt("--families", os.path.join(CE, slug, "hero_families.json"))
    t0 = time.time(); feats, refs, fam, bld, bound, subs = load_inputs(slug, families_p)
    print(f"{slug}: {len(feats)} footprints, {len(bld)} register rows, {len(bound)} sub bindings, {len(subs)} sub-communities, "
          f"{len(fam)} researched families ({os.path.basename(families_p) if fam else 'none - defaults'}); {workers} workers")
    out = {}
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(feats, refs, fam, bld, bound, subs)) as ex:
        for fi, rec in ex.map(work, range(len(feats)), chunksize=32): out[str(fi)] = rec
    # ---- report
    by_sub, by_fam, by_by = {}, {}, {}
    for r in out.values():
        by_sub.setdefault(r["sub"] or "(unbound)", []).append(r); by_fam[r["family"]] = by_fam.get(r["family"], 0) + 1; by_by[r["by"]] = by_by.get(r["by"], 0) + 1
    lines = [f"# {slug}: hero attributes for every footprint", f"generated {time.strftime('%Y-%m-%d %H:%M')} · {len(out)} footprints · {time.time() - t0:.1f}s · {workers} workers", "",
             "families: " + ", ".join(f"{k}={v}" for k, v in sorted(by_fam.items())), "evidence: " + ", ".join(f"{k}={v}" for k, v in sorted(by_by.items())), "",
             "| sub-community | n | family | storeys (min-max) | podium | look | evidence |", "|---|---|---|---|---|---|---|"]
    for s, rs in sorted(by_sub.items(), key=lambda kv: -len(kv[1])):
        st = [r.get("storeys_total") for r in rs if r.get("storeys_total")]; pods = sorted({r.get("podium_levels") for r in rs if r.get("podium_levels") is not None})
        fams = sorted({r["family"] for r in rs}); looks = sorted({r.get("look", "") for r in rs}); ev = sorted({r["by"] for r in rs})
        lines.append(f"| {s} | {len(rs)} | {'/'.join(fams)} | {min(st) if st else '-'}-{max(st) if st else '-'} | {'/'.join(map(str, pods)) or '-'} | {'/'.join(looks)} | {'; '.join(ev)} |")
    named = [r for r in out.values() if r["name"]]
    lines += ["", f"## named buildings ({len(named)})", "| fi | name | sub | storeys | podium | height m | by |", "|---|---|---|---|---|---|---|"]
    for fi, r in sorted(((int(k), v) for k, v in out.items() if v["name"]), key=lambda kv: kv[1]["name"]):
        lines.append(f"| {fi} | {r['name']} | {r['sub']} | {r.get('storeys_total', '-')} | {r.get('podium_levels', '-')} | {r.get('height_m', r['cga'].get('bHeight', '-'))} | {r['by']} |")
    ub = [int(k) for k, v in out.items() if v["bind"] == "unbound"]
    lines += ["", f"unbound footprints (district default applied): {len(ub)} {ub[:30]}"]
    cf = [(int(k), v["conflict"]) for k, v in out.items() if v.get("conflict")]
    lines += ["", f"register name conflicts kept as geography ({len(cf)}):"] + [f"- fi {k}: {c}" for k, c in cf]
    json.dump(out, open(os.path.join(CE, slug, "facade_hero.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    open(os.path.join(CE, slug, "facade_hero_report.md"), "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines[:6])); print(f"-> data/ce/{slug}/facade_hero.json + facade_hero_report.md")


if __name__ == "__main__":
    main()

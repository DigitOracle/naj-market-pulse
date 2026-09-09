"""Write resolved identity into the twin. The knowledge graph stops being a file nobody reads and becomes what the viewer shows.

resolve_identity.py decides what each footprint IS. This is the only thing that writes that decision onto the model:

    data/identity/resolved/<slug>.json          the resolved identity + all evidence
        -> data/names/anchors_<slug>.json       the twin's own label layer (name, duid, grade, role, identifier, tenants)
        -> KV anchors_<slug>                    what the viewer fetches
        -> KV identity_<slug>                   the fuller record the fact panel reads

Rules, in order of how much they matter:

  1. A HAND-VERIFIED name is never overwritten. Anything in data/names/pinned_names.json wins over every source, always.
  2. Only accepted grades are written. VERIFIED, MATCHED and STRUCTURALLY_IDENTIFIED go on the model by default;
     INFERRED (a point of interest near a footprint) stays in the review table until --include-inferred says otherwise.
  3. Nothing is ever deleted. A footprint that had a name and resolves to nothing keeps the name it had, and the row is
     reported so the regression is visible rather than silent.
  4. Every written name carries its DUID, its grade, its role and the source that produced it, so the twin can show
     "who says so" and any name can be traced back and undone.

Tenants and amenities travel with the building but never as its name - they are what makes a tap on a tower useful.

Usage: python scripts/apply_identity.py [--include-inferred] [--dry] [slug ...]
"""
import argparse, glob, json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
import pyproj
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
NAMES = os.path.join(ROOT, "data", "names"); RES = os.path.join(ROOT, "data", "identity", "resolved")
PINNED = os.path.join(NAMES, "pinned_names.json")
ACCEPT = {"VERIFIED", "MATCHED", "STRUCTURALLY_IDENTIFIED"}


KEEP_CAPS = {"JLT", "JBR", "JVC", "JVT", "DIFC", "DAMAC", "MBL", "MAG", "AZIZI", "SOL", "ONE", "II", "III", "IV", "VI", "VII", "UAE", "DXB", "MBR", "SLS", "W", "H", "O2", "AG", "AVA", "MJL"}
CANON = (json.load(open(os.path.join(ROOT, 'data', 'graph', 'canonical_names.json'), encoding='utf-8')).get('items') or {}) if os.path.exists(os.path.join(ROOT, 'data', 'graph', 'canonical_names.json')) else {}   # truth-store matrix winners (graph_export.py)

def register_case(n):
    """PRINCESS TOWER -> Princess Tower; keeps brand / district initialisms and roman numerals as written"""
    import re
    def w(t):
        core = re.sub(r"[^A-Za-z0-9]", "", t)
        if core in KEEP_CAPS or (core.isdigit()) or re.fullmatch(r"[IVX]+", core or "x"): return t
        return t[:1].upper() + t[1:].lower()
    return " ".join(w(t) for t in n.split(" "))


def run(slug, accept, dry, tok):
    matrix_n = 0; villa_n = 0
    rf = os.path.join(RES, f"{slug}.json"); af = os.path.join(NAMES, f"anchors_{slug}.json")
    vlf = os.path.join(NAMES, f"villa_labels_{slug}.json"); VL = (json.load(open(vlf, encoding="utf-8")).get("labels") or {}) if os.path.exists(vlf) else {}   # villa_labels.py: place labels for unnamed low-rise
    if not (os.path.exists(rf) and os.path.exists(af)): return None
    R = json.load(open(rf, encoding="utf-8")); A = json.load(open(af, encoding="utf-8"))
    pinned = json.load(open(PINNED, encoding="utf-8")) if os.path.exists(PINNED) else {}
    by_i = {r["i"]: r for r in R["rows"]}
    added = changed = kept = pinned_n = 0
    lost = []
    anchors = {a["i"]: a for a in A["anchors"]}
    # footprints that gain a name but never had an anchor (the label layer only carried named/developer buildings) get one now,
    # built the way build_anchors.py builds them: centroid of the largest ring, UTM x / -northing z, the footprint's own height
    gj = os.path.join(ROOT, "data", "ce", slug, "buildings.geojson")
    feats = json.load(open(gj, encoding="utf-8"))["features"] if os.path.exists(gj) else []
    def new_anchor(i, name, src):
        if i >= len(feats): return None
        f = feats[i]; g = f["geometry"]; p = f["properties"]
        rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [pg[0] for pg in g["coordinates"]] if g["type"] == "MultiPolygon" else []
        if not rings: return None
        ring = max(rings, key=len); n = max(1, len(ring) - 1); lon = sum(pt[0] for pt in ring[:n]) / n; lat = sum(pt[1] for pt in ring[:n]) / n
        e, nn = TO_UTM(lon, lat)
        rec = {"id": str(p.get("osm_id") or p.get("id") or i), "i": i, "mesh": None, "name": name, "source": src, "dev": None, "dev_project": None, "lon": round(lon, 6), "lat": round(lat, 6),
               "x": round(e, 1), "z": round(-nn, 1), "h": round(float(p.get("bHeight") or 0), 1), "levels": p.get("levels") or None, "bear": None, "fm": None, "fm_ll": None}
        A["anchors"].append(rec); anchors[i] = rec; return rec
    # register floor counts for footprints bound to a DLD building (reg_bindings first, then the transactions bindings via the units register)
    regf = {}
    try:
        RB = json.load(open(os.path.join(ROOT, "data", "identity", "official", "dld", "reg_bindings.json"), encoding="utf-8")).get(slug, {})
        for k, v in RB.items():
            fl = v.get("floors") or v.get("floors_max")
            if fl: regf[int(k)] = int(float(fl))
    except Exception: RB = {}
    try:
        TB = json.load(open(os.path.join(ROOT, "data", "identity", "official", "dld", "tx_bindings.json"), encoding="utf-8")).get(slug, {})
        UB = {str(b.get("name") or "").lower(): b for b in json.load(open(os.path.join(ROOT, "data", "dld", f"units_buildings_{slug}.json"), encoding="utf-8")).get("buildings", [])}
        for k, v in TB.items():
            if int(k) in regf: continue
            b = UB.get(str(v.get("building") or "").lower()); fl = b and (b.get("floors") or b.get("floors_max"))
            if fl: regf[int(k)] = int(float(fl))
    except Exception: pass
    # sub-community attribution (cluster_names.py). A neighbourhood, not a name: it never fills `name`.
    clusters = {}
    try:
        _cf = os.path.join(NAMES, f"clusters_{slug}.json")
        if os.path.exists(_cf):
            _cd = json.load(open(_cf, encoding="utf-8"))
            clusters = {int(k): v for k, v in (_cd.get("assign") or {}).items()}
    except Exception: clusters = {}
    hreg = {}
    out = []
    for i, r in by_i.items():
        a = anchors.get(i)
        old = (a or {}).get("name")
        pin = pinned.get(r["duid"]) or pinned.get(f"{slug}:{i}")
        if pin:
            name, role, grade, src = pin, "BUILDING_NAME", "VERIFIED", "hand-verified"
            pinned_n += 1
        elif r["grade"] in accept and r["display_name"]:
            name, role, grade, src = r["display_name"], r["display_role"], r["grade"], r["name_source"]
            cn = CANON.get(r["duid"])   # the truth store's matrix winner (graph_export.py); only an authoritative source may overrule the resolver
            if cn and cn.get("name") and (cn.get("weight") or 0) >= 90 and cn["name"].strip().lower() != (name or "").strip().lower():
                name, role, src = cn["name"], "BUILDING_NAME", "matrix:" + str(cn.get("source")); matrix_n += 1
            if not old: added += 1
            elif name != old: changed += 1
            else: kept += 1
        elif old:
            # never delete: a footprint keeps the name it had, and we say so
            name, role, grade, src = old, "BUILDING_NAME", "MATCHED", (a or {}).get("source") or "osm"
            lost.append({"i": i, "kept": old, "resolver_said": r["display_name"], "grade": r["grade"]})
        else:
            name = None; role = grade = src = None
        if name and src == "dld" and name.isupper(): name = register_case(name)      # the register shouts; the twin does not
        rec = {"i": i, "duid": r["duid"], "name": name, "cluster": clusters.get(i), "display_role": role, "identity_grade": grade,
               "name_source": src, "structural_identifier": r["structural_identifier"], "address": r["address"],
               "project_name": r["project_name"], "plot_id": r["plot_id"],
               "tenants": r["tenant_names"][:12], "amenities": r["amenity_names"][:8],
               "height_m": r["height_m"], "storeys": r["storeys"], "lon": r["lon"], "lat": r["lat"],
               "developer": r["developer"], "confidence": r["confidence"]}
        vl = VL.get(str(i)) if not name else None
        if vl: rec["kind"] = vl.get("kind"); rec["place_label"] = vl.get("place_label"); rec["place_basis"] = vl.get("basis"); rec["cluster_name"] = vl.get("cluster"); villa_n += 1
        out.append(rec)
        if a is None and name and grade in accept and not dry: a = new_anchor(i, name, src)
        if a is None and clusters.get(i) and not dry:
            a = new_anchor(i, None, None)                                       # a nameless anchor that carries the neighbourhood
            if a is not None: a["cluster"] = clusters[i]
        if a is not None and clusters.get(i): a["cluster"] = clusters[i]        # attribution rides on every anchor, named or not
        if vl and not name and not dry:                                           # villa rule: a nameless anchor that carries kind + place label
            if a is None: a = new_anchor(i, None, None)
            if a is not None:
                a["kind"] = vl.get("kind"); a["place_label"] = vl.get("place_label"); a["place_basis"] = vl.get("basis"); a["duid"] = r["duid"]
                if vl.get("cluster") and not a.get("cluster"): a["cluster"] = vl["cluster"]
        if a is not None and name:                     # the twin's own label layer keeps its shape; identity rides on it
            a["name"] = name; a["duid"] = r["duid"]; a["identity_grade"] = grade; a["display_role"] = role
            if src: a["source"] = src
            fl = regf.get(i)
            if fl and fl >= 3 and float(a.get("h") or 0) <= 12.5:            # default massing height -> register floors x 3.2 m
                a["h"] = round(fl * 3.2, 1); a["h_source"] = "dld floors"; a["floors_register"] = fl; hreg[i] = a["h"]
    ident = {"district": slug, "generated": R["generated"], "buildings": len(out),
             "accepted_grades": sorted(accept),
             "note": "Identity resolved from every source we hold. `identity_grade` says how well it is known: VERIFIED = an "
                     "authoritative register, MATCHED = a survey record on the building itself, STRUCTURALLY_IDENTIFIED = a site-plan "
                     "or street identifier, INFERRED = a point of interest nearby. Tenants and amenities are recorded against the "
                     "building and are never its name.",
             "by_index": {str(r["i"]): r for r in out}}
    named = sum(1 for r in out if r["name"])
    print(f"  {slug:<26} {len(out):>5} bldgs | named {named:>5} | heights from register {len(hreg):>4} | matrix {matrix_n} | villa labels {villa_n} | +{added} new, {changed} replaced, {kept} unchanged, "
          f"{pinned_n} pinned | kept-not-lost {len(lost)}")
    if dry: return {"slug": slug, "named": named, "added": added, "changed": changed, "lost": lost}
    if hreg and not dry:
        hp = os.path.join(ROOT, "data", "ce", slug, "heights_register.json")
        try:
            prev_h = (json.load(open(hp, encoding="utf-8")) if os.path.exists(hp) else {}).get("heights", {})
        except Exception: prev_h = {}
        prev_h.update({str(k): v for k, v in hreg.items()})
        json.dump({"source": "DLD units register floors x 3.2 m (estimate, not a survey height)", "generated": R["generated"], "heights": prev_h}, open(hp, "w", encoding="utf-8"))
    json.dump(A, open(os.path.join(NAMES, f"anchors_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(ident, open(os.path.join(ROOT, "data", "identity", f"identity_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    ok1 = push("anchors_" + slug, A, tok).get("ok"); ok2 = push("identity_" + slug, ident, tok).get("ok")
    print(f"     anchors -> {ok1} | identity -> {ok2}")
    return {"slug": slug, "named": named, "added": added, "changed": changed, "lost": lost}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-inferred", action="store_true"); ap.add_argument("--dry", action="store_true")
    ap.add_argument("slugs", nargs="*"); a = ap.parse_args()
    accept = ACCEPT | ({"INFERRED"} if a.include_inferred else set())
    tok = None if a.dry else env_token("INGEST_TOKEN")
    slugs = a.slugs or [os.path.basename(p)[:-5] for p in sorted(glob.glob(os.path.join(RES, "*.json")))]
    print(f"accepting grades: {sorted(accept)}" + ("  (DRY RUN)" if a.dry else ""))
    tot = {"named": 0, "added": 0, "changed": 0}; lost = 0
    for s in slugs:
        r = run(s, accept, a.dry, tok)
        if r:
            for k in tot: tot[k] += r[k]
            lost += len(r["lost"])
    print(f"\nTOTAL named on the twin {tot['named']:,} | {tot['added']} newly named | {tot['changed']} replaced | "
          f"{lost} kept rather than lost")

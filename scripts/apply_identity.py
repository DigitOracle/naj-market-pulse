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
NAMES = os.path.join(ROOT, "data", "names"); RES = os.path.join(ROOT, "data", "identity", "resolved")
PINNED = os.path.join(NAMES, "pinned_names.json")
ACCEPT = {"VERIFIED", "MATCHED", "STRUCTURALLY_IDENTIFIED"}


def run(slug, accept, dry, tok):
    rf = os.path.join(RES, f"{slug}.json"); af = os.path.join(NAMES, f"anchors_{slug}.json")
    if not (os.path.exists(rf) and os.path.exists(af)): return None
    R = json.load(open(rf, encoding="utf-8")); A = json.load(open(af, encoding="utf-8"))
    pinned = json.load(open(PINNED, encoding="utf-8")) if os.path.exists(PINNED) else {}
    by_i = {r["i"]: r for r in R["rows"]}
    added = changed = kept = pinned_n = 0
    lost = []
    anchors = {a["i"]: a for a in A["anchors"]}
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
            if not old: added += 1
            elif name != old: changed += 1
            else: kept += 1
        elif old:
            # never delete: a footprint keeps the name it had, and we say so
            name, role, grade, src = old, "BUILDING_NAME", "MATCHED", (a or {}).get("source") or "osm"
            lost.append({"i": i, "kept": old, "resolver_said": r["display_name"], "grade": r["grade"]})
        else:
            name = None; role = grade = src = None
        rec = {"i": i, "duid": r["duid"], "name": name, "display_role": role, "identity_grade": grade,
               "name_source": src, "structural_identifier": r["structural_identifier"], "address": r["address"],
               "project_name": r["project_name"], "plot_id": r["plot_id"],
               "tenants": r["tenant_names"][:12], "amenities": r["amenity_names"][:8],
               "height_m": r["height_m"], "storeys": r["storeys"], "lon": r["lon"], "lat": r["lat"],
               "developer": r["developer"], "confidence": r["confidence"]}
        out.append(rec)
        if a is not None and name:                     # the twin's own label layer keeps its shape; identity rides on it
            a["name"] = name; a["duid"] = r["duid"]; a["identity_grade"] = grade; a["display_role"] = role
            if src: a["source"] = src
    ident = {"district": slug, "generated": R["generated"], "buildings": len(out),
             "accepted_grades": sorted(accept),
             "note": "Identity resolved from every source we hold. `identity_grade` says how well it is known: VERIFIED = an "
                     "authoritative register, MATCHED = a survey record on the building itself, STRUCTURALLY_IDENTIFIED = a site-plan "
                     "or street identifier, INFERRED = a point of interest nearby. Tenants and amenities are recorded against the "
                     "building and are never its name.",
             "by_index": {str(r["i"]): r for r in out}}
    named = sum(1 for r in out if r["name"])
    print(f"  {slug:<26} {len(out):>5} bldgs | named {named:>5} | +{added} new, {changed} replaced, {kept} unchanged, "
          f"{pinned_n} pinned | kept-not-lost {len(lost)}")
    if dry: return {"slug": slug, "named": named, "added": added, "changed": changed, "lost": lost}
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

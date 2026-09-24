"""Full audit of the Sobha twin: do we have every building, and is each one where it should be?

Kendall, 24 Sep 2026: "run a full audit, do we have all buildings? are they placed correctly?" - after Seahaven Tower B & C
turned out to be 22 Dubai Harbour buildings (Princess Tower, Emirates Crown, a mosque) taken by the radius route.

Reads data/identity/sobha_projects.json (the 49 register projects), data/board/sobha_mask.json (footprints per project) and
data/ce/_datasmith/sobha_unreal.json (what the Unreal export actually carries). Per project:
  coverage       reached / not reached, and why not (the mask's own gap reason)
  count          register buildings vs footprints in the twin (villa / plot projects are counted, not judged)
  district       footprints lie in the district the project's DLD area maps to (build_sobha_mask.AREA_SLUG / EXTRA_SLUGS)
  names          a footprint carrying another building's name (not a Sobha name) is somebody else's building
  spread         footprints of one project more than SPREAD_M apart: one project, two places
  height         footprints at the 12 m default (no sourced height) - a tower drawn as a stub
  unreal         footprints the Unreal export does not carry (not in the level at all)
and across projects: one footprint centroid claimed by two projects. Severity: FAIL (wrong building or wrong place),
WARN (missing or unsure), OK.
Output: data/board/sobha_audit.json + data/board/sobha_audit.md.  Usage: python scripts/audit_sobha_twin.py
"""
import json, math, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_sobha_mask as M

ROOT = M.ROOT; BOARD = os.path.join(ROOT, "data", "board")
MANIFEST = os.path.join(ROOT, "data", "ce", "_datasmith", "sobha_unreal.json")
SPREAD_M = 900.0; DEFAULT_H = 12.0
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def dist_m(a, b):
    return math.hypot((a[0] - b[0]) * 101000.0, (a[1] - b[1]) * 111000.0)


def main():
    projects = {p["project_number"]: p for p in json.load(open(M.PROJECTS, encoding="utf-8"))["projects"]}
    mask = json.load(open(os.path.join(BOARD, "sobha_mask.json"), encoding="utf-8"))
    man = json.load(open(MANIFEST, encoding="utf-8")) if os.path.exists(MANIFEST) else {"districts": {}}
    gaps = {g.get("project_number"): g.get("why") for g in mask.get("gaps", []) if g.get("project_number")}
    fps_cache = {}

    def fp(slug, i):
        if slug not in fps_cache:
            fps_cache[slug] = M.footprints(slug, {}) or {}
        return fps_cache[slug].get(int(i))

    per = defaultdict(list)   # pn -> [(slug, i, rec)]
    for slug, d in mask["districts"].items():
        for i, rec in (d.get("by_i") or {}).items():
            per[rec["project_number"]].append((slug, int(i), rec))
    in_export = {slug: {int(a["i"]) for a in d.get("actors", {}).values() if a.get("actor")} for slug, d in man["districts"].items()}
    dup_of = {(slug, int(a["i"])) for slug, d in man["districts"].items() for a in d.get("actors", {}).values() if a.get("duplicate_of")}

    rows, claims = [], defaultdict(set)
    for pn, p in sorted(projects.items(), key=lambda kv: (kv[1].get("area") or "", kv[1].get("name_en") or "")):
        issues = []
        items = per.get(pn, [])
        reg = int(p.get("buildings") or 0); villas = int(p.get("villas") or 0)
        home = {M.AREA_SLUG.get(p.get("area"))} | set(M.EXTRA_SLUGS.get(p.get("area"), [])); home.discard(None)
        # a footprint seen in two overlapping district files is the same building once
        uniq = {}
        for slug, i, rec in items:
            f = fp(slug, i)
            if not f or f["lon"] is None:
                issues.append(("FAIL", "footprint %s/%d not in the district file" % (slug, i))); continue
            key = (round(f["lon"], 5), round(f["lat"], 5))
            claims[key].add(pn)
            if key in uniq or (slug, i) in dup_of:
                continue
            uniq[key] = (slug, i, rec, f)
        n = len(uniq)
        if not items:
            issues.append(("WARN", "not in the twin: " + (gaps.get(pn) or "no route reached it")))
        else:
            if villas and not reg:
                pass
            elif reg and n > reg:
                issues.append(("FAIL" if n > reg + 2 else "WARN", "%d footprints for %d register buildings" % (n, reg)))
            elif reg and n < reg:
                issues.append(("WARN", "%d of %d register buildings in the twin" % (n, reg)))
            off = sorted({s for s, i, r, f in uniq.values() if home and s not in home})
            if off:
                # overlap districts (bukadra/sobhaheartland, jltnorth/althanyahfifth) share edge buildings; flag only true strays
                cen = (sum(f["lon"] for *_, f in uniq.values()) / n, sum(f["lat"] for *_, f in uniq.values()) / n)
                issues.append(("WARN", "footprints filed under %s, DLD area %s maps to %s" % (",".join(off), p.get("area"), ",".join(sorted(home)) or "?")))
            named = sorted({f["name"] for s, i, r, f in uniq.values() if f["name"] and not M.is_sobha_name(f["name"])})
            if named:
                issues.append(("FAIL", "footprints named for other buildings: " + "; ".join(named[:6])))
            pts = [(f["lon"], f["lat"]) for *_, f in uniq.values()]
            spread = max((dist_m(a, b) for a in pts for b in pts), default=0.0)
            if spread > SPREAD_M:
                issues.append(("FAIL", "footprints %.1f km apart - one project in two places" % (spread / 1000)))
            stubs = [f for *_, f in uniq.values() if not f["height_m"] or float(f["height_m"]) <= DEFAULT_H]
            if stubs and not villas:
                issues.append(("WARN", "%d of %d footprints at the %g m default height (no sourced height)" % (len(stubs), n, DEFAULT_H)))
            missing = [(s, i) for s, i, r, f in uniq.values() if s in in_export and i not in in_export[s]]
            no_dist = sorted({s for s, *_ in uniq.values() if s not in man["districts"]})
            if missing:
                issues.append(("FAIL", "%d footprints not in the Unreal export (%s)" % (len(missing), ",".join(sorted({s for s, _ in missing})))))
            if no_dist:
                issues.append(("FAIL", "district(s) %s not in the Unreal manifest" % ",".join(no_dist)))
        sev = "FAIL" if any(s == "FAIL" for s, _ in issues) else "WARN" if issues else "OK"
        rows.append({"project_number": pn, "name": p.get("name_en"), "area": p.get("area"), "status": p.get("status"),
                     "register_buildings": reg, "villas": villas, "footprints": n,
                     "methods": sorted({r["method"] for *_, r, f in uniq.values()}) if items else [],
                     "districts": sorted({s for s, *_ in uniq.values()}) if items else [], "severity": sev,
                     "issues": [{"severity": s, "what": w} for s, w in issues]})
    shared = [{"centroid": k, "projects": sorted(v)} for k, v in claims.items() if len(v) > 1]
    for s in shared:
        for r in rows:
            if r["project_number"] in s["projects"]:
                r["issues"].append({"severity": "FAIL", "what": "shares a footprint with project(s) %s" % [x for x in s["projects"] if x != r["project_number"]]})
                r["severity"] = "FAIL"
    tot = {k: sum(1 for r in rows if r["severity"] == k) for k in ("OK", "WARN", "FAIL")}
    tot.update(projects=len(rows), in_twin=sum(1 for r in rows if r["footprints"]), footprints=sum(r["footprints"] for r in rows),
               register_buildings=sum(r["register_buildings"] for r in rows))
    out = {"generated": __import__("time").strftime("%Y-%m-%d %H:%M"), "totals": tot, "shared_footprints": shared, "projects": rows}
    json.dump(out, open(os.path.join(BOARD, "sobha_audit.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    md = ["# Sobha twin audit (%s)" % out["generated"], "",
          "%(projects)d register projects; %(in_twin)d in the twin with %(footprints)d footprints (register: %(register_buildings)d buildings). OK %(OK)d, WARN %(WARN)d, FAIL %(FAIL)d." % tot, "",
          "| Sev | Project | Area | Reg | Twin | Via | Issues |", "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: ({"FAIL": 0, "WARN": 1, "OK": 2}[r["severity"]], r["name"] or "")):
        md.append("| %s | %s | %s | %d | %d | %s | %s |" % (r["severity"], r["name"], r["area"], r["register_buildings"], r["footprints"],
                                                          ",".join(r["methods"]), "; ".join(i["what"] for i in r["issues"]) or "-"))
    open(os.path.join(BOARD, "sobha_audit.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md[:3]))
    for r in rows:
        if r["severity"] != "OK":
            print("%-4s %-40s %s" % (r["severity"], (r["name"] or "")[:40], " | ".join(i["what"] for i in r["issues"])[:200]))


if __name__ == "__main__":
    main()

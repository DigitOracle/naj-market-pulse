"""LAB (Blocks) - roll-up numbers for data/lab/blocks/QA_SUMMARY.md's summary: type hints (twin + city) and QA flags.
Prints JSON; writes nothing. Research use only.
  python scripts/lab_blocks_stats.py
"""
import glob, json, os, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "blocks")


def jl(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def hints(pattern):
    n = 0; c = Counter(); conf = Counter(); ph = Counter(); files = 0; fb = []; typed = 0; matched = 0
    for p in sorted(glob.glob(pattern)):
        o = jl(p)
        if not o or "types" not in o: continue
        files += 1; n += o["footprints"]; c.update(o["counts"]); conf.update(o["by_conf"]); ph.update(o.get("placeholder_12m_by_type") or {})
        typed += o.get("osm_building_tag_typed", 0); matched += o["footprints"] - (o.get("osm_match") or {}).get("none", 0)
        f = o.get("fallback_check") or {}
        if f.get("n"): fb.append((f["agree_pct"], o["slug"], f["n"]))
    tot_fb = sum(x[2] for x in fb); agree = sum(x[0] * x[2] / 100 for x in fb)
    return {"files": files, "footprints": n, "types": dict(c.most_common()), "conf": dict(conf), "osm_matched": matched,
            "osm_tag_typed": typed, "placeholder_by_type": dict(ph.most_common()),
            "fallback_agree_pct_weighted": round(100 * agree / tot_fb, 1) if tot_fb else None, "fallback_n": tot_fb,
            "weakest_fallback": sorted(fb)[:5]}


def qa(kind):
    st = Counter(); flags = Counter(); worst = []
    pat = os.path.join(OUT, "qa_city_*.json") if kind == "city" else os.path.join(OUT, "qa_*.json")
    for p in sorted(glob.glob(pat)):
        b = os.path.basename(p)
        if kind == "ce" and (b.startswith("qa_city_") or not b.startswith("qa_")): continue
        r = jl(p)
        if not r or "status" not in r: continue
        st[r["status"]] += 1
        for f in r.get("flags") or []:
            flags[(f["check"], f["severity"])] += f.get("n", 0)
            if f["severity"] in ("high",): worst.append((r["slug"], f["check"], f.get("n"), (f.get("detail") or [])[:2]))
    return {"status": dict(st), "flags": {"%s/%s" % k: v for k, v in sorted(flags.items())}, "high": worst[:40]}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps({"hints_twin": hints(os.path.join(OUT, "type_hints_*.json")),
                      "hints_city": hints(os.path.join(OUT, "city", "type_hints_*.json")),
                      "qa_twin": qa("ce"), "qa_city": qa("city")}, indent=1, ensure_ascii=False))

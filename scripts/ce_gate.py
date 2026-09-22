"""The three gates a CityEngine district build must pass before it is pushed.

Written 22 Sep 2026 after LOD 3 produced a payload that looked perfect and was not: 654 shapes generated with zero failures
and came out of the merge as 53 addressable buildings. Nothing in the run said so except one number in the middle of a dict.

  GATE 1  BUILDINGS. chosen['buildings'] must equal chosen['shapes_ok']. Per-building meshes are how the twin does tapping,
          the floor stack and the panel. A district with 54 of 654 is a picture you cannot interact with, and it looks
          entirely correct in a screenshot. This is the gate that matters most and the one nothing else catches.
  GATE 2  SIZE. gzipped GLB under the 5 MB KV cap. MEASURED, not inferred from the merged size - the ratio moves with how
          much of the payload is texture rather than geometry (LOD 3 ships no images at all).
  GATE 3  THE TIER FIRED. triangles must sit above --min-tris. This exists because a "hero lane" set /ce/rule/LOD per shape
          and the LOD ladder below it overwrote every shape on each rung, so the lane produced LOD 1 while logging that it
          had applied LOD 3. The log line was written before the overwrite. A log line is a claim; the triangle count is
          the measurement. Bracket a run between a known all-LOD1 and all-LOD3 count for the same district.

  python scripts/ce_gate.py businessbay --log logs/v4_tier150_businessbay.log --min-tris 400000
"""
import gzip, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CAP = 5 * 1024 * 1024


def opt(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return 2
    slug = args[0]
    ver = opt("--ver", "v4")
    log = opt("--log", os.path.join(ROOT, "data", "ce", "_glb", "sky_%s_%s.log" % (slug, ver)))
    min_tris = opt("--min-tris", 0, int)
    glb = opt("--glb", os.path.join(ROOT, "data", "ce", "_glb", "sky_%s_%s_0.glb" % (slug, ver)))

    txt = open(log, encoding="utf-8", errors="ignore").read() if os.path.exists(log) else ""
    hits = re.findall(r"chosen (\{[^}]*\})", txt)
    if not hits:
        print("FAIL  no chosen{} line in %s - the run did not finish" % log); return 1
    ch = json.loads(hits[-1].replace("'", '"').replace("True", "true").replace("False", "false"))

    b, ok, tris = ch.get("buildings"), ch.get("shapes_ok"), ch.get("triangles")
    g1 = (b == ok and b)
    print("GATE 1  buildings %s of %s shapes  ->  %s" % (b, ok, "PASS" if g1 else "FAIL - the merge collapsed per-building identity"))

    if not os.path.exists(glb):
        print("GATE 2  no GLB at %s  ->  FAIL" % glb); g2 = False
    else:
        n = len(gzip.compress(open(glb, "rb").read(), 9))
        g2 = n <= CAP
        print("GATE 2  gzipped %.2f MB of %.0f MB cap  ->  %s" % (n / 1048576.0, CAP / 1048576.0, "PASS" if g2 else "FAIL - over the KV cap"))

    g3 = tris is not None and tris >= min_tris
    print("GATE 3  %s triangles, floor %s  ->  %s" % (tris, min_tris, "PASS" if g3 else "FAIL - the tier did not fire; the log line is a claim, not a measurement"))

    allp = bool(g1 and g2 and g3)
    print("\n%s  %s %s" % ("PASS - safe to push" if allp else "DO NOT PUSH", slug, ver))
    return 0 if allp else 1


if __name__ == "__main__":
    sys.exit(main())

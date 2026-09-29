"""Add the footprints an anchors file is missing, and change nothing else in it.

An anchors_<slug>.json holds two things: `fps` (every footprint's scene position - how the twin maps a tapped mesh to its
building) and `anchors` (the named buildings, enriched after build_anchors.py by the identity, register and developer
binding steps). When footprints are appended to a district (Ellington appends, new towers), the file's `fps` goes stale
and the new buildings cannot be tapped.

Rebuilding the file with build_anchors.py is NOT the fix: on 29 Sep 2026 that dropped dubaihills from 4,262 anchors to 37
and althanyahfifth from 1,317 to 193, because the enrichment lives only in the published file. So this takes the fresh
`fps` from a rebuild written somewhere else, checks the two agree on every shared footprint (same frame, same glb_center),
and appends only the missing entries to the existing file.

  python scripts/anchors_add_missing_fps.py <slug> [...]    rebuilds each into a temp dir, merges, writes data/names
  python scripts/anchors_add_missing_fps.py --dry <slug>     report only
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NAMES = os.path.join(ROOT, "data", "names")


def fresh_fps(slug):
    """Run build_anchors.py with its output redirected, so the published file is never touched."""
    tmp = tempfile.mkdtemp(prefix="anchors_")
    orig = os.path.join(NAMES, "anchors_%s.json" % slug)
    keep = os.path.join(tmp, "orig.json")
    shutil.copy2(orig, keep)
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "build_anchors.py"), slug], cwd=ROOT, check=True,
                       capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return json.load(open(orig, encoding="utf-8"))
    finally:
        shutil.copy2(keep, orig)                      # the published file goes back exactly as it was
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    dry = "--dry" in sys.argv
    for slug in [a for a in sys.argv[1:] if not a.startswith("--")]:
        p = os.path.join(NAMES, "anchors_%s.json" % slug)
        before = open(p, "rb").read()
        old = json.loads(before)
        new = fresh_fps(slug)
        assert open(p, "rb").read() == before, "%s: published file changed during rebuild" % slug
        if old.get("glb_center") != new.get("glb_center"):
            print("%-24s REFUSED: glb_center differs (%s vs %s) - frames do not match" % (slug, old.get("glb_center"), new.get("glb_center")))
            continue
        of = {f[0]: f for f in old.get("fps") or []}
        nf = {f[0]: f for f in new.get("fps") or []}
        drift = [i for i in set(of) & set(nf) if of[i][1] is not None and nf[i][1] is not None
                 and max(abs(of[i][1] - nf[i][1]), abs(of[i][2] - nf[i][2])) > 0.01]
        if drift:
            print("%-24s REFUSED: %d shared footprints moved (e.g. %s) - rebuild properly instead" % (slug, len(drift), drift[:5]))
            continue
        add = [nf[i] for i in sorted(set(nf) - set(of))]
        if not add:
            print("%-24s nothing missing (%d fps)" % (slug, len(of)))
            continue
        old["fps"] = (old.get("fps") or []) + add
        if not dry:
            json.dump(old, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        print("%-24s %s %d footprints (%s) -> fps %d; anchors untouched (%d)" % (
            slug, "would add" if dry else "added", len(add), ",".join(str(a[0]) for a in add[:12]), len(old["fps"]), len(old.get("anchors") or [])))


if __name__ == "__main__":
    main()

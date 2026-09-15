"""ce_snap_focus.py -- viewport snapshots of the scene CityEngine currently has open (after scripts/ce_lod3_datasmith.py,
which leaves the generated district on screen). Kept separate from the export driver because snapshots stalled the Marina
batch run (12 Sep) and must never cost an export.

    python scripts/ce_snap_focus.py <slug> <name> <label> <fi,fi,...> [<label2> <fi,...> ...]
    e.g. python scripts/ce_snap_focus.py damachills damachills_lod3 orchid 484,485,482,483 loreto 14,15,16,17,19

Writes data/ce/_datasmith/<name>_<label>.png (1920 x 1080) per label, framed on the b<fi>_* shapes.
"""
import os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "ce", "_datasmith")


def main():
    slug, name = sys.argv[1], sys.argv[2]; pairs = sys.argv[3:]
    from cityengine import CE
    ce = CE()
    shapes = ce.getObjectsFrom(ce.scene, ce.isShape)
    by_fi = {}
    for s in shapes:
        m = re.match(r"b(\d+)_", str(ce.getName(s)))
        if m: by_fi[int(m.group(1))] = s
    print(f"scene has {len(shapes)} shapes, {len(by_fi)} named b<fi>")
    v3 = ce.get3DViews()[0]; ce.setSelection([])
    for label, fis in zip(pairs[0::2], pairs[1::2]):
        sel = [by_fi[int(x)] for x in fis.split(",") if int(x) in by_fi]
        if not sel: print(f"{label}: none of {fis} in scene"); continue
        v3.frame(sel)
        try: ce.waitForUIIdle()
        except Exception: time.sleep(2)
        p = os.path.join(OUT, f"{name}_{label}.png"); v3.snapshot(p, 1920, 1080); print(f"{label}: {len(sel)} shapes -> {p}")


if __name__ == "__main__":
    main()

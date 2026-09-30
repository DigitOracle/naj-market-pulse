"""Stamp a district origin into a GLB, making a local-frame tile self-describing.

A tile exported with CityEngine 2026.1's glTF global offset (-origin) holds coordinates relative to the district
origin, which keeps full precision (0.1 mm against 12.5 cm for absolute UTM in float32; measured 1 Oct 2026). The
viewer (azimuth worker v276, onSky) places such a tile by reading the origin FROM THE TILE, so a tile and its origin
can never be mismatched. This writes it to both the root extras and asset.extras:

    extras.najma_origin_ce_xyz = [x, y, z]   CE frame: x = easting, y = up, z = -northing (metres)

  python scripts/glb_stamp_origin.py <tile.glb> <origin.json>      origin.json = data/ce/<slug>/origin_v5.json
  python scripts/glb_stamp_origin.py <tile.glb> --check            print the stamped origin, if any
"""
import json
import struct
import sys


def read(p):
    b = open(p, "rb").read()
    assert b[:4] == b"glTF", "not a GLB"
    n = struct.unpack("<I", b[12:16])[0]
    return b, json.loads(b[20:20 + n]), 20 + n


def stamped(j):
    e = (j.get("extras") or {}).get("najma_origin_ce_xyz") or ((j.get("asset") or {}).get("extras") or {}).get("najma_origin_ce_xyz")
    return e


def main():
    p = sys.argv[1]
    b, j, end = read(p)
    if "--check" in sys.argv:
        print(stamped(j)); return 0
    o = json.load(open(sys.argv[2], encoding="utf-8"))["origin_ce_xyz"]
    o = [float(v) for v in o]
    j.setdefault("extras", {})["najma_origin_ce_xyz"] = o
    j.setdefault("asset", {}).setdefault("extras", {})["najma_origin_ce_xyz"] = o
    js = json.dumps(j, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    rest = b[end:]
    out = b"glTF" + struct.pack("<I", 2) + struct.pack("<I", 12 + 8 + len(js) + len(rest)) + struct.pack("<I", len(js)) + b"JSON" + js + rest
    open(p, "wb").write(out)
    print("stamped", p, o)
    return 0


if __name__ == "__main__":
    sys.exit(main())

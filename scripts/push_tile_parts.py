"""Publish a multi-key district tile: sky_<slug>_p<n> parts plus a skyparts_<slug> index.

A NEW namespace. sky_<slug> is untouched and keeps serving whatever it serves today, so nothing changes for
any reader until the page chooses to use the index. That matters because the single-key tile is what every
district currently renders from.

    sky_<slug>_p0 ... p<n>   standalone gzipped GLBs, same /img/ route, a whole number of buildings each
    skyparts_<slug>          {parts, buildings, items:[{part,key,buildings,gz,first,last}]}

The page reads skyparts_<slug>, fetches each part and adds it to the same scene. Buildings keep their b<i>
names and materials, so tapping, the floor stack and every published bld3_<slug>_b<i> key keep working.

Verifies like every other push here: each key is fetched back and checked to be a gzipped glTF, and the
index is fetched back and checked to list the parts that actually stored. Retries, because a transient DNS
failure took three districts' payloads on 23 Sep while the generate was perfectly good.

  python scripts/push_tile_parts.py althanyahfifth
  python scripts/push_tile_parts.py althanyahfifth --dry-run
  python scripts/push_tile_parts.py althanyahfifth --ver v5     local-frame lane (Rings' names, 28 Sep):
        sky_<slug>_v5_p<n> + skyparts_<slug>_v5 + skyorigin_<slug>. Never touches the v4 keys above.
        skyorigin_<slug> = origin_v5.json: CE-frame = vertex + origin_ce_xyz, applied as the object's
        position in float64. The index carries the same origin, so a reader holding one has the other.
"""
import base64
import gzip
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_avail_index import env_token, WORKER  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
UA = {"User-Agent": "najma-market-pulse/1.0"}
CAP = 5 * 1024 * 1024


def put(key, blob, ctype, tok, tries, wait):
    body = json.dumps({"imageName": key, "image": base64.b64encode(blob).decode(),
                       "contentType": ctype}).encode()
    for attempt in range(1, tries + 1):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(
                WORKER + "/ingest_market", data=body, method="POST",
                headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", **UA}), timeout=300))
            h = urllib.request.urlopen(urllib.request.Request(
                WORKER + "/img/" + key, headers={**UA, "Accept-Encoding": "gzip"}), timeout=180)
            back = h.read()
            return bool(r.get("ok")), back
        except Exception as e:
            if attempt < tries:
                print("  %-28s attempt %d/%d failed (%s) - retrying" % (key, attempt, tries, str(e)[:60]))
                time.sleep(wait)
            else:
                print("  %-28s FAILED after %d: %s" % (key, tries, str(e)[:80]))
    return False, b""


def main():
    ver = sys.argv[sys.argv.index("--ver") + 1] if "--ver" in sys.argv else "v4"
    argv = list(sys.argv[1:])
    if "--ver" in argv:                      # drop the flag AND its value, or "v5" becomes the slug
        i = argv.index("--ver"); del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    slug = args[0]
    dry = "--dry-run" in sys.argv
    tries = int(sys.argv[sys.argv.index("--tries") + 1]) if "--tries" in sys.argv else 5
    wait = int(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 120
    d = os.path.join(ROOT, "data", "ce", "_glb", "parts", slug) if ver == "v4" else         os.path.join(ROOT, "data", "ce", "_glb", "parts", slug, ver)
    man = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    if man.get("ver", "v4") != ver:
        print("manifest in %s is %s, asked for %s - refusing" % (d, man.get("ver"), ver))
        return 2
    vs = "" if ver == "v4" else "_" + ver    # v4 keeps its published names exactly
    origin = man.get("origin")
    if ver != "v4" and not origin:
        print("%s has no origin - a local-frame tile without its origin lands at 0,0. refusing" % slug)
        return 2
    tok = None if dry else env_token("INGEST_TOKEN")
    # The origin goes first: parts without it would draw 340 km from the city.
    if origin and not dry:
        okey = "skyorigin_%s" % slug
        ok, back = put(okey, gzip.compress(json.dumps(origin).encode(), 9), "application/json", tok, tries, wait)
        good = False
        try:
            good = json.loads(gzip.decompress(back)).get("origin_ce_xyz") == origin["origin_ce_xyz"]
        except Exception:
            pass
        print("  %-28s origin %s -> stored=%s served-matches=%s" % (okey, origin["origin_ce_xyz"], ok, good))
        if not (ok and good):
            print("origin did not store - no parts pushed"); return 1
    elif origin:
        print("  %-28s origin %s  (dry run)" % ("skyorigin_%s" % slug, origin["origin_ce_xyz"]))

    stored, bad = [], []
    for it in man["items"]:
        key = "sky_%s%s_p%d" % (slug, vs, it["part"])
        raw = open(os.path.join(d, it["file"]), "rb").read()
        blob = gzip.compress(raw, 9)
        if len(blob) > CAP:
            print("  %-28s %5.2f MB gz - OVER THE CAP, skipped" % (key, len(blob) / 1048576.0))
            bad.append(key)
            continue
        if dry:
            print("  %-28s %5d buildings  %5.2f MB gz  (dry run)" % (key, it["buildings"], len(blob) / 1048576.0))
            stored.append({"part": it["part"], "key": key, "buildings": it["buildings"],
                           "gz": len(blob), "first": it["first"], "last": it["last"]})
            continue
        ok, back = put(key, blob, "model/gltf-binary", tok, tries, wait)
        served = back[:2] == b"\x1f\x8b" and gzip.decompress(back)[:4] == b"glTF"
        print("  %-28s %5d buildings  %5.2f MB gz -> stored=%s served-as-gzip-glb=%s"
              % (key, it["buildings"], len(blob) / 1048576.0, ok, served))
        if ok and served:
            stored.append({"part": it["part"], "key": key, "buildings": it["buildings"],
                           "gz": len(blob), "first": it["first"], "last": it["last"]})
        else:
            bad.append(key)

    # The index lists only what actually STORED. A page told about a part that is not there would show a
    # district with a hole in it and no way to know why - the same failure as a bld3 tap hitting a 404.
    idx = {"slug": slug, "parts": len(stored), "buildings": sum(p["buildings"] for p in stored),
           "key_pattern": "sky_%s%s_p<n>" % (slug, vs), "items": stored}
    if origin:
        idx["ver"] = ver; idx["origin"] = origin
    ikey = "skyparts_%s%s" % (slug, vs)
    if dry:
        print("  %-28s %d parts, %d buildings  (dry run)" % (ikey, idx["parts"], idx["buildings"]))
    else:
        blob = gzip.compress(json.dumps(idx).encode(), 9)
        ok, back = put(ikey, blob, "application/json", tok, tries, wait)
        n = 0
        try:
            n = len(json.loads(gzip.decompress(back)).get("items", []))
        except Exception:
            pass
        print("  %-28s %d parts -> stored=%s served-with-%d-parts=%s"
              % (ikey, idx["parts"], ok, n, n == idx["parts"]))
        if not ok or n != idx["parts"]:
            bad.append(ikey)

    print()
    print("attempted %d | stored+served %d | failed %d%s"
          % (len(man["items"]) + 1, len(stored) + (0 if ikey in bad else 1), len(bad),
             (": " + " ".join(bad)) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

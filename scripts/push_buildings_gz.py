"""Push per-building LOD 3 payloads to KV, one key per building, and verify each is served back.

KV key = bld3_<slug>_<bid>, e.g. bld3_businessbay_b603. A new namespace: it overwrites nothing, and the
district tile (sky_<slug>) is untouched and keeps shipping flat at LOD 1.

This is the delivery half of the LOD 3 answer. LOD 3 cannot ride in a district tile - Business Bay is 6.49 MB
gzipped at >=200 m against a 5 MB cap, and the budget buys about eleven buildings. Per building it is trivial:
the largest tower in Business Bay is 0.60 MB gzipped, so a tap costs a fraction of what the district already
pays, and only when someone asks for it.

Verifies the same way push_sky_gz.py does - fetches the key back and checks the bytes are a gzipped glTF -
because "the push ran" is not evidence, and a silent upload loss read as success earlier today.

  python scripts/push_buildings_gz.py businessbay
  python scripts/push_buildings_gz.py businessbay --dry-run
  python scripts/push_buildings_gz.py businessbay --only b603,b573
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


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    slug = args[0]
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    dry = "--dry-run" in sys.argv
    tries = int(sys.argv[sys.argv.index("--tries") + 1]) if "--tries" in sys.argv else 5
    wait = int(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 120
    d = os.path.join(ROOT, "data", "ce", "_glb", "bld", slug)
    man = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    tok = None if dry else env_token("INGEST_TOKEN")

    ok_n, bad = 0, []
    for it in man["items"]:
        if only and it["bid"] not in only:
            continue
        key = "bld3_%s_%s" % (slug, it["bid"])
        p = os.path.join(d, it["bid"] + ".glb")
        raw = open(p, "rb").read()
        gz = gzip.compress(raw, 9)
        if len(gz) > CAP:
            print("%-28s %6d KB gz - OVER THE CAP, skipped" % (key, len(gz) // 1024))
            bad.append(it["bid"])
            continue
        if dry:
            print("%-28s %6d KB -> %5d KB gz  (dry run)" % (key, len(raw) // 1024, len(gz) // 1024))
            ok_n += 1
            continue
        body = json.dumps({"imageName": key, "image": base64.b64encode(gz).decode(),
                           "contentType": "model/gltf-binary"}).encode()
        # Retry the upload. A whole district's payloads were lost to a transient DNS failure
        # (getaddrinfo) on 23 Sep while the generate - the expensive half - was perfectly good. The push is
        # seconds; not retrying it throws away minutes of CityEngine for a network blip.
        done, last = False, ""
        for attempt in range(1, tries + 1):
            try:
                r = json.load(urllib.request.urlopen(urllib.request.Request(
                    WORKER + "/ingest_market", data=body, method="POST",
                    headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", **UA}), timeout=180))
                h = urllib.request.urlopen(urllib.request.Request(
                    WORKER + "/img/" + key, headers={**UA, "Accept-Encoding": "gzip"}), timeout=120)
                b = h.read()
                served = b[:2] == b"\x1f\x8b" and gzip.decompress(b)[:4] == b"glTF"
                print("%-28s %6d KB -> %5d KB gz -> stored=%s served-as-gzip-glb=%s" % (
                    key, len(raw) // 1024, len(gz) // 1024, r.get("ok"), served))
                if r.get("ok") and served:
                    ok_n += 1
                    done = True
                break
            except Exception as e:
                last = str(e)[:90]
                if attempt < tries:
                    print("%-28s attempt %d/%d failed (%s) - retrying" % (key, attempt, tries, last))
                    time.sleep(wait)
        if not done:
            if last:
                print("%-28s FAILED after %d attempts: %s" % (key, tries, last))
            bad.append(it["bid"])

    # THE INDEX. 18 of Business Bay's 654 buildings have a payload, and the page cannot know which without
    # being told - a tap on any other bid would 404. Without this the twin would be a feature whose NORMAL
    # case is a failed request: a console full of 404s, and on a slow network every tap feels broken. One key
    # per district removes the guessing, and carrying gz lets the page warn that 0.6 MB is coming.
    if not only and "--no-index" not in sys.argv:
        idx = {"slug": slug, "key": "bld3_%s_<bid>" % slug,
               "buildings": [{"bid": r["bid"], "name": r["name"], "triangles": r["triangles"], "gz": r["gz"]}
                             for r in man["items"] if r["bid"] not in bad],
               "source": man.get("source")}
        key = "bld3_index_%s" % slug
        gz = gzip.compress(json.dumps(idx).encode(), 9)
        if dry:
            print("%-28s %5d KB gz, %d buildings  (dry run)" % (key, len(gz) // 1024, len(idx["buildings"])))
        else:
            body = json.dumps({"imageName": key, "image": base64.b64encode(gz).decode(),
                               "contentType": "application/json"}).encode()
            r = json.load(urllib.request.urlopen(urllib.request.Request(
                WORKER + "/ingest_market", data=body, method="POST",
                headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", **UA}), timeout=180))
            h = urllib.request.urlopen(urllib.request.Request(
                WORKER + "/img/" + key, headers={**UA, "Accept-Encoding": "gzip"}), timeout=120)
            back = json.loads(gzip.decompress(h.read()))
            print("%-28s %5d KB gz -> stored=%s served-with-%d-buildings=%s" % (
                key, len(gz) // 1024, r.get("ok"), len(back.get("buildings", [])),
                len(back.get("buildings", [])) == len(idx["buildings"])))

    print()
    print("attempted %d | stored+served %d | failed %d%s" % (
        ok_n + len(bad), ok_n, len(bad), (": " + " ".join(bad)) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

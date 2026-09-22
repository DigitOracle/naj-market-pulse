"""Push a district's ground aerial (the water-graded one) to KV as ground_<slug>_jpg.

The twin fetches /img/ground_<slug>_jpg as its OWN asset - it is not baked into the GLB - so a new ground image needs
neither a re-mass nor a repack, only this. That matters: on 22 Sep the water fix was described as needing a repack, which
would have queued behind a CityEngine run measured in hours. It needed a one-image push instead.

  python scripts/push_ground.py dubaimarina
  python scripts/push_ground.py --all
"""
import os, sys, base64, json, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")
WORKER = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
CAP = 5 * 1024 * 1024
sys.path.insert(0, HERE)


def push(slug, tok):
    p = os.path.join(CE, slug, "ground_imagery.jpg")
    if not os.path.exists(p):
        print("%-26s no ground image" % slug); return False
    n = os.path.getsize(p)
    if n > CAP:
        print("%-26s %.2f MB OVER the 5 MB cap - not pushed" % (slug, n / 1048576.0)); return False
    # the same field names build_plans_index.push_img uses - imageName/image/contentType, not name/b64
    body = json.dumps({"imageName": "ground_%s_jpg" % slug, "image": base64.b64encode(open(p, "rb").read()).decode(),
                       "contentType": "image/jpeg"}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json",
                                          "User-Agent": "najma-ground/1.0"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
        print("%-26s %.2f MB -> ok=%s" % (slug, n / 1048576.0, r.get("ok"))); return bool(r.get("ok"))
    except Exception as e:
        print("%-26s PUSH FAILED: %s" % (slug, str(e).splitlines()[0][:70])); return False


def main():
    from build_avail_index import env_token
    tok = env_token("INGEST_TOKEN")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        args = sorted(d for d in os.listdir(CE)
                      if os.path.exists(os.path.join(CE, d, "ground_imagery.orig.jpg")))
    ok = sum(1 for s in args if push(s, tok))
    print("pushed %d of %d" % (ok, len(args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

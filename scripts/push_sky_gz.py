"""Push a district's packed v3 model to the store under its exact key, gzipped for transport.

KV key = sky_<slug>. The Worker's /img/ route sees the gzip magic and serves it with Content-Encoding: gzip (v86); the browser
inflates it transparently. Cap (5 MB) applies to what is stored. Verifies by fetching it back.

Usage: python scripts/push_sky_gz.py <slug> [<slug> ...]
"""
import base64, gzip, json, os, sys, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, WORKER  # noqa: E402
UA = {"User-Agent": "najma-market-pulse/1.0"}

def main():
    tok = env_token("INGEST_TOKEN")
    # --ver picks the build lane (default v3, the live one). Its VALUE has to be dropped from the slug list too
    # or "--ver v4" pushes a district called "v4"; the old filter only dropped the flag itself.
    ver = sys.argv[sys.argv.index("--ver") + 1] if "--ver" in sys.argv else "v3"
    argv = list(sys.argv[1:])
    if "--ver" in argv:
        i = argv.index("--ver"); del argv[i:i + 2]
    for t in [a for a in argv if not a.startswith("--")]:
        p = os.path.join(ROOT, "data", "ce", "_glb", f"sky_{t}_{ver}_0.glb")
        if not os.path.exists(p): print(f"{t}: no {ver} glb"); continue
        raw = open(p, "rb").read(); gz = gzip.compress(raw, 9)
        if len(gz) > 5 * 1024 * 1024: print(f"{t}: {len(gz)//1024} KB gzipped exceeds the cap - split the tile"); continue
        # v3 IS the live lane and owns the bare sky_<slug> key. Any other lane gets its own key, because
        # pushing a v4 build to sky_<slug> would silently replace a district's live tile with an experimental
        # one - and the push would report stored=True while doing it. Nothing has done that; this keeps it so.
        # --live is the deliberate act of promoting a non-v3 build to the live tile. It exists so that
        # replacing what the twin serves is something someone TYPED, never something a default did.
        key = f"sky_{t}" if (ver == "v3" or "--live" in sys.argv) else f"sky_{t}_{ver}"
        body = json.dumps({"imageName": key, "image": base64.b64encode(gz).decode(), "contentType": "model/gltf-binary"}).encode()
        r = json.load(urllib.request.urlopen(urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST", headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", **UA}), timeout=180))
        # Verify the key we actually WROTE. Fetching sky_<slug> after pushing sky_<slug>_v4 would confirm the
        # v3 tile is healthy and report it as proof the v4 push worked.
        h = urllib.request.urlopen(urllib.request.Request(WORKER + f"/img/{key}", headers={**UA, "Accept-Encoding": "gzip"}), timeout=120); b = h.read()
        ok = b[:2] == b"\x1f\x8b" and gzip.decompress(b)[:4] == b"glTF"
        print(f"{key}: {len(raw)//1024} KB -> {len(gz)//1024} KB gz -> stored={r.get('ok')} served-as-gzip-glb={ok}")

if __name__ == "__main__":
    main()

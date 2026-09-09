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
    for t in [a for a in sys.argv[1:] if not a.startswith("--")]:
        p = os.path.join(ROOT, "data", "ce", "_glb", f"sky_{t}_v3_0.glb")
        if not os.path.exists(p): print(f"{t}: no v3 glb"); continue
        raw = open(p, "rb").read(); gz = gzip.compress(raw, 9)
        if len(gz) > 5 * 1024 * 1024: print(f"{t}: {len(gz)//1024} KB gzipped exceeds the cap - split the tile"); continue
        body = json.dumps({"imageName": f"sky_{t}", "image": base64.b64encode(gz).decode(), "contentType": "model/gltf-binary"}).encode()
        r = json.load(urllib.request.urlopen(urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST", headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", **UA}), timeout=180))
        h = urllib.request.urlopen(urllib.request.Request(WORKER + f"/img/sky_{t}", headers={**UA, "Accept-Encoding": "gzip"}), timeout=120); b = h.read()
        ok = b[:2] == b"\x1f\x8b" and gzip.decompress(b)[:4] == b"glTF"
        print(f"sky_{t}: {len(raw)//1024} KB -> {len(gz)//1024} KB gz -> stored={r.get('ok')} served-as-gzip-glb={ok}")

if __name__ == "__main__":
    main()

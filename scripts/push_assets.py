"""Push Najma UI assets (backgrounds, splash video) into the azimuth-2 Worker KV.
Uses the same /ingest_market image channel as push_heatmap.py (5 MB cap per asset).
Env: AZIMUTH_URL, INGEST_TOKEN.

Usage:
  python scripts/push_assets.py                       # push bg_board + bg_market
  python scripts/push_assets.py --splash path.mp4     # also push the splash video
"""
import os, sys, json, base64, urllib.request

ASSETS = os.path.join(os.path.expanduser("~"), "Downloads", "najma_ui_assets", "backgrounds")
PUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public")
DEFAULTS = [  # (kv name, local file, content type)
    ("bg_board",  os.path.join(ASSETS, "bg1_night_cc0.jpg"), "image/jpeg"),
    ("bg_market", os.path.join(ASSETS, "bg_banner_cc0.jpg"), "image/jpeg"),  # v53: purpose-cropped skyline strip (CC0, Robert Bock) — Burj crop read as mud at banner size
    ("mp_basemap", os.path.join(PUB, "mp_basemap.json"), "application/json"),
    ("mp_areas", os.path.join(PUB, "mp_areas.json"), "application/json"),  # v57 community polygons (choropleth)
]

def push(name, path, ctype, url, token):
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) > 5 * 1024 * 1024 and ctype == "model/gltf-binary":
        # v86: a district GLB is mostly JSON (node/mesh/accessor tables, ~1.6 KB per building) and gzips 5-6x.
        # Store it gzipped; the Worker's /img/ route sees the gzip magic and serves it with Content-Encoding: gzip,
        # which the browser's fetch (and so GLTFLoader) inflates transparently. Cap applies to what is stored.
        import gzip
        gz = gzip.compress(raw, 9)
        print(f"{name}: {len(raw)//1024} KB raw -> {len(gz)//1024} KB gzipped for transport")
        raw = gz
    if len(raw) > 5 * 1024 * 1024:
        print(f"SKIP {name}: {len(raw)//1024} KB exceeds the 5 MB ingest cap — slim and re-push")
        return
    body = json.dumps({"imageName": name, "image": base64.b64encode(raw).decode(),
                       "contentType": ctype}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/ingest_market", data=body,
        headers={"X-Azimuth-Ingest": token, "Content-Type": "application/json",
                 "User-Agent": "najma-market-pulse/1.0"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        print(name, "->", r.status, r.read().decode()[:120])

def main():
    import re
    url = os.environ["AZIMUTH_URL"]; token = os.environ["INGEST_TOKEN"]
    jobs = list(DEFAULTS)
    # Development card images: drop files named after the development (e.g. "EYWA.jpg",
    # "Masaar.png") into Downloads\najma_ui_assets\developments\ — pushed as dev_<slug>,
    # picked up automatically by the radar cards. Only use images Kendall has rights to.
    devdir = os.path.join(os.path.dirname(ASSETS), "developments")
    if os.path.isdir(devdir):
        for f in sorted(os.listdir(devdir)):
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                slug = re.sub(r"[^a-z0-9]", "", os.path.splitext(f)[0].lower())
                if slug:
                    jobs.append(("dev_" + slug, os.path.join(devdir, f),
                                 "image/png" if f.lower().endswith(".png") else "image/jpeg"))
    # Satellite area banners from make_area_banners.py -> KV as sat_<slug>, used by /area pages
    # and radar cards. Real imagery of the actual location beats stock photography.
    bandir = os.path.join(PUB, "banners")
    if "--banners" in sys.argv and os.path.isdir(bandir):
        for f in sorted(os.listdir(bandir)):
            if f.lower().endswith(".jpg"):
                jobs.append((os.path.splitext(f)[0], os.path.join(bandir, f), "image/jpeg"))
    # CE skyline massings from ce_batch.py -> KV as sky_<slug>, served to /skyline/<slug>
    # (CE names single-file GLB exports "<base>_0.glb" — strip the suffix for the KV name)
    glbdir = os.path.join(PUB, "..", "data", "ce", "_glb")
    if "--skylines" in sys.argv and os.path.isdir(glbdir):
        for f in sorted(os.listdir(glbdir)):
            if f.endswith(".glb") and not f.endswith(".merged.glb"):     # v86: skip the packer's intermediate copy
                kvname = re.sub(r"_0$", "", os.path.splitext(f)[0])
                only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None   # v86: --only jltnorth,jltsouth
                if only and not any(kvname == f"sky_{o}" or kvname.startswith(f"sky_{o}_") for o in only): continue
                jobs.append((kvname, os.path.join(glbdir, f), "model/gltf-binary"))
    if "--splash" in sys.argv:
        vid = sys.argv[sys.argv.index("--splash") + 1]
        jobs.append(("splash", vid, "video/mp4"))
    for name, path, ctype in jobs:
        if not os.path.exists(path):
            print(f"skip {name}: {path} not found"); continue
        push(name, path, ctype, url, token)

if __name__ == "__main__":
    main()

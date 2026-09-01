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
    if len(raw) > 5 * 1024 * 1024:
        sys.exit(f"{name}: {len(raw)//1024} KB exceeds the Worker's 5 MB ingest cap — compress first")
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
            if f.endswith(".glb"):
                kvname = re.sub(r"_0$", "", os.path.splitext(f)[0])
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

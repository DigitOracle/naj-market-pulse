"""push_cluster_films.py -- publish the finished DAMAC Hills 720p films (30 s district film + per-cluster endings) into the
Najma app's video store so the app can serve them.

Data push into Cloudflare KV only (no worker deploy). Same mechanism as push_unreal_clip.py: bytes go to KV as vid_<key> /
vidposter_<key> through wrangler (cwd C:\\Dev\\azimuth-worker, --env azimuth2, binding MEETINGS), served range-capable at
/video/<key>, and the register img_videos (JSON {"items":[...]}) gains one item per film with kind:"unreal",
district:"damachills". Cluster items also carry "cluster": <id> and "members": [names] from data/ce/damachills/clusters.json
so the app can later match "I'm interested in Orchid B" style requests. Other register items are never touched; an existing
item with the same key is replaced (idempotent, re-runnable).

    python scripts/push_cluster_films.py                 # all films in FILMS (clusters 4 and 6 are NOT listed: still rendering)
    python scripts/push_cluster_films.py unreal_damachills_c3 unreal_damachills_film30      # single keys
    python scripts/push_cluster_films.py --register-only # rebuild the img_videos items without re-uploading bytes
    python scripts/push_cluster_films.py --verify        # only the HTTP 206 / register check
    python scripts/push_cluster_films.py --posters-only unreal_damachills_c3   # re-cut + re-put the poster only

Posters are cut with ffmpeg (1280x720, -q:v 4) at 27 s for cluster films (the ending, close to the cluster's buildings) and
at 4 s for the district film, saved next to the mp4 as <key>_poster.jpg.
KV value limit is 25 MB per key; the films are 15 to 18 MB. A wrangler login/auth failure is printed verbatim and stops the run.
"""
import json, os, re, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import WORKER, env_token, push

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
VIDEO = os.path.join(ROOT, "data", "video")
CLUSTERS = os.path.join(ROOT, "data", "ce", "damachills", "clusters.json")
WD = r"C:\Dev\azimuth-worker"
DISTRICT = "damachills"
UA = {"User-Agent": "najma-market-pulse/1.0"}
KV_LIMIT = 25 * 1024 * 1024

# key -> (scope, cluster id or None, name, title, mp4 basename). Clusters 4 and 6 are deliberately absent (still rendering).
FILMS = {
    "unreal_damachills_film30": ("district30", None, "Damac Hills", "30 s film", "unreal_damachills_film30_preview_v6.mp4"),
    "unreal_damachills_c1": ("cluster", 1, "Carson & Artesia", None, "unreal_damachills_cluster1_carson-artesia_preview.mp4"),
    "unreal_damachills_c2": ("cluster", 2, "Golf Horizon & Golf Terrace", None, "unreal_damachills_cluster2_golf-horizon-golf-terrace_preview.mp4"),
    "unreal_damachills_c3": ("cluster", 3, "Golf Promenade & Orchid", None, "unreal_damachills_cluster3_golf-promenade-orchid_preview.mp4"),
    "unreal_damachills_c5": ("cluster", 5, "Rochester & Rockwood", None, "unreal_damachills_cluster5_rochester-rockwood_preview.mp4"),
    "unreal_damachills_c7": ("cluster", 7, "Silver Springs", None, "unreal_damachills_cluster7_silver-springs_preview.mp4"),
    "unreal_damachills_c8": ("cluster", 8, "Whitefield", None, "unreal_damachills_cluster8_whitefield_preview.mp4"),
    "unreal_damachills_c9": ("cluster", 9, "Pelham & Trinity", None, "unreal_damachills_cluster9_pelham-trinity_preview.mp4"),
}

AUTH_RE = re.compile(r"(not authenticated|not logged in|login|log in|oauth|authentication error|CLOUDFLARE_API_TOKEN|code: 10000|Unable to authenticate|invalid.*token)", re.I)


def redact(s):
    return re.sub(r"key=[A-Za-z0-9_]*", "key=…", s or "")


def cluster_members():
    d = json.load(open(CLUSTERS, encoding="utf-8"))
    return {c["id"]: [m["name"] for m in c.get("members") or []] for c in d.get("clusters") or []}


POSTER_AT = {"cluster": "27", "district30": "4"}      # cluster films share the district opening; 27 s is the ending, close to the cluster's buildings


def make_poster(mp4, jpg, at, force=False):
    if not force and os.path.exists(jpg) and os.path.getmtime(jpg) >= os.path.getmtime(mp4):
        return True
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", at, "-i", mp4, "-frames:v", "1", "-vf", "scale=1280:720", "-q:v", "4", jpg],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0 or not os.path.exists(jpg):
        print("  FAIL poster " + os.path.basename(jpg) + "\n" + (r.stderr or r.stdout)[-400:], flush=True)
        return False
    return True


def kv_put(k, path):
    size = os.path.getsize(path)
    if size > KV_LIMIT:
        print(f"  FAIL {k}: {size} bytes exceeds the 25 MB KV value limit", flush=True)
        return False
    cmd = ["npx", "wrangler", "kv", "key", "put", "--env", "azimuth2", "--binding", "MEETINGS", k, "--path", os.path.abspath(path)]
    r = subprocess.run(cmd, cwd=WD, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=True, timeout=900)
    ok = r.returncode == 0
    out = redact((r.stderr or "") + (r.stdout or ""))
    print(("  ok  " if ok else "  FAIL") + f" {k} <- {os.path.basename(path)} ({size//1024} KB)" + ("" if ok else "\n" + out[-600:]), flush=True)
    if not ok and AUTH_RE.search(out):
        print("\nwrangler login/auth error - stopping. Verbatim output:\n" + out, flush=True)
        sys.exit(2)
    return ok


def read_register():
    req = urllib.request.Request(WORKER + "/img/videos?t=" + str(int(time.time())), headers=UA)
    reg = json.load(urllib.request.urlopen(req, timeout=60))
    if not isinstance(reg, dict) or not isinstance(reg.get("items"), list):
        raise SystemExit("img_videos did not parse to {items:[...]}: " + json.dumps(reg)[:200])
    return reg


def item_for(key, members):
    scope, cid, name, title, _mp4 = FILMS[key]
    it = {"key": key, "kind": "unreal", "scope": scope, "district": DISTRICT, "name": name,
          "title": title or (name + " ending"),
          "src": "/video/" + key, "poster": "/video/" + key + "?poster=1", "added": time.strftime("%Y-%m-%d")}
    if scope == "cluster":
        it["cluster"] = cid
        it["members"] = members.get(cid, [])
    return it


def update_register(keys):
    members = cluster_members()
    reg = read_register()                        # read the LIVE document first, then merge, then write the whole thing back
    before = len(reg["items"])
    others = [v for v in reg["items"] if v.get("key") not in keys]
    reg["items"] = others + [item_for(k, members) for k in keys]
    raw = json.dumps(reg, ensure_ascii=False).encode()
    assert len(raw) < KV_LIMIT
    r = push("videos", reg, env_token("INGEST_TOKEN"))
    print(f"register img_videos -> {r.get('ok')} ({before} -> {len(reg['items'])} items, {len(raw)//1024} KB)", flush=True)
    return bool(r.get("ok"))


def verify(keys):
    ok_all = True
    for k in keys:
        url = WORKER + "/video/" + k
        r = subprocess.run(["curl", "-s", "-o", os.devnull, "-w", "%{http_code} %{size_download}", "-r", "0-0", url], capture_output=True, text=True, timeout=120)
        code = (r.stdout or "").strip()
        rp = subprocess.run(["curl", "-s", "-o", os.devnull, "-w", "%{http_code} %{size_download}", url + "?poster=1"], capture_output=True, text=True, timeout=120)
        pc = (rp.stdout or "").strip()
        good = code.startswith("206")
        ok_all &= good
        print(f"  {'ok  ' if good else 'FAIL'} {k}: range GET {code} (want 206) | poster {pc}", flush=True)
    reg = read_register()
    have = {v.get("key") for v in reg["items"]}
    missing = [k for k in FILMS if k not in have]
    print(f"img_videos parses: {len(reg['items'])} items; damachills film items present: {len(FILMS) - len(missing)}/{len(FILMS)}"
          + (f"; missing {missing}" if missing else ""), flush=True)
    return ok_all and not missing


def main(argv):
    flags = {a for a in argv if a.startswith("--")}
    keys = [a for a in argv if not a.startswith("--")] or list(FILMS)
    bad = [k for k in keys if k not in FILMS]
    if bad:
        raise SystemExit("unknown key(s): %s (known: %s)" % (bad, ", ".join(FILMS)))
    if "--verify" in flags:
        return 0 if verify(keys) else 1
    if "--posters-only" in flags:                 # re-cut + re-put vidposter_<key> only; video bytes and img_videos untouched
        ok = True
        for k in keys:
            mp4, jpg = os.path.join(VIDEO, FILMS[k][4]), os.path.join(VIDEO, k + "_poster.jpg")
            ok &= bool(make_poster(mp4, jpg, POSTER_AT[FILMS[k][0]], force=True) and kv_put("vidposter_" + k, jpg))
        return 0 if ok else 1
    if "--register-only" not in flags:
        pushed = []
        for k in keys:
            mp4 = os.path.join(VIDEO, FILMS[k][4])
            jpg = os.path.join(VIDEO, k + "_poster.jpg")
            if not os.path.exists(mp4):
                print(f"  FAIL {k}: missing {mp4}", flush=True); continue
            print(f"publishing {k}", flush=True)
            if make_poster(mp4, jpg, POSTER_AT[FILMS[k][0]]) and kv_put("vid_" + k, mp4) and kv_put("vidposter_" + k, jpg):
                pushed.append(k)
        keys = pushed
        if not keys:
            print("nothing pushed; register untouched"); return 1
    ok = update_register(keys)
    return 0 if (verify(keys) and ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

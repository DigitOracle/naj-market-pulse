"""push_unreal_clip.py -- publish a pre-rendered UnReal clip for one building so the twin's UnReal button has something to play
when the laptop streamer is off.

Bytes go to KV as vid_<key> / vidposter_<key> (the same store the video tours use, served range-capable at /video/<key>) through
wrangler, and the register img_videos gains an item with kind:"unreal", district and footprint index i (the twin matches on those;
the map's tour lists ignore kind:"unreal"). Never touches other items.

    python scripts/push_unreal_clip.py <slug> <footprint_i> "<name>" <mp4> <poster.jpg> ["<title>"]
    e.g. python scripts/push_unreal_clip.py sobhaheartland 1457 "Sobha Creek Vistas Heights" data/video/unreal_sobhaheartland_1457.mp4 data/video/unreal_sobhaheartland_1457.jpg "12 s sweep"
"""
import json, os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import WORKER, env_token, push

slug, i, name, mp4, poster = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
title = sys.argv[6] if len(sys.argv) > 6 else "12 s sweep"
key = f"unreal_{slug}_{i}"
WD = r"C:\Dev\azimuth-worker"


def kv_put(k, path):
    r = subprocess.run(["npx", "wrangler", "kv", "key", "put", "--env", "azimuth2", "--binding", "MEETINGS", k, "--path", os.path.abspath(path)], cwd=WD, capture_output=True, text=True, shell=True, timeout=900)
    ok = r.returncode == 0
    print(("  ok  " if ok else "  FAIL") + f" {k} <- {os.path.basename(path)} ({os.path.getsize(path)//1024} KB)" + ("" if ok else "\n" + (r.stderr or r.stdout)[-400:]), flush=True)
    return ok


print(f"publishing {key}", flush=True)
assert kv_put("vid_" + key, mp4) and kv_put("vidposter_" + key, poster)
reg = json.load(urllib.request.urlopen(urllib.request.Request(WORKER + "/img/videos?t=" + str(int(time.time())), headers={"User-Agent": "najma-market-pulse/1.0"}), timeout=60))
items = [v for v in (reg.get("items") or []) if v.get("key") != key]
items.append({"key": key, "kind": "unreal", "district": slug, "i": i, "name": name, "title": title, "src": "/video/" + key, "poster": "/video/" + key + "?poster=1", "added": time.strftime("%Y-%m-%d")})
reg["items"] = items
r = push("videos", reg, env_token("INGEST_TOKEN")); print("register img_videos ->", r.get("ok"), f"({len(items)} items)")
head = urllib.request.urlopen(urllib.request.Request(WORKER + "/video/" + key, headers={"Range": "bytes=0-15", "User-Agent": "najma-market-pulse/1.0"}), timeout=60).read(16)
print("served bytes ok:", head[4:8] == b"ftyp")

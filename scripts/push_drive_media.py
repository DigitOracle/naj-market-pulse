"""Upload files into Najjuko's Drive (Najma_Media/<folder>) through the Worker's resumable-upload bridge, 8 MB at a time.

The Worker holds her Drive permission; this machine holds the files. Neither side ever has the whole file in memory. Skips a
file whose name already exists in the target folder (never overwrites). Names follow the bridge convention
YYYY-MM-DD_<track>_<piece>_<length>.mp4 - pass them explicitly with --as, or the local basename is used.

Usage:
  python scripts/push_drive_media.py --folder podcast/quiet_mastery FILE [--as NAME] [FILE [--as NAME] ...]
  python scripts/push_drive_media.py --folder podcast/quiet_mastery --text INDEX.md path/to/index.md
  python scripts/push_drive_media.py --list podcast/quiet_mastery
"""
import json, mimetypes, os, sys, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from build_avail_index import env_token, WORKER  # noqa: E402
CHUNK = 8 * 1024 * 1024
UA = {"User-Agent": "najma-market-pulse/1.0 (drive media)"}

def call(path, method="GET", data=None, headers=None, timeout=300):
    req = urllib.request.Request(WORKER + path, data=data, method=method, headers={**UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)

def upload(key, path, folder, name):
    size = os.path.getsize(path); mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    r = json.load(call(f"/gdrive/upload_start?key={urllib.parse.quote(key)}", "POST", json.dumps({"name": name, "folder": folder, "size": size, "mime": mime}).encode(), {"Content-Type": "application/json"}))
    if r.get("exists"): print(f"  skip {name}: already in Drive"); return True
    uid = r["id"]; t0 = time.time(); sent = 0
    with open(path, "rb") as f:
        while sent < size:
            chunk = f.read(CHUNK); end = sent + len(chunk) - 1
            for attempt in range(3):
                try:
                    j = json.load(call(f"/gdrive/upload_chunk?key={urllib.parse.quote(key)}&id={uid}&start={sent}&end={end}", "PUT", chunk, {"Content-Type": "application/octet-stream"})); break
                except Exception as e:
                    if attempt == 2: raise
                    time.sleep(3)
            sent = end + 1
            print(f"\r  {name}: {sent/1048576:6.1f} / {size/1048576:.1f} MB", end="", flush=True)
    print(f"  -> {'done' if j.get('done') else 'incomplete'} in {time.time()-t0:.0f}s")
    return bool(j.get("done"))

def main():
    key = env_token("READ_KEY"); a = sys.argv[1:]
    if "--list" in a:
        fol = a[a.index("--list") + 1]; L = json.load(call(f"/gdrive/list?key={urllib.parse.quote(key)}&folder={urllib.parse.quote(fol)}"))
        for f in L: print(f"{int(f.get('size') or 0)/1048576:7.1f} MB  {f['name']}")
        return
    folder = a[a.index("--folder") + 1] if "--folder" in a else ""
    if "--text" in a:
        i = a.index("--text"); name, path = a[i + 1], a[i + 2]
        r = json.load(call(f"/gdrive/put_text?key={urllib.parse.quote(key)}", "POST", json.dumps({"folder": folder, "name": name, "text": open(path, encoding="utf-8").read()}).encode(), {"Content-Type": "application/json"}))
        print("text:", name, "->", r.get("ok")); return
    files = []; i = 0
    while i < len(a):
        if a[i] in ("--folder",): i += 2; continue
        if a[i] == "--as": files[-1][1] = a[i + 1]; i += 2; continue
        files.append([a[i], os.path.basename(a[i])]); i += 1
    ok = 0
    for path, name in files:
        if not os.path.exists(path): print("  missing:", path); continue
        try: ok += 1 if upload(key, path, folder, name) else 0
        except Exception as e: print(f"\n  {name}: FAILED {str(e)[:120]}")
    print(f"{ok}/{len(files)} uploaded to Najma_Media/{folder}")

if __name__ == "__main__":
    main()

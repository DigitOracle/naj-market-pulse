"""Put the Valley campaign's own material where the broker can reach it from WhatsApp: floor plans and film stills.

She writes the post inside Azimuth, then has to go hunting for a picture. These are the pictures: Emaar's supplied films cut to
stills, and the ALVA floor plans rendered page by page. Everything is pushed to the Worker's asset store and served at
/img/<key>, so the pick flow can hand her an image she long-presses and posts - no file transfer, no cloud drive, no Firebase.

  floor plans   data/../Downloads/ALVA_TV_FLOORPLANS_*.pdf   -> one JPEG per page, 1080x1920, ready for a story
  stills        the two supplied films                        -> frames at chosen seconds, at the film's own aspect
  plates        VALLEY_BG_*.png                               -> already-made background plates for AI cutaways

Rights: this is Emaar's material for Emaar's own contest, used inside that contest. Nothing from a competing developer goes
in here. Each asset carries its source film and timestamp so a post never claims a still is her own photography.

Output: data/board/valley_assets.json -> KV `valley_assets`, plus one KV image per asset. Pack's assets_on_hand is refreshed.
Usage: python scripts/push_valley_assets.py [--dry]
"""
import base64, glob, json, os, subprocess, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, WORKER  # noqa: E402
DL = os.path.join(os.path.expanduser("~"), "Downloads")
OUT = os.path.join(ROOT, "data", "valley_assets"); os.makedirs(OUT, exist_ok=True)
CAP = 5 * 1024 * 1024                       # the asset channel's per-image ceiling

# (file, key, seconds to cut, caption) - the two films Emaar supplied, matched to the pack's assets_on_hand
FILMS = [
    ("WhatsApp Video 2026-09-03 at 10.29.46 AM (2).mp4", "life", [3, 12, 22, 32, 41],
     "Emaar lifestyle film (45 s, landscape)"),
    ("WhatsApp Video 2026-09-03 at 10.29.46 AM (3).mp4", "brand", [2, 6, 11],
     "Emaar branded film (13 s, vertical)"),
]


def already_there(name):
    """The Worker answers HEAD /img/<name> without sending the bytes - so a re-run only pushes what is missing."""
    try:
        req = urllib.request.Request(WORKER + "/img/" + name, method="HEAD", headers={"User-Agent": "najma-valley-assets/1.0"})
        return urllib.request.urlopen(req, timeout=30).status == 200
    except Exception:
        return False


def push_image(name, path, ctype, tok):
    raw = open(path, "rb").read()
    if len(raw) > CAP: return {"ok": False, "why": f"{len(raw)//1024} KB over the {CAP//1024//1024} MB cap"}
    body = json.dumps({"imageName": name, "image": base64.b64encode(raw).decode(), "contentType": ctype}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-valley-assets/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def floorplans():
    import fitz
    out = []
    for f in sorted(glob.glob(os.path.join(DL, "ALVA_TV_FLOORPLANS_*.pdf"))):
        base = os.path.basename(f)
        beds = "4br" if "4 BR" in base else ("3br" if "3 BR" in base else "x")
        doc = fitz.open(f)
        for i, page in enumerate(doc, 1):
            jpg = os.path.join(OUT, f"valley_fp_{beds}_{i}.jpg")
            if not os.path.exists(jpg): page.get_pixmap(dpi=150).save(jpg, jpg_quality=88)
            out.append({"key": f"valley_fp_{beds}_{i}", "path": jpg, "type": "image/jpeg", "kind": "floorplan",
                        "caption": f"ALVA at The Valley — {beds.upper()} floor plan" + (f", page {i}" if len(doc) > 1 else ""),
                        "source": "Emaar ALVA floor plan pack, " + base})
    return out


def stills():
    out = []
    for fname, tag, secs, label in FILMS:
        src = os.path.join(DL, fname)
        if not os.path.exists(src): print("  missing film:", fname); continue
        for s in secs:
            jpg = os.path.join(OUT, f"valley_still_{tag}_{s:02d}s.jpg")
            if os.path.exists(jpg):
                out.append({"key": f"valley_still_{tag}_{s:02d}s", "path": jpg, "type": "image/jpeg", "kind": "still",
                            "caption": f"{label} — still at {s}s", "source": f"{label}, frame at {s}s"}); continue
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(s), "-i", src, "-frames:v", "1", "-q:v", "3", jpg]
            try: subprocess.run(cmd, check=True, capture_output=True, timeout=180)
            except Exception as e: print("  ffmpeg failed", tag, s, str(e)[:60]); continue
            out.append({"key": f"valley_still_{tag}_{s:02d}s", "path": jpg, "type": "image/jpeg", "kind": "still",
                        "caption": f"{label} — still at {s}s", "source": f"{label}, frame at {s}s"})
    return out


def plates():
    out = []
    for f in sorted(glob.glob(os.path.join(DL, "VALLEY_BG_*.png"))):
        b = os.path.basename(f)[:-4]
        nice = b.replace("VALLEY_BG_", "").split("_", 1)
        out.append({"key": "valley_plate_" + nice[0], "path": f, "type": "image/png", "kind": "plate",
                    "caption": "The Valley — " + (nice[1] if len(nice) > 1 else b).replace("_", " "),
                    "source": "background plate for an AI-assisted cutaway (not a photograph of the project)"})
    return out


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    items = floorplans() + stills() + plates()
    print(f"assets built: {len(items)}  (floorplans {sum(1 for i in items if i['kind']=='floorplan')}, "
          f"stills {sum(1 for i in items if i['kind']=='still')}, plates {sum(1 for i in items if i['kind']=='plate')})")
    tok = None if dry else env_token("INGEST_TOKEN")
    ok = 0
    for it in items:
        kb = os.path.getsize(it["path"]) // 1024
        if dry: print(f"  {it['key']:<28} {kb:>5} KB  {it['caption'][:52]}"); continue
        if already_there(it["key"]):
            ok += 1; print(f"  {it['key']:<28} {kb:>5} KB  already there", flush=True); continue
        r = push_image(it["key"], it["path"], it["type"], tok)
        good = bool(r.get("ok")); ok += good
        print(f"  {it['key']:<28} {kb:>5} KB  {'pushed' if good else 'FAILED ' + str(r)[:60]}", flush=True)
    man = {"updated": __import__("datetime").date.today().isoformat(), "count": len(items),
           "note": "Emaar's own campaign material, used inside Emaar's own contest. Stills carry the film and timestamp they came from; "
                   "plates are generated backgrounds, never presented as photographs of the project.",
           "assets": [{k: v for k, v in i.items() if k != "path"} for i in items]}
    json.dump(man, open(os.path.join(ROOT, "data", "board", "valley_assets.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not dry:
        from build_avail_index import push
        print("valley_assets ->", push("valley_assets", man, tok).get("ok"))
        # tell the morning writer what it can actually reference
        pf = os.path.join(ROOT, "data", "board", "valley_pack.json")
        pk = json.load(open(pf, encoding="utf-8"))
        pk["assets_on_hand"] = ["Emaar lifestyle film 45 s, 1024x576 landscape (5 stills on hand)",
                                "Emaar branded film 13 s, 576x1024 vertical (3 stills on hand)",
                                f"ALVA floor plans, 3BR and 4BR, {sum(1 for i in items if i['kind']=='floorplan')} pages as images",
                                "build-out and rate cards rendered from the register",
                                f"{sum(1 for i in items if i['kind']=='plate')} background plates for AI-assisted cutaways",
                                "all of the above reachable in the chat: she taps Assets on a Valley angle"]
        json.dump(pk, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("valley_pack ->", push("valley_pack", pk, tok).get("ok"))
        print(f"{ok}/{len(items)} images pushed")

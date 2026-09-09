import hashlib
"""One floor-plan library for the app: every floor plan we hold, by developer and project, in one index the Worker serves.

Until now the plans lived in three unconnected places - the Symphony unit cards (KV cards_symphony_*), the Symphony brochure
pages (data/brochure/floorplan_pages, never pushed), and the ALVA pages (KV valley_fp_*) reachable only through the Valley
chat flow. A broker looking for "the floor plans" had no single door. This composes KV `plans_index`:

    { "updated", "count", "developers": [ { "key", "name", "projects": [ { "name", "area", "plans": [
          { "label", "kind": "unit_card" | "page" | "floorplan", "img": "<kv key>", "url": "/img/<key>", "source", "note" } ] } ] } ] }

Sources, and only these (there are no floor-plan links in any of the eleven developers' portfolio scrapes - checked 5 Sep 2026):
  Imtiaz / The Symphony   7 unit-type cards already in KV  +  the brochure's raster floor-plan pages (pushed here, labelled from the
                          deck's own text layer: level stack and view compass in floorplan_labels.json)
  Emaar / ALVA, The Valley  6 pages already in KV (push_valley_assets.py)
Rights: developer material shown to the broker who sells it, inside the app - never re-published. Each entry names its source.

Usage: python scripts/build_plans_index.py [--dry]
"""
import glob, json, os, re, sys, datetime as dt

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
import urllib.request, base64
from build_avail_index import WORKER  # noqa: E402
PAGES = os.path.join(ROOT, "data", "brochure", "floorplan_pages")
LABELS = os.path.join(ROOT, "data", "brochure", "floorplan_labels.json")
CAP = 12 * 1024 * 1024


def there(name):
    """True only when the Worker serves real image bytes for the key. HEAD answers 200 for any key (found 9 Sep 2026: 27 Six Senses plans
    indexed but never uploaded), so fetch the first bytes and check the image signature."""
    try:
        r = urllib.request.urlopen(urllib.request.Request(WORKER + "/img/" + name, headers={"User-Agent": "najma-plans/1.0", "Range": "bytes=0-15"}), timeout=30)
        b = r.read(16)
        return b[:3] == bytes([0xFF, 0xD8, 0xFF]) or b[:4] == bytes([0x89, 0x50, 0x4E, 0x47]) or b[:4] == b"RIFF"
    except Exception:
        return False


def push_img(name, path, tok):
    raw = open(path, "rb").read()
    if len(raw) > CAP: return {"ok": False, "why": "over cap"}
    ctype = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    body = json.dumps({"imageName": name, "image": base64.b64encode(raw).decode(), "contentType": ctype}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-plans/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def symphony_pages(dry, tok):
    lab = json.load(open(LABELS, encoding="utf-8")) if os.path.exists(LABELS) else {}
    per = {k: v for k, v in lab.items() if k not in ("source", "view_compass", "level_stack")}
    plans = []
    for f in sorted(glob.glob(os.path.join(PAGES, "fp_p*.jpg")) + glob.glob(os.path.join(PAGES, "crop_*.png"))):
        base = os.path.basename(f); stem = os.path.splitext(base)[0]
        key = "plan_symphony_" + re.sub(r"[^a-z0-9]", "", stem.lower())
        # the deck's own labels are keyed by page number: pages["2"] = {level: "GROUND FLOOR", content: "..."}
        m = re.match(r"(?:fp_p|crop_p)(\d+)", stem)
        pg = lab.get("pages", {}).get(str(int(m.group(1)))) if m else None
        if pg:
            label = (pg.get("level") or "").title() + (" — " + pg["content"] if pg.get("content") else "")
        elif "ground" in stem:
            label = "Site plan and ground floor"
        elif re.match(r"crop_(\d+)(st|nd|rd|th)", stem):
            label = re.match(r"crop_(\d+\w+)", stem).group(1) + " floor (unit 3307 study)"
        else:
            label = stem.replace("_", " ").title()
        if not dry and not there(key):
            r = push_img(key, f, tok); print(f"  {key:<28} {'pushed' if r.get('ok') else 'FAILED ' + str(r)[:50]}", flush=True)
        plans.append({"label": label, "kind": "page", "img": key, "url": "/img/" + key,
                      "source": "The Symphony floor-plan deck (developer brochure), page " + stem.replace("fp_p", "").replace("crop_", "")})
    return plans, lab


def main(dry):
    tok = None if dry else env_token("INGEST_TOKEN")
    devs = []
    # Imtiaz - The Symphony
    cards = [{"label": t.replace("_", " ").replace("MasterSuite 1BR", "Master Suite 1BR"), "kind": "unit_card", "img": "card_symphony_" + t.lower(),
              "url": "/img/card_symphony_" + t.lower(), "source": "unit-type card rendered from the register + brochure (build_unit_cards_v4.py)"}
             for t in ("1BR", "2BR", "3BR", "4BR", "4BR_Duplex_lower", "4BR_Duplex_upper", "MasterSuite_1BR")]
    pages, lab = symphony_pages(dry, tok)
    devs.append({"key": "imtiaz", "name": "Imtiaz", "projects": [{"name": "The Symphony", "area": "Meydan Horizon (MBR City)",
                 "note": "Level stack " + " · ".join(lab.get("level_stack", [])[:6]) + " …" if lab.get("level_stack") else "",
                 "plans": cards + pages}]})
    # Emaar - ALVA at The Valley (campaign material, in the store already)
    va = os.path.join(ROOT, "data", "board", "valley_assets.json")
    if os.path.exists(va):
        fps = [a for a in json.load(open(va, encoding="utf-8"))["assets"] if a["kind"] == "floorplan"]
        devs.append({"key": "emaar", "name": "Emaar", "projects": [{"name": "ALVA at The Valley", "area": "The Valley, Dubai-Al Ain Road",
                     "note": "3 and 4 bedroom townhouses - EOI stage, sales rooms only", "plans":
                     [{"label": a["caption"].replace("ALVA at The Valley — ", ""), "kind": "floorplan", "img": a["key"], "url": "/img/" + a["key"],
                       "source": a["source"]} for a in fps]}]})
    # developer packs dropped into data/plans/<devkey>/<project>/ with a meta.json and jpg/ renders (8 Sep 2026: Six Senses Residences Dubai Marina, Select Group)
    # packs: data/plans/<dev>/<project>/meta.json (hand-dropped) and data/plans/harvest/<dev>/<project>/meta.json (public developer pages, 9 Sep 2026).
    # Harvest files are the developer's own images as served, or whole brochure pages; nothing is redrawn or cropped (Kendall, 9 Sep 2026).
    packs = sorted(glob.glob(os.path.join(ROOT, "data", "plans", "*", "*", "meta.json"))) + sorted(glob.glob(os.path.join(ROOT, "data", "plans", "harvest", "*", "*", "meta.json")))
    for mp in packs:
        if os.sep + "_work" + os.sep in mp: continue
        meta = json.load(open(mp, encoding="utf-8")); folder = os.path.dirname(mp); dk = meta["developer"]; ps = re.sub(r"[^a-z0-9]", "", meta["project"].lower())[:24]
        plans = []; seen_keys = set()
        for it in meta.get("items", []):
            f = os.path.join(folder, "jpg", it["file"])
            if not os.path.exists(f): continue
            # the Worker keeps only the first 40 characters of an image name (ingest_market slices imageName to 40): keep every key inside that
            stem = re.sub(r"[^a-z0-9]", "", os.path.splitext(it["file"])[0].lower())
            # 32 readable characters + a 7-character fingerprint of developer/project/file: always inside the Worker's 40-character cap, never colliding
            key = ("plan_" + dk[:6] + "_" + ps[:8] + "_" + stem)[:32].rstrip("_") + "_" + hashlib.sha1(f"{dk}|{ps}|{it['file']}".encode()).hexdigest()[:7]
            if key in seen_keys: continue      # the same file listed twice in a pack (Nakheel Azure p006): keep the first
            seen_keys.add(key)
            if not dry and not there(key):
                r = push_img(key, f, tok); print(f"  {key:<60} {'pushed' if r.get('ok') else 'FAILED ' + str(r)[:50]}", flush=True)
            label = ("Amenities, page " + it["file"].split("_p")[-1].split(".")[0]) if it.get("type") == "amenities" else (f"Type {it['type']} · unit {it['unit']} · {it['levels']}".replace("levels ", "levels ").strip(" ·"))
            plans.append({"label": label, "kind": "floorplan" if it.get("type") != "amenities" else "page", "img": key, "url": "/img/" + key, "source": meta.get("source", "developer pack")})
        proj = {"name": meta["project"], "area": meta.get("area", ""), "note": meta.get("note", ""), "plans": plans}
        dev = next((d for d in devs if d["key"] == dk), None)
        if dev: dev["projects"].append(proj)
        else: devs.append({"key": dk, "name": meta.get("developer_name", dk.title()), "projects": [proj]})
    idx = {"updated": dt.date.today().isoformat(), "count": sum(len(p["plans"]) for d in devs for p in d["projects"]),
           "note": "Every floor plan we hold, by developer and project. Developer material, shown inside the app to the broker who sells it; "
                   "each plan names its source. There are no floor-plan links in any of the eleven developers' public portfolios - new plans arrive "
                   "through the developer group (PDF capture) or by hand.",
           "developers": devs}
    json.dump(idx, open(os.path.join(ROOT, "data", "board", "plans_index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"plans: {idx['count']} across {sum(len(d['projects']) for d in devs)} projects / {len(devs)} developers")
    if not dry: print("plans_index ->", push("plans_index", idx, tok).get("ok"))


if __name__ == "__main__":
    main("--dry" in sys.argv)

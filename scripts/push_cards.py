"""Push the unit-type card sheets to the Worker's KV (img_card_<type>.png + img_cards_<building>.pdf) via the ingest channel.
Run after build_unit_cards.py in the daily refresh. 5 MB cap per object (sheets are ~1.5 MB PNG, PDF ~3.6 MB)."""
import base64, glob, json, os, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORKER = "https://azimuth-2.digitalchemy.workers.dev"
SHEETS = r"C:\Users\kwils\OneDrive\Desktop\DigitAlchemy_31MAY2026\Client_Engagements\Imtiaz\02_Execution\04_Golden_Building_Symphony\02_Revit\unit_cards\sheets"
BUILDING = "symphony"


def env_token(name):
    for line in open(r"C:\Dev\azimuth-listener-naj\.env", encoding="utf-8"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()


def push(name, path, ctype, tok):
    data = open(path, "rb").read()
    if len(data) > 5 * 1024 * 1024:
        print("SKIP >5MB:", os.path.basename(path)); return None
    body = json.dumps({"imageName": name, "image": base64.b64encode(data).decode(), "contentType": ctype}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-AzimUTH-Ingest".replace("UTH", "uth"): tok, "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=120))


tok = env_token("INGEST_TOKEN")
manifest = {"building": BUILDING, "cards": []}
for p in sorted(glob.glob(os.path.join(SHEETS, "sheet_*.png"))):
    t = os.path.basename(p)[6:-4]
    name = "card_%s_%s" % (BUILDING, t.lower())
    r = push(name, p, "image/png", tok)
    manifest["cards"].append({"type": t, "img": name, "url": "/img/" + name})
    print(name, "->", r and r.get("ok"), round(os.path.getsize(p) / 1e6, 2), "MB")
pdf = os.path.join(SHEETS, "TheSymphony_UnitTypeCards.pdf")
if os.path.exists(pdf):
    r = push("cards_%s_pdf" % BUILDING, pdf, "application/pdf", tok)
    manifest["pdf"] = "/img/cards_%s_pdf" % BUILDING
    print("pdf ->", r and r.get("ok"))
raw = json.dumps(manifest).encode()
body = json.dumps({"imageName": "cards_%s_index" % BUILDING, "image": base64.b64encode(raw).decode(), "contentType": "application/json"}).encode()
req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                             headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
print("index ->", json.load(urllib.request.urlopen(req, timeout=60)).get("ok"), manifest)

"""Harvest the UAE slice of the MEED register from the Digital Abbot Cloud read API into data/meed/uae_projects.json.
Needs DAC_KEY in the environment (never stored in the repo). ~70 pages of 200; stored corpus, never live."""
import json, os, sys, time, urllib.parse, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
key = os.environ.get("DAC_KEY") or sys.exit("set DAC_KEY")
base = "https://www.digitalabbot.io/api/cloud/v1"
def get(path):
    return json.load(urllib.request.urlopen(urllib.request.Request(base + path, headers={"x-dac-key": key, "User-Agent": "najma-dna/1.0"}), timeout=90))
status = get("/meed/status"); print("corpus:", status["data"]["corpus"])
items, after, pages = [], None, 0
while True:
    r = get("/meed/projects?limit=200&country=UAE" + (("&after=" + urllib.parse.quote(after)) if after else "")); pages += 1
    items += r["data"]; after = (r.get("page") or {}).get("nextCursor")
    if not after or pages > 400:
        break
os.makedirs(os.path.join(ROOT, "data", "meed"), exist_ok=True)
json.dump({"harvested": time.strftime("%Y-%m-%dT%H:%M"), "country": "UAE", "corpus": status["data"]["corpus"], "pages": pages, "items": items}, open(os.path.join(ROOT, "data", "meed", "uae_projects.json"), "w"), indent=0)
print("UAE projects:", len(items), "pages", pages)

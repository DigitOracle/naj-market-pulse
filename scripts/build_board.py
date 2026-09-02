"""Azimuth board v73 data: the developer grid (2 x 5), each developer's property cards, and the links down to the unit cards.
Composes KV `board_devs` from developer_segments.json + developer_dna.json + DLD register + curated buildings + card indexes,
and pushes every logo in data/board/logos as KV logo_<key> (served at /img/logo_<key>). Run after build_developer_dna.py.
Drill: /home (10 developer cards) -> /dev?d=<key> (that developer's properties) -> /cards?b=<building> (unit-type cards) or /avail?d=<dev>.
"""
import base64, datetime as dt, json, os, re, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push, WORKER  # noqa: E402

SEG = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_segments.json"), encoding="utf-8"))
DNA = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_dna.json"), encoding="utf-8"))
KEY = {"OMNIYAT": "omniyat", "H&H": "hh", "Meraas": "meraas", "Select Group": "select", "Ellington": "ellington", "Arada": "arada",
       "ZAYA/Palma": "zaya_palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman"}
# buildings we hold cards / meta for, per developer key -> [{building slug, title, cards key, meta slug, drill dev key}]
OURS = {"imtiaz": [{"building": "symphony", "title": "The Symphony by Imtiaz", "cards": "symphony", "meta": "goldensymphony", "drill": "imtiaz",
                    "area": "Bukadra (Meydan Horizon)", "status": "under construction"}]}
TIER_ICON = {"ultra_luxury": "crown", "luxury": "gem", "wellness_luxury": "leaf", "premium_luxury": "spark", "accessible_premium": "key"}

devs = []
for seg in SEG["segments"]:
    for name in seg["developers"]:
        k = KEY[name]; d = DNA["developers"].get(name, {})
        tx = d.get("tx_2026", {}); meed = d.get("meed", {})
        # property cards: DLD 2026 registrations + transaction-active projects (deduped by name) + our buildings
        props, seen = [], set()
        for b in OURS.get(k, []):
            props.append({"kind": "ours", "name": b["title"], "area": b["area"], "status": b["status"], "cards": b["cards"], "meta": b["meta"], "drill": b["drill"], "building": b["building"]}); seen.add(b["title"].lower())
        for p in d.get("dld_projects_2026", []):
            nm = p["project"].strip()
            if nm.lower() in seen or any(s in nm.lower() for s in seen): continue
            props.append({"kind": "registered", "name": nm, "area": p.get("area"), "status": (p.get("status") or "").lower(), "units": p.get("units"), "pct": p.get("pct_complete"), "value_aed": p.get("value_aed"), "start": p.get("start")}); seen.add(nm.lower())
        for t in tx.get("projects", [])[:24]:
            nm = t["project"].strip()
            if nm.lower() in seen: continue
            props.append({"kind": "trading", "name": nm, "area": t.get("area"), "tx": t["tx"], "median_aed_per_sqm": t.get("median_aed_per_sqm"), "offplan_share": t.get("offplan_share"), "last": t.get("last")}); seen.add(nm.lower())
        devs.append({"key": k, "name": name, "segment": seg["key"], "segment_label": seg["label"], "tier": seg["rank"], "icon": TIER_ICON.get(seg["key"], "spark"),
                     "logo": "/img/logo_" + k if os.path.exists(os.path.join(ROOT, "data", "board", "logos", k + ".png")) else None,
                     "kpi": {"tx_2026": tx.get("transactions", 0), "value_aed": tx.get("value_aed", 0), "projects_trading": len(tx.get("projects", [])),
                             "registered_2026": len(d.get("dld_projects_2026", [])), "meed_projects": meed.get("projects", 0), "meed_active": len(meed.get("active", [])),
                             "median_aed_per_sqm": tx.get("median_aed_per_sqm_across_projects")},
                     "entities": d.get("dld_entities", []), "properties": props, "ours": [b["building"] for b in OURS.get(k, [])]})
board = {"updated": dt.date.today().isoformat(), "source": SEG["source"], "segments": SEG["segments"], "developers": devs,
         "note": "DLD figures = naj.duckdb corpus (transactions Jan-Aug 2026, 2026 registrations), name-matched; MEED counts = stored corpus v55; developer sheets shown only where captured from the group."}
out = os.path.join(ROOT, "data", "board", "board_devs.json"); os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(board, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
tok = env_token("INGEST_TOKEN")
r = push("board_devs", board, tok)
print("board_devs ->", r.get("ok"), "| developers", len(devs), "| properties", sum(len(x["properties"]) for x in devs))
# logos -> KV logo_<key> (PNG bytes through the same ingest channel push_cards uses)
LOGOS = os.path.join(ROOT, "data", "board", "logos")
for f in sorted(os.listdir(LOGOS)) if os.path.isdir(LOGOS) else []:
    if not f.endswith(".png") or f.startswith("raw_") or f.startswith("_"): continue
    k = f[:-4]; data = open(os.path.join(LOGOS, f), "rb").read()
    body = json.dumps({"imageName": "logo_" + k, "image": base64.b64encode(data).decode(), "contentType": "image/png"}).encode()   # same channel as push_cards.py
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST", headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-board/1.0"})
    try:
        rr = json.load(urllib.request.urlopen(req, timeout=60)); print("logo", k, "->", rr.get("ok"), len(data), "B")
    except Exception as e:
        print("logo", k, "FAILED", str(e)[:80])

"""Links posted in the developer groups (captured by the listener into docs/<group>/links.jsonl) — list the new ones, keep a register,
push a small KV image so the app and the sweep can show them. Kendall, 9 Sep 2026, after Naj's Prestige One asset-library link left no trace.

Reads  C:/Dev/azimuth-listener-naj/docs/*/links.jsonl
Writes data/avail/group_links.json  {updated, n, links:[{ts, group, sender_name, url, host, title, description, text, first_seen}]}
Pushes KV dev_group_links (same ingest channel as the availability index).
Usage: python scripts/group_links.py [--no-push]
"""
import glob, json, os, sys, time, urllib.parse
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
DOCS = r"C:\Dev\azimuth-listener-naj\docs"; OUT = os.path.join(ROOT, "data", "avail", "group_links.json")


def main():
    prev = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"links": []}
    known = {(l["url"], l.get("msg_id")) for l in prev["links"]}; links = list(prev["links"]); new = []
    for f in glob.glob(os.path.join(DOCS, "*", "links.jsonl")):
        for line in open(f, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line: continue
            try: r = json.loads(line)
            except Exception: continue
            k = (r.get("url"), r.get("msg_id"))
            if k in known: continue
            known.add(k); r["host"] = urllib.parse.urlparse(r.get("url", "")).netloc; r["first_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S"); links.append(r); new.append(r)
    links.sort(key=lambda x: x.get("ts", ""), reverse=True)
    out = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": len(links), "links": links[:500]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True); json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"group links: {len(links)} on register · {len(new)} new")
    for r in new[:20]: print(f"  {r.get('ts','')[:16]} {r.get('group','')[:26]:26s} {r.get('sender_name','')[:14]:14s} {r.get('url','')[:80]}")
    if "--no-push" not in sys.argv and links:
        r = push("dev_group_links", out, env_token("INGEST_TOKEN")); print("dev_group_links ->", r.get("ok"))


if __name__ == "__main__":
    main()

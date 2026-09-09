"""Pull Prestige One's asset library (assets.prestigeone.ae, the link Naj forwarded to the DEVELOPER AVAILABILITY group on 9 Sep 2026).

A Next.js site: each development page embeds its asset list ({id, title} items grouped under section titles) and every file is served
whole by /api/download/<id> with its original filename. Files are saved exactly as served (no re-encoding, no re-rendering):
  data/kits/prestigeone/assets/<development>/<section>/<original filename>
  data/kits/prestigeone/assets/ASSET_MANIFEST.json   {development: {section: [{id, title, file, bytes, mime}]}}
Floor-plan files (title or name says floor plan / layout / typical / unit plan, or the section does) are also mirrored to
  data/plans/harvest/prestigeone/<development>/jpg/ + meta.json   so build_plans_index.py picks them up (PDF plans are kept whole as PDFs there too).
Polite: one request per second. Videos above --max-mb (default 300) are listed in the manifest but not downloaded.
Usage: python scripts/pull_prestigeone_assets.py [--list] [--only slug,slug] [--max-mb 300]
"""
import json, os, re, sys, time, urllib.parse, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "kits", "prestigeone", "assets"); os.makedirs(OUT, exist_ok=True)
PLANS = os.path.join(ROOT, "data", "plans", "harvest", "prestigeone")
BASE = "https://assets.prestigeone.ae"; H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PLAN_RX = re.compile(r"floor ?plan|layout|typical|unit plan|\bplan\b|\bfp\b", re.I)


def get(u, raw=False, timeout=120):
    time.sleep(1.0)
    r = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=timeout)
    return r if raw else r.read().decode("utf-8", errors="ignore")


def payload_of(html):
    chunks = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html):
        try: chunks.append(json.loads('"' + m.group(1) + '"'))
        except Exception: pass
    return "\n".join(chunks)


def sections_of(payload):
    """Walk the payload in order: a short quoted title that is followed (before the next item) by an item array opens a section."""
    out = []; cur = "assets"
    tokens = re.finditer(r'"title":"([^"]{2,80})"(?:,"items":\[)?|\{"id":"(01[A-Z0-9]{30,34})","title":"([^"]{1,160})"(?:,"size":(\d+))?(?:,"mime(?:Type)?":"([^"]+)")?', payload)
    for m in tokens:
        if m.group(2):
            out.append((cur, m.group(2), m.group(3), int(m.group(4)) if m.group(4) else None, m.group(5)))
        else:
            t = m.group(1)
            if not re.search(r"\.(png|jpe?g|pdf|mp4|webp|zip)$", t, re.I) and len(t) < 40: cur = t
    # de-duplicate by id, first section wins
    seen = set(); res = []
    for s in out:
        if s[1] in seen: continue
        seen.add(s[1]); res.append(s)
    return res


def safe(s):
    return re.sub(r"[^A-Za-z0-9 ._()&-]+", "_", s).strip()[:120]


def main():
    listing = "--list" in sys.argv; only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    max_mb = float(sys.argv[sys.argv.index("--max-mb") + 1]) if "--max-mb" in sys.argv else 300.0
    home = get(BASE + "/"); slugs = sorted(set(re.findall(r'href="/([a-z0-9-]+)"', home)) - {"search", "locations"}) + ["brand"]
    slugs = [s for s in dict.fromkeys(slugs) if not only or s in only]
    man_path = os.path.join(OUT, "ASSET_MANIFEST.json"); man = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    total_files = total_bytes = 0
    for slug in slugs:
        try: html = get(f"{BASE}/{slug}")
        except Exception as e: print(slug, "ERROR", str(e)[:80]); continue
        title = (re.search(r"<title>(.*?)</title>", html) or [None, slug])[1].split("—")[0].strip()
        items = sections_of(payload_of(html))
        if not items: print(f"{slug:40s} no items"); continue
        by_sec = {}
        for sec, iid, t, size, mime in items: by_sec.setdefault(sec, []).append({"id": iid, "title": t, "size": size, "mime": mime})
        print(f"{slug:40s} {title[:32]:32s} {len(items):4d} items · sections: " + ", ".join(f"{k} {len(v)}" for k, v in by_sec.items()))
        if listing: continue
        rec = man.get(slug, {})
        for sec, arr in by_sec.items():
            d = os.path.join(OUT, safe(slug), safe(sec)); os.makedirs(d, exist_ok=True); done = {x["id"]: x for x in rec.get(sec, []) if x.get("file")}
            for it in arr:
                if it["id"] in done: continue
                try:
                    r = get(f"{BASE}/api/download/{it['id']}", raw=True, timeout=600)
                    cd = r.headers.get("content-disposition", ""); m = re.search(r"filename\*=utf-8''([^;]+)", cd) or re.search(r'filename="([^"]+)"', cd)
                    fname = safe(urllib.parse.unquote(m.group(1))) if m else safe(it["title"]) + ".bin"
                    ctype = r.headers.get("content-type", ""); clen = int(r.headers.get("content-length") or 0)
                    if ctype.startswith("video/") and clen > max_mb * 1024 * 1024:
                        r.close(); rec.setdefault(sec, []).append({**it, "file": None, "mime": ctype, "bytes": clen, "skipped": f"video over {max_mb:.0f} MB"}); continue
                    p = os.path.join(d, fname); n = 0
                    with open(p, "wb") as f:
                        while True:
                            b = r.read(1 << 20)
                            if not b: break
                            f.write(b); n += len(b)
                    rec.setdefault(sec, []).append({**it, "file": os.path.relpath(p, ROOT), "mime": ctype, "bytes": n}); total_files += 1; total_bytes += n
                    print(f"    {sec[:18]:18s} {fname[:60]:60s} {n >> 10:8,d} KB")
                except Exception as e:
                    rec.setdefault(sec, []).append({**it, "file": None, "error": str(e)[:80]}); print(f"    {sec[:18]:18s} {it['title'][:60]:60s} ERROR {str(e)[:60]}")
            man[slug] = rec; json.dump(man, open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        # floor plans -> harvest pack (images copied as-is; PDFs kept whole)
        plans = [x for sec, arr in rec.items() for x in arr if x.get("file") and (PLAN_RX.search(sec) or PLAN_RX.search(x["title"]) or PLAN_RX.search(os.path.basename(x["file"])))]
        if plans:
            pd = os.path.join(PLANS, safe(slug), "jpg"); os.makedirs(pd, exist_ok=True); items_meta = []
            import shutil
            for x in plans:
                src = os.path.join(ROOT, x["file"]); dst = os.path.join(pd, os.path.basename(src))
                if not os.path.exists(dst): shutil.copy2(src, dst)
                if dst.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    items_meta.append({"file": os.path.basename(dst), "levels": "", "type": x["title"], "unit": "", "kb": x["bytes"] // 1024})
            json.dump({"developer": "prestigeone", "developer_name": "Prestige One", "project": title, "area": "", "source": f"Prestige One asset library ({BASE}/{slug}), forwarded by the developer group 9 Sep 2026; files as served, PDFs kept whole", "items": items_meta},
                      open(os.path.join(PLANS, safe(slug), "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"    plans -> {len(items_meta)} image plans (+{len(plans) - len(items_meta)} PDF) in data/plans/harvest/prestigeone/{safe(slug)}")
    print(f"done: {total_files} files · {total_bytes / 2**20:,.0f} MB -> {OUT}")


if __name__ == "__main__":
    main()

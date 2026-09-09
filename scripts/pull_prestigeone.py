"""Pull everything public about Prestige One (prestigeone.ae) — Kendall, 9 Sep 2026: "pull everything for prestige".

For every project page linked from the home page: the page text (title, description, headings, FAQ questions and answers, local essentials),
every gallery image and document as served (originals, never re-encoded), and a meta.json per project. Output:
  data/kits/prestigeone/<slug>/{original files}, meta.json      and      data/kits/prestigeone/PRESTIGE_ONE_SITE.json (everything in one file)
Polite: one request per second, browser User-Agent, public pages only, no forms.
Usage: python scripts/pull_prestigeone.py
"""
import html, json, os, re, sys, time, urllib.parse, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "kits", "prestigeone"); os.makedirs(OUT, exist_ok=True)
BASE = "https://prestigeone.ae"; H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def get(u, raw=False):
    time.sleep(1.0)
    r = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60); b = r.read()
    return b if raw else b.decode("utf-8", errors="ignore")


def text_of(t):
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", t, flags=re.S)
    t = re.sub(r"<(br|/p|/h\d|/li|/div|/tr)[^>]*>", "\n", t, flags=re.I); t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t); return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def main():
    home = get(BASE + "/")
    links = sorted(set(re.findall(r'href="(/projects/[a-z0-9-]+)"', home)) | set(re.findall(r'href="(/destinations/[a-z0-9-]+)"', home)))
    for extra in ("/projects", "/project-documents", "/about-us", "/about"):
        links.append(extra)
    site = {"pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "base": BASE, "pages": {}}
    for path in links:
        url = BASE + path
        try: t = get(url)
        except Exception as e: site["pages"][path] = {"error": str(e)[:100]}; print(path, "ERROR", str(e)[:80]); continue
        slug = path.strip("/").replace("/", "_")
        title = (re.search(r"<title>(.*?)</title>", t, re.S) or [None, ""])[1].strip()
        desc = (re.search(r'(?:name|property)="(?:description|og:description)" content="([^"]*)"', t) or [None, ""])[1]
        heads = [html.unescape(re.sub(r"<[^>]+>", "", h)).strip() for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", t, re.S)]
        body = text_of(t)
        faqs = re.findall(r"((?:Where|What|How|When|Who|Is|Are|Can|Does|Do)[^\n?]{5,140}\?)\s*\n?\s*([^\n]{20,600})", body)
        assets = sorted(set(re.findall(r'(?:src|href|data-src|content)="([^"]+\.(?:jpg|jpeg|png|webp|pdf|mp4))(?:\?[^"]*)?"', t, re.I)))
        assets = [a for a in assets if "/amenities-sliders/" not in a and "fav-" not in a and "slogan" not in a and "/logo" not in a.lower()]
        rec = {"url": url, "title": title, "description": desc, "headings": heads[:40], "faq": [{"q": q.strip(), "a": a.strip()} for q, a in faqs][:20], "text": body[:12000], "assets": []}
        if path.startswith("/projects/") and path != "/projects":
            d = os.path.join(OUT, slug.replace("projects_", "")); os.makedirs(d, exist_ok=True)
            for a in assets:
                au = a if a.startswith("http") else BASE + a
                name = os.path.basename(urllib.parse.urlparse(au).path)
                p = os.path.join(d, name)
                try:
                    if not os.path.exists(p):
                        b = get(au, raw=True); open(p, "wb").write(b)
                    rec["assets"].append({"file": name, "url": au, "bytes": os.path.getsize(p)})
                except Exception as e:
                    rec["assets"].append({"file": name, "url": au, "error": str(e)[:60]})
            json.dump({"developer": "prestigeone", "developer_name": "Prestige One Developments", "project": title.split("|")[0].strip(), "url": url, "pulled": site["pulled"],
                       "description": desc, "faq": rec["faq"], "items": [{"file": x["file"], "kind": "pdf" if x["file"].lower().endswith(".pdf") else "image", "kb": (x.get("bytes") or 0) // 1024} for x in rec["assets"] if "error" not in x]},
                      open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        else:
            rec["assets"] = [{"url": a if a.startswith("http") else BASE + a} for a in assets]
        site["pages"][path] = rec
        print(f"{path:55s} assets {len(rec['assets']):3d} · faq {len(rec['faq']):2d} · {title[:50]}")
    json.dump(site, open(os.path.join(OUT, "PRESTIGE_ONE_SITE.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("->", OUT)


if __name__ == "__main__":
    main()

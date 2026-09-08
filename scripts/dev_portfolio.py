"""Developer-site portfolio registers for the whitelist (same schema as imtiaz_portfolio.py -> data/dev_meta/<key>_portfolio.json).
One generic engine, one config block per developer: seed listing pages + a detail-URL pattern, or a WordPress REST post type where the site
exposes one (Ellington, Palma, Arada). Each detail page yields name, area, hero image, description, facts (location, structure/storeys,
units, handover, payment plans, mix) and amenity keywords from the page text; direct PDF links are RECORDED, never downloaded.
Meraas blocks scripted fetches (403) - its register is built separately (meraas_portfolio.json via the research fetcher, see notes).
ZAYA has no live site (zaya.ae is parked; zaya.com is a one-page brochure) -> ZAYA is register/MEED only; Palma reads palmaholding.com. Split 8 Sep 2026.
Usage: python scripts/dev_portfolio.py [key ...]
"""
import html, json, os, re, ssl, sys, time, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dev_meta"); os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36", "Accept": "text/html,application/json,*/*", "Accept-Language": "en-GB,en;q=0.9"}
CTX = ssl.create_default_context()

CFG = {
    "omniyat":    {"base": "https://www.omniyat.com", "seeds": ["/", "/residential", "/mixed-use"], "detail": r"^/(residential|mixed-use)/[^/]+$", "drop": r"alba-resorts$"},
    "hh":         {"base": "https://www.h-h.ae", "seeds": ["/development", "/properties"], "detail": r"^/development/[^/]+$"},
    "select":     {"base": "https://www.select-group.ae", "seeds": ["/developments"], "detail": r"^/developments/[^/]+$", "drop": r"london|baker-street|avenue-road"},
    "ellington":  {"base": "https://ellingtonproperties.ae", "rest": "/wp-json/wp/v2/property?per_page=100&_fields=slug,link,title"},
    "arada":      {"base": "https://www.arada.com", "seeds": ["/en", "/en/"], "detail": r"^/en/[^/]+/?$",
                   "keep": r"aljada|masaar|jouri-hills|nasma|armani-beach|w-residences|anantara|inaura|cbd", "name": "slug"},
    "zaya":       None,   # ZAYA has no live site (zaya.ae parked; zaya.com is a brochure page) - register/MEED only
    "sobha":      None,   # sobharealty.com answers slowly / blocks scripted fetches - register/MEED only for now
    "palma":      {"base": "https://palmaholding.com", "rest": "/wp-json/wp/v2/projects?per_page=100&_fields=slug,link,title", "drop": r"school"},
    "fakhruddin": {"base": "https://www.fakhruddinproperties.com", "seeds": ["/projects", "/"], "detail": r"^/projects/[^/]+$"},
    "beyond":     {"base": "https://beyonddevelopments.ae", "seeds": ["/", "/our-portfolio/"], "detail": r"^/Projects/[^/]+$"},
    "iman":       {"base": "https://www.imandevelopers.com", "seeds": ["/properties", "/"], "detail": r"^/iman-properties/[^/]+$"},
    "emaar":      {"base": "https://www.emaar.com", "sitemap": "/sitemap.xml", "detail": r"^/en/properties/[^/]+$", "name": "slug"},
}
AMEN_KW = [("pool", "pool"), ("gym", "gym"), ("kids", "kids' zone"), ("clubhouse", "clubhouse"), ("bbq", "BBQ"), ("cinema", "cinema"), ("spa", "spa"), ("sauna", "sauna"),
           ("yoga", "yoga"), ("ev charg", "EV charging"), ("padel", "padel"), ("co-working", "co-working"), ("coworking", "co-working"), ("beach", "beach access"),
           ("concierge", "concierge"), ("lagoon", "lagoon"), ("golf", "golf"), ("marina", "marina"), ("jogging", "jogging track"), ("tennis", "tennis"), ("valet", "valet")]
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"

CACHE = os.path.join(OUT, "_html"); os.makedirs(CACHE, exist_ok=True)

def get(u, t=40, cache_key=None, tries=3):
    """Fetch with retry/backoff; detail pages are cached under data/dev_meta/_html/<key>/ so re-parsing never re-hits the site."""
    cf = None
    if cache_key:
        d = os.path.join(CACHE, cache_key[0]); os.makedirs(d, exist_ok=True); cf = os.path.join(d, re.sub(r"[^A-Za-z0-9._-]", "_", cache_key[1])[:120] + ".html")
        if os.path.exists(cf) and os.path.getsize(cf) > 2000:
            return open(cf, encoding="utf-8", errors="ignore").read()
    last = None
    for i in range(tries):
        try:
            h = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=t, context=CTX).read().decode("utf-8", "ignore")
            if cf: open(cf, "w", encoding="utf-8").write(h)
            return h
        except Exception as e:
            last = e; time.sleep(2 + 3 * i)
    raise last

def strip(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", s))).strip()

def discover(cfg):
    base = cfg["base"]; host = re.sub(r"^https?://(www\.)?", "", base)
    urls = {}
    if cfg.get("sitemap"):                                                     # every <loc> in the sitemap that looks like a detail page
        for u in re.findall(r"<loc>" + r"\s*([^<\s]+)" + r"\s*</loc>", get(base + cfg["sitemap"])):
            path = re.sub(r"^https?://[^/]+", "", u.strip())
            if re.search(cfg["detail"], path) and not (cfg.get("drop") and re.search(cfg["drop"], path)): urls.setdefault(base + path.rstrip("/"), None)
    if cfg.get("rest"):
        for it in json.loads(get(base + cfg["rest"])):
            urls[it["link"]] = strip(it["title"]["rendered"]) if isinstance(it.get("title"), dict) else None
    for pg in cfg.get("seeds", []):
        try:
            h = get(base + pg)
        except Exception as e:
            print("   seed", pg, "FAILED", str(e)[:50]); continue
        for m in re.findall(r'href="([^"#?]+)"', h):
            l = re.sub(r"^https?://(www\.)?" + re.escape(host), "", m)
            if re.match(cfg["detail"], l): urls.setdefault(base + l.rstrip("/"), None)
    if cfg.get("keep"): urls = {u: n for u, n in urls.items() if re.search(cfg["keep"], u)}
    if cfg.get("drop"): urls = {u: n for u, n in urls.items() if not re.search(cfg["drop"], u)}
    return urls

def parse(url, h, hint_name=None, name_mode=None):
    rec = {"slug": url.rstrip("/").split("/")[-1], "url": url}
    m = re.search(r"<title>(.*?)</title>", h, re.S); rec["title"] = strip(m.group(1)) if m else rec["slug"]
    m = re.search(r'<meta name="description" content="([^"]*)"', h); rec["description"] = html.unescape(m.group(1)) if m else ""
    m = re.search(r'<meta property="og:image" content="([^"]*)"', h); rec["image"] = m.group(1) if m else None
    m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S); rec["h1"] = strip(m.group(1)) if m else ""
    brand = re.sub(r"^https?://(www\.)?", "", url).split(".")[0].replace("-", "")
    t0 = re.split(r"\s[|\-–]\s", rec["title"])[0]
    name = hint_name or rec["h1"] or t0
    if name_mode == "slug":                                          # sites whose h1 is a marketing tagline (Arada) -> title-case the slug
        name = re.sub(r"-en$", "", rec["slug"]).replace("-", " ").title().replace("Cbd", "Central Business District (Aljada)").replace("W Residences", "W Residences at")
    if not hint_name and (len(name) < 4 or re.sub(r"[^a-z]", "", name.lower()) in (brand, brand + "properties", brand + "developments", brand + "group")):
        name = t0                                                    # h1 is just the site brand (Omniyat) -> use the title's first segment
    rec["name"] = re.sub(r"\s+", " ", name).strip()[:80]
    body = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", h, flags=re.S)
    text = strip(body); rec["text_chars"] = len(text); rec["_text"] = text
    tp = [x.strip() for x in re.split(r"\s[|\-–]\s", rec["title"])]
    area = tp[1] if len(tp) >= 3 else None
    rec["_area_title"] = area
    facts_from(rec, text, area)
    rec["pdfs"] = sorted(set(re.findall(r'href="([^"]+\.pdf)"', h)))[:6]
    return rec

def facts_from(rec, text, area):
    def grab(rx, src=None, flags=re.I):
        mm = re.search(rx, src if src is not None else text, flags); return mm.group(1).strip() if mm else None
    loc = grab(r"(?:located|situated|nestled|set) (?:in|at|within|on|along) (?:the heart of )?([A-Z][^.,;]{2,60})", flags=0) or grab(r"\bin ([A-Z][A-Za-z' ]{3,40}(?:,\s?Dubai)?)\b", rec["description"] or "", flags=0)
    mix = []
    for tok in re.findall(r"(studios?|\d\s?-?\s?(?:bed(?:room)?s?|BR\b|BHK)|penthouses?|duplex(?:es)?|villas?|townhouses?|mansions?|retail|offices?|sky mansion)", text, re.I):
        t = re.sub(r"\s", "", tok.lower()); t = re.sub(r"bedrooms?|beds?|bhk", "BR", t).replace("studios", "studio").replace("duplexes", "duplex").replace("penthouses", "penthouse").replace("villas", "villa").replace("townhouses", "townhouse").replace("offices", "office").replace("mansions", "mansion")
        if t not in mix: mix.append(t)
    amen = []
    for kw, label in AMEN_KW:
        if kw in text.lower() and label not in amen: amen.append(label)
    rec["area"] = area or loc
    rec["facts"] = {
        "location": loc, "structure": grab(r"\(((?:\d?[BGPRM]\s?\+\s?)+\d+(?:\s?\+\s?R)?)\)"),
        "storeys": grab(r"(\d{1,3})\s?-?\s?(?:storey|stories|floors|levels)\b"), "units": grab(r"(\d{2,4})\s(?:residential |luxury |exclusive |branded |spacious )?(?:units|residences|apartments|homes|villas|townhouses)"),
        "handover": grab(r"(?:handover|completion|hand over|move in|delivery|ready by|completed in)[^.]{0,60}?((?:Q[1-4]\s|" + MONTH + r"\s)?20\d\d)"),
        "payment_plans": sorted(set(re.findall(r"\b(\d{2}/\d{2}(?:/\d{2})?)\b(?=[^.]{0,40}(?:payment|plan))", text, re.I))), "mix": mix[:10],
    }
    rec["amenities"] = amen

if __name__ == "__main__":
    keys = sys.argv[1:] or list(CFG)
    for k in keys:
        cfg = CFG[k]; print("==", k)
        if not cfg: print("   no live site - register/MEED only"); continue
        try:
            urls = discover(cfg)
        except Exception as e:
            print("   discovery FAILED", str(e)[:80]); continue
        print("   candidate pages:", len(urls))
        out = []
        for u, hint in sorted(urls.items()):
            try:
                rec = parse(u, get(u, cache_key=(k, u.rstrip("/").split("/")[-1])), hint, cfg.get("name")); out.append(rec)
                f = rec["facts"]; print(f"   {rec['name'][:36]:<36} | {(rec['area'] or '-')[:26]:<26} | {f['structure'] or f['storeys'] or '-':<10} | u {f['units'] or '-':<4} | {f['handover'] or '-':<9} | {','.join(f['mix'])[:26]:<26} | am {len(rec['amenities'])} pdf {len(rec['pdfs'])}")
            except Exception as e:
                print("   ", u, "FAILED", str(e)[:60])
            time.sleep(0.3)
        # boilerplate pass: sentences that appear on >45 % of this site's pages are navigation / footer, not facts about the project
        if len(out) >= 3:
            import collections
            sent = lambda t: [x.strip() for x in re.split(r"(?<=[.!?])\s+|\s{2,}|\s[|·]\s", t) if len(x.strip()) > 12]
            freq = collections.Counter()
            for r in out: freq.update(set(sent(r["_text"])))
            boiler = {x for x, c in freq.items() if c / len(out) > 0.45}
            for r in out:
                clean = " ".join(x for x in sent(r["_text"]) if x not in boiler)
                facts_from(r, clean, r.get("_area_title")); r["text_chars_clean"] = len(clean)
            print("   boilerplate sentences removed:", len(boiler))
        for r in out:
            r.pop("_text", None); r.pop("_area_title", None)
        json.dump({"source": cfg["base"], "fetched": time.strftime("%Y-%m-%d %H:%M"), "properties": out}, open(os.path.join(OUT, k + "_portfolio.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"   -> {k}_portfolio.json: {len(out)} properties")

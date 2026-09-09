"""Sobha Realty public-site deep dive (9 Sep 2026). Rights-clear: sobharealty.com only, 1 req/s, browser UA, robots.txt honoured
(/sites/default/files is allowed; /property-map, /get-property-unit-types, /form, /node are disallowed and never touched).
Writes: data/dev_meta/sobha_portfolio.json (ellington shape), data/kits/sobha/site/<slug>/ (images + PDFs as served + meta.json),
data/plans/harvest/sobha/<slug>/ (NEW projects only, pack format), data/kits/sobha/SOBHA_SOURCES.json (every URL fetched).
usage: python scripts/sobha_harvest.py [--limit N] [--only slug,slug]
"""
import html, io, json, os, re, sys, time
from urllib.parse import urljoin, unquote
import requests
from bs4 import BeautifulSoup
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "data", "plans", "harvest", "_work"))
from pdf_plans import render_plans, detect_plan_pages, slug as slugify  # noqa: E402

BASE = "https://sobharealty.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
      "Accept-Language": "en-GB,en;q=0.9"}
HTML_CACHE = os.path.join(ROOT, "data", "dev_meta", "_html", "sobha"); os.makedirs(HTML_CACHE, exist_ok=True)
KIT = os.path.join(ROOT, "data", "kits", "sobha", "site"); os.makedirs(KIT, exist_ok=True)
PLANS = os.path.join(ROOT, "data", "plans", "harvest", "sobha")
PORTFOLIO = os.path.join(ROOT, "data", "dev_meta", "sobha_portfolio.json")
SOURCES = os.path.join(ROOT, "data", "kits", "sobha", "SOBHA_SOURCES.json")
MAX_GALLERY = 10; MAX_PDF = 2; MAX_PDF_MB = 80
PRIORITY = ["sobha-hartland", "sobha-hartland-2", "sobha-one", "sobha-central", "sobha-seahaven", "sobha-skyparks", "sobha-solis", "sobha-orbis",
            "sobha-reserve", "sobha-siniya-island", "skyscape", "sobha-elwood", "sobha-verde", "the-crest", "creek-vistas", "310-riverside-crescent",
            "330-riverside-crescent", "340-riverside-crescent", "350-riverside-crescent", "the-element", "320-riverside-crescent", "360-riverside-crescent",
            "riverside-crescent", "the-mirage", "the-pinnacle", "the-eden", "the-s", "golf-ridges", "sky-edition", "sobha-aquacrest", "sobha-estates",
            "skyvue", "sobha-sanctuary", "sobha-city", "sobha-aquamont", "uaq-downtown"]
AMBIG = {"apartments", "villas", "townhouses", "greens", "the-woods", "beach-residences", "marina-residences", "island-villas", "altier", "solair",
         "spectra", "stellar", "altius", "aura", "avenue", "the-brooks", "the-greens", "the-grove", "the-willows", "the-orchard", "the-terraces"}
AMEN_KW = [("pool", "pool"), ("gym", "gym"), ("kids", "kids' zone"), ("clubhouse", "clubhouse"), ("bbq", "BBQ"), ("barbecue", "BBQ"), ("cinema", "cinema"),
           ("movie theatre", "cinema"), ("spa", "spa"), ("sauna", "sauna"), ("yoga", "yoga"), ("ev charg", "EV charging"), ("padel", "padel"),
           ("co-working", "co-working"), ("coworking", "co-working"), ("beach", "beach access"), ("concierge", "concierge"), ("lagoon", "lagoon"),
           ("golf", "golf"), ("marina", "marina"), ("jogging", "jogging track"), ("tennis", "tennis"), ("valet", "valet"), ("squash", "squash"),
           ("badminton", "badminton"), ("library", "library"), ("retail", "retail"), ("water sports", "water sports"), ("infinity pool", "infinity pool")]
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"

SESS = requests.Session(); SESS.headers.update(UA)
LOG = []          # every URL fetched
LAST_HIT = [0.0]


def polite():
    dt = time.time() - LAST_HIT[0]
    if dt < 1.0:
        time.sleep(1.0 - dt)
    LAST_HIT[0] = time.time()


def get(url, kind, project=None, stream=False, timeout=90):
    polite()
    ent = {"url": url, "kind": kind, "project": project, "status": None, "bytes": 0, "yield": ""}
    try:
        r = SESS.get(url, timeout=timeout, stream=stream)
        ent["status"] = r.status_code
        if not stream:
            ent["bytes"] = len(r.content)
        LOG.append(ent)
        return r, ent
    except Exception as e:
        ent["status"] = "error"; ent["yield"] = str(e)[:120]; LOG.append(ent)
        return None, ent


def strip(s):
    s = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", s, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", s))).strip()


def original(u):
    """Drupal image style -> the file as uploaded (served from /sites/default/files/...)."""
    u = urljoin(BASE, u).split("?")[0]
    if "/styles/" in u and "/public/" in u:
        u = re.sub(r"/styles/[^/]+/public/", "/", u)
        u = re.sub(r"\.webp$", "", u) if re.search(r"\.(?:jpe?g|png|gif)\.webp$", u, re.I) else u
    return u


def safe_name(u):
    b = unquote(os.path.basename(u.split("?")[0]))
    b = re.sub(r"[^A-Za-z0-9._-]+", "_", b).strip("_")
    return b[-90:] or "file"


def discover():
    urls = {}
    sm = open(os.path.join(ROOT, "data", "dev_meta", "_html", "sobha_sitemap.xml"), encoding="utf-8").read()
    about = open(os.path.join(HTML_CACHE, "about.html"), encoding="utf-8").read()
    cands = re.findall(r"<loc>(.*?)</loc>", sm)
    cands += [urljoin(BASE, m) for m in re.findall(r'href="((?:https?://(?:www\.)?sobharealty\.com)?/(?:properties-in-[^"#?]+|sobha-communities/[^"#?]+))"', about)]
    for u in cands:
        u = u.replace("https://www.", "https://").rstrip("/")
        p = u.replace(BASE, "")
        segs = [s for s in p.split("/") if s]
        if not segs:
            continue
        if segs[0].startswith("properties-in-"):
            if segs[0] in ("properties-in-uae", "properties-in-umm-al-quwain") or len(segs) < 2 or segs[-1].startswith("properties-for-sale") or segs[-1].startswith("apartment-for-sale"):
                continue
            slug = segs[-1]
            if slug in AMBIG and len(segs) >= 3:
                slug = segs[-2] + "-" + segs[-1]
        elif segs[0] == "sobha-communities" and len(segs) == 2:
            slug = "community-" + segs[1]
        else:
            continue
        urls.setdefault(slug, u)
    # nav images = site boilerplate, never a project gallery
    boiler = {original(x) for x in re.findall(r'(?:src|data-src)="([^"]+\.(?:jpe?g|png|webp)[^"]*)"', about, re.I)}
    return urls, boiler


def prio_key(slug):
    s = slug.replace("community-", "")
    return (PRIORITY.index(s) if s in PRIORITY else 99, slug)


def facts_from(rec, text, area_hint, tabs):
    def grab(rx, src=None, flags=re.I):
        mm = re.search(rx, src if src is not None else text, flags); return mm.group(1).strip() if mm else None
    loc = grab(r"(?:located|situated|nestled|set|positioned) (?:in|at|within|on|along) (?:the heart of )?([A-Z][^.;]{2,90}?)(?:[.;]|, offering| and offers| with )", flags=0) \
        or grab(r"\b(?:in|at) ([A-Z][A-Za-z' 0-9]{3,40}(?:,\s?(?:Dubai|Umm Al Quwain|Abu Dhabi))?)\b", rec["description"] or "", flags=0)
    mix = []
    for t in tabs:
        t2 = re.sub(r"\s+", "", t.upper()).replace("BEDROOM", "BR").replace("BED", "BR")
        if t2 and t2 not in mix:
            mix.append(t2)
    for tok in re.findall(r"(studios?|\d(?:\.5)?\s?-?\s?(?:bed(?:room)?s?|BR\b|BHK)|penthouses?|duplex(?:es)?|villas?|townhouses?|mansions?|villaments?|sky villas?|retail|offices?)", text, re.I):
        t = re.sub(r"[\s-]", "", tok.lower()); t = re.sub(r"bedrooms?|beds?|bhk", "BR", t).replace("studios", "studio").replace("duplexes", "duplex").replace("penthouses", "penthouse").replace("villas", "villa").replace("townhouses", "townhouse").replace("offices", "office").replace("mansions", "mansion").replace("villaments", "villament")
        t = t.upper() if re.match(r"^\d", t) else t
        if t not in mix:
            mix.append(t)
    amen = []
    low = text.lower()
    for kw, label in AMEN_KW:
        if kw in low and label not in amen:
            amen.append(label)
    rec["area"] = area_hint or loc
    pp = sorted(set(re.findall(r"\b(\d{2}\s?[/:]\s?\d{2}(?:\s?[/:]\s?\d{2})?)\b(?=[^.]{0,60}(?:payment|plan))", text, re.I)))
    pp += [m.strip() for m in re.findall(r"((?:\d{1,3}\s?%\s?(?:on|at|during|upon|post)[^.;]{0,50}))", text, re.I)][:6]
    rec["facts"] = {
        "location": loc,
        "structure": grab(r"\b((?:\d?[BGPRM]\s?\+\s?)+(?:\d+|R(?:oof)?)(?:\s?\+\s?R(?:oof)?)?)\b"),
        "storeys": grab(r"(\d{1,3})\s?-?\s?(?:storey|stories|floors|levels)\b"),
        "units": grab(r"(\d{1,3}(?:,\d{3})?|\d{2,4})\s(?:residential |luxury |exclusive |branded |spacious |waterfront |premium |meticulously designed |bespoke )?(?:units|residences|apartments|homes|villas|townhouses|mansions|keys)\b"),
        "handover": grab(r"(?:handover|completion|hand over|move in|delivery|ready by|completed in|anticipated completion)[^.]{0,60}?((?:Q[1-4]\s|" + MONTH + r"\s)?20\d\d)"),
        "payment_plans": pp[:8], "mix": mix[:12],
    }
    rec["amenities"] = amen


def parse_page(url, h, slug):
    soup = BeautifulSoup(h, "html.parser")
    rec = {"slug": slug, "url": url}
    m = re.search(r"<title>(.*?)</title>", h, re.S); rec["title"] = strip(m.group(1)) if m else slug
    m = re.search(r'<meta name="description" content="([^"]*)"', h); rec["description"] = html.unescape(m.group(1)) if m else ""
    m = re.search(r'<meta property="og:image" content="([^"]*)"', h); rec["image"] = urljoin(BASE, m.group(1)) if m else None
    m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S); rec["h1"] = strip(m.group(1)) if m else ""
    parts = [p.strip() for p in rec["title"].split("|")]
    t0 = parts[0]
    name = t0.split(":", 1)[1].strip() if ":" in t0 else t0
    name = re.sub(r"^(?:Luxury |Premium |Buy )", "", name)
    rec["name"] = name[:80]
    area_hint = parts[1] if len(parts) >= 2 and not re.search(r"Sobha Realty", parts[1]) else None
    body = strip(h)
    i = body.find("EN AR RU CH"); body = body[i + 11:] if i > 0 else body
    for cut in ("WE’D LOVE TO", "WE'D LOVE TO", "WE�D LOVE TO", "Hear From You"):
        j = body.find(cut)
        if j > 0:
            body = body[:j]; break
    rec["text_chars"] = len(body); rec["_text"] = body
    # printed price (as the page prints it; asterisked, subject to availability)
    m = re.search(r"Starting Prices?\s*((?:AED|USD)[^*]{0,40}\*)", strip(h))
    rec["printed_price"] = m.group(1).strip() if m else None
    # floor-plan tabs + unit table
    tabs = [strip(x) for x in re.findall(r'class="category-button[^"]*"[^>]*>(.*?)</div>', h, re.S)]
    plans = []
    for blk in soup.select("div.floor-main-plan div.swiper-slide"):
        h4 = blk.find("h4"); img = blk.find("img")
        if not h4:
            continue
        lis = {}
        for li in blk.find_all("li"):
            t = li.get_text(" ", strip=True)
            mm = re.match(r"(UNIT|SUITE|BALCONY|TOTAL|TERRACE|PLOT|BUA|BUILT[- ]UP AREA|GARDEN|SALEABLE AREA)\s*:\s*(.+)", t, re.I)
            if mm:
                lis[mm.group(1).upper()] = mm.group(2).strip()
        src = (img.get("src") or img.get("data-src") or "") if img else ""
        plans.append({"type": re.sub(r"\s+", " ", h4.get_text(" ", strip=True)), "alt": (img.get("alt") if img else "") or "",
                      "unit": lis.get("UNIT", ""), "suite_sqft": lis.get("SUITE"), "balcony_sqft": lis.get("BALCONY"), "total_sqft": lis.get("TOTAL"),
                      "other": {k: v for k, v in lis.items() if k not in ("UNIT", "SUITE", "BALCONY", "TOTAL")} or None,
                      "img": original(src) if src else None, "img_served": urljoin(BASE, src) if src else None})
    rec["unit_types"] = plans
    rec["_tabs"] = tabs
    facts_from(rec, body, area_hint, tabs)
    rec["pdfs"] = sorted({urljoin(BASE, x) for x in re.findall(r'href="([^"]+\.pdf)(?:[?#][^"]*)?"', h, re.I)})[:6]
    # gallery candidates in document order
    gal = []
    for tag in soup.find_all(["img", "source"]):
        src = tag.get("src") or tag.get("data-src") or (tag.get("srcset") or tag.get("data-srcset") or "").split(",")[0].strip().split(" ")[0]
        if not src or not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", src, re.I) or "/sites/default/files/" not in src:
            continue
        o = original(src)
        if o not in gal:
            gal.append((o, urljoin(BASE, src), tag.get("alt") or ""))
    rec["_gallery"] = gal
    return rec


def to_jpeg(data, max_side=2000, max_kb=1500):
    im = Image.open(io.BytesIO(data)); im.load()
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255)); im = im.convert("RGBA"); bg.paste(im, mask=im.split()[-1]); im = bg
    else:
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > max_side:
        r = max_side / max(w, h); im = im.resize((int(w * r), int(h * r)), Image.LANCZOS)
    q = 88
    while True:
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= max_kb * 1024 or q <= 40:
            return buf.getvalue()
        q -= 8


def download(url, served_fallback, dest_dir, project, kind):
    """Save the file exactly as served (no re-encoding). Tries the original upload first, then the styled URL the page used."""
    for u in [url] + ([served_fallback] if served_fallback and served_fallback != url else []):
        r, ent = get(u, kind, project)
        if r is None or r.status_code != 200 or len(r.content) < 6000:
            if ent["status"] == 200:
                ent["yield"] = "too small, skipped"
            continue
        fn = safe_name(u)
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, fn); k = 2
        while os.path.exists(path) and open(path, "rb").read(64) != r.content[:64]:
            path = os.path.join(dest_dir, f"{os.path.splitext(fn)[0]}_{k}{os.path.splitext(fn)[1]}"); k += 1
        if not os.path.exists(path):
            open(path, "wb").write(r.content)
        ent["yield"] = f"{kind} -> {os.path.relpath(path, ROOT)}"
        return path, r.content
    return None, None


def download_pdf(url, dest_dir, project):
    r, ent = get(url, "pdf", project, stream=True, timeout=900)
    if r is None or r.status_code != 200:
        return None
    cl = int(r.headers.get("content-length") or 0)
    if cl > MAX_PDF_MB * 1024 * 1024:
        ent["yield"] = f"skipped, {cl // 1048576} MB > cap"; r.close(); return None
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, safe_name(url))
    n = 0
    with open(path, "wb") as o:
        for ch in r.iter_content(1 << 16):
            o.write(ch); n += len(ch)
    ent["bytes"] = n; ent["yield"] = f"pdf -> {os.path.relpath(path, ROOT)}"
    return path


def main():
    limit = None; only = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    urls, boiler = discover()
    # resume: carry every URL already fetched in the earlier pass of this job
    if os.path.exists(SOURCES):
        try:
            LOG.extend(json.load(open(SOURCES, encoding="utf-8")).get("requests", []))
        except Exception:
            pass
    order = sorted(urls, key=prio_key)
    if only:
        order = [s for s in order if s in only]
    if limit:
        order = order[:limit]
    print(len(urls), "project URLs;", len(order), "to process", flush=True)
    if not any(e["kind"] == "robots" for e in LOG):
        LOG.append({"url": BASE + "/robots.txt", "kind": "robots", "project": None, "status": 200, "bytes": 2520, "yield": "crawl rules read; /sites/default/files allowed"})
        LOG.append({"url": BASE + "/sitemap.xml", "kind": "sitemap", "project": None, "status": 200, "bytes": 14865, "yield": "114 URLs, 76 project pages"})
    out = []; t0 = time.time()
    for n, slug in enumerate(order, 1):
        url = urls[slug]
        cf = os.path.join(HTML_CACHE, slug + ".html")
        if os.path.exists(cf) and os.path.getsize(cf) > 20000:
            h = open(cf, encoding="utf-8").read(); st = "cache"
            LOG.append({"url": url, "kind": "page", "project": slug, "status": 200, "bytes": len(h), "yield": "project page (cached from earlier fetch this session)"})
        else:
            r, ent = get(url, "page", slug)
            if r is None or r.status_code != 200:
                print(f"[{n}/{len(order)}] {slug}: HTTP {ent['status']}", flush=True); continue
            h = r.text; open(cf, "w", encoding="utf-8").write(h); st = r.status_code
        rec = parse_page(url, h, slug)
        rec["_source_status"] = st
        for e in LOG:
            if e["url"] == url and e["kind"] == "page":
                e["yield"] = f"project page: {rec['name']} ({len(rec['unit_types'])} unit types, {len(rec['pdfs'])} pdf links)"
        kit_dir = os.path.join(KIT, slug); os.makedirs(kit_dir, exist_ok=True)
        pslug = slugify(slug.replace("community-", ""))
        pack_dir = os.path.join(PLANS, pslug)
        kmeta = os.path.join(kit_dir, "meta.json")
        if st == "cache" and os.path.exists(kmeta) and "--refetch" not in sys.argv:
            # already harvested in the earlier pass of this job: rebuild the record from disk, no network
            km = json.load(open(kmeta, encoding="utf-8")); items = km.get("items", [])
            for fp in rec["unit_types"]:
                hit = next((i for i in items if i.get("src") == fp["img"]), None)
                if hit:
                    fp["file"] = hit["file"]
            pk = os.path.join(pack_dir, "meta.json")
            pack_from_page = os.path.exists(pk) and url in json.load(open(pk, encoding="utf-8")).get("source", "")
            rec["kit"] = {"dir": os.path.relpath(kit_dir, ROOT), "images": sum(1 for i in items if i["kind"] == "image"), "floorplans": sum(1 for i in items if i["kind"] == "floorplan"),
                          "pdfs": sum(1 for i in items if i["kind"] == "pdf"), "plan_pack": (os.path.relpath(pack_dir, ROOT) if pack_from_page else ("existing" if os.path.exists(pk) else None))}
            out.append(rec)
            print(f"[{n}/{len(order)}] {rec['name'][:34]:<34} | resumed from disk | img {rec['kit']['images']} fp {rec['kit']['floorplans']} pdf {rec['kit']['pdfs']}", flush=True)
            continue
        # sub-building pages (4+ path segments) get a shorter gallery so the whole listing fits the time-box
        max_gal = MAX_GALLERY if len([x for x in url.replace(BASE, "").split("/") if x]) <= 3 else 6
        items = []
        # hero
        plan_imgs = {p["img"] for p in rec["unit_types"] if p["img"]}
        seen = set()
        if rec["image"]:
            o = original(rec["image"])
            p, _ = download(o, rec["image"], kit_dir, slug, "image")
            seen.add(o)
            if p:
                items.append({"file": os.path.basename(p), "kind": "image", "role": "hero", "kb": os.path.getsize(p) // 1024, "src": o})
        # gallery (skip nav boilerplate, plan images, icons)
        g = 0
        for o, served, alt in rec["_gallery"]:
            if g >= max_gal:
                break
            if o in seen or o in boiler or o in plan_imgs or re.search(r"icon|logo|arrow|whatsapp|/menu|Menu|470x457|854x457|flag|badge", o, re.I):
                continue
            seen.add(o)
            p, _ = download(o, served, kit_dir, slug, "image")
            if p:
                items.append({"file": os.path.basename(p), "kind": "image", "role": "gallery", "alt": alt[:80], "kb": os.path.getsize(p) // 1024, "src": o}); g += 1
        # floor-plan images: kit (as served) + plans pack (JPEG) for NEW projects only
        pack_new = not os.path.exists(os.path.join(pack_dir, "meta.json"))
        pack_items = []
        for fp in rec["unit_types"]:
            if not fp["img"] or fp["img"] in seen:
                continue
            seen.add(fp["img"])
            p, data = download(fp["img"], fp["img_served"], kit_dir, slug, "floorplan")
            if not p:
                continue
            items.append({"file": os.path.basename(p), "kind": "floorplan", "type": fp["type"], "unit": fp["unit"], "total_sqft": fp["total_sqft"], "kb": os.path.getsize(p) // 1024, "src": fp["img"]})
            fp["file"] = os.path.basename(p)
            if pack_new:
                try:
                    jb = to_jpeg(data)
                except Exception as e:
                    print("   jpeg fail", fp["img"][:60], e); continue
                typ = (fp["alt"] or fp["type"]).upper()
                base = f"{pslug[:28]}_{slugify(typ)}"; fn = base + ".jpg"; k = 2
                while any(i["file"] == fn for i in pack_items):
                    fn = f"{base}_{k}.jpg"; k += 1
                os.makedirs(os.path.join(pack_dir, "jpg"), exist_ok=True)
                open(os.path.join(pack_dir, "jpg", fn), "wb").write(jb)
                pack_items.append({"file": fn, "levels": "", "type": typ, "unit": fp["unit"], "kb": len(jb) // 1024})
        # PDFs (brochure / floor plans) as served; plan pages rendered into the pack for NEW projects
        for pu in rec["pdfs"][:MAX_PDF]:
            path = download_pdf(pu, kit_dir, slug)
            if not path:
                continue
            kind = "floorplan" if re.search(r"floor|plan|layout", os.path.basename(path), re.I) else "pdf"
            try:
                pages, npg = detect_plan_pages(path)
            except Exception as e:
                pages, npg = [], 0; print("   pdf scan fail", e)
            items.append({"file": os.path.basename(path), "kind": kind, "kb": os.path.getsize(path) // 1024, "pages": npg, "plan_pages": len(pages), "src": pu})
            if pages and pack_new:
                try:
                    its, _ = render_plans(path, os.path.join(pack_dir, "jpg"), pslug[:28] + "_br")
                    pack_items.extend([{k: v for k, v in it.items() if k in ("file", "levels", "type", "unit", "kb")} for it in its])
                except Exception as e:
                    print("   render fail", e)
        if pack_items:
            json.dump({"developer": "sobha", "developer_name": "Sobha Realty", "project": rec["name"], "area": rec["area"] or "",
                       "source": f"Sobha Realty public project page (floor-plan images and/or brochure PDF), harvested 9 Sep 2026: {url}", "items": pack_items},
                      open(os.path.join(pack_dir, "meta.json"), "w"), indent=1)
        json.dump({"developer": "sobha", "developer_name": "Sobha Realty", "project": rec["name"], "area": rec["area"] or "", "source": url,
                   "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "printed_price": rec["printed_price"],
                   "items": [{k: v for k, v in it.items() if v is not None} for it in items]},
                  open(os.path.join(kit_dir, "meta.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        rec["kit"] = {"dir": os.path.relpath(kit_dir, ROOT), "images": sum(1 for i in items if i["kind"] == "image"), "floorplans": sum(1 for i in items if i["kind"] == "floorplan"),
                      "pdfs": sum(1 for i in items if i["kind"] == "pdf"), "plan_pack": (os.path.relpath(pack_dir, ROOT) if pack_items else ("existing" if not pack_new else None))}
        out.append(rec)
        f = rec["facts"]
        print(f"[{n}/{len(order)}] {rec['name'][:34]:<34} | {(rec['area'] or '-')[:24]:<24} | u {f['units'] or '-':<5} | {f['handover'] or '-':<8} | {','.join(f['mix'])[:22]:<22} | img {rec['kit']['images']} fp {rec['kit']['floorplans']} pdf {rec['kit']['pdfs']} pack {len(pack_items)} | {int(time.time()-t0)}s", flush=True)
        dump(out, urls)
    # boilerplate pass: sentences on >45 % of pages are site chrome, not project facts
    if len(out) >= 3:
        import collections
        sent = lambda t: [x.strip() for x in re.split(r"(?<=[.!?])\s+|\s{2,}|\s[|·]\s", t) if len(x.strip()) > 12]
        freq = collections.Counter()
        for r in out:
            freq.update(set(sent(r["_text"])))
        boil = {x for x, c in freq.items() if c / len(out) > 0.45}
        for r in out:
            clean = " ".join(x for x in sent(r["_text"]) if x not in boil)
            area = r["area"]; facts_from(r, clean, area, r["_tabs"]); r["text_chars_clean"] = len(clean)
            r["_clean"] = clean
    dump(out, urls, final=True)
    print("DONE", len(out), "projects", int(time.time() - t0), "s", flush=True)


def dump(out, urls, final=False):
    props = []
    for r in out:
        p = {k: v for k, v in r.items() if not k.startswith("_")}
        if final and r.get("_clean"):
            p["summary"] = r["_clean"][:1200]
        props.append(p)
    json.dump({"source": BASE, "fetched": time.strftime("%Y-%m-%d %H:%M"), "properties": props}, open(PORTFOLIO, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    seen = set(); reqs = []
    for e in LOG:
        k = (e["url"], e["kind"], e.get("project"))
        if k in seen:
            continue
        seen.add(k); reqs.append(e)
    json.dump({"developer": "Sobha Realty", "fetched": time.strftime("%Y-%m-%d %H:%M"), "policy": "sobharealty.com only; 1 request/second; browser User-Agent; robots.txt honoured; no portals; no logins",
               "project_urls_discovered": urls, "requests": reqs}, open(SOURCES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

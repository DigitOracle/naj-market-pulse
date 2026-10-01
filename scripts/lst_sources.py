"""Advertised rental supply beyond Property Finder: four agency/portal sites that a 1 Oct 2026 probe found readable
without a bot check, within their robots.txt. Research use only. ADVERTISED SUPPLY, not vacancy.

Sources (portal codes): allsopp (www.allsoppandallsopp.com), fam (famproperties.com), bhomes (bhomes.com), espace (espace.ae).
Excluded on purpose: Bayut, Dubizzle, Metropolitan (challenge pages); Houza, Zoom (dead); PropSearch (directory);
haus & haus, Driven, Emaar (JS-only); Nakheel, DAMAC Living (no inventory).

Rules this crawler keeps: robots.txt read first and disallowed paths refused; one request per host every 4-6 s (randomised);
honest User-Agent with a contact address; 20 h URL cache under data/listings/<source>/cache/; --max-requests cap; exponential
backoff on 429/403/5xx; stop after 5 consecutive failures or on any challenge/CAPTCHA page (exit 3); no login, no proxies.
Privacy: no agent/broker names, ids, phones, emails or share URLs are persisted - only a public licence number (ORN/BRN).
Lake: no lake connection is open while requests are in flight; the crawl runs to memory, then ONE short write via lake.retry.
While the production daily chain runs (daily_refresh.log has '=== daily start' with no later '=== daily done') nothing is
written: rows spill to data/listings/<source>/pending_<date>.json, exit 4, re-runnable with --offline (cached pages).

Tables: lst_listing_snapshot / lst_listing / lst_building_alias (DDL owned by scripts/pf_listings.py, reused here;
pf_location_* are null for these portals; permit_token holds the DLD permit NUMBER where the site exposes it).

Usage:
  python scripts/lst_sources.py probe   --source allsopp|fam|bhomes|espace --district jumeirahvillagecircle [--max-requests 10]
  python scripts/lst_sources.py crawl   --source fam --district jumeirahvillagecircle [--district businessbay] [--max-requests 150] [--dry] [--offline]
  python scripts/lst_sources.py crawl   --source all --district jumeirahvillagecircle --max-requests 150
  python scripts/lst_sources.py replay  --source fam            re-run the lake write from the newest pending_<date>.json (no network)
Every run appends a summary to data/listings/<source>/run_<date>.json and logs to logs/lst_sources.log.
"""
import argparse, datetime as dt, gzip, hashlib, html as htmlmod, io, json, math, os, random, re, sys, time
from urllib.parse import urlsplit, urljoin

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import lake  # noqa: E402
import pf_listings as pf  # noqa: E402  (read-only reuse: Robots, norm_name, match_building, DDL, write_lake, chain_running)

UA = "naj-market-pulse research crawler (academic, non-commercial; contact@digitalabbot.io)"
OUT = os.path.join(ROOT, "data", "listings")
LOG = os.path.join(ROOT, "logs", "lst_sources.log")
CACHE_HOURS = 20
DELAY = (4.0, 6.0)
BREAKER = 5
CHALLENGE_MARKS = ("captcha", "cf-challenge", "challenge-platform", "access denied", "are you a robot", "px-captcha",
                   "just a moment...", "attention required")
SQM_TO_SQFT = 10.7639
MEASURE = "ADVERTISED SUPPLY (live adverts), not vacancy; research use only"

# our district slug -> the words each site uses for that community in its URLs / filter labels (verified in the probe)
DISTRICT_WORDS = {
    "jumeirahvillagecircle": ["jumeirah village circle", "jvc"],
    "businessbay": ["business bay"],
}


def log(msg):
    line = "%s %s" % (dt.datetime.now().isoformat(timespec="seconds"), msg)
    print(line)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------------------------------------------- the fetcher
class Fetcher:
    """One per source host. Robots first, 20 h cache, 4-6 s pacing, backoff, circuit breaker, request cap, challenge stop."""

    def __init__(self, source, host, max_requests, offline=False):
        self.source, self.host = source, host
        self.base = "https://" + host
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                               "Accept-Language": "en"})
        self.max_requests, self.offline = max_requests, offline
        self.requests_made = self.cache_hits = self.consecutive = 0
        self.failures, self.last_at, self.stopped, self.robots = [], 0.0, None, None
        self.cache = os.path.join(OUT, source, "cache")
        os.makedirs(self.cache, exist_ok=True)

    def _path(self, url):
        return os.path.join(self.cache, hashlib.sha1(url.encode()).hexdigest())

    def _cached(self, url):
        p = self._path(url)
        if not os.path.exists(p + ".json"):
            return None
        try:
            meta = json.load(open(p + ".json", encoding="utf-8"))
            if (time.time() - meta["fetched_at"]) / 3600.0 > CACHE_HOURS and not self.offline:
                return None
            return open(p + ".body", encoding="utf-8").read()
        except Exception:
            return None

    def _store(self, url, text, status):
        p = self._path(url)
        with open(p + ".body", "w", encoding="utf-8") as f:
            f.write(text)
        with open(p + ".json", "w", encoding="utf-8") as f:
            json.dump({"url": url, "fetched_at": time.time(), "status": status}, f)

    def _pace(self):
        wait = self.last_at + random.uniform(*DELAY) - time.time()
        if wait > 0:
            time.sleep(wait)
        self.last_at = time.time()

    def load_robots(self):
        url = self.base + "/robots.txt"
        text = self._cached(url)
        if text is None:
            if self.offline:
                raise RuntimeError("robots.txt not cached and --offline given")
            self._pace()
            r = self.s.get(url, timeout=30)
            self.requests_made += 1
            if r.status_code != 200:
                raise RuntimeError("%s robots.txt returned %s - refusing to crawl" % (self.host, r.status_code))
            text = r.text
            self._store(url, text, r.status_code)
        else:
            self.cache_hits += 1
        self.robots = pf.Robots(text)
        log("[%s] robots.txt: %d rules for our group" % (self.source, self.robots.n))

    def allowed(self, url):
        if self.robots is None:
            self.load_robots()
        return self.robots.allowed(url)

    def get(self, url, binary_ok=False):
        if self.stopped:
            return None
        if not self.allowed(url):
            self.failures.append({"url": url, "why": "robots disallow"})
            log("[%s] REFUSED by robots.txt: %s" % (self.source, url))
            return None
        text = self._cached(url)
        if text is not None:
            self.cache_hits += 1
            return text
        if self.offline:
            self.failures.append({"url": url, "why": "not cached (offline)"})
            return None
        if self.requests_made >= self.max_requests:
            self.stopped = "request cap %d reached" % self.max_requests
            log("[%s] STOP: %s" % (self.source, self.stopped))
            return None
        backoff = 10.0
        net_tries = 0
        for attempt in range(4):
            self._pace()
            self.requests_made += 1
            try:
                r = self.s.get(url, timeout=45, allow_redirects=True)
                status = r.status_code
            except requests.RequestException as e:
                # a local network / DNS failure (this laptop, 1 Oct 2026) is not the site refusing us: wait 60 s and retry up to
                # 3 times without counting it against the host's circuit breaker or the request cap; then mark it unreachable
                status, r = None, None
                self.requests_made -= 1
                net_tries += 1
                log("[%s] network error on %s (%d/3): %s" % (self.source, url, net_tries, str(e)[:120]))
                if net_tries >= 3:
                    self.failures.append({"url": url, "why": "unreachable: %s" % str(e)[:80]})
                    self.net_failures = getattr(self, "net_failures", 0) + 1
                    if self.net_failures >= BREAKER:
                        self.stopped = "network: %d URLs unreachable - this end, not the site" % self.net_failures
                        log("[%s] STOP: %s" % (self.source, self.stopped))
                    return None
                time.sleep(60)
                continue
            if r is not None and status == 200:
                raw = r.content
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                body = raw.decode(r.encoding or "utf-8", "replace") if not binary_ok else raw.decode("utf-8", "replace")
                low = body[:20000].lower()
                has_data = ("__next_data__" in low or "application/ld+json" in low or "<urlset" in low or "<sitemapindex" in low
                            or "user-agent" in low)
                if not has_data and any(m in low for m in CHALLENGE_MARKS):
                    self.stopped = "challenge page at %s" % url
                    log("[%s] STOP: %s" % (self.source, self.stopped))
                    self.failures.append({"url": url, "why": "challenge page"})
                    return None
                self.consecutive = 0
                self._store(url, body, status)
                return body
            if r is not None and status in (404, 410):
                self.consecutive = 0
                self.failures.append({"url": url, "why": str(status)})
                log("[%s] %s %s" % (self.source, status, url))
                return None
            self.consecutive += 1
            log("[%s] HTTP %s on %s (attempt %d)" % (self.source, status, url, attempt + 1))
            if self.consecutive >= BREAKER:
                self.stopped = "circuit breaker: %d consecutive failures" % self.consecutive
                log("[%s] STOP: %s" % (self.source, self.stopped))
                return None
            if self.requests_made >= self.max_requests:
                break
            time.sleep(backoff + random.uniform(0, 3))
            backoff *= 2
        self.failures.append({"url": url, "why": "gave up after retries"})
        return None

    def sitemap_urls(self, url, depth=0):
        """<loc> entries of a sitemap or sitemap index (recursing one level), gz tolerated."""
        body = self.get(url, binary_ok=True)
        if not body:
            return []
        locs = [htmlmod.unescape(m) for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", body, re.S)]
        if "<sitemapindex" in body[:2000].lower() and depth < 1:
            out = []
            for l in locs:
                out.extend(self.sitemap_urls(l, depth + 1))
            return out
        return locs


# ------------------------------------------------------------------------------------------------------- parse helpers
LD_RX = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
NEXT_RX = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
PUSH_RX = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', re.S)


def ld_blocks(html):
    out = []
    for m in LD_RX.finditer(html):
        txt = m.group(1).strip()
        try:
            d = json.loads(txt)
        except ValueError:
            try:
                d = json.loads(htmlmod.unescape(txt))
            except ValueError:
                continue
        out.extend(d if isinstance(d, list) else [d])
    return out


def ld_walk(obj, types):
    """Every node whose @type is one of `types` (ItemList items are entered, @graph flattened)."""
    found = []

    def rec(o, depth):
        if depth > 12:
            return
        if isinstance(o, dict):
            t = o.get("@type")
            tl = t if isinstance(t, list) else [t]
            if any(x in types for x in tl):
                found.append(o)
            for v in o.values():
                rec(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                rec(v, depth + 1)
    rec(obj, 0)
    return found


def next_data(html):
    m = NEXT_RX.search(html)
    return json.loads(m.group(1)) if m else None


def rsc_text(html):
    """Concatenated, unescaped payload of Next.js App Router flight pushes (self.__next_f.push)."""
    parts = []
    for m in PUSH_RX.finditer(html):
        try:
            parts.append(json.loads('"' + m.group(1) + '"'))
        except ValueError:
            parts.append(m.group(1).encode().decode("unicode_escape", "replace"))
    return "".join(parts)


def find_dicts(obj, pred, limit=5000, depth=0):
    """Depth-first: every dict for which pred(d) is true."""
    out = []
    if depth > 14 or len(out) > limit:
        return out
    if isinstance(obj, dict):
        if pred(obj):
            out.append(obj)
        for v in obj.values():
            out.extend(find_dicts(v, pred, limit, depth + 1))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(find_dicts(v, pred, limit, depth + 1))
    return out


def json_objects_in(text, key_marker):
    """Balanced-brace JSON objects embedded in a flight/RSC text stream that contain key_marker. Tolerant, best effort."""
    out = []
    start = 0
    while True:
        i = text.find(key_marker, start)
        if i < 0:
            break
        # walk back to the enclosing '{' at depth 0 for this object
        j = i
        depth = 0
        while j >= 0:
            c = text[j]
            if c == "}":
                depth += 1
            elif c == "{":
                if depth == 0:
                    break
                depth -= 1
            j -= 1
        if j < 0:
            start = i + len(key_marker)
            continue
        # walk forward to the matching '}'
        k, depth, instr, esc = j, 0, False, False
        while k < len(text):
            c = text[k]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
            else:
                if c == '"':
                    instr = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        break
            k += 1
        chunk = text[j:k + 1]
        try:
            out.append(json.loads(chunk))
        except ValueError:
            pass
        start = k + 1 if k > i else i + len(key_marker)
    return out


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def beds_from(v):
    if v is None:
        return None
    if isinstance(v, str) and v.strip().lower().startswith("studio"):
        return 0
    n = num(v)
    return int(n) if n is not None else None


def slugify(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-") or None


def digits_only(s):
    if not s:
        return None
    d = re.sub(r"\D", "", str(s))
    return d or None


def ts(s):
    if not s:
        return None
    try:
        if isinstance(s, (int, float)):
            return dt.datetime.fromtimestamp(s / (1000.0 if s > 1e11 else 1.0), dt.timezone.utc).replace(tzinfo=None)
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t.astimezone(dt.timezone.utc).replace(tzinfo=None) if t.tzinfo else t
    except (ValueError, OSError):
        return None


def district_of(community_text):
    low = (community_text or "").lower()
    for d, words in DISTRICT_WORDS.items():
        if any(w in low for w in words):
            return d
    return None


# ------------------------------------------------------------------------------------------------------ the row model
def snapshot_row(portal, run_date, r):
    """r: adapter dict with keys listing_id, building_name, community, bedrooms, price, price_period, size_sqft, property_type,
    furnished, lat, lon, listed_date, last_refreshed_at, permit, broker_license, is_verified, stable (dict for the hash)."""
    bedrooms = r.get("bedrooms")
    return {
        "run_date": run_date, "portal": portal, "listing_id": str(r["listing_id"]),
        "building_slug": r.get("building_slug") or slugify(r.get("building_name")), "building_name": r.get("building_name"),
        "pf_location_id": None, "pf_location_path": None, "community": r.get("community"),
        "bedrooms": bedrooms, "beds_band": pf.beds_band(bedrooms),
        "price": r.get("price"), "price_period": r.get("price_period") or "yearly", "size_sqft": r.get("size_sqft"),
        "property_type": r.get("property_type"), "furnished": r.get("furnished"),
        "is_verified": r.get("is_verified"), "is_direct_from_developer": None,
        "broker_license": r.get("broker_license"), "lat": r.get("lat"), "lon": r.get("lon"),
        "listed_date": r.get("listed_date"), "last_refreshed_at": r.get("last_refreshed_at"),
        "permit_token": digits_only(r.get("permit")),
        "raw_hash": hashlib.sha256(json.dumps(r.get("stable") or {}, sort_keys=True, default=str).encode()).hexdigest(),
    }


# ------------------------------------------------------------------------------------------------------- adapters
def furnished_from_text(*texts):
    t = " ".join(x for x in texts if isinstance(x, str)).lower()
    if "unfurnished" in t or "un-furnished" in t:
        return "unfurnished"
    if "semi furnished" in t or "semi-furnished" in t or "partly furnished" in t:
        return "partly"
    if "furnished" in t:
        return "furnished"
    return None


class Adapter:
    """collect(district) -> (rows, pages_fetched). Each adapter does its own paging with self.f (robots/cache/pacing inside)."""
    portal = host = None

    def __init__(self, fetcher):
        self.f = fetcher
        self.notes = []
        self.sitemap_total = None

    def note(self, s):
        if s not in self.notes:
            self.notes.append(s)
            log("[%s] NOTE %s" % (self.portal, s))


def _ld_listing_fields(node):
    """Common JSON-LD RealEstateListing / Offer reading (espace): price, address, floorSize, rooms, geo, permit, url, datePosted."""
    out = {}
    offers = node.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = offers.get("price") or node.get("price") or (offers.get("priceSpecification") or {}).get("price")
    out["price"] = num(price)
    addr = node.get("address") or {}
    if isinstance(addr, dict):
        out["street"] = addr.get("streetAddress")
        out["locality"] = addr.get("addressLocality")
    fs = node.get("floorSize") or {}
    if isinstance(fs, dict) and fs.get("value") is not None:
        v = num(fs.get("value"))
        unit = str(fs.get("unitCode") or fs.get("unitText") or "").upper()
        out["size_sqft"] = v * SQM_TO_SQFT if unit in ("MTK", "SQM", "M2") else v
    rooms = node.get("numberOfRooms") or node.get("numberOfBedrooms")
    if isinstance(rooms, dict):
        rooms = rooms.get("value")
    out["bedrooms"] = beds_from(rooms)
    geo = node.get("geo") or {}
    out["lat"], out["lon"] = num(geo.get("latitude")), num(geo.get("longitude"))
    out["permit"] = node.get("permitNumber")
    out["url"] = node.get("url") or offers.get("url")
    out["name"] = node.get("name")
    out["listed_date"] = ts(node.get("datePosted") or offers.get("validFrom") or node.get("dateCreated"))
    return out


# ---------------------------------------------------------------------------------------- Allsopp & Allsopp (Next.js)
class Allsopp(Adapter):
    """List pages /dubai/properties/residential/lettings/in-areas-area-<slug>[/page-N]: __NEXT_DATA__ pageProps.data.data.hits are
    Elasticsearch docs whose `fields` are Salesforce columns (pba__*). The area slug comes from the site's own footer links on the
    lettings page (JVC verified 1 Oct 2026); any slug is accepted only when the page echoes it in params.inAreas and page-N only
    when params.page echoes N. Seen 1 Oct 2026 (deviations from the probe): pba__totalarea_pb__c is SQFT (detail JSON-LD unitCode
    FTK), not SQM; no trakheesiNumber / permit anywhere on list or detail pages (pba_uaefields__Title_Deed__c is a title-deed
    number, NOT a permit, so permit_token stays null); listed date = transferred_date__c; the ES `sort` value is the update time."""
    portal, host = "allsopp", "www.allsoppandallsopp.com"
    LIST = "/dubai/properties/residential/lettings"
    AREA_SLUG = {"jumeirahvillagecircle": "area-jumeirah-village-circle", "businessbay": "area-business-bay"}
    PER_PAGE = 20
    # Salesforce agent/owner columns present in every hit: read for nothing, never persisted
    DROP = ("listing_agent_name", "listing_agent_mobile", "listing_agent_Whatsapp", "listing_agent_Email", "ownerid", "pba__propertyownercontact_pb__c")

    def collect(self, district):
        rows, pages = [], 0
        slug = self.AREA_SLUG[district]
        page, total = 1, None
        while not self.f.stopped and page <= 80:
            url = "%s%s/in-areas-%s%s" % (self.f.base, self.LIST, slug, "" if page == 1 else "/page-%d" % page)
            h = self.f.get(url)
            if not h:
                break
            pages += 1
            d = ((next_data(h) or {}).get("props") or {}).get("pageProps", {}).get("data") or {}
            params = d.get("params") or {}
            echoed = (params.get("inAreas") or {}).get("keywordwithArea_Codes_aa__c") or []
            if slug not in echoed:
                self.note("area slug %s not echoed by the page (params.inAreas=%s) - stopping this district" % (slug, echoed))
                break
            if str((params.get("page") or [page])[0]) != str(page):
                self.note("page %d not echoed (params.page=%s) - stopping" % (page, params.get("page")))
                break
            total = d.get("total")
            hits = ((d.get("data") or {}).get("hits")) or []
            for hit in hits:
                r = self.row(hit.get("fields") or {}, hit.get("sort"))
                if r:
                    rows.append(r)
            if not hits or total is None or page * self.PER_PAGE >= total:
                break
            page += 1
        log("[allsopp] %s: total %s adverts, %d pages, %d rows" % (district, total, pages, len(rows)))
        return rows, pages

    def row(self, f, sort):
        g = lambda k: (f.get(k) or [None])[0]
        ref = g("pba__broker_s_listing_id__c")
        if not ref or g("pba__listingtype__c") not in (None, "Rent"):
            return None
        area = (g("listing_area") or "").strip().strip(".")
        parts = [x.strip() for x in area.split(",") if x.strip()]
        bname = parts[-2] if len(parts) >= 2 else (parts[0] if parts else None)
        comm = parts[-1] if parts else None
        upd = sort[0] if isinstance(sort, list) and sort else None
        return {"listing_id": ref, "building_name": bname, "community": comm, "bedrooms": beds_from(g("pba__bedrooms_pb__c")),
                "price": num(g("pba__listingprice_pb__c")), "price_period": "yearly", "size_sqft": num(g("pba__totalarea_pb__c")),
                "property_type": g("property_type_website__c"), "furnished": furnished_from_text(g("name")),
                "lat": num(g("pba__latitude_pb__c")), "lon": num(g("pba__longitude_pb__c")),
                "listed_date": ts(g("transferred_date__c")), "last_refreshed_at": ts(upd) if isinstance(upd, (int, float)) else None,
                "permit": None, "broker_license": None, "is_verified": None,
                "stable": {"ref": ref, "price": g("pba__listingprice_pb__c"), "beds": g("pba__bedrooms_pb__c"), "area": g("pba__totalarea_pb__c"),
                           "status": g("pba__status__c"), "name": g("name"), "listing_area": area}}


# --------------------------------------------------------------------------------------------- fam Properties (sitemap)
class Fam(Adapter):
    """Detail pages enumerated from /sitemap.xml (robots forbids ?page= and ?sort=, so no list paging). Path
    /<area>-dubai/<building-slug>/<beds>-for-rent-<id>. Data: JSON-LD RealEstateListing.about (Apartment: numberOfBedrooms,
    floorSize sqft, geo, addressLocality) + offers.price; the reference 'AR-<id>' is in the HTML 'Ref no.' cell; building name
    from the BreadcrumbList (position 3). Seen 1 Oct 2026: no permitNumber field and no permit digits on the page - only a
    Madmoun QR link (permit_token null); no listedAt - only 'N days ago' text, so listed_date is approximate (today - N)."""
    portal, host = "fam", "famproperties.com"
    SITEMAP = "/sitemap.xml"
    AREA_PATH = {"jumeirahvillagecircle": "jumeirah-village-circle-dubai", "businessbay": "business-bay-dubai"}
    APT_RX = re.compile(r"/(?:studio|\d+-bedroom-(?:apartment|penthouse|hotel-apartment|duplex))-for-rent-\d+/?$")

    def collect(self, district):
        urls = self.f.sitemap_urls(self.f.base + self.SITEMAP)
        self.sitemap_total = len(urls)
        area = self.AREA_PATH[district]
        rx = re.compile(r"^https?://(?:www\.)?famproperties\.com/%s/[^/]+/[^/]+-for-rent-\d+/?$" % re.escape(area))
        all_rent = sorted(u for u in urls if rx.match(u))
        picked = [u for u in all_rent if self.APT_RX.search(u)]
        log("[fam] sitemap: %d URLs; %s: %d rent detail URLs, %d apartments/studios" % (len(urls), area, len(all_rent), len(picked)))
        rows, pages = [], 0
        for u in picked:
            if self.f.stopped:
                break
            h = self.f.get(u)
            if not h:
                continue
            pages += 1
            r = self.row(h, u)
            if r:
                rows.append(r)
        return rows, pages

    def row(self, html, url):
        parts = urlsplit(url).path.strip("/").split("/")
        bslug = parts[1] if len(parts) > 1 else None
        m = re.search(r"-(\d+)/?$", url)
        lid = m.group(1) if m else url
        ld = ld_blocks(html)
        node = next((n for n in ld_walk(ld, {"RealEstateListing"})), {})
        about = node.get("about") or {}
        offers = node.get("offers") or {}
        price = num(offers.get("price") or (offers.get("priceSpecification") or {}).get("price"))
        fs = about.get("floorSize") or {}
        size = num(fs.get("value")) if isinstance(fs, dict) else None
        if size is not None and str(fs.get("unitText") or fs.get("unitCode") or "sqft").lower() in ("sqm", "mtk", "m2"):
            size *= SQM_TO_SQFT
        geo = about.get("geo") or {}
        addr = about.get("address") or {}
        bname = None
        for bc in ld_walk(ld, {"BreadcrumbList"}):
            items = sorted(bc.get("itemListElement") or [], key=lambda x: x.get("position", 0))
            if len(items) >= 3:
                bname = items[2].get("name")
        m = re.search(r"Ref no\.\s*</dt>\s*<dd[^>]*>\s*(AR-\d+)", html) or re.search(r"\b(AR-\d{4,})\b", html)
        ref = m.group(1) if m else "AR-" + lid
        m = re.search(r">Listed</dt>\s*<dd[^>]*>\s*(\d+)\s*(day|week|month|hour)s?\s*ago", html)
        listed = None
        if m:
            n, unit = int(m.group(1)), m.group(2)
            days = {"hour": 0, "day": n, "week": 7 * n, "month": 30 * n}[unit]
            listed = dt.datetime.combine(dt.date.today() - dt.timedelta(days=days), dt.time())
        m = re.search(r"Permit(?: Number| No\.?)?\s*</[a-z]+>\s*<[a-z]+[^>]*>\s*(\d{6,})", html, re.I)
        permit = m.group(1) if m else None
        return {"listing_id": ref, "building_name": bname, "building_slug": bslug, "community": addr.get("addressLocality") or parts[0],
                "bedrooms": beds_from(about.get("numberOfBedrooms")), "price": price, "price_period": "yearly", "size_sqft": size,
                "property_type": about.get("@type"), "furnished": furnished_from_text(node.get("name"), node.get("description")),
                "lat": num(geo.get("latitude")), "lon": num(geo.get("longitude")), "listed_date": listed, "last_refreshed_at": None,
                "permit": permit, "broker_license": None, "is_verified": None,
                "stable": {"ref": ref, "price": price, "beds": about.get("numberOfBedrooms"), "size": size, "name": node.get("name"), "building": bname}}


# ------------------------------------------------------------------------------------------------ Betterhomes (bhomes)
class Bhomes(Adapter):
    """Clean paths only: /en/rent/apartment/uae/dubai/<community>/<project>[/<tower>] from sitemap/properties-for-rent.xml; the
    deepest level under each project is fetched (tower pages, or the project page when it has no towers). Never ?page=, never
    _next/data. Data: RSC flight 'initialData.properties' (16 per page: slug bh-r-N, address 'Tower, Community', bedrooms,
    totalArea sqft, price, priceUnit, lat/lon, dataSourceCreatedAt/UpdatedAt) + JSON-LD ItemList (all adverts on the path, price only).
    Seen 1 Oct 2026: the probe's createdAt/statusUpdatedAt are named dataSourceCreatedAt/dataSourceUpdatedAt; the DLD permit is a
    QR image only (permit_token null); adverts beyond the first 16 of a path appear only in JSON-LD (price, no beds/size)."""
    portal, host = "bhomes", "www.bhomes.com"
    SITEMAP = "/sitemap/properties-for-rent.xml"
    AREA_PATH = {"jumeirahvillagecircle": "jumeirah-village-circle", "businessbay": "business-bay"}

    def collect(self, district):
        urls = self.f.sitemap_urls(self.f.base + self.SITEMAP)
        self.sitemap_total = len(urls)
        area = self.AREA_PATH[district]
        prefix = "/en/rent/apartment/uae/dubai/%s" % area
        paths = sorted({urlsplit(u).path.rstrip("/") for u in urls if urlsplit(u).path.rstrip("/").startswith(prefix)})
        leaves = [p for p in paths if p != prefix and not any(q != p and q.startswith(p + "/") for q in paths)]
        log("[bhomes] sitemap: %d URLs; %s: %d paths, %d leaf (tower/project) pages" % (len(urls), area, len(paths), len(leaves)))
        rows, pages = [], 0
        for p in leaves:
            if self.f.stopped:
                break
            h = self.f.get(self.f.base + p)
            if not h:
                continue
            pages += 1
            rows.extend(self.rows(h, p))
        return rows, pages

    def rows(self, html, path):
        tail = path.strip("/").split("/")
        path_tower = tail[-1].replace("-", " ").title() if len(tail) > 6 else None
        flight = rsc_text(html)
        full = {}
        for o in json_objects_in(flight, '"listingTypeSlug"'):
            if isinstance(o, dict) and str(o.get("slug", "")).lower().startswith("bh-"):
                full.setdefault(o["slug"].upper(), o)
        out, seen = [], set()
        for o in full.values():
            ref = o["slug"].upper()
            seen.add(ref)
            addr = [x.strip() for x in (o.get("address") or "").split(",") if x.strip()]
            bname = addr[0] if len(addr) >= 2 else path_tower
            out.append({"listing_id": ref, "building_name": bname, "community": o.get("location") or (addr[-1] if addr else None),
                        "bedrooms": beds_from(o.get("bedrooms")), "price": num(o.get("price")) if not o.get("isPriceOnRequest") else None,
                        "price_period": (o.get("priceUnit") or "yearly").lower(), "size_sqft": num(o.get("totalArea")),
                        "property_type": o.get("propertyType"), "furnished": furnished_from_text(o.get("title")),
                        "lat": num(o.get("latitude")), "lon": num(o.get("longitude")),
                        "listed_date": ts(o.get("dataSourceCreatedAt")), "last_refreshed_at": ts(o.get("dataSourceUpdatedAt")),
                        "permit": None, "broker_license": None, "is_verified": None,
                        "stable": {"ref": ref, "price": o.get("price"), "beds": o.get("bedrooms"), "size": o.get("totalArea"), "title": o.get("title"),
                                   "updated": o.get("dataSourceUpdatedAt"), "address": o.get("address")}})
        ld_only = 0
        for n in ld_walk(ld_blocks(html), {"RealEstateListing"}):
            m = re.search(r"(bh-r-\d+)", (n.get("@id") or n.get("url") or ""), re.I)
            if not m:
                continue
            ref = m.group(1).upper()
            if ref in seen:
                continue
            seen.add(ref)
            ld_only += 1
            loc = (n.get("location") or {}).get("address") or {}
            out.append({"listing_id": ref, "building_name": path_tower, "community": (n.get("location") or {}).get("name") or loc.get("addressRegion"),
                        "bedrooms": None, "price": num((n.get("offers") or {}).get("price")), "price_period": "yearly", "size_sqft": None,
                        "property_type": "Apartment", "furnished": furnished_from_text(n.get("name")), "lat": None, "lon": None,
                        "listed_date": None, "last_refreshed_at": None, "permit": None, "broker_license": None, "is_verified": None,
                        "stable": {"ref": ref, "price": (n.get("offers") or {}).get("price"), "name": n.get("name")}})
        if ld_only:
            self.note("%s: %d adverts beyond the first 16 came from JSON-LD only (price, no beds/size) - clean paths carry one flight page" % (path, ld_only))
        return out


# ------------------------------------------------------------------------------------------------------- Espace
class Espace(Adapter):
    """HTML list page /properties-for-rent/in-<area>/type-apartment (taken from the site's own /sitemap page; JVC has no rent
    page there, only sale) -> detail pages /properties-single/...-marl-<id>: JSON-LD RealEstateListing with permitNumber,
    floorSize FTK, numberOfRooms, datePosted, identifier 'MARL-<id>', streetAddress 'Tower, Community'. seller.employee is never kept."""
    portal, host = "espace", "espace.ae"
    AREA_PATH = {"businessbay": "business-bay"}

    def collect(self, district):
        area = self.AREA_PATH.get(district)
        if not area:
            self.note("no rent list page for %s on espace.ae/sitemap (only sale) - 0 requests" % district)
            return [], 0
        h = self.f.get(self.f.base + "/properties-for-rent/in-%s/type-apartment" % area)
        if not h:
            return [], 0
        links = sorted({m for m in re.findall(r'href="((?:https?://(?:www\.)?espace\.ae)?/properties-single/[^"#?]+)"', h)})
        log("[espace] %s list: %d detail links" % (area, len(links)))
        rows, pages = [], 1
        for l in links:
            if self.f.stopped:
                break
            u = l if l.startswith("http") else self.f.base + l
            dh = self.f.get(u)
            if not dh:
                continue
            pages += 1
            r = self.row(dh, u)
            if r:
                rows.append(r)
        return rows, pages

    def row(self, html, url):
        node = next((n for n in ld_walk(ld_blocks(html), {"RealEstateListing"})), None)
        if not node:
            return None
        f = _ld_listing_fields(node)
        m = re.search(r"(marl-\d+)", url, re.I)
        ref = node.get("identifier") or (m.group(1) if m else url)
        street = f.get("street") or ""
        parts = [x.strip() for x in street.split(",") if x.strip()]
        permit = node.get("permitNumber")
        if not permit:
            m = re.search(r"Permit Number</span>\s*<p[^>]*>\s*(\d{6,})", html)
            permit = m.group(1) if m else None
        return {"listing_id": str(ref).upper(), "building_name": parts[0] if parts else None, "community": parts[-1] if len(parts) > 1 else None,
                "bedrooms": f.get("bedrooms"), "price": f.get("price"), "price_period": "yearly", "size_sqft": f.get("size_sqft"),
                "property_type": "Apartment", "furnished": furnished_from_text(node.get("name"), node.get("description")),
                "lat": f.get("lat"), "lon": f.get("lon"), "listed_date": f.get("listed_date"), "last_refreshed_at": None,
                "permit": permit, "broker_license": None, "is_verified": None,
                "stable": {"ref": ref, "price": f.get("price"), "beds": f.get("bedrooms"), "size": f.get("size_sqft"), "permit": permit, "street": street}}


ADAPTERS = {"allsopp": Allsopp, "fam": Fam, "bhomes": Bhomes, "espace": Espace}


# ---------------------------------------------------------------------------------------------------------- binding
def bind_rows(portal, snap):
    """lst_building_alias tuples for every distinct building_slug in snap: exact normalised name match (pf_listings rules)."""
    idx = pf.register_index()
    seen, rows = {}, []
    for r in snap:
        if not r["building_slug"] or r["building_slug"] in seen:
            continue
        districts = [d for d in [district_of(r.get("community"))] if d]
        m = pf.match_building(r["building_name"], idx, districts or None) \
            or {"dld_project": None, "dld_project_number": None, "key": None, "method": "unmatched", "confidence": 0.0}
        if m["method"].startswith("cross_district"):
            # beds_left rows carry 'dld:<name>' keys with no district prefix, so pf_listings' district narrowing rejects them
            # as "another district" (seen 1 Oct 2026: AB Cavalier, Belgravia, Binghatti Gems in JVC). Same exact-normalised
            # rule, un-narrowed: accepted only when every candidate agrees on one dld: key (no district-keyed rival exists).
            m2 = pf.match_building(r["building_name"], idx, None)
            if m2 and m2["method"] == "exact_norm_name" and str(m2.get("key") or "").startswith("dld:"):
                m = m2
        seen[r["building_slug"]] = m
        rows.append((portal, r["building_slug"], None, r["building_name"], r.get("community"),
                     m["dld_project"], m["dld_project_number"], m["key"], m["method"], m["confidence"]))
    return rows


def write_summary(source, summary):
    d = os.path.join(OUT, source)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "run_%s.json" % dt.date.today().isoformat())
    summary = dict(summary, written_at=dt.datetime.now().isoformat(timespec="seconds"), measure=MEASURE)
    existing = []
    if os.path.exists(path):
        try:
            existing = json.load(open(path, encoding="utf-8"))
        except Exception:
            existing = []
    existing.append(summary)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=1, default=str)


# --------------------------------------------------------------------------------------------------------- lake write
def lake_write(portal, run_date, snap, alias_rows, spill_stem):
    """ONE short write window after every request is done. Chain running / lake held -> spill and return 4."""
    d = os.path.join(OUT, portal)
    os.makedirs(d, exist_ok=True)
    spill = os.path.join(d, "pending_%s.json" % run_date.isoformat())
    with open(spill, "w", encoding="utf-8") as fh:
        json.dump({"run_date": str(run_date), "portal": portal, "rows": snap, "aliases": alias_rows}, fh, default=str)
    try:
        con = pf.lake_connect(read_only=False)
    except Exception as e:
        log("[%s] lake unavailable (%s); %d rows spilled to %s - re-run with --offline, or `replay --source %s`, after '=== daily done'"
            % (portal, str(e)[:110], len(snap), spill, portal))
        return 4, spill
    try:
        pf.ensure_schema(con)
        slugs = sorted({r["building_slug"] for r in snap if r["building_slug"]})

        def body():
            con.execute("delete from lst_listing_snapshot where portal = ? and run_date = ?", [portal, run_date])     # idempotent same-day re-run
            if snap:
                con.executemany("insert into lst_listing_snapshot (%s) values (%s)" % (", ".join(pf.SNAP_COLS), ", ".join("?" * len(pf.SNAP_COLS))),
                                [tuple(r[c] for c in pf.SNAP_COLS) for r in snap])
            con.execute("create temp table if not exists _snap_in as select * from lst_listing limit 0")
            con.execute("delete from _snap_in")
            con.executemany("insert into _snap_in values (?,?,?,?,?,?,?,?,?,?)",
                            [(portal, r["listing_id"], run_date, run_date, r["building_slug"], r["beds_band"], r["price"], r["price"],
                              r["listed_date"], r["permit_token"]) for r in snap])
            con.execute("""update lst_listing l set last_seen = ?, last_price = i.last_price, beds_band = i.beds_band,
                               permit_token = coalesce(i.permit_token, l.permit_token)
                           from _snap_in i where i.portal = l.portal and i.listing_id = l.listing_id""", [run_date])
            con.execute("""insert into lst_listing select i.* from _snap_in i
                           where not exists (select 1 from lst_listing l where l.portal = i.portal and l.listing_id = i.listing_id)""")
            if alias_rows:
                con.execute("create temp table if not exists _alias_in as select * from lst_building_alias limit 0")
                con.execute("delete from _alias_in")
                con.executemany("insert into _alias_in values (?,?,?,?,?,?,?,?,?,?)", alias_rows)
                con.execute("""delete from lst_building_alias where portal = ? and method <> 'manual'
                               and building_slug in (select building_slug from _alias_in)""", [portal])
                con.execute("""insert into lst_building_alias select i.* from _alias_in i
                               where not exists (select 1 from lst_building_alias a where a.portal = i.portal and a.building_slug = i.building_slug)""")
        pf.write_lake(con, body, "lst %s" % portal)
        n = con.execute("select count(*) from lst_listing_snapshot where portal = ? and run_date = ?", [portal, run_date]).fetchone()[0]
        log("[%s] lake write done: %d snapshot rows for %s, %d alias rows" % (portal, n, run_date, len(alias_rows)))
    finally:
        con.close()
    try:
        os.replace(spill, spill + ".written")
    except OSError:
        pass
    return 0, None


# ------------------------------------------------------------------------------------------------------------ actions
def run_source(source, districts, max_requests, dry=False, offline=False, probe=False):
    cls = ADAPTERS[source]
    f = Fetcher(source, cls.host, max_requests, offline=offline)
    ad = cls(f)
    run_date = dt.date.today()
    t0 = time.time()
    snap, per_district, raw_first = [], {}, None
    f.load_robots()
    for district in districts:
        if probe:
            f.max_requests = min(f.max_requests, f.requests_made + 3)    # a probe parses one or two pages, no more
        try:
            rows, pages = ad.collect(district)
        except Exception as e:
            log("[%s] collect error for %s: %s" % (source, district, str(e)[:200]))
            f.failures.append({"district": district, "why": "collect: %s" % str(e)[:160]})
            rows, pages = [], 0
        kept = [r for r in rows if r.get("price") is not None or r.get("bedrooms") is not None]
        for r in kept:
            if not r.get("community"):
                r["community"] = district
            if raw_first is None:
                raw_first = r
            snap.append(snapshot_row(source, run_date, r))
        per_district[district] = {"pages": pages, "rows": len(kept), "dropped_empty": len(rows) - len(kept)}
    seen, uniq = set(), []
    for r in snap:
        if r["listing_id"] not in seen:
            seen.add(r["listing_id"])
            uniq.append(r)
    snap = uniq
    alias_rows = bind_rows(source, snap)
    bound = sum(1 for a in alias_rows if a[7])
    fields = ("price", "bedrooms", "size_sqft", "lat", "lon", "listed_date", "last_refreshed_at", "permit_token", "furnished", "building_name")
    summary = {"action": "probe" if probe else ("crawl_dry" if dry else "crawl"), "source": source, "districts": per_district, "run_date": str(run_date),
               "requests_made": f.requests_made, "cache_hits": f.cache_hits, "seconds": round(time.time() - t0, 1),
               "listings": len(snap), "permits": sum(1 for r in snap if r["permit_token"]),
               "fields_present": {k: sum(1 for r in snap if r.get(k) is not None) for k in fields},
               "buildings": len(alias_rows), "buildings_bound": bound, "buildings_unbound": len(alias_rows) - bound,
               "unbound_names": sorted({a[3] for a in alias_rows if not a[7] and a[3]})[:80],
               "notes": ad.notes, "failures": f.failures[:40], "stopped": f.stopped, "sitemap_total": ad.sitemap_total}
    if probe or dry:
        if raw_first:
            print("--- first record (adapter dict, stable omitted):")
            print(json.dumps({k: v for k, v in raw_first.items() if k != "stable"}, indent=1, default=str))
        for r in snap[:30]:
            print("  %-14s %-30s beds=%-4s band=%-6s price=%-9s sqft=%-7s furn=%-11s listed=%s permit=%s"
                  % (r["listing_id"], (r["building_name"] or "")[:30], r["bedrooms"], r["beds_band"], r["price"], round(r["size_sqft"]) if r["size_sqft"] else None,
                     r["furnished"], r["listed_date"], r["permit_token"]))
        print(json.dumps(summary, indent=1, default=str))
        write_summary(source, summary)
        return 3 if (f.stopped and "challenge" in f.stopped) else 0
    rc, spill = lake_write(source, run_date, snap, alias_rows, "crawl")
    summary["lake_write"] = "deferred" if rc == 4 else "done"
    summary["spill"] = spill
    write_summary(source, summary)
    log("[%s] crawl: %d requests, %d cache hits, %d listings, %d permits, %d/%d buildings bound%s" % (
        source, f.requests_made, f.cache_hits, len(snap), summary["permits"], bound, len(alias_rows), "; STOPPED: " + f.stopped if f.stopped else ""))
    return 3 if (f.stopped and "challenge" in f.stopped) else rc


def replay(source):
    d = os.path.join(OUT, source)
    files = sorted(fn for fn in os.listdir(d) if fn.startswith("pending_") and fn.endswith(".json")) if os.path.isdir(d) else []
    if not files:
        log("[%s] nothing pending" % source)
        return 0
    p = os.path.join(d, files[-1])
    data = json.load(open(p, encoding="utf-8"))
    run_date = dt.date.fromisoformat(data["run_date"])
    rows = data["rows"]
    for r in rows:
        r["run_date"] = run_date
        for k in ("listed_date", "last_refreshed_at"):
            r[k] = ts(r[k]) if r.get(k) else None
    aliases = bind_rows(source, rows)                           # re-bound at replay time, so a matcher fix reaches spilled runs too
    rc, _ = lake_write(source, run_date, rows, aliases, "replay")
    write_summary(source, {"action": "replay", "source": source, "run_date": str(run_date), "rows": len(rows), "lake_write": "deferred" if rc == 4 else "done"})
    return rc


def rebind(source, date=None):
    """Re-bind lst_building_alias for one portal from its snapshot rows (one short read, then one short write). No network."""
    run_date = dt.date.fromisoformat(date) if date else dt.date.today()
    con = pf.lake_connect(read_only=True)
    try:
        cols = ["building_slug", "building_name", "community"]
        rows = [dict(zip(cols, r)) for r in con.execute(
            "select building_slug, any_value(building_name), any_value(community) from lst_listing_snapshot where portal = ? and run_date = ? group by 1",
            [source, run_date]).fetchall()]
    finally:
        con.close()
    alias_rows = bind_rows(source, rows)
    con = pf.lake_connect(read_only=False)
    try:
        def body():
            con.execute("create temp table if not exists _alias_in as select * from lst_building_alias limit 0")
            con.execute("delete from _alias_in")
            con.executemany("insert into _alias_in values (?,?,?,?,?,?,?,?,?,?)", alias_rows)
            con.execute("delete from lst_building_alias where portal = ? and method <> 'manual' and building_slug in (select building_slug from _alias_in)", [source])
            con.execute("""insert into lst_building_alias select i.* from _alias_in i
                           where not exists (select 1 from lst_building_alias a where a.portal = i.portal and a.building_slug = i.building_slug)""")
        pf.write_lake(con, body, "lst rebind %s" % source)
    finally:
        con.close()
    bound = sum(1 for a in alias_rows if a[7])
    log("[%s] rebind %s: %d buildings, %d bound, %d unbound" % (source, run_date, len(alias_rows), bound, len(alias_rows) - bound))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="action", required=True)
    for name in ("probe", "crawl"):
        s = sub.add_parser(name)
        s.add_argument("--source", required=True, help="allsopp|fam|bhomes|espace|all")
        s.add_argument("--district", action="append", required=True, help="our district slug (repeatable): jumeirahvillagecircle, businessbay")
        s.add_argument("--max-requests", type=int, default=150 if name == "crawl" else 10)
        s.add_argument("--dry", action="store_true")
        s.add_argument("--offline", action="store_true")
    r = sub.add_parser("replay", help="write the newest pending_<date>.json of a source to the lake (no network)")
    r.add_argument("--source", required=True)
    b = sub.add_parser("rebind", help="re-bind lst_building_alias for a source from its snapshot rows (no network)")
    b.add_argument("--source", required=True, help="allsopp|fam|bhomes|espace|all")
    b.add_argument("--date")
    a = ap.parse_args()
    if a.action == "replay":
        return replay(a.source)
    if a.action == "rebind":
        return max(rebind(s, a.date) for s in (list(ADAPTERS) if a.source == "all" else [a.source]))
    sources = list(ADAPTERS) if a.source == "all" else [a.source]
    rc = 0
    for s in sources:
        try:
            r = run_source(s, a.district, a.max_requests, dry=a.dry, offline=a.offline, probe=(a.action == "probe"))
        except pf.LakeUnavailable as e:
            log("[%s] %s" % (s, e))
            r = 4
        rc = max(rc, r)
    return rc


if __name__ == "__main__":
    sys.exit(main())

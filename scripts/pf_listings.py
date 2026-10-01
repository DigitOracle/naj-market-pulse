"""Property Finder rental listings per building and bedroom band: ADVERTISED SUPPLY, not vacancy (research use only, 1 Oct 2026).

What it measures. The count of live rental adverts a portal shows for a building on a day, by bedroom band. An advert is
not an empty unit: one unit can carry several adverts, an advert can outlive its unit's letting, and buildings let
privately never appear. Every table and view here says "listings", never "vacant".

Where it reads. Only server-rendered SEO slug pages on www.propertyfinder.ae, plus a bare ?page=N on such a page - the
paths robots.txt allows (probed 1 Oct 2026: /search, /ajax/, /property-api/ and any filter query string are disallowed and
this crawler refuses them). Each page carries <script id="__NEXT_DATA__"> with props.pageProps.searchResult {meta, listings}.

How politely. One request every 4-6 s (randomised), an honest User-Agent with a contact address, robots.txt parsed at
start, exponential backoff on 429/403/5xx, a host circuit breaker (5 consecutive failures end the run), a 20-hour HTTP
cache under data/listings/cache/ so a same-day re-run costs the site nothing, a --max-requests cap (default 300), no
login, no proxies, and a stop on any challenge page.

Privacy. No agent names or ids, no broker names, no phone numbers, no share_url are persisted. broker.license_number (a
public ORN) is kept. A hash of the raw listing JSON is stored for change detection; the raw JSON is not.

Tables (lake, DuckLake - no constraints, so uniqueness is kept by the code):
  lst_listing_snapshot    one row per listing per run_date (append-only)
  lst_listing             one row per listing: first/last seen, first/last price (upserted)
  lst_building_alias      building slug -> pf location -> our register key (exact normalised name match only; else 'unmatched')
  v_lst_daily_building_counts   run_date x building x beds_band: listings_live, median_price, days-on-market medians

Deviations from the portal's documented shapes (seen 1 Oct 2026, SERP rows): `bedrooms` is a STRING ('studio', '1', ...)
with an integer twin `bedrooms_value`; `broker` has no `license_number` (only id/name/slug/phone/email/address/logo -
none of which is stored), so broker_license is always null from SERP rows; `rera` is "" (an empty string, not a dict)
on SERP rows, so permit_token is always null from SERP rows.
TODO (v2, NOT implemented - needs a separate GO): a per-listing detail-page fetch to read the RERA permit number / ORN.
It would cost one request per NEW listing (hundreds per day across the two crawled districts), so it must be rationed to
new listing_ids only, keep the same 4-6 s pacing, store only the permit token and the ORN (never agent fields), and
honour robots.txt for the /en/plp/ path - check it before building anything.

Community map. data/listings/pf_communities.json binds our 45 district slugs (data/names/anchors_<district>.json) to the
Property Finder community slug(s) in its rental URLs. A mapping is recorded only when a 200 community page named at
least one of our VERIFIED anchors (or a beds_left DLD project name) among its TOWER locations; the rest are 'unmapped'.

Usage:
  python scripts/pf_listings.py communities [--max-requests 150]              build/refresh pf_communities.json
  python scripts/pf_listings.py discover --community jumeirah-village-circle [--max-requests N] [--max-pages N] [--dry]
  python scripts/pf_listings.py discover --all-mapped --max-pages 10 [--pages-for jumeirah-village-circle=25,business-bay=25]
  python scripts/pf_listings.py crawl --buildings <slug-or-tail>,... [--max-requests N] [--dry]
  python scripts/pf_listings.py crawl --bound-only --district jumeirahvillagecircle [--max-requests N]
  python scripts/pf_listings.py crawl --all-bound [--max-requests N]
  python scripts/pf_listings.py report [--building slug] [--date YYYY-MM-DD]
  python scripts/pf_listings.py report --district jumeirahvillagecircle      -> data/listings/pf_supply_<district>.json
  python scripts/pf_listings.py bind-locations --community damac-hills --district damachills [--max-requests 120] [--dry]
Every run appends its summary to data/listings/pf_run_<date>.json.

Location bindings (1 Oct 2026, for villa / townhouse communities). Towers are bound by `discover` (TOWER locations seen in
listings). A villa community has no towers: its clusters are Property Finder SUBCOMMUNITY locations ('Carson', 'The Park
Villas > Topanga'). `bind-locations` reads that tree from the community's own villas / townhouses / apartments rent pages
(pageMeta.aggregationLinks, the same robots-allowed slug pages; one level of children per subcommunity) and binds a location
to a DLD project of the district register (beds_left_<district>.json, else a VERIFIED anchor) only when the names agree once
the community name is taken off both ('DAMAC HILLS - CARSON' = 'Carson'; 'Veneto at Damac Hills' = 'DAMAC HILLS-VENETO'), or
differ only by a doubled letter ('Picadilly' / 'PICCADILLY', method pf_location_spelling). Everything else goes to the review
list in data/listings/pf_bindings_<district>.json; nothing is guessed. A listing is counted once, under the most specific
bound location in its own location tree (a bound child, e.g. 'Silver Springs 3', owns its adverts; its bound parent 'Silver
Springs' keeps the rest). A register key 'dld:<project>' belongs to the district whose beds_left file holds it.
"""
import argparse, datetime as dt, hashlib, json, os, random, re, statistics, sys, time
from urllib.parse import urlsplit

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import lake  # noqa: E402

PORTAL = "propertyfinder"
HOST = "www.propertyfinder.ae"
BASE = "https://" + HOST
UA = "naj-market-pulse research crawler (academic, non-commercial; contact@digitalabbot.io)"
OUT = os.path.join(ROOT, "data", "listings")
CACHE = os.path.join(OUT, "cache")
LOG = os.path.join(ROOT, "logs", "pf_listings.log")
CACHE_HOURS = 20
DELAY = (4.0, 6.0)
BREAKER = 5
CHALLENGE_MARKS = ("captcha", "cf-challenge", "challenge-platform", "access denied", "are you a robot", "px-captcha")
GENERIC_WORDS = {"tower", "towers", "residence", "residences", "residency", "by", "the", "building", "bldg", "apartments", "apartment", "at", "and"}


# ----------------------------------------------------------------------------------------------------------- logging
def log(msg):
    line = "%s %s" % (dt.datetime.now().isoformat(timespec="seconds"), msg)
    print(line)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------------------------------------------- robots.txt
class Robots:
    """Google-style matcher: longest matching rule wins, '*' wildcard, '$' end anchor. Rules for our UA token or '*'."""

    def __init__(self, text):
        self.rules = []                                        # (allow: bool, regex, pattern_len)
        groups, cur, applies = {}, None, False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, v = [p.strip() for p in line.split(":", 1)]
            k = k.lower()
            if k == "user-agent":
                cur = v.lower()
                groups.setdefault(cur, [])
            elif k in ("allow", "disallow") and cur is not None:
                groups[cur].append((k == "allow", v))
        chosen = groups.get("naj-market-pulse") or groups.get("*") or []
        for allow, pat in chosen:
            if not pat:
                continue
            rx = "^" + "".join(".*" if c == "*" else ("$" if c == "$" else re.escape(c)) for c in pat)
            self.rules.append((allow, re.compile(rx), len(pat)))
        self.n = len(self.rules)

    def allowed(self, url):
        u = urlsplit(url)
        target = u.path + ("?" + u.query if u.query else "")
        best = None
        for allow, rx, ln in self.rules:
            if rx.match(target) and (best is None or ln > best[1] or (ln == best[1] and allow)):
                best = (allow, ln)
        return True if best is None else best[0]


# ------------------------------------------------------------------------------------------------------- the fetcher
class Fetcher:
    def __init__(self, max_requests, offline=False):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en"})
        self.max_requests = max_requests
        self.offline = offline
        self.requests_made = 0
        self.cache_hits = 0
        self.failures = []
        self.consecutive = 0
        self.last_at = 0.0
        self.stopped = None                                    # reason the run must end
        self.robots = None
        os.makedirs(CACHE, exist_ok=True)

    def _cache_path(self, url):
        return os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())

    def _cached(self, url):
        p = self._cache_path(url)
        if not os.path.exists(p + ".json"):
            return None
        try:
            meta = json.load(open(p + ".json", encoding="utf-8"))
            age_h = (time.time() - meta["fetched_at"]) / 3600.0
            if age_h > CACHE_HOURS and not self.offline:
                return None
            return open(p + ".html", encoding="utf-8").read()
        except Exception:
            return None

    def _store(self, url, text, status):
        p = self._cache_path(url)
        with open(p + ".html", "w", encoding="utf-8") as f:
            f.write(text)
        with open(p + ".json", "w", encoding="utf-8") as f:
            json.dump({"url": url, "fetched_at": time.time(), "status": status}, f)

    def _pace(self):
        gap = random.uniform(*DELAY)
        wait = self.last_at + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self.last_at = time.time()

    def load_robots(self):
        url = BASE + "/robots.txt"
        text = self._cached(url)
        if text is None:
            if self.offline:
                raise RuntimeError("robots.txt not cached and --offline given")
            self._pace()
            r = self.s.get(url, timeout=30)
            self.requests_made += 1
            if r.status_code != 200:
                raise RuntimeError("robots.txt returned %s - refusing to crawl" % r.status_code)
            text = r.text
            self._store(url, text, r.status_code)
        else:
            self.cache_hits += 1
        self.robots = Robots(text)
        log("robots.txt: %d rules loaded for our group" % self.robots.n)

    def get(self, url):
        """Return HTML or None. Honour robots, cache, pacing, backoff, circuit breaker, request cap."""
        if self.stopped:
            return None
        if self.robots is None:
            self.load_robots()
        if not self.robots.allowed(url):
            self.failures.append({"url": url, "why": "robots disallow"})
            log("REFUSED by robots.txt: %s" % url)
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
            log("STOP: " + self.stopped)
            return None
        backoff = 10.0
        for attempt in range(4):
            self._pace()
            self.requests_made += 1
            try:
                r = self.s.get(url, timeout=45, allow_redirects=True)
                status = r.status_code
            except requests.RequestException as e:
                status, r = None, None
                log("network error on %s: %s" % (url, str(e)[:120]))
            if r is not None and status == 200:
                body = r.text
                low = body[:20000].lower()
                if "__next_data__" not in low and any(m in low for m in CHALLENGE_MARKS):
                    self.stopped = "challenge page at %s" % url
                    log("STOP: " + self.stopped)
                    self.failures.append({"url": url, "why": "challenge page"})
                    return None
                self.consecutive = 0
                self._store(url, body, status)
                return body
            if r is not None and status == 404:
                self.consecutive = 0
                self.failures.append({"url": url, "why": "404"})
                log("404 %s" % url)
                return None
            self.consecutive += 1
            log("HTTP %s on %s (attempt %d)" % (status, url, attempt + 1))
            if self.consecutive >= BREAKER:
                self.stopped = "circuit breaker: %d consecutive failures" % self.consecutive
                log("STOP: " + self.stopped)
                self.failures.append({"url": url, "why": "status %s; breaker" % status})
                return None
            if self.requests_made >= self.max_requests:
                break
            time.sleep(backoff + random.uniform(0, 3))
            backoff *= 2
        self.failures.append({"url": url, "why": "gave up after retries"})
        return None


# -------------------------------------------------------------------------------------------------------- the parser
NEXT_RX = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def _find_search_result(obj, path="", depth=0):
    """Fallback: the first dict with 'listings' and 'meta' keys anywhere under props."""
    if depth > 8:
        return None, None
    if isinstance(obj, dict):
        if "listings" in obj and "meta" in obj and isinstance(obj["listings"], list):
            return obj, path
        for k, v in obj.items():
            got, p = _find_search_result(v, path + "." + k, depth + 1)
            if got is not None:
                return got, p
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            got, p = _find_search_result(v, path + "[%d]" % i, depth + 1)
            if got is not None:
                return got, p
    return None, None


def parse_page(html, verbose=False, want_props=False):
    m = NEXT_RX.search(html)
    if not m:
        raise ValueError("no __NEXT_DATA__ script in page")
    data = json.loads(m.group(1))
    props = (data.get("props") or {}).get("pageProps", {})
    sr = props.get("searchResult")
    path = "props.pageProps.searchResult"
    if not isinstance(sr, dict) or "listings" not in sr:
        sr, path = _find_search_result(data.get("props"), "props")
        if sr is None:
            raise ValueError("searchResult not found; pageProps keys: %s" % sorted((data.get("props") or {}).get("pageProps", {}).keys()))
        log("NOTE: searchResult found at %s (not the documented path)" % path)
    meta = sr.get("meta") or {}
    rows = []
    for item in sr.get("listings") or []:
        p = item.get("property") if isinstance(item, dict) and "property" in item else item
        if isinstance(p, dict):
            rows.append(p)
    if verbose:
        log("__NEXT_DATA__ path %s; meta keys %s; listing keys %s" % (path, sorted(meta.keys()), sorted(rows[0].keys()) if rows else "-"))
    if want_props:
        return meta, rows, path, props
    return meta, rows, path


def page_location_names(rows, props):
    """Every named location a community page exposes, for verifying a community mapping without extra requests:
    the listings' own TOWER/SUBCOMMUNITY names and tree, serpEnrichmentData.averagePrices tower names (~20 per page),
    and pageMeta.aggregationLinks (sub-community names). Returns {norm_name: (display name, source)}."""
    out = {}
    for p in rows:
        loc = p.get("location") or {}
        if loc.get("name") and (loc.get("type") or "").upper() in ("TOWER", "SUBCOMMUNITY"):
            out.setdefault(norm_name(loc["name"]), (loc["name"], "listing"))
        for t in p.get("location_tree") or []:
            if (t.get("type") or "").upper() in ("TOWER", "SUBCOMMUNITY") and t.get("name"):
                out.setdefault(norm_name(t["name"]), (t["name"], "listing_tree"))
    enrich = ((props.get("serpEnrichmentData") or {}).get("data") or {}) if isinstance(props, dict) else {}
    for a in enrich.get("averagePrices") or []:
        n = (a.get("location") or {}).get("n")
        if n:
            out.setdefault(norm_name(n), (n, "enrichment"))
    for a in ((props.get("pageMeta") or {}).get("aggregationLinks") or []) if isinstance(props, dict) else []:
        if a.get("name"):
            out.setdefault(norm_name(a["name"]), (a["name"], "aggregation"))
    out.pop("", None)
    return out


def beds_int(p):
    """SERP rows carry bedrooms as a string ('studio', '1', '2'; seen 1 Oct 2026) and an integer bedrooms_value."""
    v = p.get("bedrooms_value")
    if isinstance(v, int):
        return v
    b = p.get("bedrooms")
    if isinstance(b, str) and b.lower() == "studio":
        return 0
    try:
        return int(b)
    except (TypeError, ValueError):
        return None


def beds_band(b):
    if isinstance(b, str) and b.lower() == "studio":
        return "studio"
    if b is None:
        return "other"
    try:
        n = int(b)
    except (TypeError, ValueError):
        return "other"
    if n == 0:
        return "studio"
    if n in (1, 2):
        return str(n)
    if n >= 3:
        return "3+"
    return "other"


def _ts(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t.astimezone(dt.timezone.utc).replace(tzinfo=None) if t.tzinfo else t
    except ValueError:
        return None


def _sqft(size):
    if not isinstance(size, dict) or size.get("value") is None:
        return None
    v, unit = float(size["value"]), (size.get("unit") or "sqft").lower()
    return v * 10.7639 if unit in ("sqm", "m2", "sq.m") else v


def to_row(p, run_date, building_slug, building_name, community):
    """A privacy-reduced snapshot row. Only broker.license_number survives from broker/agent."""
    loc = p.get("location") or {}
    coords = loc.get("coordinates") or {}
    price = p.get("price") or {}
    broker = p.get("broker") or {}
    rera = p.get("rera") or {}
    token = None
    if isinstance(rera, dict):
        u = rera.get("permit_validation_url") or ""
        mm = re.search(r"([A-Za-z0-9_-]{40,})", u)
        token = mm.group(1) if mm else (rera.get("number") or None)
    # hash the advert's substance, not its rank: position/ranking_factors/is_new_insert churn every page view
    stable = {k: p.get(k) for k in ("id", "listing_id", "reference", "price", "bedrooms", "bathrooms", "size", "furnished",
                                    "property_type", "listed_date", "is_verified", "is_direct_from_developer", "completion_status",
                                    "rera", "title", "listing_level")}
    stable["location_id"] = loc.get("id")
    stable["broker_id"] = broker.get("id")
    raw_hash = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()
    bedrooms = beds_int(p)
    return {
        "run_date": run_date, "portal": PORTAL, "listing_id": str(p.get("listing_id") or p.get("id")),
        "building_slug": building_slug, "building_name": building_name or loc.get("name"),
        "pf_location_id": str(loc.get("id")) if loc.get("id") is not None else None,
        "pf_location_path": loc.get("path"), "community": community,
        "bedrooms": bedrooms,
        "beds_band": beds_band(p.get("bedrooms") if isinstance(p.get("bedrooms"), str) else bedrooms),
        "price": float(price["value"]) if price.get("value") is not None else None,
        "price_period": price.get("period"), "size_sqft": _sqft(p.get("size")),
        "property_type": p.get("property_type"), "furnished": str(p.get("furnished")) if p.get("furnished") is not None else None,
        "is_verified": bool(p.get("is_verified")) if p.get("is_verified") is not None else None,
        "is_direct_from_developer": bool(p.get("is_direct_from_developer")) if p.get("is_direct_from_developer") is not None else None,
        "broker_license": str(broker.get("license_number")) if broker.get("license_number") else None,
        "lat": coords.get("lat"), "lon": coords.get("lon"),
        "listed_date": _ts(p.get("listed_date")), "last_refreshed_at": _ts(p.get("last_refreshed_at")),
        "permit_token": token, "raw_hash": raw_hash,
    }


# ------------------------------------------------------------------------------------------------- URLs and slugs
def building_url(tail, page=1):
    u = "%s/en/rent/dubai/properties-for-rent-%s.html" % (BASE, tail)
    return u if page == 1 else u + "?page=%d" % page


def community_url(slug, page=1):
    u = "%s/en/rent/dubai/apartments-for-rent-%s.html" % (BASE, slug)
    return u if page == 1 else u + "?page=%d" % page


def tower_tail(loc):
    """Infer the SEO tail of a TOWER location from its slug, the way the verified Binghatti Amber URL is formed:
    'jumeirah-village-circle-district-11-binghatti-amber'. Slugs seen as '/dubai/a/b/c' or 'a-b-c' both reduce to that."""
    slug = (loc.get("slug") or "").strip("/")
    if not slug:
        return None
    parts = [p for p in slug.split("/") if p and p not in ("dubai", "en", "rent")]
    return "-".join(parts)


# -------------------------------------------------------------------------------------------------------- the lake
DDL = [
    """create table if not exists lst_listing_snapshot (
        run_date date, portal varchar, listing_id varchar, building_slug varchar, building_name varchar,
        pf_location_id varchar, pf_location_path varchar, community varchar, bedrooms integer, beds_band varchar,
        price double, price_period varchar, size_sqft double, property_type varchar, furnished varchar,
        is_verified boolean, is_direct_from_developer boolean, broker_license varchar, lat double, lon double,
        listed_date timestamp, last_refreshed_at timestamp, permit_token varchar, raw_hash varchar)""",
    """create table if not exists lst_listing (
        portal varchar, listing_id varchar, first_seen date, last_seen date, building_slug varchar, beds_band varchar,
        first_price double, last_price double, listed_date timestamp, permit_token varchar)""",
    """create table if not exists lst_building_alias (
        portal varchar, building_slug varchar, pf_location_id varchar, building_name varchar, community varchar,
        dld_project varchar, dld_project_number bigint, "key" varchar, method varchar, confidence double)""",
]
SNAP_COLS = ["run_date", "portal", "listing_id", "building_slug", "building_name", "pf_location_id", "pf_location_path",
             "community", "bedrooms", "beds_band", "price", "price_period", "size_sqft", "property_type", "furnished",
             "is_verified", "is_direct_from_developer", "broker_license", "lat", "lon", "listed_date", "last_refreshed_at",
             "permit_token", "raw_hash"]
VIEW = """create or replace view v_lst_daily_building_counts as
    with s as (
        select s.*, l.first_seen
        from lst_listing_snapshot s
        left join lst_listing l on l.portal = s.portal and l.listing_id = s.listing_id)
    select s.run_date, s.portal, s.building_slug, any_value(s.building_name) building_name,
           any_value(a."key") "key", any_value(a.dld_project) dld_project, s.beds_band,
           count(*) listings_live,
           median(s.price) median_price,
           median(s.run_date - cast(s.listed_date as date)) median_days_since_listed,
           max(s.run_date - cast(s.listed_date as date)) max_days_since_listed,
           median(s.run_date - s.first_seen) median_days_tracked
    from s
    left join lst_building_alias a on a.portal = s.portal and a.building_slug = s.building_slug
    group by s.run_date, s.portal, s.building_slug, s.beds_band"""


def write_lake(con, body, what):
    def tx():
        con.execute("BEGIN TRANSACTION")
        try:
            body()
            con.execute("COMMIT")
        except Exception:
            # a COMMIT that lost to another writer has already aborted the transaction; swallow the ROLLBACK's own error
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
    lake.retry(tx, what)


DAILY_LOG = os.path.join(ROOT, "daily_refresh.log")
ALIAS_FILE = os.path.join(OUT, "pf_aliases.json")              # lake-free copy of lst_building_alias, for building picks while the chain runs


class LakeUnavailable(RuntimeError):
    pass


def chain_running():
    """True while the production daily chain is running: the last '=== daily start' in daily_refresh.log has no later
    '=== daily done'. Decided from the log only, never from the clock (production owner's rule, 1 Oct 2026)."""
    try:
        with open(DAILY_LOG, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 400000))
            tail = fh.read().decode("utf-8", "ignore")
    except OSError:
        return False
    last = None
    for line in tail.splitlines():
        if "=== daily start" in line:
            last = "start"
        elif "=== daily done" in line:
            last = "done"
    return last == "start"


def lake_connect(read_only):
    """lake.connect, retried: another loader holding the catalogue makes even the ATTACH probe say 'database is locked'.
    Refuses outright (no connection at all, read or write) while the daily chain is running - see chain_running()."""
    if chain_running():
        raise LakeUnavailable("daily chain running (daily_refresh.log has a '=== daily start' with no later '=== daily done'); no lake connection opened")
    last = None
    for attempt in range(12):
        try:
            return lake.connect(read_only=read_only)
        except Exception as e:                                 # duckdb.Error, not a subclass we can name without importing duckdb
            last = e
            if "locked" not in str(e).lower():
                raise
            log("lake attach held (%s) - retry %d/12 in 10 s" % (str(e)[:60], attempt + 1))
            time.sleep(10)
    raise last


def ensure_schema(con):
    def body():
        for d in DDL:
            con.execute(d)
        con.execute(VIEW)
        con.execute(DELIST_VIEW)
    write_lake(con, body, "lst schema")


# ------------------------------------------------------------------------------------------------ register matching
def norm_name(s):
    words = re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split()
    return "".join(w for w in words if w not in GENERIC_WORDS)


def register_index():
    """normalised name -> list of candidate dicts from beds_left_*.json and anchors_*.json (all districts)."""
    idx = {}
    bl_dir = os.path.join(ROOT, "data", "dld", "beds_left")
    for fn in sorted(os.listdir(bl_dir)) if os.path.isdir(bl_dir) else []:
        if not fn.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(bl_dir, fn), encoding="utf-8"))
        except Exception:
            continue
        for r in d.get("rows", []):
            nm = norm_name(r.get("dld_project") or r.get("name"))
            if nm:
                idx.setdefault(nm, []).append({"dld_project": r.get("dld_project"), "dld_project_number": r.get("dld_project_number"),
                                               "key": r.get("key") or r.get("app_key"), "src": "beds_left"})
    nm_dir = os.path.join(ROOT, "data", "names")
    for fn in sorted(os.listdir(nm_dir)) if os.path.isdir(nm_dir) else []:
        if not fn.startswith("anchors_") or not fn.endswith(".json"):
            continue
        district = fn[len("anchors_"):-5]
        try:
            d = json.load(open(os.path.join(nm_dir, fn), encoding="utf-8"))
        except Exception:
            continue
        for a in d.get("anchors", []):
            nm = norm_name(a.get("name"))
            if nm and a.get("id") is not None:
                idx.setdefault(nm, []).append({"dld_project": a.get("name"), "dld_project_number": None,
                                               "key": "%s:%s" % (district, a["id"]), "src": "anchor"})
    return idx


def district_names(district):
    """Normalised register names for one district: VERIFIED anchors and beds_left DLD project names, with their source."""
    out = {}
    bl = os.path.join(ROOT, "data", "dld", "beds_left", "beds_left_%s.json" % district)
    if os.path.exists(bl):
        try:
            for r in json.load(open(bl, encoding="utf-8")).get("rows", []):
                nm = norm_name(r.get("dld_project") or r.get("name"))
                if nm:
                    out.setdefault(nm, (r.get("dld_project") or r.get("name"), "beds_left"))
        except Exception:
            pass
    an = os.path.join(ROOT, "data", "names", "anchors_%s.json" % district)
    if os.path.exists(an):
        try:
            for a in json.load(open(an, encoding="utf-8")).get("anchors", []):
                nm = norm_name(a.get("name"))
                if nm and a.get("identity_grade") == "VERIFIED":
                    out[nm] = (a.get("name"), "verified_anchor")           # anchors outrank beds_left as evidence
        except Exception:
            pass
    return out


def our_districts():
    nm_dir = os.path.join(ROOT, "data", "names")
    return sorted(fn[len("anchors_"):-5] for fn in os.listdir(nm_dir) if fn.startswith("anchors_") and fn.endswith(".json"))


def load_communities():
    p = os.path.join(OUT, "pf_communities.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {"districts": {}}


def community_districts(pf_slug, cmap=None):
    """Our district slug(s) a Property Finder community is mapped to (from pf_communities.json)."""
    cmap = cmap or load_communities()
    return sorted(d for d, v in cmap.get("districts", {}).items() if any(c["pf_slug"] == pf_slug for c in v.get("communities", [])))


def match_building(name, idx, districts=None):
    """Exact normalised match only. Unambiguous = all candidates agree on one key (or one dld_project_number).
    `districts`: when the building's community is mapped to our district(s), a same-named project elsewhere in Dubai
    is not a rival - candidates are first narrowed to those districts (if any survive)."""
    cands = idx.get(norm_name(name)) or []
    if not cands:
        return None
    if districts:
        narrowed = [c for c in cands if c.get("key") and c["key"].split(":")[0] in districts]
        if not narrowed:
            # the community is ours, but the only same-named projects sit in OTHER districts (e.g. 'Astoria Building', Al Satwa,
            # vs a JVC 'Astoria'): not a binding
            return {"dld_project": None, "dld_project_number": None, "key": None, "method": "cross_district:%d" % len(cands), "confidence": 0.0}
        cands = narrowed
    keys = {c["key"] for c in cands if c.get("key")}
    nums = {c["dld_project_number"] for c in cands if c.get("dld_project_number") is not None}
    if len(keys) == 1 or (len(nums) == 1 and len(keys) <= 1):
        c = next(c for c in cands if c.get("key") in keys) if keys else cands[0]
        proj = next((x["dld_project"] for x in cands if x["src"] == "beds_left"), c["dld_project"])
        num = next(iter(nums)) if nums else None
        return {"dld_project": proj, "dld_project_number": num, "key": c["key"], "method": "exact_norm_name", "confidence": 0.9}
    return {"dld_project": None, "dld_project_number": None, "key": None, "method": "ambiguous:%d" % len(keys), "confidence": 0.0}


def bind_aliases(aliases):
    """Pure Python, no lake: each tower dict -> the lst_building_alias row tuple, bound by exact normalised name."""
    idx = register_index()
    cmap = load_communities()
    rows = []
    for a in aliases:
        m = match_building(a["building_name"], idx, community_districts(a.get("community"), cmap)) \
            or {"dld_project": None, "dld_project_number": None, "key": None, "method": "unmatched", "confidence": 0.0}
        rows.append((PORTAL, a["building_slug"], a.get("pf_location_id"), a["building_name"], a.get("community"),
                     m["dld_project"], m["dld_project_number"], m["key"], m["method"], m["confidence"]))
    return rows


ALIAS_COLS = ["portal", "building_slug", "pf_location_id", "building_name", "community", "dld_project", "dld_project_number", "key", "method", "confidence"]


def save_alias_file(rows):
    """Merge alias rows into data/listings/pf_aliases.json (keyed by building_slug) so crawl can pick buildings while the lake is off-limits."""
    cur = {}
    try:
        cur = {r["building_slug"]: r for r in json.load(open(ALIAS_FILE, encoding="utf-8")).get("rows", [])}
    except Exception:
        pass
    for r in rows:
        d = dict(zip(ALIAS_COLS, r))
        if cur.get(d["building_slug"], {}).get("method") != "manual":
            cur[d["building_slug"]] = d
    os.makedirs(OUT, exist_ok=True)
    with open(ALIAS_FILE, "w", encoding="utf-8") as fh:
        json.dump({"as_of": dt.date.today().isoformat(), "note": "lake-free copy of lst_building_alias (research only); the lake is the record",
                   "rows": sorted(cur.values(), key=lambda d: d["building_slug"])}, fh, indent=0, ensure_ascii=False, default=str)
    return len(cur)


def alias_file_rows():
    try:
        return json.load(open(ALIAS_FILE, encoding="utf-8")).get("rows", [])
    except Exception:
        return []


def upsert_aliases(con, aliases):
    """aliases: list of dicts (building_slug, pf_location_id, building_name, community). Keeps existing manual rows."""
    rows = bind_aliases(aliases)
    save_alias_file(rows)

    def body():
        con.execute("create temp table if not exists _alias_in as select * from lst_building_alias limit 0")
        con.execute("delete from _alias_in")
        con.executemany("insert into _alias_in values (?,?,?,?,?,?,?,?,?,?)", rows)
        # rows a person has bound by hand (method 'manual') are never overwritten
        con.execute("""delete from lst_building_alias where portal = ? and method <> 'manual'
                       and building_slug in (select building_slug from _alias_in)""", [PORTAL])
        con.execute("""insert into lst_building_alias select i.* from _alias_in i
                       where not exists (select 1 from lst_building_alias a where a.portal = i.portal and a.building_slug = i.building_slug)""")
    write_lake(con, body, "lst_building_alias")
    matched = sum(1 for r in rows if r[7])
    return len(rows), matched


# ------------------------------------------------------------------------------------------------------- communities
# Candidate Property Finder community slugs per district, taken from the Dubai-level rent index pages
# (data/listings/pf_dubai_index.json: pageMeta.aggregationLinks of /en/rent/dubai/{apartments,villas}-for-rent.html,
# 100 + 94 communities, fetched 1 Oct 2026) and chosen by hand from each district's VERIFIED anchor names. Each entry
# is (slug, kind); kind 'villas' uses the villas-for-rent URL. A candidate becomes a mapping only when its page names
# one of our register names - nothing here is trusted unverified.
CANDIDATE_COMMUNITIES = {
    "alhebiahfifth": [("remraam", "apartments"), ("damac-lagoons", "villas")],
    "alkhairanfirst": [("dubai-creek-harbour-the-lagoons", "apartments")],
    "alsatwa": [("al-satwa", "apartments"), ("city-walk", "apartments")],
    "althanyahfifth": [("jumeirah-lake-towers", "apartments")],
    "alwasl": [("al-wasl", "apartments"), ("city-walk", "apartments"), ("al-safa", "apartments")],
    "alyelayiss1": [("cherrywoods", "villas")],
    "alyelayiss2": [("town-square", "apartments")],
    "alyufrah1": [("the-valley", "villas")],
    "arjan": [("arjan", "apartments")],
    "burjkhalifa": [("downtown-dubai", "apartments")],
    "businessbay": [("business-bay", "apartments")],
    "damachills": [("damac-hills", "apartments")],
    "dubaihills": [("dubai-hills-estate", "apartments")],
    "dubaiinvestmentparkfirst": [("dubai-investment-park-dip", "apartments")],
    "dubaiinvestmentparksecond": [("dubai-investment-park-dip", "apartments")],
    "dubaimarina": [("dubai-marina", "apartments")],
    "dubaimaritimecity": [("maritime-city", "apartments")],
    "dubaiproductioncity": [("dubai-production-city-impz", "apartments")],
    "dubaisciencepark": [("dubai-science-park", "apartments")],
    "dubaisportscity": [("dubai-sports-city", "apartments")],
    "dubaistudiocity": [("dubai-studio-city", "apartments")],
    "jabalalifirst": [("al-furjan", "apartments"), ("discovery-gardens", "apartments"), ("downtown-jebel-ali", "apartments"),
                      ("jebel-ali", "apartments"), ("the-gardens", "apartments")],
    "jabalaliindustrialsecond": [("downtown-jebel-ali", "apartments"), ("jebel-ali", "apartments")],
    "jltnorth": [("jumeirah-lake-towers", "apartments")],
    "jumeirahvillagecircle": [("jumeirah-village-circle", "apartments")],
    "jumeirahvillagetriangle": [("jumeirah-village-triangle", "apartments")],
    "madinatalmataar": [("dubai-south-dubai-world-central", "apartments"), ("expo-city", "apartments")],
    "madinathind4": [("damac-hills-2", "apartments"), ("damac-hills-2", "villas"), ("madinat-hind-4", "villas")],
    "majan": [("majan", "apartments"), ("living-legends", "apartments"), ("al-barari", "apartments")],
    "motorcity": [("motor-city", "apartments")],
    "palmdeira": [("dubai-islands", "apartments")],
    "palmjumeirah": [("palm-jumeirah", "apartments")],
    "samaaljadaf": [("al-jaddaf", "apartments"), ("culture-village", "apartments")],
    "siliconoasis": [("dubai-silicon-oasis", "apartments")],
    "sobhaheartland": [("mohammed-bin-rashid-city", "apartments")],
    "wadialsafa4": [("meydan", "apartments"), ("arabian-ranches", "villas")],
    "wadialsafa5": [("dubai-land-residence-complex", "apartments"), ("rukan", "apartments"), ("villanova", "villas"), ("arabian-ranches-2", "villas")],
}
# districts with no VERIFIED anchor and no beds_left row: nothing to verify against, so no request is spent. The hint
# is a guess for a future pass and is recorded as UNVERIFIED.
UNVERIFIABLE_HINTS = {
    "bukadra": "bukadra", "dubaiindustrialcity": "dubai-industrial-city", "goldensymphony": None, "jltsouth": "jumeirah-lake-towers",
    "liwan1": "liwan", "meydanone": "meydan", "rasalkhor": "ras-al-khor", "wadialsafa3": "wadi-al-safa-3",
}


def kind_url(slug, kind, page=1):
    u = "%s/en/rent/dubai/%s-for-rent-%s.html" % (BASE, kind, slug)
    return u if page == 1 else u + "?page=%d" % page


def communities(args):
    """Verify candidate community slugs against each district's register names; write pf_communities.json."""
    t0 = time.time()
    f = Fetcher(args.max_requests, offline=args.offline)
    prev = load_communities().get("districts", {})
    result = {}
    for district in our_districts():
        names = district_names(district)
        cands = CANDIDATE_COMMUNITIES.get(district, [])
        entry = {"status": "unmapped", "register_names": len(names),
                 "verified_anchors": sum(1 for v in names.values() if v[1] == "verified_anchor"), "communities": [], "rejected": []}
        if not names:
            entry["reason"] = "no VERIFIED anchor and no beds_left row to verify against; no request spent"
            if UNVERIFIABLE_HINTS.get(district):
                entry["unverified_hint"] = UNVERIFIABLE_HINTS[district]
            result[district] = entry
            continue
        if not cands:
            entry["reason"] = "no candidate slug in CANDIDATE_COMMUNITIES"
            result[district] = entry
            continue
        for slug, kind in cands:
            if f.stopped:
                break
            found, seen_total, page_count, total_count, loc_id = {}, 0, None, None, None
            for page in (1, 2):                                # page 2 only when page 1 names nothing of ours
                html = f.get(kind_url(slug, kind, page))
                if html is None:
                    break
                try:
                    meta, rows, _, props = parse_page(html, want_props=True)
                except ValueError as e:
                    log("%s/%s: %s" % (slug, kind, e))
                    break
                page_count = int(meta.get("page_count") or 1)
                total_count = meta.get("total_count")
                loc_id = loc_id or (props.get("seoData") or {}).get("locationId")
                locs = page_location_names(rows, props)
                seen_total += len(locs)
                for nm, (disp, src) in locs.items():
                    if nm in names:
                        found.setdefault(nm, {"pf_name": disp, "pf_source": src, "our_name": names[nm][0], "our_source": names[nm][1]})
                if found or page >= page_count:
                    break
            rec = {"pf_slug": slug, "kind": kind, "pf_location_id": loc_id, "total_count": total_count, "page_count": page_count,
                   "names_on_page": seen_total, "matches": len(found), "matched": sorted(found.values(), key=lambda m: m["our_name"])[:12]}
            if found:
                entry["communities"].append(rec)
                log("%-26s <- %s/%s: %d of our names among %d (%s)" % (district, slug, kind, len(found), seen_total,
                                                                      ", ".join(m["pf_name"] for m in list(found.values())[:4])))
            else:
                rec["why"] = "no register name on page 1-2" if page_count else "page not fetched"
                entry["rejected"].append(rec)
                log("%-26s x  %s/%s: none of our %d names among %d" % (district, slug, kind, len(names), seen_total))
        entry["status"] = "mapped" if entry["communities"] else "unmapped"
        if not entry["communities"]:
            entry["reason"] = f.stopped or "no candidate page named a register name"
        result[district] = entry
    # keep an earlier verified mapping if this run could not refetch it (cap / stop)
    for d, e in prev.items():
        if d in result and result[d]["status"] == "unmapped" and e.get("status") == "mapped" and f.stopped:
            result[d] = dict(e, carried_from=prev.get("as_of"))
    doc = {"as_of": dt.date.today().isoformat(), "measure": "community map for ADVERTISED SUPPLY research; not vacancy; research use only",
           "method": "a mapping is recorded only when a 200 Property Finder community rent page named at least one of the district's "
                     "VERIFIED anchors (anchors_<district>.json identity_grade=VERIFIED) or beds_left DLD project names among its TOWER / "
                     "SUBCOMMUNITY locations (listing locations, serpEnrichmentData.averagePrices, pageMeta.aggregationLinks); pages 1-2 only",
           "index_source": "data/listings/pf_dubai_index.json (Dubai-level aggregationLinks, 1 Oct 2026)",
           "requests_made": f.requests_made, "cache_hits": f.cache_hits, "seconds": round(time.time() - t0, 1), "stopped": f.stopped,
           "mapped": sum(1 for e in result.values() if e["status"] == "mapped"), "unmapped": sum(1 for e in result.values() if e["status"] != "mapped"),
           "districts": result}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "pf_communities.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    log("communities: %d mapped, %d unmapped of %d districts; %d requests, %d cache hits, %.0f s%s"
        % (doc["mapped"], doc["unmapped"], len(result), f.requests_made, f.cache_hits, doc["seconds"], "; STOPPED: " + f.stopped if f.stopped else ""))
    write_summary({k: v for k, v in doc.items() if k != "districts"} | {"action": "communities"}, None)
    return 3 if f.stopped else 0


# ---------------------------------------------------------------------------------------------------------- discover
def discover(args):
    if args.all_mapped:
        return discover_all(args)
    return discover_one(args)


def discover_all(args):
    """Every mapped community once, pages rationed: --max-pages for all, --pages-for slug=N overrides."""
    cmap = load_communities()
    plan = {}
    for d, e in cmap.get("districts", {}).items():
        for c in e.get("communities", []):
            plan.setdefault((c["pf_slug"], c["kind"]), set()).add(d)
    overrides = {}
    for kv in (args.pages_for or "").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            overrides[k.strip()] = int(v)
    shared = Fetcher(args.max_requests, offline=args.offline)
    rows, t0 = [], time.time()
    for (slug, kind), districts in sorted(plan.items(), key=lambda kv: (-max(0, overrides.get(kv[0][0], 0)), kv[0])):
        if shared.stopped:
            break
        sub = argparse.Namespace(**vars(args))
        sub.community, sub.kind, sub.max_pages, sub.verify = slug, kind, overrides.get(slug, args.max_pages), False
        rows.append(discover_one(sub, fetcher=shared, districts=sorted(districts), defer=True))
    # all fetching is over; now ONE short lake window for every community's towers (no lake handle existed until here)
    all_towers = {t["building_slug"]: t for r in rows for t in r.pop("towers_data", [])}
    if all_towers and not args.dry:
        # coverage table first, so a deferred lake write (exit 4) still leaves it on screen and in the run file
        for r in rows:
            log("discovered %-34s %-10s pages %3d/%-4s towers %4d reqs %3d" % (r["community"], r.get("kind", "apartments"), r["pages_fetched"],
                                                                                 r.get("page_count"), r["towers"], r["requests_made"]))
        written = write_aliases(list(all_towers.values()), "discover_all")
        con = lake_connect(read_only=True)
        try:
            meth = con.execute("""select community, case when method like 'ambiguous%' then 'ambiguous' when method = 'unmatched' then 'unmatched' else 'bound' end m, count(*)
                                  from lst_building_alias where portal = ? and building_slug in (select unnest(?::varchar[])) group by 1, 2""",
                               [PORTAL, list(all_towers)]).fetchall()
        finally:
            con.close()
        for r in rows:
            r.update({m: c for comm, m, c in meth if comm == r["community"]})
            r["alias_written"] = written.get("alias_rows")
    print("\n%-34s %-10s %7s %5s %6s %6s %6s %6s %6s" % ("community", "kind", "pages", "of", "towers", "bound", "ambig", "unmat", "reqs"))
    for r in rows:
        print("%-34s %-10s %7d %5s %6d %6d %6d %6d %6d" % (r["community"], r.get("kind", "apartments"), r["pages_fetched"], r.get("page_count"),
                                                            r["towers"], r.get("bound", 0), r.get("ambiguous", 0), r.get("unmatched", 0), r["requests_made"]))
    log("discover --all-mapped: %d communities, %d requests, %d cache hits, %.0f s%s" % (len(rows), shared.requests_made, shared.cache_hits,
                                                                                        time.time() - t0, "; STOPPED: " + shared.stopped if shared.stopped else ""))
    write_summary({"action": "discover_all", "communities": rows, "requests_made": shared.requests_made, "cache_hits": shared.cache_hits,
                   "seconds": round(time.time() - t0, 1), "stopped": shared.stopped}, "discover_all")
    return 3 if shared.stopped else 0


def write_aliases(tower_rows, spill_stem="discover"):
    """One short lake window: attach (retried), upsert, count, close. If the lake stays held, the towers are spilled to
    data/listings/pf_pending_<stem>_<date>.json and the run exits 4 instead of crashing; re-run later with --offline (cached pages)."""
    spill = os.path.join(OUT, "pf_pending_%s_%s.json" % (spill_stem, dt.date.today().isoformat()))
    os.makedirs(OUT, exist_ok=True)
    with open(spill, "w", encoding="utf-8") as fh:
        json.dump(tower_rows, fh, default=str)
    # the binding itself needs no lake: do it now and keep the lake-free alias copy current whatever happens next
    bound_rows = bind_aliases(tower_rows)
    save_alias_file(bound_rows)
    mem = {"bound": sum(1 for r in bound_rows if r[7]), "ambiguous": sum(1 for r in bound_rows if r[8].startswith("ambiguous")),
           "unmatched": sum(1 for r in bound_rows if r[8] == "unmatched")}
    try:
        con = lake_connect(read_only=False)
    except Exception as e:
        log("lake unavailable (%s); %d tower rows kept in %s and bound in %s (%s) - re-run with --offline once the chain is done"
            % (str(e)[:100], len(tower_rows), spill, ALIAS_FILE, mem))
        write_summary({"action": "discover_write_deferred", "stem": spill_stem, "towers": len(tower_rows), "spill": spill, "in_memory_binding": mem}, None)
        sys.exit(4)
    try:
        ensure_schema(con)
        n, matched = upsert_aliases(con, tower_rows)
        meth = con.execute("""select case when method like 'ambiguous%' then 'ambiguous' when method = 'unmatched' then 'unmatched' else 'bound' end m, count(*)
                              from lst_building_alias where portal = ? and building_slug in (select unnest(?::varchar[])) group by 1""",
                           [PORTAL, [t["building_slug"] for t in tower_rows]]).fetchall()
    finally:
        con.close()
    os.remove(spill)
    out = {"alias_rows": n, "alias_matched": matched}
    out.update({m: c for m, c in meth})
    log("lst_building_alias: %d towers written, %d bound to a register key by exact normalised name (%s)" % (n, matched, dict(meth)))
    return out


def discover_one(args, fetcher=None, districts=None, defer=False):
    kind = getattr(args, "kind", None) or "apartments"
    f = fetcher or Fetcher(args.max_requests, offline=args.offline)
    t0, req0 = time.time(), f.requests_made
    towers = {}
    path_seen = None
    page, page_count = 1, 1
    while page <= page_count and page <= args.max_pages:
        html = f.get(kind_url(args.community, kind, page))
        if html is None:
            break
        meta, rows, path_seen = parse_page(html, verbose=(page == 1))
        page_count = int(meta.get("page_count") or 1)
        for p in rows:
            loc = p.get("location") or {}
            if (loc.get("type") or "").upper() != "TOWER":
                continue
            tail = tower_tail(loc)
            if not tail:
                continue
            tree = p.get("location_tree") or []
            comm = next((t.get("slug") or t.get("name") for t in tree if (t.get("type") or "").upper() == "COMMUNITY"), args.community)
            towers.setdefault(tail, {"building_slug": tail, "pf_location_id": str(loc.get("id")), "building_name": loc.get("name"),
                                     "community": comm if isinstance(comm, str) else args.community, "pf_slug": loc.get("slug"),
                                     "pf_location_path": loc.get("path"), "n": 0})
            towers[tail]["n"] += 1
        log("discover %s/%s page %d/%d: %d listings, %d distinct towers so far" % (args.community, kind, page, page_count, len(rows), len(towers)))
        page += 1
    pages_fetched = page - 1
    log("discover: %d distinct TOWER slugs from %d request(s), %d cache hit(s); first tower slug seen: %r -> tail %r"
        % (len(towers), f.requests_made - req0, f.cache_hits, next(iter(towers.values()))["pf_slug"] if towers else None,
           next(iter(towers)) if towers else None))
    verified = None
    if towers and args.verify:
        tail = sorted(towers, key=lambda t: -towers[t]["n"])[0]
        html = f.get(building_url(tail))
        if html:
            meta, rows, _ = parse_page(html)
            verified = {"tail": tail, "total_count": meta.get("total_count"), "all_same_tower":
                        all(tower_tail(r.get("location") or {}) == tail for r in rows)}
            log("verify inferred URL %s: total_count=%s, listings on page all in that tower: %s" % (building_url(tail), meta.get("total_count"), verified["all_same_tower"]))
        else:
            verified = {"tail": tail, "ok": False}
    summary = {"action": "discover", "community": args.community, "kind": kind, "districts": districts, "requests_made": f.requests_made - req0,
               "cache_hits": f.cache_hits, "pages_fetched": pages_fetched, "page_count": page_count, "max_pages": args.max_pages,
               "coverage": round(pages_fetched / float(page_count), 3) if page_count else None, "towers": len(towers),
               "next_data_path": path_seen, "verified": verified, "failures": f.failures, "stopped": f.stopped, "seconds": round(time.time() - t0, 1)}
    if args.dry:
        for t in list(towers.values())[:40]:
            print("  %-70s %-40s n=%d" % (t["building_slug"], t["building_name"], t["n"]))
        print(json.dumps(summary, indent=1, default=str))
        return summary if fetcher else 0
    if towers and defer:
        summary["towers_data"] = list(towers.values())         # discover_all writes every community in one window at the end
    elif towers:
        # the lake is opened only now, after every request for this community is done, and closed straight after
        summary.update(write_aliases(list(towers.values())))
    write_summary(summary, "discover_%s" % args.community)
    return summary if fetcher else (3 if f.stopped else 0)


# ------------------------------------------------------------------------------------------------------------- crawl
def resolve_buildings(con, wanted):
    """Each entry is a full SEO tail (contains the community) or a short slug matched against lst_building_alias."""
    out = []
    known = {r["building_slug"]: r.get("building_name") for r in alias_file_rows()}
    if con is not None:
        try:
            known.update(dict(con.execute("select building_slug, building_name from lst_building_alias where portal = ?", [PORTAL]).fetchall()))
        except Exception:
            pass
    for w in wanted:
        w = w.strip().strip("/")
        if not w:
            continue
        if w in known:
            out.append(w)
            continue
        hits = [k for k in known if k.endswith("-" + w) or k == w]
        if len(hits) == 1:
            out.append(hits[0])
        elif len(hits) > 1:
            log("ambiguous short slug %r: %s - skipped" % (w, hits))
        elif "-" in w and w.count("-") >= 3:
            out.append(w)                                      # treat as a full tail
        else:
            log("unknown building %r (not in lst_building_alias; pass the full SEO tail) - skipped" % w)
    return out


def district_dld_keys(district):
    """Register keys of the district's beds_left file that do not carry the district prefix ('dld:damachillscarson'-style:
    a DLD project with no app building id). They belong to this district because its beds_left file holds them."""
    bl = os.path.join(ROOT, "data", "dld", "beds_left", "beds_left_%s.json" % district)
    try:
        rows = json.load(open(bl, encoding="utf-8")).get("rows", [])
    except Exception:
        return []
    return sorted({r.get("key") for r in rows if r.get("key") and not r["key"].startswith(district + ":")})


def key_in_district(key, district, dld_keys=None):
    if not key:
        return False
    if key.startswith(district + ":"):
        return True
    return key in (dld_keys if dld_keys is not None else district_dld_keys(district))


def district_key_sql(district, col='"key"'):
    """SQL fragment + params: the alias key belongs to `district` (prefix 'district:' or one of its beds_left dld: keys)."""
    return "(%s like ? or %s in (select unnest(?::varchar[])))" % (col, col), [district + ":%", district_dld_keys(district)]


def bound_buildings(con, district=None):
    """Alias rows with a register key: for one district (key prefix 'district:', or a dld: key of its beds_left file) or all.
    Ordered by district, slug."""
    if con is None:                                            # lake off-limits: the lake-free copy written by every discover
        dk = district_dld_keys(district) if district else None
        rows = [r for r in alias_file_rows() if r.get("key") and (not district or key_in_district(r["key"], district, dk))]
        return [r["building_slug"] for r in sorted(rows, key=lambda r: (r["key"].split(":")[0], r["building_slug"]))]
    sql = 'select building_slug from lst_building_alias where portal = ? and "key" is not null'
    params = [PORTAL]
    if district:
        frag, p = district_key_sql(district)
        sql += " and " + frag
        params += p
    sql += ' order by split_part("key", \':\', 1), building_slug'
    return [r[0] for r in con.execute(sql, params).fetchall()]


def location_tails(p):
    """The SEO tails of a listing's own location tree, root first (SUBCOMMUNITY / TOWER nodes, then its own location)."""
    out = []
    for t in (p.get("location_tree") or []):
        if (t.get("type") or "").upper() in ("SUBCOMMUNITY", "TOWER") and t.get("slug"):
            tl = tower_tail(t)
            if tl and tl not in out:
                out.append(tl)
    own = tower_tail(p.get("location") or {})
    if own and own not in out:
        out.append(own)
    return out


def owned_elsewhere(p, tail, bound):
    """The bound location deeper than `tail` in this listing's own tree, if any: the listing is counted there, not under
    `tail`. None when `tail` is the most specific bound location (always so for a tower with no bound child)."""
    tails = location_tails(p)
    if tail not in tails:
        return None
    for deeper in tails[tails.index(tail) + 1:]:
        if deeper in bound:
            return deeper
    return None


def crawl(args):
    run_date = dt.date.today()
    t0 = time.time()
    # Lake discipline (1 Oct 2026 incident: a connection left attached across a 25-page fetch loop held the catalogue and a
    # production step failed on 'database is locked'): a short READ-ONLY attach to pick the buildings, closed before the
    # first request; no lake handle exists while requests are in flight; one short write window at the end.
    rcon = _ro_con()
    try:
        bound_all = set(bound_buildings(rcon))                 # for the one-owner rule: a listing counts under its deepest bound location
        loc_names = {r["building_slug"]: r.get("building_name") for r in alias_file_rows() if (r.get("method") or "").startswith("pf_location")}
        if args.all_bound:
            buildings = bound_buildings(rcon)                  # rcon None -> pf_aliases.json
            scope = "all-bound"
        elif args.bound_only:
            if not args.district:
                log("--bound-only needs --district <our-slug>")
                return 2
            buildings = bound_buildings(rcon, args.district)
            scope = "bound:" + args.district
        else:
            buildings = resolve_buildings(rcon, [b for b in (args.buildings or "").split(",")])
            scope = "list"
    finally:
        if rcon is not None:
            rcon.close()
    if not buildings:
        log("nothing to crawl")
        return 2
    log("crawl %s: %d building(s), request cap %d" % (scope, len(buildings), args.max_requests))
    f = Fetcher(args.max_requests, offline=args.offline)
    snap, per_building, path_seen = [], {}, None
    completed, partial = [], None                              # a building cut by the cap/stop is not written: counts stay whole
    for tail in buildings:
        page, page_count, n_b, n_else = 1, 1, 0, 0
        bname = loc_names.get(tail)                            # a bound SUBCOMMUNITY keeps its own name, not its first tower's
        tb0, treq0 = time.time(), f.requests_made
        if f.stopped:
            break
        while page <= page_count:
            html = f.get(building_url(tail, page))
            if html is None:
                break
            meta, rows, path_seen = parse_page(html, verbose=(page == 1 and tail == buildings[0]))
            page_count = int(meta.get("page_count") or 1)
            if page == 1:
                log("%s: total_count=%s page_count=%s per_page=%s new=%s" % (tail, meta.get("total_count"), page_count, meta.get("per_page"), meta.get("new_properties_count")))
            for p in rows:
                loc = p.get("location") or {}
                if owned_elsewhere(p, tail, bound_all):        # counted under the deeper bound location instead (no-op for towers)
                    n_else += 1
                    continue
                if tower_tail(loc) != tail and (loc.get("type") or "").upper() == "TOWER" and tail not in loc_names:
                    log("  note: listing %s on %s page %d sits in tower %r" % (p.get("listing_id") or p.get("id"), tail, page, loc.get("slug")))
                bname = bname or (loc.get("name") if (loc.get("type") or "").upper() == "TOWER" else None)
                tree = p.get("location_tree") or []
                comm = next((t.get("slug") or t.get("name") for t in tree if (t.get("type") or "").upper() == "COMMUNITY"), None)
                snap.append(to_row(p, run_date, tail, bname, comm))
                n_b += 1
            page += 1
        seen_b = n_b + n_else                                  # n_else: adverts on this page owned by a deeper bound location
        whole = (page > page_count) and seen_b > 0 and not f.stopped
        per_building[tail] = {"listings": n_b, "pages": page - 1, "page_count": page_count if seen_b else None,
                              "total_count": meta.get("total_count") if seen_b else None, "requests": f.requests_made - treq0,
                              "seconds": round(time.time() - tb0, 1), "complete": whole}
        if n_else:
            per_building[tail]["owned_by_deeper_location"] = n_else
            log("%s: %d advert(s) left to the deeper bound location that holds them" % (tail, n_else))
        if whole:
            completed.append(tail)
        elif seen_b == 0:
            log("%s: no rows (404 / empty) - nothing written for it today" % tail)
        else:
            snap = [r for r in snap if r["building_slug"] != tail]
            log("%s: cut at page %d/%d by '%s' - its %d rows are dropped so the day's counts stay whole"
                % (tail, page - 1, page_count, f.stopped or "fetch failure", n_b))
            if f.stopped:
                partial = tail
                break
    # one row per listing per run: a listing shown on two pages (list shifted between fetches) is kept once
    seen, uniq = set(), []
    for r in snap:
        k = (r["listing_id"], r["building_slug"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    snap = uniq
    pages_dist = sorted(v["pages"] for v in per_building.values() if v["complete"])
    summary = {"action": "crawl", "scope": scope, "run_date": str(run_date), "requests_made": f.requests_made, "cache_hits": f.cache_hits,
               "seconds": round(time.time() - t0, 1), "buildings_planned": len(buildings), "buildings_fetched": len(per_building),
               "buildings_complete": len(completed), "building_cut_by_stop": partial,
               "buildings_not_reached": [b for b in buildings if b not in per_building],
               "pages_per_building": {"n": len(pages_dist), "min": pages_dist[0] if pages_dist else None, "median": statistics.median(pages_dist) if pages_dist else None,
                                      "p90": pages_dist[int(0.9 * (len(pages_dist) - 1))] if pages_dist else None, "max": pages_dist[-1] if pages_dist else None,
                                      "sum": sum(pages_dist)},
               "listings_seen": len(snap), "per_building": per_building,
               "next_data_path": path_seen, "failures": f.failures, "stopped": f.stopped, "detail_pages_fetched": 0,
               "permit_tokens_found": sum(1 for r in snap if r["permit_token"])}
    buildings = completed                                      # only whole buildings are written / counted as crawled today
    if args.dry:
        for r in snap:
            print("  %-12s beds=%-4s band=%-6s price=%-10s %-6s sqft=%-8s listed=%s refreshed=%s verified=%s orn=%s"
                  % (r["listing_id"], r["bedrooms"], r["beds_band"], r["price"], r["price_period"],
                     round(r["size_sqft"]) if r["size_sqft"] else None, r["listed_date"], r["last_refreshed_at"], r["is_verified"], r["broker_license"]))
        print(json.dumps(summary, indent=1, default=str))
        return 0

    def body():
        con.execute("delete from lst_listing_snapshot where portal = ? and run_date = ? and building_slug in (select unnest(?::varchar[]))",
                    [PORTAL, run_date, buildings])                 # idempotent same-day re-run
        if snap:
            con.executemany("insert into lst_listing_snapshot (%s) values (%s)" % (", ".join(SNAP_COLS), ", ".join("?" * len(SNAP_COLS))),
                            [tuple(r[c] for c in SNAP_COLS) for r in snap])
        con.execute("create temp table if not exists _snap_in as select * from lst_listing limit 0")
        con.execute("delete from _snap_in")
        con.executemany("insert into _snap_in values (?,?,?,?,?,?,?,?,?,?)",
                        [(PORTAL, r["listing_id"], run_date, run_date, r["building_slug"], r["beds_band"], r["price"], r["price"],
                          r["listed_date"], r["permit_token"]) for r in snap])
        con.execute("""update lst_listing l set last_seen = ?, last_price = i.last_price, beds_band = i.beds_band,
                           permit_token = coalesce(i.permit_token, l.permit_token)
                       from _snap_in i where i.portal = l.portal and i.listing_id = l.listing_id""", [run_date])
        con.execute("""insert into lst_listing select i.* from _snap_in i
                       where not exists (select 1 from lst_listing l where l.portal = i.portal and l.listing_id = i.listing_id)""")
    # every request is done; the lake is opened only now, for one short write window, and closed again
    # a parse of the whole run already sits in memory (snap); save it to disk first so a held lake loses nothing
    spill = os.path.join(OUT, "pf_pending_crawl_%s_%s.json" % (re.sub(r"[^a-z0-9]+", "_", scope), run_date.isoformat()))
    with open(spill, "w", encoding="utf-8") as fh:
        json.dump({"run_date": str(run_date), "buildings": buildings, "rows": snap}, fh, default=str)
    tw0 = time.time()
    try:
        con = lake_connect(read_only=False)
    except Exception as e:
        log("lake held after retries (%s); %d snapshot rows kept in %s - re-run the same crawl with --offline once the lake is free (pages are cached 20 h)"
            % (str(e)[:80], len(snap), spill))
        write_summary(dict(summary, lake_write="deferred", spill=spill), None)
        return 4
    try:
        ensure_schema(con)
        # counts before the write, so "new" means not yet in lst_listing and "delisted" means seen before but not today
        ids = [r["listing_id"] for r in snap]
        prev = con.execute("select listing_id, last_seen from lst_listing where portal = ? and building_slug in (select unnest(?::varchar[]))",
                           [PORTAL, buildings]).fetchall()
        prev_ids = {p[0] for p in prev}
        prev_date = max([p[1] for p in prev], default=None)
        new_ids = [i for i in ids if i not in prev_ids]
        delisted = [p[0] for p in prev if p[0] not in set(ids) and prev_date is not None and p[1] == prev_date and prev_date < run_date]
        write_lake(con, body, "lst snapshot")
        # make sure every crawled building has an alias row (discover may not have run for it)
        have = {r[0] for r in con.execute("select building_slug from lst_building_alias where portal = ?", [PORTAL]).fetchall()}
        missing = {}
        for r in snap:
            if r["building_slug"] not in have and r["building_name"]:
                missing[r["building_slug"]] = {"building_slug": r["building_slug"], "pf_location_id": r["pf_location_id"],
                                               "building_name": r["building_name"], "community": r["community"]}
        if missing:
            n, m = upsert_aliases(con, list(missing.values()))
            log("lst_building_alias: %d new building(s) from crawl, %d bound by exact name" % (n, m))
    finally:
        con.close()
    os.remove(spill)
    summary.update({"new_listings": len(new_ids), "delisted_since_last_run": len(delisted), "lake_write_seconds": round(time.time() - tw0, 1)})
    log("crawl %s: %d listings in %d whole buildings (%d planned, %d fetched), %d new, %d delisted; %d requests, %d cache hits, %.0f s; pages/building median %s max %s%s"
        % (scope, len(snap), len(completed), summary["buildings_planned"], len(per_building), len(new_ids), len(delisted), f.requests_made, f.cache_hits,
           summary["seconds"], summary["pages_per_building"]["median"], summary["pages_per_building"]["max"], "; STOPPED: " + f.stopped if f.stopped else ""))
    write_summary(summary, None)
    return 3 if f.stopped else 0


def _ro_con():
    """A short read-only attach, or None when the chain is running / the lake is held (callers fall back to pf_aliases.json)."""
    try:
        return lake_connect(read_only=True)
    except Exception as e:
        log("lake read skipped (%s) - using %s" % (str(e)[:90], ALIAS_FILE))
        return None


def write_summary(summary, stem):
    """Append to data/listings/pf_run_<today>.json (every run) and, when `stem` is given, to pf_<stem>.json as well."""
    os.makedirs(OUT, exist_ok=True)
    summary["written_at"] = dt.datetime.now().isoformat(timespec="seconds")
    summary["measure"] = "ADVERTISED SUPPLY (live portal adverts), not vacancy; research use only"
    for st in ["run_%s" % dt.date.today().isoformat()] + ([stem] if stem else []):
        path = os.path.join(OUT, "pf_%s.json" % st)
        existing = []
        if os.path.exists(path):
            try:
                existing = json.load(open(path, encoding="utf-8"))
                existing = existing if isinstance(existing, list) else [existing]
            except Exception:
                existing = []
        existing.append(summary)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=1, default=str)
        log("summary -> %s" % path)


# ------------------------------------------------------------------------------------------------------------ report
DELIST_VIEW = """create or replace view v_lst_daily_delisting as
    -- per building and run_date: adverts live on that building's PREVIOUS run but absent on this one (delisted),
    -- and adverts first seen on this run (new). 'delisted' is an advert withdrawn, not a unit let.
    with runs as (
        select distinct portal, building_slug, run_date from lst_listing_snapshot),
    pairs as (
        select portal, building_slug, run_date,
               lag(run_date) over (partition by portal, building_slug order by run_date) prev_date
        from runs)
    select p.portal, p.building_slug, p.run_date, p.prev_date,
           (select count(*) from lst_listing_snapshot a where a.portal = p.portal and a.building_slug = p.building_slug and a.run_date = p.prev_date
              and not exists (select 1 from lst_listing_snapshot b where b.portal = a.portal and b.building_slug = a.building_slug
                                                                   and b.run_date = p.run_date and b.listing_id = a.listing_id)) delisted,
           (select count(*) from lst_listing_snapshot b join lst_listing l on l.portal = b.portal and l.listing_id = b.listing_id
             where b.portal = p.portal and b.building_slug = p.building_slug and b.run_date = p.run_date and l.first_seen = p.run_date) new_listings,
           (select count(*) from lst_listing_snapshot a where a.portal = p.portal and a.building_slug = p.building_slug and a.run_date = p.prev_date) prev_live
    from pairs p"""


def register_projects(district):
    """{key: DLD project name} of the district register (beds_left_<district>.json), and its as_of."""
    bl = os.path.join(ROOT, "data", "dld", "beds_left", "beds_left_%s.json" % district)
    try:
        d = json.load(open(bl, encoding="utf-8"))
    except Exception:
        return {}, None
    out = {}
    for r in d.get("rows", []):
        if r.get("key"):
            out.setdefault(r["key"], r.get("dld_project") or r.get("name"))
    return out, d.get("as_of")


def home_type_totals(by_building):
    tot = {}
    for v in by_building.values():
        for t, n in v.items():
            tot[t] = tot.get(t, 0) + n
    return dict(sorted(tot.items(), key=lambda kv: -kv[1]))


def coverage_block(district, bound_rows, out_rows, listings_live):
    """How much of the district the bound locations cover: DLD projects of the register bound to a Property Finder location
    (N of M), how many of those had adverts today, bound locations outside the register (VERIFIED-anchor towers), and -
    when bind-locations has read the community pages - the adverts captured against the community's own advert count."""
    reg, reg_as_of = register_projects(district)
    bound_keys = {r["key"] for r in bound_rows if r.get("key")}
    in_reg = bound_keys & set(reg)
    with_adverts = {r["key"] for r in out_rows if r.get("key") in reg}
    cov = {"unit": "DLD projects in the district register", "register_source": "data/dld/beds_left/beds_left_%s.json" % district,
           "register_as_of": reg_as_of, "register_total": len(reg), "register_bound": len(in_reg),
           "register_with_adverts": len(with_adverts), "bound_locations": len(bound_rows),
           "bound_locations_outside_register": sum(1 for r in bound_rows if r.get("key") and r["key"] not in reg),
           "unbound_register": sorted(reg[k] for k in set(reg) - in_reg)[:80],
           "say": "covers %d of %d DLD projects" % (len(in_reg), len(reg))}
    try:
        b = json.load(open(os.path.join(OUT, "pf_bindings_%s.json" % district), encoding="utf-8"))
        ca = b.get("community_adverts") or {}
        if ca.get("total"):
            cov["community_adverts"] = dict(ca, captured=listings_live)
            cov["say_adverts"] = "%d of %d adverts the site shows for %s" % (listings_live, ca["total"], ca.get("community_name") or district)
    except Exception:
        pass
    return cov


# --------------------------------------------------------------------------------------------- bind-locations
AGG_RX = re.compile(r"/en/rent/dubai/([a-z-]+)-for-rent-([a-z0-9-]+)\.html$")
LOC_KINDS = ("villas", "townhouses", "apartments")


def spelling(name, comm_words=()):
    """'Picadilly Green' and 'PICCADILLY GREEN' agree: doubled letters collapsed WITHIN each word (a spelling variant), the
    community's own words and the generic words dropped. Word by word, so 'Golf Vita A' never collapses into 'Golf Vita'."""
    words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split() if w not in GENERIC_WORDS]
    n = len(comm_words)
    if n and words[:n] == list(comm_words) and len(words) > n:
        words = words[n:]
    elif n and words[-n:] == list(comm_words) and len(words) > n:
        words = words[:-n]
    return " ".join(re.sub(r"(.)\1+", r"\1", w) for w in words)


def strip_community(nm, comm):
    """Take the community's own name off a normalised name, front or back ('damachillscarson' -> 'carson')."""
    if comm and nm != comm:
        if nm.startswith(comm):
            nm = nm[len(comm):]
        elif nm.endswith(comm):
            nm = nm[:-len(comm)]
    return nm


def location_register(district, comm):
    """{stripped norm name: [candidate]} from the district's beds_left DLD projects and VERIFIED anchors."""
    reg = {}
    bl = os.path.join(ROOT, "data", "dld", "beds_left", "beds_left_%s.json" % district)
    try:
        for r in json.load(open(bl, encoding="utf-8")).get("rows", []):
            nm = strip_community(norm_name(r.get("dld_project") or r.get("name")), comm)
            if nm and r.get("key"):
                c = {"name": r.get("dld_project") or r.get("name"), "key": r["key"], "num": r.get("dld_project_number"), "src": "beds_left"}
                if c not in reg.setdefault(nm, []):
                    reg[nm].append(c)
    except Exception:
        pass
    an = os.path.join(ROOT, "data", "names", "anchors_%s.json" % district)
    try:
        for a in json.load(open(an, encoding="utf-8")).get("anchors", []):
            if a.get("identity_grade") != "VERIFIED" or a.get("id") is None:
                continue
            nm = strip_community(norm_name(a.get("name")), comm)
            if nm:
                reg.setdefault(nm, []).append({"name": a.get("name"), "key": "%s:%s" % (district, a["id"]), "num": None, "src": "verified_anchor"})
    except Exception:
        pass
    return reg


def twin_clusters(district, comm):
    """{stripped norm cluster name: cluster} from the twin's building list (anchors_<district>.json 'cluster')."""
    an = os.path.join(ROOT, "data", "names", "anchors_%s.json" % district)
    try:
        return {strip_community(norm_name(a["cluster"]), comm): a["cluster"].strip()
                for a in json.load(open(an, encoding="utf-8")).get("anchors", []) if a.get("cluster")}
    except Exception:
        return {}


def match_location(name, reg, comm, comm_words=()):
    """-> (binding dict or None, review reason or None). Exact after the community name is stripped; else spelling."""
    nm = strip_community(norm_name(name), comm)
    method, cands = "pf_location_name", reg.get(nm) or []
    if not cands:
        sp = spelling(name, comm_words)
        cands = [c for v in reg.values() for c in v if sp and spelling(c["name"], comm_words) == sp]
        method = "pf_location_spelling"
    if not cands:
        near = sorted({c["name"] for k, v in reg.items() if k and nm and (k.startswith(nm) or nm.startswith(k)) and k != nm for c in v})
        return None, ("name differs from the register: %s" % "; ".join(near[:6])) if near else "no register name"
    bl = {c["key"]: c for c in cands if c["src"] == "beds_left"}
    an = {c["key"]: c for c in cands if c["src"] == "verified_anchor"}
    pick = bl if bl else an
    if len(pick) != 1:
        return None, "several register entries: %s" % "; ".join(sorted(c["name"] for c in pick.values()))
    c = next(iter(pick.values()))
    return {"key": c["key"], "dld_project": c["name"], "dld_project_number": c["num"], "register_source": c["src"], "method": method,
            "confidence": 0.9 if method == "pf_location_name" else 0.8}, None


def bind_locations(args):
    """Read a community's location tree from its own rent pages and bind clusters to the district register (see the header)."""
    t0 = time.time()
    comm_slug, district = args.community, args.district
    f = Fetcher(args.max_requests, offline=args.offline)
    nodes, ids, comm_total, comm_name = {}, {}, {}, None      # tail -> {name, parent, counts{kind: n}, depth}

    def links(html):
        meta, rows, _, props = parse_page(html, want_props=True)
        for p in rows:
            for t in (p.get("location_tree") or []) + [p.get("location") or {}]:
                if t.get("slug") and t.get("id") is not None:
                    ids.setdefault(tower_tail(t), str(t["id"]))
        out = []
        for a in ((props.get("pageMeta") or {}).get("aggregationLinks") or []):
            m = AGG_RX.search(a.get("link") or "")
            if m and a.get("name"):
                out.append((m.group(2), a["name"], int(a.get("count") or 0)))
        return meta, props, out

    for kind in LOC_KINDS:                                     # level 1: the community's subcommunities, per home type
        html = f.get(kind_url(comm_slug, kind))
        if html is None:
            continue
        meta, props, ls = links(html)
        comm_total[kind] = meta.get("total_count")
        comm_name = comm_name or (props.get("seoData") or {}).get("locationName")
        for tail, name, n in ls:
            if not tail.startswith(comm_slug + "-"):
                continue
            nd = nodes.setdefault(tail, {"name": name, "parent": None, "depth": 1, "counts": {}})
            nd["counts"][kind] = n
    for tail in [t for t in nodes if nodes[t]["depth"] == 1]:  # level 2: each subcommunity's own children, per home type
        for kind, n in list(nodes[tail]["counts"].items()):
            if f.stopped or not n:
                continue
            html = f.get(kind_url(tail, kind))
            if html is None:
                continue
            meta, props, ls = links(html)
            ids.setdefault(tail, str((props.get("seoData") or {}).get("locationId") or "") or None)
            for ctail, cname, cn in ls:
                if not ctail.startswith(tail + "-"):
                    continue
                nd = nodes.setdefault(ctail, {"name": cname, "parent": tail, "depth": 2, "counts": {}})
                nd["counts"][kind] = cn
    if f.stopped:
        log("bind-locations: STOPPED (%s) after %d requests - nothing bound; the pages fetched so far are cached" % (f.stopped, f.requests_made))
        write_summary({"action": "bind_locations", "community": comm_slug, "district": district, "stopped": f.stopped,
                       "requests_made": f.requests_made, "failures": f.failures}, None)
        return 3
    comm = norm_name(comm_name or comm_slug.replace("-", " "))
    cw = tuple(w for w in re.sub(r"[^a-z0-9 ]+", " ", (comm_name or comm_slug.replace("-", " ")).lower()).split() if w not in GENERIC_WORDS)
    reg, twin = location_register(district, comm), twin_clusters(district, comm)
    bindings, review = [], []
    for tail, nd in sorted(nodes.items()):
        b, why = match_location(nd["name"], reg, comm, cw)
        total = sum(nd["counts"].values())
        rec = {"building_slug": tail, "pf_name": nd["name"], "parent": nd["parent"], "depth": nd["depth"], "counts": nd["counts"],
               "adverts": total, "pf_location_id": ids.get(tail),
               "twin_cluster": twin.get(strip_community(norm_name(nd["name"]), comm))}
        if b:
            bindings.append(dict(rec, **b))
        else:
            review.append(dict(rec, why=why))
    # one register entry matched by two locations that are not parent and child is not clear: both go to review
    seen = {}
    for b in bindings:
        seen.setdefault(b["key"], []).append(b)
    for k, bs in seen.items():
        if len(bs) > 1 and any(x["parent"] != y["building_slug"] and y["parent"] != x["building_slug"] for x in bs for y in bs if x is not y):
            for b in bs:
                bindings.remove(b)
                review.append(dict({x: b[x] for x in ("building_slug", "pf_name", "parent", "depth", "counts", "adverts", "pf_location_id", "twin_cluster")},
                                   why="register entry %s matched by %d locations" % (b["dld_project"], len(bs))))
    # an unbound child of a bound location is not missing: its adverts are counted under the parent
    bound_tails = {b["building_slug"] for b in bindings}
    covered = [dict(r, covered_by=r["parent"]) for r in review if r["parent"] in bound_tails]
    review = [r for r in review if r["parent"] not in bound_tails]
    bound_keys = {b["key"] for b in bindings}
    reg_unbound = sorted({c["name"] for v in reg.values() for c in v if c["src"] == "beds_left" and c["key"] not in bound_keys})
    doc = {"as_of": dt.date.today().isoformat(), "community": comm_slug, "community_name": comm_name, "district": district,
           "measure": "Property Finder location -> DLD register binding for ADVERTISED SUPPLY research; not vacancy",
           "method": "names agree after the community name is stripped (or differ only by a doubled letter); one register entry per "
                     "location; level-1 subcommunities from the community's villas/townhouses/apartments rent pages, level-2 from each "
                     "subcommunity's own pages (pageMeta.aggregationLinks)",
           "community_adverts": {"total": sum(v for v in comm_total.values() if v), "by_kind": comm_total, "as_of": dt.date.today().isoformat(),
                                 "community_name": comm_name, "note": "villas + townhouses + apartments pages; hotel apartments etc. not included"},
           "requests_made": f.requests_made, "cache_hits": f.cache_hits, "locations_seen": len(nodes),
           "bound": len(bindings), "bound_adverts_on_index": sum(b["adverts"] for b in bindings if b["parent"] not in bound_tails),
           "review": sorted(review, key=lambda r: -r["adverts"]), "register_unbound": reg_unbound,
           "covered_by_bound_parent": sorted(covered, key=lambda r: -r["adverts"]),
           "bindings": sorted(bindings, key=lambda b: -b["adverts"])}
    for b in doc["bindings"]:
        log("bind %-52s %-26s -> %-34s %s (%d adverts)" % (b["building_slug"], b["pf_name"], b["dld_project"], b["method"], b["adverts"]))
    for r in doc["review"]:
        log("review %-50s %-26s %s (%d adverts)" % (r["building_slug"], r["pf_name"], r["why"], r["adverts"]))
    log("bind-locations %s -> %s: %d locations, %d bound, %d to review; register projects bound %d of %d; %d requests, %d cache hits"
        % (comm_slug, district, len(nodes), len(bindings), len(review), len(bound_keys & {c["key"] for v in reg.values() for c in v if c["src"] == "beds_left"}),
           len({c["key"] for v in reg.values() for c in v if c["src"] == "beds_left"}), f.requests_made, f.cache_hits))
    if args.dry:
        print(json.dumps({k: v for k, v in doc.items() if k not in ("bindings", "review", "covered_by_bound_parent")}, indent=1, default=str))
        return 0
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "pf_bindings_%s.json" % district), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    rows = [(PORTAL, b["building_slug"], b["pf_location_id"], b["pf_name"], comm_slug, b["dld_project"], b["dld_project_number"],
             b["key"], b["method"], b["confidence"]) for b in bindings]
    write_location_aliases(rows, comm_slug)
    write_summary({k: v for k, v in doc.items() if k not in ("bindings", "review", "register_unbound", "covered_by_bound_parent")} | {"action": "bind_locations"}, None)
    return 0


def write_location_aliases(rows, comm_slug):
    """Replace this community's pf_location* alias rows (file copy, then one short lake window). Manual rows are never touched."""
    keep = {r[1] for r in rows}
    cur = [r for r in alias_file_rows() if not ((r.get("method") or "").startswith("pf_location") and r.get("community") == comm_slug
                                                and r["building_slug"] not in keep)]
    with open(ALIAS_FILE, "w", encoding="utf-8") as fh:
        json.dump({"as_of": dt.date.today().isoformat(), "note": "lake-free copy of lst_building_alias (research only); the lake is the record",
                   "rows": sorted(cur, key=lambda d: d["building_slug"])}, fh, indent=0, ensure_ascii=False, default=str)
    save_alias_file(rows)
    con = lake_connect(read_only=False)
    try:
        ensure_schema(con)

        def body():
            con.execute("""delete from lst_building_alias where portal = ? and method like 'pf_location%' and community = ?""", [PORTAL, comm_slug])
            con.execute("delete from lst_building_alias where portal = ? and method <> 'manual' and building_slug in (select unnest(?::varchar[]))",
                        [PORTAL, sorted(keep)])
            have = {r[0] for r in con.execute("select building_slug from lst_building_alias where portal = ?", [PORTAL]).fetchall()}
            new = [r for r in rows if r[1] not in have]
            if new:
                con.executemany("insert into lst_building_alias values (?,?,?,?,?,?,?,?,?,?)", new)
        write_lake(con, body, "lst_building_alias (locations)")
    finally:
        con.close()
    log("lst_building_alias: %d location binding(s) written for %s" % (len(rows), comm_slug))


def report_district(args):
    """data/listings/pf_supply_<district>.json - the shape Rings will read later. Advertised supply only; research use."""
    con = lake_connect(read_only=True)
    kfrag, kparams = district_key_sql(args.district, 'a."key"')
    vfrag, vparams = district_key_sql(args.district, 'v."key"')
    as_of = args.date or con.execute('select max(run_date) from lst_listing_snapshot s join lst_building_alias a on a.portal = s.portal '
                                     'and a.building_slug = s.building_slug where s.portal = ? and ' + kfrag, [PORTAL] + kparams).fetchone()[0]
    if as_of is None:
        log("report --district %s: no snapshot for a bound building yet" % args.district)
        return 2
    rows = con.execute("""select v."key", v.dld_project, v.building_slug, v.beds_band, v.listings_live, v.median_price, v.median_days_since_listed,
                                 (select min(l.first_seen) from lst_listing l join lst_listing_snapshot s
                                     on s.portal = l.portal and s.listing_id = l.listing_id
                                   where s.run_date = v.run_date and s.building_slug = v.building_slug and s.beds_band = v.beds_band and s.portal = v.portal) first_seen_min
                          from v_lst_daily_building_counts v
                          where v.portal = ? and v.run_date = ? and """ + vfrag + """
                          order by v.building_slug, case v.beds_band when 'studio' then 0 when '1' then 1 when '2' then 2 when '3+' then 3 else 9 end""",
                       [PORTAL, as_of] + vparams).fetchall()
    out_rows = [{"key": r[0], "dld_project": r[1], "building_slug": r[2], "beds_band": r[3], "listings_live": r[4],
                 "median_price": round(r[5]) if r[5] is not None else None, "median_days_listed": int(r[6]) if r[6] is not None else None,
                 "first_seen_min": str(r[7]) if r[7] else None} for r in rows]
    # daily delisting: per building, adverts live on the previous run of that building and gone on this one
    try:
        con.execute("select 1 from v_lst_daily_delisting limit 0")
    except Exception:
        wcon = lake_connect(read_only=False)
        write_lake(wcon, lambda: wcon.execute(DELIST_VIEW), "v_lst_daily_delisting")
        wcon.close()
        con = lake_connect(read_only=True)
    dl = con.execute("""select d.building_slug, d.prev_date, d.delisted, d.new_listings, d.prev_live
                        from v_lst_daily_delisting d join lst_building_alias a on a.portal = d.portal and a.building_slug = d.building_slug
                        where d.portal = ? and d.run_date = ? and """ + kfrag, [PORTAL, as_of] + kparams).fetchall()
    # home type (Villa / Townhouse / Apartment ...) per bound location, and the bound locations themselves (for coverage)
    ht = con.execute("""select s.building_slug, coalesce(s.property_type, 'unknown'), count(*)
                        from lst_listing_snapshot s join lst_building_alias a on a.portal = s.portal and a.building_slug = s.building_slug
                        where s.portal = ? and s.run_date = ? and """ + kfrag + " group by 1, 2", [PORTAL, as_of] + kparams).fetchall()
    bound = con.execute('select building_slug, "key", dld_project, method from lst_building_alias a where a.portal = ? and ' + kfrag,
                        [PORTAL] + kparams).fetchall()
    delisting = {"as_of": str(as_of), "buildings_with_previous_run": sum(1 for r in dl if r[1] is not None),
                 "prev_live": sum(r[4] for r in dl if r[1] is not None), "delisted": sum(r[2] for r in dl if r[1] is not None),
                 "new": sum(r[3] for r in dl), "daily_delisting_rate": None,
                 "per_building": {r[0]: {"prev_date": str(r[1]), "delisted": r[2], "new": r[3], "prev_live": r[4]} for r in dl if r[1] is not None},
                 "note": "delisted = advert gone since the building's previous run; an advert withdrawn is not a unit let"}
    if delisting["prev_live"]:
        delisting["daily_delisting_rate"] = round(delisting["delisted"] / float(delisting["prev_live"]), 4)
    doc = {"as_of": str(as_of), "district": args.district,
           "measure": "advertised supply (live Property Finder rental adverts), not vacancy; research use only",
           "buildings": len({r["building_slug"] for r in out_rows}), "listings_live": sum(r["listings_live"] for r in out_rows),
           "rows": out_rows, "delisting": delisting}
    con.close()
    # additive keys only: rows / buildings / listings_live / delisting above keep their shape for every district
    by_b = {}
    for slug, typ, n in ht:
        by_b.setdefault(slug, {})[typ] = by_b.setdefault(slug, {}).get(typ, 0) + n
    doc["home_types"] = home_type_totals(by_b)
    doc["home_types_by_building"] = {s: dict(sorted(v.items(), key=lambda kv: -kv[1])) for s, v in sorted(by_b.items())}
    doc["coverage"] = coverage_block(args.district, [{"building_slug": b[0], "key": b[1], "dld_project": b[2], "method": b[3]} for b in bound],
                                     out_rows, doc["listings_live"])
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "pf_supply_%s.json" % args.district)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    log("report --district %s: %d rows over %d buildings, %d live adverts as of %s; delisted %s of %s since previous run -> %s"
        % (args.district, len(out_rows), doc["buildings"], doc["listings_live"], as_of, delisting["delisted"], delisting["prev_live"], path))
    log("report --district %s: %s; home types %s" % (args.district, doc["coverage"]["say"], doc["home_types"]))
    write_summary({"action": "report_district", "district": args.district, "as_of": str(as_of), "rows": len(out_rows), "buildings": doc["buildings"],
                   "listings_live": doc["listings_live"], "delisting": {k: v for k, v in delisting.items() if k != "per_building"}}, None)
    return 0


def report(args):
    if args.district:
        return report_district(args)
    con = lake_connect(read_only=True)
    where, params = ["portal = ?"], [PORTAL]
    if args.building:
        where.append("building_slug like ?")
        params.append("%" + args.building + "%")
    if args.date:
        where.append("run_date = ?")
        params.append(args.date)
    else:
        where.append("run_date = (select max(run_date) from lst_listing_snapshot)")
    sql = """select run_date, building_slug, building_name, "key", dld_project, beds_band, listings_live, median_price,
                    median_days_since_listed, median_days_tracked
             from v_lst_daily_building_counts where %s
             order by building_slug, case beds_band when 'studio' then 0 when '1' then 1 when '2' then 2 when '3+' then 3 else 9 end""" % " and ".join(where)
    rows = con.execute(sql, params).fetchall()
    print("ADVERTISED SUPPLY on Property Finder (live rental adverts per building and bedroom band) - not vacancy; research use only")
    print("%-10s %-55s %-28s %-24s %-6s %5s %12s %8s %8s" % ("run_date", "building_slug", "key", "dld_project", "beds", "live", "median_AED", "dom_med", "tracked"))
    for r in rows:
        print("%-10s %-55s %-28s %-24s %-6s %5d %12s %8s %8s" % (r[0], r[1][:55], (r[3] or "-")[:28], (r[4] or "-")[:24], r[5], r[6],
                                                                  ("%.0f" % r[7]) if r[7] is not None else "-", r[8] if r[8] is not None else "-", r[9] if r[9] is not None else "-"))
    tot = con.execute("select count(*), count(distinct building_slug), min(run_date), max(run_date) from lst_listing_snapshot where portal = ?", [PORTAL]).fetchone()
    al = con.execute('select count(*), count("key") from lst_building_alias where portal = ?', [PORTAL]).fetchone()
    print("snapshot rows %d over %d buildings, %s..%s; aliases %d (%d bound to a register key)" % (tot[0], tot[1], tot[2], tot[3], al[0], al[1]))
    con.close()
    return 0


# -------------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="action", required=True)
    m = sub.add_parser("communities", help="verify district -> Property Finder community slugs; writes data/listings/pf_communities.json")
    m.add_argument("--max-requests", type=int, default=150)
    m.add_argument("--offline", action="store_true")
    d = sub.add_parser("discover")
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--community", help="one Property Finder community slug")
    g.add_argument("--all-mapped", action="store_true", help="every community in pf_communities.json, pages rationed by --max-pages / --pages-for")
    d.add_argument("--kind", choices=["apartments", "villas"], default=None, help="URL family for --community (default apartments)")
    d.add_argument("--pages-for", help="per-community page caps for --all-mapped, e.g. jumeirah-village-circle=25,business-bay=25")
    d.add_argument("--max-requests", type=int, default=300)
    d.add_argument("--max-pages", type=int, default=1000)
    d.add_argument("--no-verify", dest="verify", action="store_false", help="skip the one-request check of an inferred building URL")
    d.add_argument("--dry", action="store_true")
    d.add_argument("--offline", action="store_true", help="serve only from cache; never touch the network")
    c = sub.add_parser("crawl")
    cg = c.add_mutually_exclusive_group(required=True)
    cg.add_argument("--buildings", help="comma list: full SEO tails or short slugs known to lst_building_alias")
    cg.add_argument("--bound-only", action="store_true", help="every alias row with a register key in --district")
    cg.add_argument("--all-bound", action="store_true", help="every alias row with a register key, all districts")
    c.add_argument("--district", help="our district slug, with --bound-only")
    c.add_argument("--max-requests", type=int, default=300)
    c.add_argument("--dry", action="store_true")
    c.add_argument("--offline", action="store_true")
    r = sub.add_parser("report")
    r.add_argument("--building")
    r.add_argument("--district", help="write data/listings/pf_supply_<district>.json for one of our district slugs")
    r.add_argument("--date")
    bl = sub.add_parser("bind-locations", help="bind a community's subcommunity locations (villa/townhouse clusters) to the district register")
    bl.add_argument("--community", required=True, help="Property Finder community slug, e.g. damac-hills")
    bl.add_argument("--district", required=True, help="our district slug, e.g. damachills")
    bl.add_argument("--max-requests", type=int, default=120)
    bl.add_argument("--dry", action="store_true", help="read and match, print, write nothing")
    bl.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    try:
        return {"communities": communities, "discover": discover, "crawl": crawl, "report": report,
                "bind-locations": bind_locations}[a.action](a)
    except LakeUnavailable as e:
        log("%s: %s - nothing written; re-run once daily_refresh.log shows '=== daily done'" % (a.action, e))
        return 4


if __name__ == "__main__":
    sys.exit(main())

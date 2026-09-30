"""v274 - the RENT index behind the HOMES panel's Rent mode (KV img_rent_index, served at /img/rent_index).

Why. A client asked Naj for "three options in JVC, one bedroom, AED 65K" - an annual rent. The HOMES filter only searched homes for
sale. The Ejari register already tells us what homes in each building actually rent for: this folds the latest daily pull into one
record per building (DLD PROJECT_EN) with the median and interquartile annual rent per bedroom band.

Input   data/rents-YYYY-MM-DD[-api].csv   the newest complete daily pull (scripts/fetch_dld.py; trailing ~28 days of registrations)
        data/dld/rent_bed_bands.json      size cut points per DLD area, learned from contracts that DO carry the bedroom type
                                          (scripts/calibrate_rent_bands.py) - ROOMS is blank on ~95% of daily rows
        data/identity/official/dld/tx_bindings.json, data/names/anchors_<slug>.json   DLD project/building name -> the app's building (d, i)
Output  data/board/rent_index.json
    {"generated", "as_of", "source_file", "window": [first, last registration], "contracts", "note", "bands",
     "items": [{"p": key, "n": name, "a": [other DLD names the same contracts are filed under], "area": AREA_EN, "d": slug|null,
                "i": anchor i|null, "is": [every bound anchor i], "lon", "lat", "bind": "tx"|"anchor"|null, "last": "YYYY-MM-DD",
                "b": {band: stats}   apartments (Flat / Studio),  "v": {band: stats}  villas and townhouses}],
     "areas": [{"area", "d", "b", "v"}]}           the whole DLD area, named or not (half the contracts carry no project name)
    band "0" studio, "1", "2", "3" = 3 or more bedrooms
    stats {"n": contracts, "nn": new, "nr": renewed, "m": median annual AED (all), "q1", "q3": interquartile (all),
           "mn", "q1n", "q3n": the same over NEW lettings only (absent when there are none), "s": median m2, "last": latest registration}
Rules   residential usage only; Flat / Studio -> apartment, Villa / Complex Villas -> villa; annual 5k-20M, size 10-2000 m2.
        The same contract is often filed under two to twelve project names on one plot (CANAL VIEWS = BLOOM HEIGHTS, PREMIERS TWIN
        TOWER = Binghatti Corner): contracts are de-duplicated by (area, registration timestamp, start, end, amount, size, version, type)
        and project names that share a contract are merged into one record, so nothing is counted twice.
        A name binds to a building only where the register (tx_bindings) or the anchor itself carries that name; a geocoded register
        bind is refused when the footprint's own name says otherwise (a name lookup must agree with the record).
Usage   python scripts/build_rent_index.py [--file data/rents-2026-09-30.csv] [--push]      (no push without --push)
"""
import collections, csv, datetime as dt, glob, json, os, re, statistics, sys, time, unicodedata
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from dld_rent_buildings import DLD_AREA   # noqa: E402  the shared map: DLD area name -> [twin slug, ...]
DATA = os.path.join(ROOT, "data"); NAMES = os.path.join(DATA, "names")
OUT = os.path.join(DATA, "board", "rent_index.json")
BANDS_P = os.path.join(DATA, "dld", "rent_bed_bands.json")
TXB_P = os.path.join(DATA, "identity", "official", "dld", "tx_bindings.json")
KV_NAME = "rent_index"
MIN_ROWS = 20000          # a daily pull below this is a failed or partial download, never the index
APT = {"Flat", "Studio"}; VILLA = {"Villa", "Complex Villas"}


# the unit-mix card's own name key (build_unit_mix.py), so a rent record and a card agree on what "the same name" means
def fold(s): return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
def norm(s): return re.sub(r"[^a-z0-9]", "", fold(s).lower())
def stem(s): return re.sub(r"\b(by|the|tower|towers|residences?|residence|building|bldg|apartments?)\b", "", fold(s).lower())
def nkey(s): return norm(stem(s))


def pick_file(explicit=None):
    """The newest rents file that is finished: newest date first; for one date the variant with more rows (the -api re-pull
    carries the same day plus the morning's registrations); never a file still being written (touched in the last minute)."""
    if explicit: return explicit
    cands = []
    for f in glob.glob(os.path.join(DATA, "rents-*.csv")):
        m = re.match(r"rents-(\d{4}-\d{2}-\d{2})(-api)?\.csv$", os.path.basename(f))
        if not m or time.time() - os.path.getmtime(f) < 60: continue
        cands.append((m.group(1), f))
    for day in sorted({d for d, _ in cands}, reverse=True):
        best = None
        for d, f in cands:
            if d != day: continue
            with open(f, encoding="utf-8-sig") as fh: n = sum(1 for _ in fh) - 1
            if n >= MIN_ROWS and (best is None or n > best[0]): best = (n, f)
        if best: return best[1]
    sys.exit("no complete rents-*.csv under data/")


def fnum(x):
    try: return float(x)
    except Exception: return None


def load_bands():
    b = json.load(open(BANDS_P, encoding="utf-8"))
    return b, b["flat"]["city"]["cuts"], {a: v["cuts"] for a, v in b["flat"]["areas"].items()}, b["villa"]["city"]["cut"]


def bed_band(kind, rooms, sqm, area, city_cuts, area_cuts, villa_cut):
    r = str(rooms or "").strip()
    if r.isdigit(): return str(min(int(r), 3))                # ROOMS when the register filled it (mostly villas)
    if kind == "villa": return "3" if sqm >= villa_cut else "2"
    cuts = area_cuts.get(area) or city_cuts
    for j, c in enumerate(cuts):
        if sqm < c: return str(j)
    return "3"


def q(vals, p):
    v = sorted(vals); k = (len(v) - 1) * p; lo = int(k); hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def stats(rows):
    amt = [r["amt"] for r in rows]; new = [r["amt"] for r in rows if r["new"]]
    out = {"n": len(rows), "nn": len(new), "nr": len(rows) - len(new), "m": round(statistics.median(amt)), "q1": round(q(amt, .25)), "q3": round(q(amt, .75)),
           "s": round(statistics.median(r["sqm"] for r in rows), 1), "last": max(r["reg"] for r in rows)}
    if new: out.update({"mn": round(statistics.median(new)), "q1n": round(q(new, .25)), "q3n": round(q(new, .75))})
    return out


def band_stats(rows):
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows: by["v" if r["kind"] == "villa" else "b"][r["band"]].append(r)
    return {k: {bd: stats(rs) for bd, rs in sorted(v.items())} for k, v in by.items()}


def building_lookup():
    """(slug, nkey(name)) -> [(i, source)] from the register bindings and the anchors' own names."""
    txb = json.load(open(TXB_P, encoding="utf-8")) if os.path.exists(TXB_P) else {}
    anchors, look = {}, collections.defaultdict(list)
    for slug in sorted({s for v in DLD_AREA.values() for s in v}):
        ap = os.path.join(NAMES, f"anchors_{slug}.json")
        A = {int(a["i"]): a for a in (json.load(open(ap, encoding="utf-8")).get("anchors", []) if os.path.exists(ap) else [])}
        anchors[slug] = A
        for i, a in A.items():
            for nm in (a.get("name"), a.get("dev_project")):
                if nm and a.get("display_role") != "ADDRESS" and nkey(nm): look[(slug, nkey(nm))].append((i, "anchor"))
        for si, b in (txb.get(slug) or {}).items():
            i = int(si); a = A.get(i) or {}
            own = nkey(a.get("name")) if a.get("name") and a.get("display_role") != "ADDRESS" else None
            names = [b.get("project"), b.get("building")] + [x.get(k) for x in (b.get("also") or []) for k in ("project", "building")]
            for nm in names:
                k = nkey(nm)
                if not k: continue
                if b.get("method") == "geocoded" and own and own != k: continue    # the footprint is named otherwise: never borrow its page
                look[(slug, k)].append((i, "tx"))
    return look, anchors


def main():
    path = pick_file(sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else None)
    day = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path)).group(1)
    bands_meta, city_cuts, area_cuts, villa_cut = load_bands()
    look, anchors = building_lookup()
    t0 = time.time(); seen = set(); rows = []; skipped = collections.Counter()
    floor = (dt.date.fromisoformat(day) - dt.timedelta(days=60)).isoformat()      # a stray months-old registration is not "what it rents for now"
    for x in csv.DictReader(open(path, encoding="utf-8-sig")):
        if (x.get("USAGE_EN") or "").strip() != "Residential": skipped["not residential"] += 1; continue
        st = (x.get("PROP_SUB_TYPE_EN") or "").strip()
        kind = "apt" if st in APT else ("villa" if st in VILLA else None)
        if not kind: skipped["not a flat or villa"] += 1; continue
        amt, sqm = fnum(x.get("ANNUAL_AMOUNT")), fnum(x.get("ACTUAL_AREA"))
        if not amt or not sqm or not (5000 <= amt <= 20_000_000) or not (10 <= sqm <= 2000): skipped["amount or size out of range"] += 1; continue
        reg = (x.get("REGISTRATION_DATE") or "")[:10]
        if reg < floor: skipped["registered over 60 days before the pull"] += 1; continue
        area = (x.get("AREA_EN") or "").strip(); proj = (x.get("PROJECT_EN") or "").strip()
        sig = (area, x.get("REGISTRATION_DATE"), x.get("START_DATE"), x.get("END_DATE"), x.get("ANNUAL_AMOUNT"), x.get("ACTUAL_AREA"), x.get("VERSION_EN"), st)
        if (sig, proj) in seen: skipped["exact duplicate row"] += 1; continue
        seen.add((sig, proj))
        rows.append({"sig": sig, "area": area, "proj": proj, "kind": kind, "amt": amt, "sqm": sqm, "reg": reg, "new": (x.get("VERSION_EN") or "").strip() == "New",
                     "band": bed_band(kind, x.get("ROOMS"), sqm, area, city_cuts, area_cuts, villa_cut)})
    # one contract, many project names: union the names that share a contract (per area), then count each contract once
    parent = {}
    def find(a):
        while parent.setdefault(a, a) != a: parent[a] = parent[parent[a]]; a = parent[a]
        return a
    by_sig = collections.defaultdict(set)
    for r in rows:
        if r["proj"]: by_sig[r["sig"]].add((r["area"], r["proj"]))
    for names in by_sig.values():
        names = sorted(names)
        for nm in names[1:]: parent[find(nm)] = find(names[0])
    groups = collections.defaultdict(dict)                # root -> {sig: row}
    members = collections.defaultdict(set)
    for r in rows:
        if not r["proj"]: continue
        root = find((r["area"], r["proj"])); groups[root].setdefault(r["sig"], r); members[root].add(r["proj"])
    area_rows = collections.defaultdict(dict)
    for r in rows: area_rows[r["area"]].setdefault(r["sig"], r)
    items = []; bound = 0
    for root, sigs in groups.items():
        area = root[0]; slugs = DLD_AREA.get(area) or []
        names = sorted(members[root], key=lambda s: (-sum(1 for r in sigs.values() if r["proj"] == s), s))
        hits = []                                          # (name, slug, i, source)
        for nm in names:
            for slug in slugs:
                for i, src in look.get((slug, nkey(nm)), []): hits.append((nm, slug, i, src))
        # the record is named after the name that binds (anchor agreement first), else the name with most contracts
        hits.sort(key=lambda h: (h[3] != "anchor", names.index(h[0])))
        primary = hits[0][0] if hits else names[0]
        d = hits[0][1] if hits else (slugs[0] if slugs else None)
        iss = []
        for h in hits:
            if h[1] == d and h[2] not in iss: iss.append(h[2])
        it = {"p": nkey(primary) or norm(primary), "n": primary, "area": area, "d": d}
        others = [nm for nm in names if nm != primary]
        if others: it["a"] = others
        if iss:
            a = anchors[d].get(iss[0]) or {}
            it.update({"i": iss[0], "bind": hits[0][3]})
            if len(iss) > 1: it["is"] = iss
            if a.get("lon") is not None: it["lon"], it["lat"] = round(a["lon"], 6), round(a["lat"], 6)
            bound += 1
        rs = list(sigs.values()); it["last"] = max(r["reg"] for r in rs); it.update(band_stats(rs))
        items.append(it)
    items.sort(key=lambda it: (it["d"] or "~", it["area"], it["n"].lower()))
    areas = [dict({"area": a, "d": (DLD_AREA.get(a) or [None])[0]}, **band_stats(list(s.values()))) for a, s in sorted(area_rows.items())]
    regs = [r["reg"] for r in rows]
    out = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "as_of": day, "source_file": os.path.basename(path),
           "window": [min(regs), max(regs)], "contracts": len({r["sig"] for r in rows}),
           "note": "DLD Ejari rent contracts registered in the window: what homes in each building actually rented for, new lettings and renewals. "
                   "NOT live availability. Bedrooms are inferred from the contract's size (bands learned per DLD area from contracts that carry the type); "
                   "villas use ROOMS where the register fills it. The same contract filed under several project names is counted once.",
           "bands": {"flat_city_cuts": city_cuts, "villa_cut": villa_cut, "flat_accuracy_city": bands_meta["flat"]["city"]["accuracy"],
                     "flat_accuracy_area": bands_meta["flat"].get("accuracy_with_area_cuts"), "source": "data/dld/rent_bed_bands.json"},
           "skipped": dict(skipped), "items": items, "areas": areas}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(OUT) // 1024
    merged = sum(1 for it in items if it.get("a"))
    print(f"{os.path.basename(path)}: {len(rows):,} residential contracts ({out['contracts']:,} distinct) {out['window'][0]}..{out['window'][1]} | "
          f"buildings {len(items):,} (bound to an app building {bound:,}; {merged} carry 2+ DLD names) | areas {len(areas)} | {kb} KB | {time.time()-t0:.1f}s")
    print("skipped:", dict(skipped))
    if "--push" in sys.argv:
        from build_avail_index import env_token, push
        print("push", KV_NAME, push(KV_NAME, out, env_token("INGEST_TOKEN")))
    else:
        print(f"not pushed (run with --push to POST /ingest_market as img_{KV_NAME})")


if __name__ == "__main__":
    main()

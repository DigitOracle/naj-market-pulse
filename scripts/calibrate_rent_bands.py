"""v274 - bedroom bands for the RENT mode, measured, not guessed.

Why. The daily Ejari pull (data/rents-YYYY-MM-DD.csv, scripts/fetch_dld.py) leaves ROOMS blank on ~95% of rows, so the bedroom count
of a rented flat has to be inferred from its size. The full rent_contracts export (data/raw_downloads/rent_contracts_*.json, about
6.3 million contracts) DOES carry the bedroom type (ejari_property_sub_type_en = Studio / 1bed room+Hall / 2 bed rooms+hall ...), so
we learn the size cut points from it: for every DLD area, the m2 cut between studio|1, 1|2 and 2|3+ that misclassifies the fewest
contracts since 2025-01-01. An area with fewer than 150 contracts on either side of a cut takes the citywide cut.

Output data/dld/rent_bed_bands.json
    {"generated", "source", "window", "method",
     "flat": {"city": {"cuts": [c1, c2, c3], "accuracy": a, "n": n, "quantiles": {...}}, "areas": {AREA_EN: {"cuts", "n", "accuracy", "accuracy_city_cuts"}}},
     "villa": {"city": {"cut": c, "accuracy": a, "n": n}}}          (villa: under c m2 = 2 bed or fewer, else 3+)
Read as: size < c1 -> studio, < c2 -> 1 bed, < c3 -> 2 bed, else 3+.
Usage: python scripts/calibrate_rent_bands.py          (about 2 minutes, reads ~10 GB of JSON, writes a few KB)
"""
import collections, datetime as dt, glob, json, os, sys, time
import duckdb
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dld", "rent_bed_bands.json")
SINCE = "2025-01-01"
FLAT_IDX = {"Studio": 0, "1bed room+Hall": 1, "2 bed rooms+hall": 2, "3 bed rooms+hall": 3, "4 bed rooms+hall": 3, "5 bed rooms+hall": 3}
VILLA_IDX = {"1bed room+Hall": 0, "2 bed rooms+hall": 0, "3 bed rooms+hall": 1, "4 bed rooms+hall": 1, "5 bed rooms+hall": 1, "6 bed rooms+hall": 1, "7 bed rooms+hall": 1}
MIN_SIDE = 150


def best_cut(a, b):
    best = None
    for c in range(20, 600, 2):
        e = sum(n for x, n in a.items() if x >= c) + sum(n for x, n in b.items() if x < c)
        if best is None or e < best[1]: best = (c, e)
    return best[0]


def band_of(x, cuts):
    for j, c in enumerate(cuts):
        if x < c: return j
    return len(cuts)


def accuracy(classes, cuts):
    ok = tot = 0
    for i, d in enumerate(classes):
        for x, n in d.items():
            tot += n; ok += n * (band_of(x, cuts) == i)
    return (ok / tot) if tot else None, tot


def quant(d, p):
    tot = sum(d.values()); c = 0
    for b in sorted(d):
        c += d[b]
        if c >= p * tot: return b


def main():
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "data", "raw_downloads", "rent_contracts_*.json")) if "(1)" not in f)
    if not files: sys.exit("no rent_contracts export under data/raw_downloads")
    con = duckdb.connect(); con.execute("SET memory_limit='6GB'"); t0 = time.time()
    H = collections.defaultdict(dict)          # (area, prop_type, sub_type) -> {2 m2 bin: contracts}
    for f in files:
        q = f"""select area_name_en, trim(ejari_property_type_en), ejari_property_sub_type_en, cast(floor(actual_area/2)*2 as int), count(*)
                from read_json_auto('{f.replace(chr(92), '/')}', maximum_object_size=200000000, sample_size=20000)
                where cast(contract_start_date as varchar) >= '{SINCE}' and property_usage_en='Residential' and actual_area between 10 and 1500
                group by 1,2,3,4"""
        for area, pt, st, b, n in con.execute(q).fetchall():
            d = H[(area, pt, st)]; d[b] = d.get(b, 0) + n
        print(f"  {os.path.basename(f)}  {time.time()-t0:.0f}s", flush=True)
    flat_area = collections.defaultdict(lambda: [dict(), dict(), dict(), dict()]); flat_city = [dict(), dict(), dict(), dict()]
    villa_city = [dict(), dict()]
    for (area, pt, st), d in H.items():
        if pt in ("Flat", "Studio") and st in FLAT_IDX:
            for tgt in (flat_area[area][FLAT_IDX[st]], flat_city[FLAT_IDX[st]]):
                for b, n in d.items(): tgt[b] = tgt.get(b, 0) + n
        if pt in ("Villa", "Complex Villas") and st in VILLA_IDX:
            tgt = villa_city[VILLA_IDX[st]]
            for b, n in d.items(): tgt[b] = tgt.get(b, 0) + n
    city_cuts = [best_cut(flat_city[j], flat_city[j + 1]) for j in range(3)]
    city_acc, city_n = accuracy(flat_city, city_cuts)
    areas = {}
    for area, cls in flat_area.items():
        if not area: continue
        cuts = []
        for j in range(3):
            a, b = cls[j], cls[j + 1]
            cuts.append(best_cut(a, b) if sum(a.values()) >= MIN_SIDE and sum(b.values()) >= MIN_SIDE else city_cuts[j])
        for j in (1, 2): cuts[j] = max(cuts[j], cuts[j - 1] + 10)    # bands never cross or collapse
        acc, n = accuracy(cls, cuts); acc_c, _ = accuracy(cls, city_cuts)
        if n: areas[area] = {"cuts": cuts, "n": n, "by_band": [sum(d.values()) for d in cls], "accuracy": round(acc, 3), "accuracy_city_cuts": round(acc_c, 3)}
    vcut = best_cut(villa_city[0], villa_city[1]); vacc, vn = accuracy(villa_city, [vcut])
    ok_area = sum(areas[a]["accuracy"] * areas[a]["n"] for a in areas) / max(1, sum(areas[a]["n"] for a in areas))
    out = {"generated": dt.datetime.now().isoformat(timespec="seconds"),
           "source": f"DLD Ejari rent_contracts export ({len(files)} files, data/raw_downloads), residential contracts starting on or after {SINCE}, actual_area 10-1500 m2",
           "window": SINCE,
           "method": "For each adjacent pair of true bedroom types, the m2 cut that misclassifies the fewest contracts (2 m2 bins). Per DLD area when both sides hold >= 150 contracts, else the citywide cut. size < c1 studio, < c2 1 bed, < c3 2 bed, else 3+.",
           "flat": {"city": {"cuts": city_cuts, "accuracy": round(city_acc, 3), "n": city_n, "by_band": [sum(d.values()) for d in flat_city],
                             "quantiles": {lab: {str(p): quant(d, p) for p in (0.1, 0.25, 0.5, 0.75, 0.9)} for lab, d in zip(("studio", "1", "2", "3+"), flat_city)}},
                    "areas": dict(sorted(areas.items())), "accuracy_with_area_cuts": round(ok_area, 3)},
           "villa": {"city": {"cut": vcut, "accuracy": round(vacc, 3), "n": vn, "note": "villas: ROOMS is usually filled in the daily pull; this cut (2 bed or fewer vs 3+) is used only when it is blank"}}}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"flat city cuts {city_cuts} accuracy {city_acc:.3f} over {city_n:,} | per-area {ok_area:.3f} over {len(areas)} areas | villa cut {vcut} accuracy {vacc:.3f} | -> {OUT}")


if __name__ == "__main__":
    main()

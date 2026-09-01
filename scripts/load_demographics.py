"""Merge community demographics into pulse.json areaIntel (pop / households / densityKm2).

Sources (either works, first found wins):
  data/demographics.csv        — manual: columns community,population,households[,area_km2]
                                 (Dubai Statistics Center publishes these tables per community)
  Data.Dubai API               — once the API key arrives (ticket 876229117), point --url at
                                 the population-by-community endpoint and pass --token.

Run AFTER build_pulse.py, BEFORE ingest (daily_refresh can call it; missing source = no-op).
Join is by normalized community name against areaIntel area names — unmatched rows are
reported, never guessed.
"""
import csv, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "public")
SRC = os.path.join(HERE, "..", "data", "demographics.csv")

nz = lambda s: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s or "").lower())).strip()


def main():
    if not os.path.exists(SRC):
        print("load_demographics: no data/demographics.csv — skipping (no-op)")
        return
    pulse_path = os.path.join(PUB, "pulse.json")
    pulse = json.load(open(pulse_path, encoding="utf-8"))
    areas = pulse.get("areaIntel", {}).get("areas", [])
    idx = {nz(a["area"]): a for a in areas}
    rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
    hit, miss = 0, []
    for r in rows:
        k = nz(r.get("community"))
        a = idx.get(k)
        if not a:
            miss.append(r.get("community"))
            continue
        pop = r.get("population")
        hh = r.get("households")
        km2 = r.get("area_km2")
        if pop and str(pop).replace(",", "").isdigit():
            a["pop"] = int(str(pop).replace(",", ""))
        if hh and str(hh).replace(",", "").isdigit():
            a["households"] = int(str(hh).replace(",", ""))
        if km2:
            try:
                a["densityKm2"] = round(a.get("pop", 0) / float(km2)) if a.get("pop") else None
            except (ValueError, ZeroDivisionError):
                pass
        hit += 1
    json.dump(pulse, open(pulse_path, "w"), separators=(",", ":"))
    print(f"load_demographics: merged {hit}/{len(rows)} rows into areaIntel; unmatched: {miss[:10]}")


if __name__ == "__main__":
    main()

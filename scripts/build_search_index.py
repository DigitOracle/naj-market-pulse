"""One search index for the app's FIND room: developers, developments (register project names) and buildings, each with where it lives.

Sources, in order of authority: the register-backed unit-mix project index (build_unit_mix.py: name, district, footprint i, status, units,
developer), the register bindings (bind_register_buildings.py: name, master project, units), the anchors (names on the twin), the
transactions bindings (register names + master project), the eleven developers (developer_dna.json + DEVNAME on the worker) and the
register projects that are NOT yet on the twin (rent / units register names without a footprint) so a search still answers.
Output data/board/search_index.json  {"generated", "n", "items": [{n, t (developer|development|building), d (district), i, dev, units, st, m (master), a (area label), sheet (the client-sheet slug, where one could exist)}]}
Pushed to KV as search_index -> the worker serves /img/search_index and the FIND page filters it client-side.
Usage: python scripts/build_search_index.py [--dry]
"""
import json, os, re, sys, time, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
from bind_dld_buildings import AREA_LABEL  # noqa: E402
BOARD = os.path.join(ROOT, "data", "board"); NAMES = os.path.join(ROOT, "data", "names"); DLD = os.path.join(ROOT, "data", "dld"); IDENT = os.path.join(ROOT, "data", "identity", "official", "dld")
DEVS = {"omniyat": "OMNIYAT", "hh": "H&H", "meraas": "Meraas", "select": "Select Group", "ellington": "Ellington", "arada": "Arada", "zaya": "ZAYA", "palma": "Palma", "fakhruddin": "Fakhruddin", "beyond": "BEYOND", "imtiaz": "Imtiaz", "binghatti": "Binghatti", "sobha": "Sobha Realty", "damac": "DAMAC", "emaar": "Emaar", "azizi": "Azizi", "danube": "Danube", "samana": "Samana", "nakheel": "Nakheel", "deyaar": "Deyaar", "mag": "MAG"}


def nk(s): return re.sub(r"[^a-z0-9]", "", str(s or "").lower())
def title(s):
    s = str(s or "").strip()
    return " ".join(w if (w.isupper() and len(w) <= 4) or re.fullmatch(r"[IVX]+", w) else w[:1].upper() + w[1:].lower() for w in s.split()) if s.isupper() else s


def load(p, default):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return default


# --- the client sheet's address on each row (16 Sep 2026) ----------------------------------------
# The FIND row carries the action that sends a client a fact sheet, so the row has to know where that
# sheet lives. It must NOT derive the slug from the display name: the slug comes from the LAND
# DEPARTMENT project name, and where the two differ the derivation is silently wrong - the Find row
# says "Peninsula Four, The Plaza" while the sheet is at peninsula_four, so a client-ready building
# would show as having none.
#
# Only the slug goes in. No hold reason, no page count, no has-a-sheet flag: the index is cached in
# ten-minute buckets and all three of those change the moment the pipeline pushes, so they would go
# stale and promise her a sheet that is not there. State is fetched on tap from /sheet/<slug>/meta;
# this is identity, which does not move.
#
# A row with no `sheet` key has no Land Department project behind it, so a sheet can never be built
# for it - the app can grey the action without a round trip.
FILLER = ("at", "by", "the", "in", "on", "of", "and", "a")


def strip_filler(s):
    """Drop joining words that carry no identity. Used only as a FALLBACK, after the exact and
    before-comma lookups, so it can never turn a correct exact match into something else."""
    return " ".join(w for w in re.split(r"[^A-Za-z0-9]+", str(s or "")) if w and w.lower() not in FILLER)


def resolve_sheet(sheets, name):
    """The marketing name is often longer than the registered one - the Find row says "Peninsula
    Four, The Plaza" where the register says "Peninsula Four". Exact first, then the part before a
    comma, then the longest registered name that this row's name starts with. The length floor stops
    a short key swallowing unrelated buildings, and "longest wins" stops Peninsula Four capturing
    Peninsula Five."""
    k = nk(name)
    if k in sheets:
        return sheets[k]
    head = nk(str(name).split(",")[0])
    if head and head in sheets:
        return sheets[head]
    # Filler words only. "Palace Residences AT Dubai Hills Estate" lost its own sheet - which was
    # registered, exactly, as palace_residences_dubai_hills_estate - over the single word "at", and
    # fell through to the prefix rule, which handed a Dubai Hills buyer Creek Harbour prices. Try
    # the name again without the joining words before resorting to a prefix.
    for cand in (nk(strip_filler(name)), nk(strip_filler(str(name).split(",")[0]))):
        if cand and cand in sheets:
            return sheets[cand]
    best, ambiguous = None, False
    for kk, sl in sheets.items():
        if len(kk) >= 9 and k.startswith(kk) and (best is None or len(kk) > len(best[0])):
            best = (kk, sl)
    if best:
        # A prefix that fronts SEVERAL different sheets names a family, not a building: "Palace
        # Residences" is registered in its own right and points at Creek Harbour, so every
        # "Palace Residences <somewhere>" that missed above landed on the wrong community's prices.
        # Where the prefix cannot tell them apart, refuse - no sheet beats the wrong sheet.
        kin = {sl for kk, sl in sheets.items() if kk.startswith(best[0])}
        ambiguous = len(kin) > 1
    return None if (best is None or ambiguous) else best[1]


# Jumeirah Lake Towers arrives under three tile names for one place. Treating them as different
# districts would make every JLT project look like a cross-district collision.
ONE_PLACE = {"althanyahfifth": "jlt", "jltnorth": "jlt", "jltsouth": "jlt"}


def sheet_slugs():
    """nk(project or building name) -> the slug build_client_sheet.py writes.

    A project NAME is not unique. "AG TOWER" names a tower in Jumeirah Lake Towers and a different
    one in Business Bay; so do Botanica, Capital One, Imperial Residence and Indigo Tower. Both
    resolved to the same slug, so a sheet built for one would have been served under the other's
    address - and whichever was pushed second would silently replace the first. Where a project name
    is used in more than one place the slug carries the place, and a NAME that would lead to two
    different buildings leads to neither.
    """
    rows, places = [], {}
    for f in sorted(os.listdir(DLD)):
        if not (f.startswith("tx_buildings_") and f.endswith(".json")):
            continue
        d = f[len("tx_buildings_"):-len(".json")]
        for b in load(os.path.join(DLD, f), {}).get("buildings", []):
            proj = b.get("project")
            if not proj:
                continue
            base = re.sub(r"[^a-z0-9]+", "_", proj.lower()).strip("_")[:50]
            where = ONE_PLACE.get(d, d)
            places.setdefault(base, set()).add(where)
            rows.append((base, where, proj, b.get("building")))

    out, seen = {}, {}
    for base, where, proj, bld in rows:
        slug = base if len(places[base]) == 1 else ("%s_%s" % (base, where))[:50]
        for nm in (proj, bld):
            k = nk(nm)
            if not k:
                continue
            if k in seen and seen[k] != slug:
                out[k] = None            # two different buildings answer to this name: neither wins
                continue
            # A tower ("Bellevue Towers-1") resolves to its development's sheet; the longest project
            # name wins a collision so "Peninsula Four" does not capture "Peninsula Five".
            if k not in out or (out[k] is not None and len(slug) > len(out[k])):
                out[k] = slug
                seen[k] = slug
    return {k: v for k, v in out.items() if v}


def main():
    dry = "--dry" in sys.argv
    items = {}
    def add(name, t, **kw):
        if not name or len(str(name)) < 3: return
        key = (t, nk(name), kw.get("d"))
        cur = items.get(key)
        rec = {"n": title(name), "t": t}; rec.update({k: v for k, v in kw.items() if v not in (None, "", [], {})})
        if cur is None or len(json.dumps(rec)) > len(json.dumps(cur)): items[key] = {**(cur or {}), **rec}
    # developers: the eleven on the board, plus any developer the register index names
    dna = load(os.path.join(ROOT, "data", "dev_meta", "developer_dna.json"), {})
    # 15 Sep 2026 (digital thread Q9): iterate the DNA's developers, not the file's top level - that loop published four junk
    # "developers" named developers, segments, source_note and updated. Keys map to the board's dev_key.
    by_name = {v.lower(): k for k, v in DEVS.items()}
    for name, v in ((dna.get("developers") or {}).items() if isinstance(dna, dict) else []):
        key = by_name.get(str(name).lower()) or next((k for k in DEVS if k == nk(name)), None) or nk(name)
        add(name, "developer", dev=key, seg=(v.get("segment") if isinstance(v, dict) else None))
    for k, v in DEVS.items(): add(v, "developer", dev=k)
    # the developer pages (board_devs.json): every property card on HOMES, keyed to its developer and its card anchor (p = normalised name)
    bd = load(os.path.join(BOARD, "board_devs.json"), {})
    prop_dev = {}; prop_area = {}
    for dv in (bd.get("developers") or []):
        add(dv.get("name") or dv.get("key"), "developer", dev=dv.get("key"), seg=dv.get("segment_label") or dv.get("segment"), np=len(dv.get("properties") or []))
        for pr in (dv.get("properties") or []):
            nm = pr.get("name")
            if not nm: continue
            prop_dev[nk(nm)] = dv.get("key"); prop_area[nk(nm)] = nk(pr.get("area") or "")
            add(nm, "development", dev=dv.get("key"), p=nk(nm), a=pr.get("area"), units=pr.get("units"), kind=pr.get("kind"))
    # developments and buildings from the register-backed unit-mix index
    up = load(os.path.join(BOARD, "unitmix_projects.json"), {})
    P = up.get("projects", up) if isinstance(up, dict) else {}
    for k, r in P.items():
        if not isinstance(r, dict): continue
        add(r.get("name") or k, "building" if r.get("dld") else "development", d=r.get("district"), i=r.get("i"), dev=r.get("developer"), units=r.get("total_units"), st=r.get("status"), m=r.get("master_project"), a=AREA_LABEL.get(r.get("district")))
    # register bindings: every named register building on a footprint, with its master project
    rb = load(os.path.join(IDENT, "reg_bindings.json"), {})
    for slug, d in rb.items():
        if slug.startswith("_") or not isinstance(d, dict): continue
        for i, v in d.items():
            add(v.get("name"), "building", d=slug, i=int(i), units=v.get("units"), m=v.get("master"), a=AREA_LABEL.get(slug))
            for x in v.get("also") or []: add(x.get("name"), "building", d=slug, i=int(i), units=x.get("units"), m=x.get("master"), a=AREA_LABEL.get(slug))
    # anchors: names on the twin (survey names, developer projects)
    for f in os.listdir(NAMES):
        if not (f.startswith("anchors_") and f.endswith(".json")): continue
        slug = f[8:-5]
        for a in load(os.path.join(NAMES, f), {}).get("anchors", []):
            if a.get("name"): add(a["name"], "building", d=slug, i=a.get("i"), dev=a.get("dev"), a=AREA_LABEL.get(slug))
            if a.get("dev_project"): add(a["dev_project"], "development", d=slug, i=a.get("i"), dev=a.get("dev"), a=AREA_LABEL.get(slug))
    # register names not yet on the twin: still searchable, flagged
    for f in os.listdir(DLD):
        if f.startswith("units_buildings_") and f.endswith(".json"):
            slug = f[16:-5]
            for b in load(os.path.join(DLD, f), {}).get("buildings", []):
                if b.get("name") and b.get("units", 0) >= 3 and ("building", nk(b["name"]), slug) not in items:
                    add(b["name"], "building", d=slug, units=b.get("units"), m=b.get("master"), a=AREA_LABEL.get(slug), off=1)
    # verified sub-communities: what a buyer actually asks for in a villa district ("Sidra", "Golf Promenade")
    for f in os.listdir(NAMES):
        if not (f.startswith("clusters_") and f.endswith(".json")): continue
        slug = f[9:-5]
        cd = load(os.path.join(NAMES, f), {}) or {}
        for c in cd.get("clusters", []):
            add(c.get("name"), "development", d=slug, a=AREA_LABEL.get(slug), nb=c.get("footprints"), units=c.get("units") or None, sub=1)
    # master projects as developments
    masters = collections.Counter((v.get("m"), v.get("d")) for v in items.values() if v.get("m"))
    for (m, d), c in masters.items(): add(m, "development", d=d, a=AREA_LABEL.get(d), nb=c)
    # any building or development that carries a developer-page card name gets the card anchor too (search -> HOMES card)
    for v in items.values():
        k = nk(v["n"])
        if k in prop_dev and not v.get("p"): v["dev"] = v.get("dev") or prop_dev[k]; v["p"] = k
        elif not v.get("p"):
            # a partial name match only counts when the developer page places that property in the same area as the item
            # (Arada's "Masaar" is in Sharjah; JVC's "Masaar Residences" is somebody else's building)
            ia = nk(v.get("a") or "")
            hit = next((pk for pk in prop_dev if len(pk) >= 6 and (pk in k or k in pk) and prop_area.get(pk) and ia and (prop_area[pk] in ia or ia in prop_area[pk])), None)
            if hit: v["dev"] = v.get("dev") or prop_dev[hit]; v["p"] = hit
    # one entry per name: a register-only "building" row gives way to the developer-page development of the same name
    seen = {}
    for v in list(items.values()):
        k = nk(v["n"])
        if k in seen:
            a, b = seen[k], v
            keep, drop = (a, b) if (a.get("dev") and a.get("p")) or (a["t"] == "development" and b["t"] == "building" and not b.get("i")) else ((b, a) if (b.get("dev") and b.get("p")) else (a, b))
            for kk, vv in drop.items():
                if kk not in keep and vv not in (None, "", [], {}): keep[kk] = vv
            items = {kk: vv for kk, vv in items.items() if vv is not drop}
            seen[k] = keep
        else: seen[k] = v
    sheets = sheet_slugs()
    _tagged = 0
    for v in items.values():
        if v["t"] == "developer":
            continue
        sl = resolve_sheet(sheets, v["n"])
        if sl:
            v["sheet"] = sl
            _tagged += 1

    out = sorted(items.values(), key=lambda r: ({"developer": 0, "development": 1, "building": 2}[r["t"]], -(float(r.get("units")) if isinstance(r.get("units"),(int,float)) or str(r.get("units") or "").replace(".","").isdigit() else 0), r["n"]))
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "n": len(out), "items": out}
    json.dump(doc, open(os.path.join(BOARD, "search_index.json"), "w", encoding="utf-8"), ensure_ascii=False)
    c = collections.Counter(r["t"] for r in out)
    print(f"search index: {len(out):,} items | {dict(c)} | {os.path.getsize(os.path.join(BOARD, 'search_index.json')) // 1024} KB")
    print(f"  client-sheet slugs on {_tagged:,} rows ({len(out) - _tagged:,} rows have no Land Department project behind them)")
    if not dry: print("push ->", push("search_index", doc, env_token("INGEST_TOKEN")))


if __name__ == "__main__":
    main()

"""Azimuth board v73 data: the developer grid (2 x 5), each developer's property cards, and the links down to the unit cards.
Composes KV `board_devs` from developer_segments.json + developer_dna.json + DLD register + curated buildings + card indexes,
and pushes every logo in data/board/logos as KV logo_<key> (served at /img/logo_<key>). Run after build_developer_dna.py.
Drill: /home (10 developer cards) -> /dev?d=<key> (that developer's properties) -> /cards?b=<building> (unit-type cards) or /avail?d=<dev>.
"""
import base64, datetime as dt, glob, json, os, re, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push, WORKER  # noqa: E402

# The "mix" on a portfolio card is scraped off the developer's own page, and the scrape picks up the
# site NAVIGATION: nearly every Emaar card carries one identical ten-word list, and Ellington tags
# almost every tower "villa" because the word sits in its menu. Eltiera Views read ["villa"] with 617
# registered sales, every one an apartment - and Naj was about to sit with Ellington's own team.
# Where a project has 20+ registered sales and EVERY one is an apartment ("Unit"), the register
# contradicts villa / townhouse / mansion and those words are dropped. Villa communities register as
# LAND plots (Eden Hills, Jouri Hills, Sidra), so they are left alone. A missing word is a gap she
# can live with; a wrong one said to a developer's own team is not.
_PROP_TYPES = None


def honest_mix(name, mix):
    global _PROP_TYPES
    if not mix:
        return mix
    if _PROP_TYPES is None:
        _PROP_TYPES = {}
        try:
            import duckdb
            con = duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)
            for p, t, n in con.execute("select upper(trim(PROJECT_EN)), PROP_TYPE_EN, count(*) "
                                       "from transactions group by 1, 2").fetchall():
                _PROP_TYPES.setdefault(p, {})[t] = n
            con.close()
        except Exception as e:
            print("  honest_mix: register unavailable (%s) - mix left as scraped" % str(e)[:60])
    t = _PROP_TYPES.get(str(name or "").upper().strip()) or {}
    if sum(t.values()) >= 20 and set(t) == {"Unit"}:
        return [m for m in mix if m.lower().rstrip("s") not in ("villa", "townhouse", "mansion")]
    return mix

SEG = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_segments.json"), encoding="utf-8"))
DNA = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_dna.json"), encoding="utf-8"))
KEY = {"OMNIYAT": "omniyat", "H&H": "hh", "Meraas": "meraas", "Select Group": "select", "Ellington": "ellington", "Arada": "arada",
       "ZAYA": "zaya", "Palma": "palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman", "Prestige One": "prestigeone", "Emaar": "emaar", "Sobha": "sobha"}
# buildings we hold cards / meta for, per developer key -> [{building slug, title, cards key, meta slug, drill dev key}]
OURS = {"imtiaz": [{"building": "symphony", "title": "The Symphony by Imtiaz", "cards": "symphony", "meta": "goldensymphony", "drill": "imtiaz",
                    "area": "Bukadra (Meydan Horizon)", "status": "under construction"}]}
TIER_ICON = {"ultra_luxury": "crown", "luxury": "gem", "wellness_luxury": "leaf", "premium_luxury": "spark", "accessible_premium": "key"}

devs = []
for seg in SEG["segments"]:
    for name in seg["developers"]:
        k = KEY[name]; d = DNA["developers"].get(name, {})
        tx = d.get("tx_2026", {}); meed = d.get("meed", {})
        # property cards: DLD 2026 registrations + transaction-active projects (deduped by name) + our buildings
        props, seen = [], set()
        for b in OURS.get(k, []):
            props.append({"kind": "ours", "name": b["title"], "area": b["area"], "status": b["status"], "cards": b["cards"], "meta": b["meta"], "drill": b["drill"], "building": b["building"]}); seen.add(b["title"].lower())
        # developer-site portfolio -> one card per property, enriched with DLD register/trading stats and the availability sheet
        port = d.get("portfolio")
        if port:
            sys.path.insert(0, HERE); from build_developer_dna import norm_name, same  # noqa: E402  (same normaliser + exact matcher as the DNA builder)
            al = SEG["aliases"].get(name, [name.lower()])
            reg = {norm_name(p["project"], al): p for p in d.get("dld_projects_2026", [])}
            trd = {norm_name(t["project"], al): t for t in tx.get("projects", [])}
            # 12 Sep 2026: was `sorted(glob(...))[-1:]` - the LAST sheet file by name. These developers
            # post one PDF per project on different days, so that showed whichever project happened to
            # arrive last and hid the rest; for Fakhruddin the last file is a floor-plan set with no
            # units at all, so the board saw nothing. Union per project instead, same as the drill.
            from build_avail_index import latest_projects                      # noqa: E402
            _lp = latest_projects().get(k) or {"projects": [], "meta": {}}

            def _pj_units(pj):
                """Unit rows if we have them; else the type table's own counts (level='type')."""
                if pj.get("units"):
                    return len(pj["units"]), sorted({u[1] for u in pj["units"]})
                if pj.get("types"):
                    return (sum(t.get("n") or 0 for t in pj["types"]), [t["t"] for t in pj["types"]])
                return 0, []

            sheet = {}
            for pj in _lp["projects"]:
                n, ty = _pj_units(pj)
                sheet[norm_name(pj["p"] + ((" " + pj["block"]) if pj.get("block") and pj["block"].lower() not in pj["p"].lower() else ""), al)] = {
                    "units": n, "types": ty, "plan": pj.get("plan"), "completion": pj.get("completion"),
                    "sheet": _lp["meta"].get(pj["p"], {}).get("as_of"), "level": pj.get("level") or "unit"}
            def find(dct, nn):
                return next((v for kk, v in dct.items() if same(kk, nn)), None)
            # Sheets name projects the way the sales desk does ("Treppan Tower", "Hado Tower A", "Passo Avita"); the portfolio names
            # them the way the website does ("Treppan Tower Residences at JVT by Fakhruddin Properties", "Hado by Beyond", "Passo").
            # Every sheet block is assigned to AT MOST ONE property card, so bound units can never exceed the sheet:
            #   1. the block's project words equal the card's words (filler and places removed, accents folded)
            #   2. else the block's words sit inside exactly one card's words        ("Talea" -> "Talea (Forest) by Beyond")
            #   3. else exactly one card's words sit inside the block's words        ("Passo" <- "Passo Avita", "Passo Bella")
            # Blocks of one project (Hado Tower A/B/C, Hatimi Duplex + Towers) merge onto the card they resolve to.
            import unicodedata
            FILL = {"at", "by", "in", "on", "of", "and", "the", "a", "an", "properties", "property", "developments", "development",
                    "jvt", "jvc", "islands", "island", "palm", "deira", "marina", "downtown", "bay", "business", "creek", "harbour", "hills",
                    "dubai", "residences", "residence", "residency", "apartments", "apartment", "block", "phase", "forest"}
            def toks(t):
                t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
                t = re.sub(r"\b(tower|towers|building)\s+[a-z0-9]{1,2}\b", " ", t)          # "Hado Tower A" -> "Hado"; "Building B" -> ""
                return {w for w in re.sub(r"[^a-z0-9 ]", " ", t).split() if w not in FILL and len(w) > 1 and w not in al}
            # sheet blocks keyed by their PROJECT name (the block label is a sub-division, never a different project)
            blocks = {}
            for pj in _lp["projects"]:
                n, ty = _pj_units(pj)
                blocks.setdefault(pj["p"], []).append({"units": n, "types": ty, "plan": pj.get("plan"),
                                                      "completion": pj.get("completion"),
                                                      "sheet": _lp["meta"].get(pj["p"], {}).get("as_of"),
                                                      "level": pj.get("level") or "unit"})
            cards = [o["name"] for o in props if o["kind"] == "ours"] + [pr["name"] for pr in port["properties"]]
            card_toks = {c: toks(c) for c in cards}
            assign = {}                                                   # project name -> card name
            for pj_name in blocks:
                bt = toks(pj_name)
                if not bt: continue
                nb = norm_name(pj_name, al)
                eq = [c for c in cards if same(norm_name(c, al), nb)]                     # the DNA builder's own exact matcher first ("Seacliff" = "Sea Cliff")
                eq = eq or [c for c, ct in card_toks.items() if ct and ct == bt]
                if len(eq) >= 1: assign[pj_name] = eq[0]; continue
                inside = [c for c, ct in card_toks.items() if ct and bt < ct]
                if len(inside) == 1: assign[pj_name] = inside[0]; continue
                around = [c for c, ct in card_toks.items() if ct and ct < bt]
                if len(around) == 1: assign[pj_name] = around[0]; continue
            def find_sheet(nn, raw_name):
                hits = [b for pj_name, c in assign.items() if c == raw_name for b in blocks[pj_name]]
                if not hits: return None
                return {"units": sum(h["units"] for h in hits), "types": sorted({t for h in hits for t in h["types"]}),
                        "plan": next((h.get("plan") for h in hits if h.get("plan")), None),
                        "completion": next((h.get("completion") for h in hits if h.get("completion")), None),
                        "sheet": max(h.get("sheet") or "" for h in hits) or None, "blocks": len(hits),
                        "projects": sorted({pj_name for pj_name, c in assign.items() if c == raw_name})}
            # A type-level project is a project in its own right, not a block of another one. Name
            # matching folded "Treppan Vision" into a sibling Treppan card and its 463 units vanished,
            # so keep it out of the assignment and let it take its own card below.
            for _t in {pj["p"] for pj in _lp["projects"] if pj.get("level") == "type"}:
                assign.pop(_t, None)
            unbound = [pj for pj in blocks if pj not in assign]
            if unbound: print("  %-12s sheet projects with no card: %s" % (k, unbound))
            # the modelled ("ours") cards absorb their sheet + trading stats and block a duplicate portfolio card
            for o in props:
                if o["kind"] != "ours": continue
                on = norm_name(o["name"], al); sh, t = find_sheet(on, o["name"]), find(trd, on)
                if sh: o["sheet"] = sh
                if t: o["tx"], o["median_aed_per_sqm"] = t.get("tx"), t.get("median_aed_per_sqm")
                seen.add(on.replace(" ", ""))
            for pr in port["properties"]:
                nn = norm_name(pr["name"], al)
                if nn.replace(" ", "") in seen: continue
                r, t, sh = find(reg, nn), find(trd, nn), find_sheet(nn, pr["name"])
                props.append({"kind": "portfolio", "name": pr["name"], "slug": pr["slug"], "url": pr["url"], "image": pr.get("image"), "area": pr.get("area") or (r or {}).get("area") or (t or {}).get("area"),
                              "location": pr.get("location"), "structure": pr.get("structure"), "storeys": pr.get("storeys"), "units": pr.get("units") or ((r or {}).get("units")),
                              "handover": pr.get("handover"), "plans": pr.get("payment_plans") or [], "mix": honest_mix(pr["name"], pr.get("mix") or []),
                              "dld": {"status": (r or {}).get("status"), "pct": (r or {}).get("pct_complete"), "value_aed": (r or {}).get("value_aed")} if r else None,
                              "tx": (t or {}).get("tx"), "median_aed_per_sqm": (t or {}).get("median_aed_per_sqm"), "last": (t or {}).get("last"),
                              "sheet": sh, "gated": pr.get("downloads_gated") or []})
                seen.add(nn.replace(" ", "")); seen.add(pr["name"].lower())
            # A project we hold availability for, that matches no modelled card and no website card,
            # used to be printed as "unbound" and then dropped - it appeared nowhere. Treppan Vision
            # is exactly that: a pre-launch the developer had not yet put on its own site, whose only
            # numbers are the broker pack's type table. Give it its own card so the developer's
            # property list is everything we hold, not only what the website happens to publish.
            _by_name = {pj["p"]: pj for pj in _lp["projects"]}
            for pj_name in unbound:
                pj = _by_name.get(pj_name) or {}
                nn = norm_name(pj_name, al)
                if nn.replace(" ", "") in seen:
                    continue
                if re.match(r"^(unknown|untitled|n/?a)\b", pj_name.strip(), re.I):
                    # the extractor's placeholder for a sheet whose header it could not read - a
                    # real gap to fix upstream, never a property to show a broker
                    print("  %-12s PLACEHOLDER project not carded: %r (%d units need a real name)"
                          % (k, pj_name, _pj_units(pj)[0]))
                    continue
                n, ty = _pj_units(pj)
                r, t = find(reg, nn), find(trd, nn)
                props.append({"kind": "sheet", "name": pj_name,
                              "area": pj.get("location") or (r or {}).get("area") or (t or {}).get("area"),
                              "location": pj.get("location"),
                              "units": pj.get("total_units") or n or None,
                              "handover": pj.get("completion"),
                              "plans": [pj["plan"]] if pj.get("plan") else [],
                              "mix": ty,
                              "types": pj.get("types") or [],
                              "level": pj.get("level") or "unit",
                              "note": pj.get("source_note"),
                              "dld": {"status": (r or {}).get("status"), "pct": (r or {}).get("pct_complete"),
                                      "value_aed": (r or {}).get("value_aed")} if r else None,
                              "tx": (t or {}).get("tx"), "median_aed_per_sqm": (t or {}).get("median_aed_per_sqm"),
                              "sheet": find_sheet(nn, pj_name) or {"units": n, "types": ty,
                                                                   "sheet": _lp["meta"].get(pj_name, {}).get("as_of")}})
                seen.add(nn.replace(" ", "")); seen.add(pj_name.lower())
            # sort: on the availability sheet first, then trading volume, then handover
            props[len(OURS.get(k, [])):] = sorted(props[len(OURS.get(k, [])):], key=lambda x: (0 if x.get("sheet") else 1, -(x.get("tx") or 0), x.get("handover") or "z"))
        for p in d.get("dld_projects_2026", []):
            nm = p["project"].strip()
            if nm.lower() in seen or any(s in nm.lower() for s in seen) or (d.get("portfolio") and norm_name(nm, al).replace(" ", "") in seen): continue
            props.append({"kind": "registered", "name": nm, "area": p.get("area"), "status": (p.get("status") or "").lower(), "units": p.get("units"), "pct": p.get("pct_complete"), "value_aed": p.get("value_aed"), "start": p.get("start")}); seen.add(nm.lower())
        for t in tx.get("projects", [])[:24]:
            nm = t["project"].strip()
            if nm.lower() in seen or (d.get("portfolio") and norm_name(nm, al).replace(" ", "") in seen): continue
            props.append({"kind": "trading", "name": nm, "area": t.get("area"), "tx": t["tx"], "median_aed_per_sqm": t.get("median_aed_per_sqm"), "offplan_share": t.get("offplan_share"), "last": t.get("last")}); seen.add(nm.lower())
        devs.append({"key": k, "name": name, "segment": seg["key"], "segment_label": seg["label"], "tier": seg["rank"], "icon": TIER_ICON.get(seg["key"], "spark"),
                     "logo": "/img/logo_" + k if os.path.exists(os.path.join(ROOT, "data", "board", "logos", k + ".png")) else None,
                     "portfolio_count": (d.get("portfolio") or {}).get("count"), "kpi": {"tx_2026": tx.get("transactions", 0), "value_aed": tx.get("value_aed", 0), "projects_trading": len(tx.get("projects", [])),
                             "registered_2026": len(d.get("dld_projects_2026", [])), "meed_projects": meed.get("projects", 0), "meed_active": len(meed.get("active", [])),
                             "median_aed_per_sqm": tx.get("median_aed_per_sqm_across_projects")},
                     "entities": d.get("dld_entities", []), "properties": props, "ours": [b["building"] for b in OURS.get(k, [])]})
board = {"updated": dt.date.today().isoformat(), "source": SEG["source"], "segments": SEG["segments"], "developers": devs,
         "note": "DLD figures = naj.duckdb corpus (transactions Jan-Aug 2026, 2026 registrations), attributed by the DLD register (a sale's register row filed under one of the developer's DLD entities) or a confirmed name match; MEED counts = stored corpus v55; developer sheets shown only where captured from the group."}
out = os.path.join(ROOT, "data", "board", "board_devs.json"); os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(board, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
tok = env_token("INGEST_TOKEN")
r = push("board_devs", board, tok)
print("board_devs ->", r.get("ok"), "| developers", len(devs), "| properties", sum(len(x["properties"]) for x in devs))
# logos -> KV logo_<key> (PNG bytes through the same ingest channel push_cards uses)
LOGOS = os.path.join(ROOT, "data", "board", "logos")
for f in sorted(os.listdir(LOGOS)) if os.path.isdir(LOGOS) else []:
    if not f.endswith(".png") or f.startswith("raw_") or f.startswith("_"): continue
    k = f[:-4]; data = open(os.path.join(LOGOS, f), "rb").read()
    body = json.dumps({"imageName": "logo_" + k, "image": base64.b64encode(data).decode(), "contentType": "image/png"}).encode()   # same channel as push_cards.py
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST", headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-board/1.0"})
    try:
        rr = json.load(urllib.request.urlopen(req, timeout=60)); print("logo", k, "->", rr.get("ok"), len(data), "B")
    except Exception as e:
        print("logo", k, "FAILED", str(e)[:80])

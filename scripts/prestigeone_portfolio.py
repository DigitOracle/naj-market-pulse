"""Prestige One portfolio for the board — from the site pull (data/kits/prestigeone/PRESTIGE_ONE_SITE.json) in the same shape as the
other <dev>_portfolio.json files that build_developer_dna.py reads (properties: slug, url, title, description, image, h1, name, area, facts, amenities, pdfs).
Facts are only what the page states; the register (DLD) supplies units and status through the DNA builder, never this file.
Usage: python scripts/prestigeone_portfolio.py
"""
import json, os, re, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
K = os.path.join(ROOT, "data", "kits", "prestigeone")
AREA_HINTS = [("dubai islands", "Dubai Islands"), ("palm deira", "Dubai Islands"), ("jumeirah village circle", "Jumeirah Village Circle (JVC)"), ("jvc", "Jumeirah Village Circle (JVC)"),
              ("sports city", "Dubai Sports City"), ("barsha heights", "Barsha Heights"), ("maritime city", "Dubai Maritime City"), ("dubailand", "Dubailand"), ("dubai land", "Dubailand"),
              ("business bay", "Business Bay"), ("al jaddaf", "Al Jaddaf"), ("meydan", "Meydan"), ("motor city", "Motor City"), ("arjan", "Arjan"), ("jumeirah garden city", "Jumeirah Garden City"), ("palm jumeirah", "Palm Jumeirah")]


def main():
    site = json.load(open(os.path.join(K, "PRESTIGE_ONE_SITE.json"), encoding="utf-8")); props = []
    for path, v in sorted(site["pages"].items()):
        if not path.startswith("/projects/") or path == "/projects" or "error" in v: continue
        name = v["title"].split("|")[0].strip(); text = (v.get("text") or ""); low = (text + " " + (v.get("description") or "")).lower()
        # the site menu names every destination on every page, so read the location from the FAQ answer first, then the description, then the body
        loc = " ".join(f["a"] for f in v.get("faq", []) if "located" in f["q"].lower() or "where" in f["q"].lower()).lower()
        slug_ = path.split("/")[-1]
        DLD_AREA = {"berkeley-square-north": "Jumeirah Village Circle (JVC)", "berkeley-square-south": "Jumeirah Village Circle (JVC)", "vista-by-prestige-one": "Dubai Sports City", "the-one-by-prestige-one": "Barsha Heights",
                    "seaside-by-prestige-one": "Dubai Islands", "the-boulevard-by-prestige-one": "Dubailand (Dubai Land Residence Complex)", "golf-residences-by-prestige-one": "Dubai Sports City", "the-residence-by-prestige-one": "Jumeirah Village Circle (JVC)",
                    "luxury-canal-residences-by-prestige-one": "Dubai Islands", "coastal-haven-by-prestige-one": "Dubai Islands", "hilton-residences-dubai-maritime-city": "Dubai Maritime City"}   # DLD projects register, 4 Sep 2026
        area = DLD_AREA.get(slug_) or next((a for k, a in AREA_HINTS if k in loc), None) or next((a for k, a in AREA_HINTS if k in (v.get("description") or "").lower()), None) or next((a for k, a in AREA_HINTS if k in low), None)
        m_units = re.search(r"(\d{2,4})\s+(?:residential\s+)?(?:units|residences|apartments|homes)", low); m_floors = re.search(r"(?:g\s*\+\s*|ground\s*\+\s*)?(\d{1,2})\s+(?:floors|storeys|stories)", low)
        m_hand = re.search(r"(?:handover|completion)[^.\n]{0,40}?(q[1-4]\s*20\d\d|20\d\d)", low)
        mix = sorted(set(re.findall(r"\b(studio|[1-6])\s*(?:-|\s)?(?:br|bed|bedroom)s?\b", low)))
        imgs = [a for a in v.get("assets", []) if "error" not in a and not a["file"].lower().endswith(".pdf")]; pdfs = [a["url"] for a in v.get("assets", []) if a["file"].lower().endswith(".pdf")]
        props.append({"slug": path.split("/")[-1], "url": v["url"], "title": v["title"], "description": v.get("description"), "image": imgs[0]["url"] if imgs else None, "h1": (v.get("headings") or [name])[0],
                      "name": re.sub(r"\s+by Prestige One$", "", name, flags=re.I).strip(), "text_chars": len(text), "area": area,
                      "facts": {"location": area, "structure": None, "storeys": int(m_floors.group(1)) if m_floors else None, "units": int(m_units.group(1)) if m_units else None,
                                "handover": m_hand.group(1).upper() if m_hand else None, "payment_plans": [], "mix": [x if x == "studio" else f"{x}BR" for x in mix]},
                      "amenities": [h for h in (v.get("headings") or []) if 3 < len(h) < 40][:12], "pdfs": pdfs, "faq": v.get("faq", [])[:8], "images": [a["url"] for a in imgs], "kind": "villa" if "villa" in low[:600] else "apartments"})
    out = {"source": "prestigeone.ae project pages (public), pulled " + site.get("pulled", ""), "fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "properties": props}
    json.dump(out, open(os.path.join(ROOT, "data", "dev_meta", "prestigeone_portfolio.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"portfolio: {len(props)} properties -> data/dev_meta/prestigeone_portfolio.json"); [print(f"  {p['name']:42s} {p['area'] or '-':32s} units {p['facts']['units'] or '-'} · mix {p['facts']['mix']} · imgs {len(p['images'])} · pdfs {len(p['pdfs'])}") for p in props]


if __name__ == "__main__":
    main()

"""Sanctuary by Prestige One - the sales brief as an Azimuth web page (dist_brief/sanctuary/).

Reuses every figure computed by build_sanctuary_brief.py (loaded with SANCT_NO_PDF=1, so the PDF and the page never disagree),
embeds them as JSON, and renders an interactive, phone-first page in the Azimuth brief style (dist_brief/index.html palette).
"""
import io, json, os, sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("SANCT_WEB_OUT", r"C:\Dev\naj-market-pulse\dist_brief\sanctuary")
os.environ["SANCT_NO_PDF"] = "1"
g = {"__name__": "sanctuary_brief"}
try:
    exec(compile(io.open(os.path.join(HERE, "build_sanctuary_brief.py"), encoding="utf-8").read(), "build_sanctuary_brief.py", "exec"), g)
except SystemExit:
    pass

C, S_PSF, TYPOS, PLATES, PRICED = g["C"], g["S_PSF"], g["TYPOS"], g["PLATES"], g["PRICED"]
sanct_row = g["sanct_row"]


def reg(c):
    r = c.get("register") or {}
    pc = r.get("percent_completed")
    n = r.get("no_of_units")
    return {"built": None if pc in (None, "") else round(float(pc)),
            "due": (r.get("project_end_date") or r.get("completion_date") or "")[:7] or None,
            "units": int(float(n)) if n not in (None, "") and float(n) > 0 else None}


def comp(name, dev, where):
    c = C[name]
    return dict(name=name, dev=dev, where=where, psf=c["last12_psf"], sales=c["last12_sales"],
                rooms={r[0]: {"n": r[1], "sqft": r[2], "price": r[3], "psf": r[4]} for r in c["rooms"]}, **reg(c))


sanct = {}
for rooms, beds in (("1 B/R", 1), ("2 B/R", 2), ("3 B/R", 3)):
    s = sanct_row(rooms, beds)
    sanct[rooms] = dict(indoor=[s[0], s[1]], total=[s[2], s[3]], from_=s[4], to=s[5], median=s[6], psf=s[7], priced=s[8], units=g["units_by_beds"][beds])

khda = sorted(g["khda"], key=lambda s: ({"outstanding": 0, "very good": 1, "good": 2}.get((s[3] or "").lower(), 9), s[0]))
clean = lambda n: n.split(" L.L.C")[0].split(" - ")[0].split(" FZ")[0]
hosp = sorted(g["hosp"], key=lambda x: x[0])
spin, metro = g["spin"], g["metro"]

DATA = {
    "today": g["today"], "S_PSF": S_PSF, "sanct": sanct,
    "dist": g["DIST"], "drive": g["DRIVE"],
    "districts": [dict(name=k, **{"n": g["PT"][k]["n"], "psf": g["PT"][k]["psf"], "br1": g["PT"][k]["br1"], "br2": g["PT"][k]["br2"]})
                  for k in ("Palm Jumeirah", "Downtown Dubai", "Business Bay", "Dubai Marina", "Dubai Creek Harbour", "Meydan Horizon")],
    "neighbours": [comp(k, g["dev"][k], g["where"][k]) for k in g["order"]],
    "win": g["win"], "ask": g["ask"],
    "ellington": [comp(k, "Ellington", g["ell_where"][k]) for k in g["ELL"]],
    "ew": g["ew"], "ea": g["ea"],
    "typos": {t: {k: d[k] for k in ("label", "suite", "balc", "floors", "note", "page")} for t, d in TYPOS.items()},
    "typecol": g["TYPE_COL"], "stackview": g["STACK_VIEW"],
    "plates": PLATES, "priced": PRICED, "qa": g["qa"],
    "sub": g["MK"]["sub_monthly"],
    "schools": [dict(name=clean(s[1]), rating=s[3] or "Not rated", curr=(s[2] or "").split(" - ")[0], km=s[0]) for s in khda[:12]],
    "n_schools": len(khda), "curr": g["curr"].most_common(4),
    "hospitals": [dict(name=h[1], kind=h[2], km=h[0]) for h in hosp[:5]],
    "clinics": len(g["clin3"]), "pharm": len(g["ph3"]), "groc": sum(1 for x in g["groc"] if x[0] <= 3),
    "spinneys": spin[0] if spin else None, "metro": [metro[0][0], metro[0][1]["n"]],
}

# images: downscaled copies of the brochure pages the PDF uses
IMGS = ["cover", "sanctuary_map", "plate_01_08", "living_deck", "plate_10_12", "plate_13_20", "int_2br", "sky_deck"] + [d["page"] for d in TYPOS.values()]
os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
for n in IMGS:
    im = Image.open(os.path.join(g["IMG"], n + ".jpg")).convert("RGB")
    if im.width > 1400:
        im = im.resize((1400, round(im.height * 1400 / im.width)), Image.LANCZOS)
    im.save(os.path.join(OUT, "img", n + ".jpg"), quality=80, optimize=True, progressive=True)

pdf = os.path.join(os.environ["TEMP"], "sanctuary_brief.pdf")   # built by build_sanctuary_brief.py
if os.path.exists(pdf):
    import shutil; shutil.copyfile(pdf, os.path.join(OUT, "Sanctuary_Brief_PrestigeOne.pdf"))
html = io.open(os.path.join(HERE, "sanctuary_web_template.html"), encoding="utf-8").read()
html = html.replace("/*__DATA__*/null", json.dumps(DATA, ensure_ascii=False, default=str).replace("</", "<\\/"))
io.open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(html)
print("wrote", OUT, os.path.getsize(os.path.join(OUT, "index.html")), "bytes +", len(IMGS), "images")

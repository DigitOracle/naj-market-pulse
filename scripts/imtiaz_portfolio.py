"""Imtiaz portfolio register, from the developer's own site (imtiaz.ae/property/<slug>).
Per property: title, meta description, hero image, the FAQ block (location, mix, floors, handover, payment plan, amenities),
the download buttons (brochure / fact sheet / floor plans -> href or data-* targets) and a few parsed facts.
Output: data/dev_meta/imtiaz_portfolio.json (+ .md digest). This is the authority for "which projects are Imtiaz's";
DLD/MEED rows are then matched AGAINST it (build_developer_dna.py), which kills the name-noise ("The Cove" = Emaar, "Symphony" = Town Square).
"""
import html, json, os, re, sys, time, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dev_meta"); os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
BASE = "https://imtiaz.ae"

def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read().decode("utf-8", "ignore")

def strip(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", s))).strip()

def slugs():
    h = get(BASE + "/")
    s = sorted(set(re.findall(r'href="https?://imtiaz\.ae/property/([^"#?]+)"', h)))
    try:
        h2 = get(BASE + "/properties"); s = sorted(set(s) | set(re.findall(r'href="https?://imtiaz\.ae/property/([^"#?]+)"', h2)))
    except Exception:
        pass
    return s

def parse(slug, h):
    rec = {"slug": slug, "url": BASE + "/property/" + slug}
    m = re.search(r"<title>(.*?)</title>", h, re.S); rec["title"] = strip(m.group(1)) if m else slug
    m = re.search(r'<meta name="description" content="([^"]*)"', h); rec["description"] = html.unescape(m.group(1)) if m else ""
    m = re.search(r'<meta property="og:image" content="([^"]*)"', h); rec["image"] = m.group(1) if m else None
    m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S); rec["h1"] = strip(m.group(1)) if m else ""
    parts = [x.strip() for x in re.split(r"\s[-–]\s", rec["h1"] or rec["title"].split("|")[0])]
    rec["name"] = next((x for x in parts if "imtiaz" in x.lower()), parts[-1])
    tp = [x.strip() for x in rec["title"].split("|")]
    rec["area"] = tp[1] if len(tp) >= 3 else None            # title pattern "Name | Area | Imtiaz"
    # FAQ accordion: question in h3, answer paragraphs in .acc-body
    faq = []
    for chunk in re.split(r'<div class="faq-item"', h)[1:]:
        q = re.search(r"<h3[^>]*>(.*?)</h3>", chunk, re.S); body = re.search(r'<div class="acc-body">(.*?)(?:<div class="faq-item"|<section|</section>|$)', chunk, re.S)
        if q: faq.append({"q": strip(q.group(1)), "a": strip(body.group(1))[:1200] if body else ""})
    rec["faq"] = faq
    # download buttons: any anchor/button whose text mentions download -> href + data-* attributes
    dl = []   # gated: <a open-modal="inquery-modal" class="property-inquiry" data-file_id="N"> opens a lead form first. We record the ids; we NEVER submit the form.
    for m in re.finditer(r'<a[^>]*property-inquiry[^>]*data-file_id="(\d+)"[^>]*>(.*?)</a>', h, re.S):
        lab = re.search(r"<p[^>]*>(.*?)</p>", m.group(2), re.S)
        dl.append({"label": strip(lab.group(1)) if lab else "", "file_id": m.group(1), "gated": True})
    rec["downloads"] = dl
    rec["pdfs"] = sorted(set(re.findall(r'(https?://[^"\'\s<>]+\.pdf)', h)))
    # parsed facts from FAQ text
    text = " ".join(f["q"] + " " + f["a"] for f in faq) + " " + rec["description"]
    def grab(rx, flags=re.I):
        m = re.search(rx, text, flags); return m.group(1).strip() if m else None
    MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    mix = []
    for tok in re.findall(r"(studios?|\d\s?-?\s?bedroom|\d\s?BR\b|penthouses?|duplex(?:es)?|retail|offices?)", text, re.I):
        t = re.sub(r"\s", "", tok.lower()).replace("bedroom", "BR").replace("studios", "studio").replace("duplexes", "duplex").replace("penthouses", "penthouse").replace("offices", "office")
        if t not in mix: mix.append(t)
    rec["facts"] = {
        "location": grab(r"located (?:in|at|within|on) ([^.]{3,120})\."),
        "structure": grab(r"\(((?:\d?[BGPRM]\s?\+\s?)+\d+(?:\s?\+\s?R)?)\)"),
        "storeys": grab(r"(\d{1,2})\s?-?\s?(?:storey|residential floors)"),
        "units": grab(r"(?:around |approximately |about |some )?(\d{2,4})\s(?:well-planned |residential |spacious )?(?:units|residences|apartments|homes)"),
        "handover": grab(r"(?:handover|completion|hand over the keys|move in|delivery)[^.]{0,60}?((?:Q[1-4]\s|" + MONTH + r"\s)?20\d\d)"),
        "payment_plans": sorted(set(re.findall(r"\b(\d{2}/\d{2})\b", text))),
        "mix": mix,
    }
    return rec

if __name__ == "__main__":
    ss = slugs(); print("property pages:", len(ss))
    out = []
    for i, s in enumerate(ss):
        try:
            rec = parse(s, get(BASE + "/property/" + s)); out.append(rec)
            f = rec["facts"]; print(f"{i+1:>2} {rec['name'][:34]:<34} | {(rec['area'] or '-')[:22]:<22} | {f['structure'] or f['storeys'] or '-':<14} | u {f['units'] or '-':<4} | {f['handover'] or '-':<10} | {','.join(f['payment_plans']) or '-':<6} | {','.join(f['mix'])[:28]:<28} | dl {len(rec['downloads'])}")
        except Exception as e:
            print(i + 1, s, "FAILED", str(e)[:80])
        time.sleep(0.4)
    json.dump({"source": BASE, "fetched": time.strftime("%Y-%m-%d %H:%M"), "properties": out}, open(os.path.join(OUT, "imtiaz_portfolio.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = ["# Imtiaz portfolio register (imtiaz.ae, %s)\n" % time.strftime("%Y-%m-%d"), "| # | property | location | structure | handover | plans | mix |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(out):
        f = r["facts"]; md.append(f"| {i+1} | [{r['name']}]({r['url']}) | {f['location'] or '-'} | {f['structure'] or '-'} | {f['handover'] or '-'} | {', '.join(f['payment_plans']) or '-'} | {f['mix'] or '-'} |")
    open(os.path.join(OUT, "imtiaz_portfolio.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("written", len(out), "properties")

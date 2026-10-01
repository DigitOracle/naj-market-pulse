"""The Brief, part C - publish the developer brochures (photos + amenities) for /brief_pdf, and the header picture.

Reads   data/brand/buildings/<district>_<id>/brochure.json  or  data/brand/buildings/name_<slug>/brochure.json  (+ the photo files)
        data/brand/najjuko_with_n_cutout.png   Najjuko leaning on the Najma N (Kendall's still, background removed) - the header picture
Writes  (dry run, the default) a folder of exactly what would be stored, plus manifest.json - nothing leaves the machine
        (--push) KV through POST /ingest_market, like every other img_* key (see build_avail_index.py push()):
          img_brochure_<dir>     the brochure JSON, each photo carrying "key" = the KV name of its picture
          img_bph_<16 hex>       each photo, scaled to the size it prints at (exterior 1400 px wide, others 900) as JPEG q84
          img_brand_najjuko_n    the header picture, PNG, 300 px tall
Why the photo names are hashes. /ingest_market cuts imageName at 40 characters, and "brochure_jumeirahvillagecircle_1490_exterior"
is 44: a readable name would be silently truncated and two photos could land on one key. The brochure JSON is stored under
"brochure_<dir>" when that fits in 40 characters, else "brochure_h<16 hex>" - the same FNV-1a function as fnv16() in the Worker's
src/brief_docs.js, so both sides agree on the name without a lookup table.

Rules this enforces (client documents, Kendall): photos and amenities come ONLY from the developer's own project page. A brochure whose
source_url is a listing portal is refused whole; a photo whose source or page is a portal is dropped. The listing portal list is the
same as PORTAL_RX in src/brief_docs.js (the Worker refuses them too, as a second lock).

Usage   python scripts/push_brochures.py                 dry run into %TEMP%/brochure_kv
        python scripts/push_brochures.py --out DIR       dry run into DIR
        python scripts/push_brochures.py --push          publish (needs INGEST_TOKEN in the listener .env)   - NOT run by the Brief build
"""
import argparse, base64, io, json, os, re, sys, tempfile, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BR = os.path.join(ROOT, "data", "brand", "buildings")
HEADER = os.path.join(ROOT, "data", "brand", "najjuko_with_n_cutout.png")
WORKER = "https://azimuth-2.digitalchemy.workers.dev"
PORTAL_RX = re.compile(r"(propertyfinder|bayut|dubizzle|justproperty|houza|opensooq|zillow|rightmove|zoopla|propsearch|emirates\.estate|"
                       r"drivenproperties|betterhomes|allsoppandallsopp|hausandhaus|fam-?properties|luxhabitat|axcapital|"
                       r"metropolitan\.realestate|provident)", re.I)
MAX_NAME = 40
MAX_BYTES = 5 * 1024 * 1024


def env_token(name):
    p = r"C:\Dev\azimuth-listener-naj\.env"
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(name)


def fnv16(s):
    """Two FNV-1a 32-bit hashes over the UTF-8 bytes - identical to fnv16() in src/brief_docs.js."""
    def h(seed):
        x = seed & 0xFFFFFFFF
        for ch in s.encode("utf-8"):
            x ^= ch
            x = (x * 16777619) & 0xFFFFFFFF
        return "%08x" % x
    return h(2166136261) + h(0x811C9DC5 ^ 0x5BD1E995)


def brochure_kv_name(d):
    return "brochure_" + d if len("brochure_" + d) <= MAX_NAME else "brochure_h" + fnv16(d)


def is_portal(u):
    return bool(PORTAL_RX.search(str(u or "")))


def jpeg(path, width):
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True)
    return buf.getvalue()


def header_png():
    im = Image.open(HEADER)
    im = im.resize((round(im.width * 300 / im.height), 300), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def collect():
    """-> [(kv name, bytes, content type, note)] and a list of refusals."""
    out, refused = [], []
    if os.path.exists(HEADER):
        out.append(("brand_najjuko_n", header_png(), "image/png", "header picture"))
    else:
        refused.append(("header", "no %s" % HEADER))
    for d in sorted(os.listdir(BR)):
        bp = os.path.join(BR, d, "brochure.json")
        if not os.path.exists(bp):
            continue
        if not re.fullmatch(r"[a-z0-9_]+", d):
            refused.append((d, "folder name is not [a-z0-9_] - the Worker could not name it"))
            continue
        br = json.load(open(bp, encoding="utf-8"))
        if is_portal(br.get("source_url")):
            refused.append((d, "source_url is a listing portal: %s" % br.get("source_url")))
            continue
        photos = []
        for p in br.get("photos", []):
            f = os.path.join(BR, d, p.get("file", ""))
            if is_portal(p.get("source_url")) or is_portal(p.get("page_url")):
                refused.append((d + "/" + p.get("file", "?"), "photo from a listing portal - dropped"))
                continue
            if not p.get("file") or not os.path.exists(f):
                refused.append((d + "/" + p.get("file", "?"), "file missing - dropped"))
                continue
            key = "bph_" + fnv16(d + "/" + p["file"])
            data = jpeg(f, 1400 if p["file"].startswith("exterior") else 640)   # page-3 photos print ~170 px wide; 640 keeps them sharp at 2x and light
            if len(data) > MAX_BYTES:
                refused.append((d + "/" + p["file"], "over 5 MB after scaling - dropped"))
                continue
            out.append((key, data, "image/jpeg", "%s/%s" % (d, p["file"])))
            photos.append(dict(p, key=key))
        doc = dict(br, photos=photos, dir=d)
        raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        out.append((brochure_kv_name(d), raw, "application/json", "%s brochure, %d photos" % (d, len(photos))))
    return out, refused


def push(name, data, ct, tok):
    body = json.dumps({"imageName": name, "image": base64.b64encode(data).decode(), "contentType": ct}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json",
                                          "User-Agent": "najma-market-pulse/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=900))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "brochure_kv"))
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    items, refused = collect()
    for name, data, ct, note in items:
        assert len(name) <= MAX_NAME, name
    tok = env_token("INGEST_TOKEN") if a.push else None
    if a.push and not tok:
        sys.exit("--push needs INGEST_TOKEN")
    os.makedirs(a.out, exist_ok=True)
    manifest = {}
    for name, data, ct, note in items:
        fn = name + (".json" if ct == "application/json" else ".png" if ct == "image/png" else ".jpg")
        open(os.path.join(a.out, fn), "wb").write(data)
        manifest[name] = {"file": fn, "contentType": ct, "bytes": len(data), "note": note}
        print("%-44s %-17s %8.0f KB  %s" % ("img_" + name, ct, len(data) / 1024, note))
        if a.push:
            print("   pushed", push(name, data, ct, tok))
    json.dump(manifest, open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8"), indent=1)
    for what, why in refused:
        print("REFUSED  %-40s %s" % (what, why))
    print("%d keys, %.1f MB in %s%s" % (len(items), sum(len(i[1]) for i in items) / 1048576, a.out,
                                          "" if a.push else "  (dry run - nothing pushed)"))


if __name__ == "__main__":
    main()

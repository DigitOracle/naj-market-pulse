"""Media register: every picture we hold, bound to the developer and project it belongs to.

The truth store knew projects, units, prices and documents, but not one image. Renders sat inside
brochure PDFs, plates sat in Worker storage, and nothing said "these belong to Palma, Serenia
District". So the question "do we have any pictures from EYWA?" could not be answered by anything
except a person opening folders.

This builds the answer:
  1. opens every brochure / render pack we hold (developer group captures + data/brochure),
  2. renders each page, keeps the pages that are pictures (image-dominant, little text),
  3. writes them as JPEGs under data/media/<developer>/<project>/,
  4. loads a `media` table in najma.duckdb, one row per image, with developer, project, source, page,
     reuse basis and where it came from,
  5. with --push, uploads the best few per project to the Worker (img_media_<id>) and pushes a
     compact media_index the picture route can read from a phone tap.

Reuse basis, stated on every row: material a developer posts to a broker group is sent for
brokers to use; that is "developer-supplied". Generated plates are "ours". DLD plans are register
documents and are never registered here as backdrops.
"""
import argparse, datetime as dt, glob, hashlib, io, json, os, re, sys

import fitz  # PyMuPDF
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
MEDIA = os.path.join(ROOT, "data", "media")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
CAPTURE = r"C:\Dev\azimuth-listener-naj\docs\developer_availability"
BROCHURE = os.path.join(ROOT, "data", "brochure")
INBOX = os.path.join(ROOT, "data", "brochure_inbox")      # what she sends on WhatsApp lands here (pull_brochures.py)
MAX_SIDE = 1600
MIN_IMAGE_COVER = 0.55      # a page is a picture when images cover this much of it
MAX_TEXT_CHARS = 260        # ...and it carries no more than a caption's worth of text

# First-pass binding by filename. The alias machinery can take over once these are also in `project`.
BIND = [
    (r"treppan\s*vision", "Fakhruddin", "Treppan Vision", "Dubai Land Residence Complex"),
    (r"archive", "Imtiaz", "The Archive by Imtiaz", "Dubai Hills"),
    (r"serenia", "Palma", "Serenia District", "East Jumeirah Islands"),
    (r"symphony", "Imtiaz", "Imtiaz Symphony Tower", "Business Bay"),
]


def bind(name):
    low = name.lower()
    for rx, dev, proj, area in BIND:
        if re.search(rx, low):
            return dev, proj, area
    return None, None, None


def slug(t):
    return re.sub(r"[^a-z0-9]+", "_", str(t or "").lower()).strip("_")[:40]


def page_is_picture(page):
    """Image coverage of the page area, and how much text rides on it."""
    area = page.rect.width * page.rect.height or 1
    cover = 0.0
    try:
        for img in page.get_images(full=True):
            for r in page.get_image_rects(img[0]):
                cover += (r.width * r.height) / area
    except Exception:
        pass
    text = page.get_text().strip()
    return min(cover, 1.0), len(text), (cover >= MIN_IMAGE_COVER and len(text) <= MAX_TEXT_CHARS)


def classify(im):
    """render, or plan. A floor plan is image-dominant and low-text too, so page shape cannot separate
    them - but a plan is drawn on white and barely coloured, and a render is neither. The Archive's
    43 'pictures' were all floor plans on the first pass; offering one as a backdrop would put a unit
    layout behind her head."""
    from PIL import ImageStat, ImageFilter
    small = im.convert("RGB").resize((200, 200))
    sat = ImageStat.Stat(small.convert("HSV")).mean[1]
    px = list(small.getdata())
    white = sum(1 for p in px if min(p) > 235) / len(px)
    # A brochure's cover and its section dividers are dark, coloured and low-text, so saturation alone
    # calls them renders - and one of them went behind her head on the first live card, showing the
    # developer's own logo and typography under her headline. A photograph is DETAILED: grey-level
    # spread and edge density separate it from a flat title slide (Serenia p1 read 12/8, its renders 30-68/18-42).
    g = small.convert("L")
    detail = ImageStat.Stat(g).stddev[0]
    edges = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
    if white >= 0.15 or sat < 30:
        kind = "plan"
    elif detail < 25 or edges < 15:
        kind = "cover"                       # title page or section divider: real, but never a backdrop
    else:
        kind = "render"
    return kind, round(sat, 1), round(white, 3), round(detail, 1), round(edges, 2)


def sources():
    out = []
    if os.path.isdir(CAPTURE):
        for f in sorted(os.listdir(CAPTURE)):
            if f.lower().endswith(".pdf"):
                out.append((os.path.join(CAPTURE, f), "developer group (DEVELOPER AVAILABILITY)", "developer-supplied: posted to the broker group for broker use"))
    if os.path.isdir(BROCHURE):
        for f in sorted(os.listdir(BROCHURE)):
            if f.lower().endswith(".pdf"):
                out.append((os.path.join(BROCHURE, f), "brochure folder (" + f.split("_")[-1].replace(".pdf", "") + ")", "published brochure: public marketing material"))
    if os.path.isdir(INBOX):
        for f in sorted(os.listdir(INBOX)):
            if f.lower().endswith(".pdf"):
                out.append((os.path.join(INBOX, f), "sent by Naj on WhatsApp", "developer-supplied: given to her as a broker, for broker use"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="upload the best renders per project to the Worker and push media_index")
    ap.add_argument("--per-project", type=int, default=4, help="how many renders per project to upload with --push")
    ap.add_argument("--dpi", type=int, default=110)
    a = ap.parse_args()
    os.makedirs(MEDIA, exist_ok=True)

    rows, seen_sha, seen_pdf = [], set(), set()
    for path, source, basis in sources():
        raw = open(path, "rb").read()
        h = hashlib.sha1(raw).hexdigest()
        if h in seen_pdf:                                   # the group re-posts the same file; keep one
            continue
        seen_pdf.add(h)
        dev, proj, area = bind(os.path.basename(path))
        if not dev:
            print("  unbound, skipped:", os.path.basename(path)[:70])
            continue
        try:
            doc = fitz.open(path)
        except Exception as e:
            print("  cannot open:", os.path.basename(path)[:60], e)
            continue
        outdir = os.path.join(MEDIA, slug(dev), slug(proj))
        os.makedirs(outdir, exist_ok=True)
        kept = 0
        for i, page in enumerate(doc):
            cover, ntext, ok = page_is_picture(page)
            if not ok:
                continue
            pix = page.get_pixmap(dpi=a.dpi, alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            buf = io.BytesIO(); im.save(buf, "JPEG", quality=86, optimize=True)
            b = buf.getvalue(); ih = hashlib.sha1(b).hexdigest()
            if ih in seen_sha:                              # the compressed and full versions of a pack give the same page twice
                continue
            seen_sha.add(ih)
            kind, sat, white, detail, edges = classify(im)
            mid = "m_" + ih[:12]
            fn = os.path.join(outdir, "%s_p%02d.jpg" % (mid, i + 1))
            open(fn, "wb").write(b)
            rows.append({"media_id": mid, "kind": kind, "sat": sat, "white": white, "detail": detail, "edges": edges, "developer": dev, "project": proj, "area": area,
                         "path": os.path.relpath(fn, ROOT).replace("\\", "/"), "bytes": len(b), "w": im.width, "h": im.height,
                         "orient": "landscape" if im.width >= im.height else "portrait",
                         "source_file": os.path.basename(path), "source": source, "page": i + 1, "image_cover": round(cover, 2), "text_chars": ntext,
                         "reuse_basis": basis, "sha1": ih, "registered_at": dt.datetime.now().isoformat(timespec="seconds")})
            kept += 1
        print("  %-14s %-26s %3d pages -> %2d pictures   %s" % (dev, proj, len(doc), kept, os.path.basename(path)[:48]))

    json.dump({"updated": dt.datetime.now().isoformat(timespec="seconds"), "n": len(rows), "items": rows},
              open(os.path.join(MEDIA, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    import duckdb
    con = duckdb.connect(DB)
    con.execute("""create or replace table media (media_id varchar primary key, kind varchar, developer varchar, project varchar, area varchar,
                   path varchar, bytes integer, w integer, h integer, orient varchar, source_file varchar, source varchar, page integer,
                   image_cover double, text_chars integer, reuse_basis varchar, sha1 varchar, registered_at varchar, worker_key varchar,
                   saturation double, whiteness double, detail double, edge_density double)""")
    con.executemany("insert into media values (" + ",".join("?" * 23) + ")",
                    [(r["media_id"], r["kind"], r["developer"], r["project"], r["area"], r["path"], r["bytes"], r["w"], r["h"], r["orient"],
                      r["source_file"], r["source"], r["page"], r["image_cover"], r["text_chars"], r["reuse_basis"], r["sha1"], r["registered_at"], None, r["sat"], r["white"], r["detail"], r["edges"]) for r in rows])
    print("\nmedia table: %d rows" % len(rows))
    for r in con.execute("""select developer, project, count(*) as n_total,
                                   sum(case when kind='render' then 1 else 0 end) as n_renders,
                                   sum(case when kind='plan' then 1 else 0 end) as n_plans,
                                   sum(case when kind='cover' then 1 else 0 end) as n_covers
                            from media group by 1,2 order by 1,2""").fetchall():
        print("  %-12s %-26s %3d pages = %3d renders + %3d plans + %2d covers" % r)

    if a.push:
        sys.path.insert(0, HERE)
        from build_avail_index import env_token, push
        import base64, urllib.request
        tok = env_token("INGEST_TOKEN")
        index = {"updated": dt.date.today().isoformat(), "developers": {}}
        by = {}
        for r in rows:
            if r["kind"] != "render":                       # a floor plan is never a backdrop
                continue
            by.setdefault((r["developer"], r["project"]), []).append(r)
        for (dev, proj), items in by.items():
            # portrait first (the card is portrait-friendly on the right), then the most image-dominant
            items.sort(key=lambda r: (-r["detail"], -r["image_cover"], r["page"]))     # the most photographic page wins
            chosen = items[: a.per_project]
            lst = []
            for r in chosen:
                name = "media_" + r["media_id"][2:]                                  # 40-char cap on Worker image names
                b64 = base64.b64encode(to_plate(os.path.join(ROOT, r["path"]))).decode()
                body = json.dumps({"imageName": name, "image": b64, "contentType": "image/jpeg"}).encode()
                req = urllib.request.Request("https://azimuth-2.digitalchemy.workers.dev/ingest_market", data=body, method="POST",
                                             headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
                ok = json.load(urllib.request.urlopen(req, timeout=900)).get("ok")
                # the upstream is slow and a HEAD lies: prove it by GET
                got = urllib.request.urlopen(urllib.request.Request("https://azimuth-2.digitalchemy.workers.dev/img/" + name, headers={"User-Agent": "najma-market-pulse/1.0"}), timeout=120).read()
                if not ok or len(got) < 10000:
                    print("  UPLOAD FAILED", name); continue
                con.execute("update media set worker_key=? where media_id=?", [name, r["media_id"]])
                lst.append({"id": name, "page": r["page"], "orient": r["orient"], "credit": "Render: " + dev, "from": r["source_file"][:60]})
                print("  up  %-22s %-28s p%02d %5.0f KB" % (dev, proj, r["page"], len(got) / 1024))
            index["developers"].setdefault(slug(dev), {"name": dev, "projects": {}})["projects"][proj] = {"area": area_for(rows, proj), "renders": lst, "on_file": len(items)}
        print("media_index ->", push("media_index", index, tok).get("ok"))
    con.close()


def to_plate(path):
    """A render is landscape; the card is 1024x1536 portrait and fills the whole frame behind a cream
    wash on the left. A straight squeeze would distort the building, and a centre crop cuts the sky off
    a tower. So: crop to 2:3 keeping the full width where possible, biased UP - a render puts its
    subject above the midline and its foreground below, and her cut-out stands over the bottom right."""
    im = Image.open(path).convert("RGB")
    # A brochure page is not a photograph: it carries the developer's frame line at the top and a caption
    # band along the bottom. Crop straight and her card shows half a sentence under her own headline.
    # Trim the furniture first - a little off every edge, more off the bottom where captions live.
    w0, h0 = im.size
    im = im.crop((int(w0 * 0.035), int(h0 * 0.055), int(w0 * 0.965), int(h0 * 0.885)))
    w, h = im.size
    tw, th = 1024, 1536
    want = tw / th                                             # 0.667
    if w / h > want:                                           # too wide: take a full-height slice from the middle
        nw = int(h * want)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:                                                      # too tall: take a slice biased to the upper third
        nh = int(w / want)
        top = int((h - nh) * 0.33)
        im = im.crop((0, top, w, top + nh))
    im = im.resize((tw, th), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue()


def area_for(rows, proj):
    for r in rows:
        if r["project"] == proj:
            return r["area"]
    return ""


if __name__ == "__main__":
    main()

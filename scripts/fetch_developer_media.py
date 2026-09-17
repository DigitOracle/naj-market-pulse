"""Pull a developer's own published pictures off their own project page into the media register.

The register was built for PDFs - broker packs posted to the WhatsApp group, brochures Naj forwards.
That covers the developers who post; it does not cover the ones whose material lives on a website,
which is most of the buildings already trading. Bellevue's pictures came off dp.ae by hand in about
ten minutes. This makes that repeatable, and puts the result in the same table so the sheet pipeline
does not care where a picture came from.

Rights sit exactly where they did for the PDFs: this is material a developer publishes to sell a
building, used on a sheet for a buyer considering that building, and the source is recorded on every
row and restated on the sheet. Brochures behind a "give us your name and phone number" form are NOT
fetched - we do not hand a third party personal details to get a picture.

A manifest per project, tracked, so the fetch is auditable and repeatable:

  data/media/_sources/<slug>.json
  { "project": "...", "developer": "...", "page": "<the page these came from>",
    "images": [ {"url": "...", "note": "what the developer calls it"} ] }

The developer's own filename is often the honest caption ("1BD kitchen", "The Lofts - Master
Bedroom"), so it is kept as the note and can be promoted to a role by hand. Nothing is inferred from
the picture itself.

Usage
  python scripts/fetch_developer_media.py --slug peninsula_four_the_plaza
  python scripts/fetch_developer_media.py --slug ... --dry
"""
import argparse, hashlib, io, json, os, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_media_register import classify, MAX_SIDE  # noqa: E402  - one classifier, one definition

MEDIA = os.path.join(ROOT, "data", "media")
SOURCES = os.path.join(MEDIA, "_sources")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
UA = {"User-Agent": "DigitAlchemy-najma/1.0 (contact@digitalabbot.io)"}
MIN_SIDE = 600          # below this it is a thumbnail or a logo, not sheet material


def slugify(s):
    import re
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")[:50]


def fetch(url, timeout=90):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    mpath = os.path.join(SOURCES, "%s.json" % a.slug)
    if not os.path.exists(mpath):
        print("no manifest at %s" % os.path.relpath(mpath, ROOT))
        return 2
    man = json.load(open(mpath, encoding="utf-8"))
    project, developer = man["project"], man["developer"]
    dest = os.path.join(MEDIA, slugify(developer), slugify(project))
    if not a.dry:
        os.makedirs(dest, exist_ok=True)

    rows, skipped = [], 0
    for i, item in enumerate(man["images"], 1):
        url = item["url"]
        try:
            raw = fetch(url)
        except Exception as e:
            print("  %2d  FAILED %s  (%s)" % (i, url.rsplit("/", 1)[-1][:46], e))
            continue
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            print("  %2d  not an image: %s" % (i, url.rsplit("/", 1)[-1][:46]))
            continue
        if min(im.size) < MIN_SIDE:
            skipped += 1
            continue
        if max(im.size) > MAX_SIDE:
            r = MAX_SIDE / max(im.size)
            im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        kind, sat, white, detail, edges = classify(im)
        sha = hashlib.sha1(raw).hexdigest()
        mid = "m_" + sha[:12]
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        fn = "%s_%s.jpg" % (mid, slugify(os.path.splitext(name)[0])[:28])
        path = os.path.join(dest, fn)
        if not a.dry:
            im.save(path, quality=86, optimize=True)
        rows.append({"media_id": mid, "kind": kind, "developer": developer, "project": project,
                     "area": man.get("area"), "path": os.path.relpath(path, ROOT).replace("\\", "/"),
                     "bytes": os.path.getsize(path) if not a.dry else len(raw),
                     "w": im.width, "h": im.height,
                     "orient": "landscape" if im.width >= im.height else "portrait",
                     "source_file": name, "source": man.get("page") or "developer website",
                     "page": i, "image_cover": 1.0, "text_chars": 0,
                     "reuse_basis": "developer-published: on the developer's own project page for this building",
                     "sha1": sha, "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "worker_key": None, "saturation": sat, "whiteness": white,
                     "detail": detail, "edge_density": edges})
        print("  %2d  %-7s %-52s %dx%d" % (i, kind, name[:52], im.width, im.height))

    print("\n%d registered, %d skipped as too small" % (len(rows), skipped))
    if a.dry or not rows:
        return 0

    # DuckDB takes a single writer lock on the file. Several scouts fetching different developers at
    # once is the whole point of running them in parallel, and without this they collide and one loses
    # its work after doing all the downloading. Wait for the writer rather than fail.
    import random
    import duckdb
    for attempt in range(12):
        try:
            con = duckdb.connect(DB)
            break
        except Exception as e:
            if "lock" not in str(e).lower() and "being used" not in str(e).lower():
                raise
            wait = min(20, 2 ** attempt * 0.4) + random.random()
            print("  media table busy (another fetch is writing); waiting %.1fs" % wait)
            time.sleep(wait)
    else:
        print("could not get the media table after 12 tries - the images are on disk, re-run this slug")
        return 1

    cols = [c[0] for c in con.execute("describe media").fetchall()]
    # One image published on two projects shares a sha1, so the media_id collides and the whole batch
    # rolls back. Drop rows already registered elsewhere rather than lose the fetch.
    have = {r[0] for r in con.execute("select media_id from media where project <> ?", [project]).fetchall()}
    clash = [r for r in rows if r["media_id"] in have]
    if clash:
        rows = [r for r in rows if r["media_id"] not in have]
        print("  %d image(s) already registered under another project - skipped: %s"
              % (len(clash), ", ".join(c["source_file"][:40] for c in clash[:3])))
    con.execute("delete from media where project = ? and source not like 'developer group%'", [project])
    if rows:
        con.executemany("insert into media (%s) values (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                        [[r.get(c) for c in cols] for r in rows])
    con.close()
    print("media table updated for %s (%d rows)" % (project, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

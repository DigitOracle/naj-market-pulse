"""Rebuild the media register's WEB-SOURCED rows from the files already on disk.

Why this exists: build_media_register.py recreates the `media` table from the documents it scans, so
running it deleted every row the developer-website fetcher had written - about 800 images across 86
projects, from four scouts. The pictures themselves were never touched; only the index of them.

That is the actual lesson and it is now fixed in build_media_register.py: a scan of ONE source must
never delete another source's rows. This script recovers what was lost without re-downloading a
single byte - the files are on disk, their media_id is in each filename, and the manifests say where
each came from and what it shows.

Usage: python scripts/reregister_web_media.py [--dry]
"""
import argparse, glob, io, json, os, re, sys, time, urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_media_register import classify  # noqa: E402  - one classifier, one definition

MEDIA = os.path.join(ROOT, "data", "media")
SOURCES = os.path.join(MEDIA, "_sources")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")[:50]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    rows, missing, projects = [], 0, 0
    for mf in sorted(glob.glob(os.path.join(SOURCES, "*.json"))):
        try:
            man = json.load(io.open(mf, encoding="utf-8"))
        except Exception:
            continue
        project, developer = man.get("project"), man.get("developer")
        if not project or not developer:
            continue
        folder = os.path.join(MEDIA, slug(developer), slug(project))
        if not os.path.isdir(folder):
            missing += 1
            continue
        on_disk = {}
        for f in os.listdir(folder):
            m = re.match(r"(m_[0-9a-f]{12})_(.*)\.jpg$", f)
            if m:
                on_disk[m.group(2)] = (m.group(1), os.path.join(folder, f))

        found = 0
        for i, item in enumerate(man.get("images", []), 1):
            name = urllib.parse.unquote(item["url"].rsplit("/", 1)[-1])
            key = slug(os.path.splitext(name)[0])[:28]
            hit = on_disk.get(key)
            if not hit:
                continue
            mid, path = hit
            try:
                im = Image.open(path).convert("RGB")
            except Exception:
                continue
            kind, sat, white, detail, edges = classify(im)
            rows.append({"media_id": mid, "kind": kind, "developer": developer, "project": project,
                         "area": man.get("area"),
                         "path": os.path.relpath(path, ROOT).replace("\\", "/"),
                         "bytes": os.path.getsize(path), "w": im.width, "h": im.height,
                         "orient": "landscape" if im.width >= im.height else "portrait",
                         "source_file": name, "source": man.get("page") or "developer website",
                         "page": i, "image_cover": 1.0, "text_chars": 0,
                         "reuse_basis": "developer-published: on the developer's own project page for this building",
                         "sha1": mid[2:], "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                         "worker_key": None, "saturation": sat, "whiteness": white,
                         "detail": detail, "edge_density": edges})
            found += 1
        if found:
            projects += 1
            print("  %-40s %3d images" % (project[:40], found))

    # A media_id is a content hash, so the same picture published on two projects collides.
    seen, dedup = set(), []
    for r in rows:
        if r["media_id"] in seen:
            continue
        seen.add(r["media_id"])
        dedup.append(r)
    print("\n%d images across %d projects (%d dropped as duplicates of another project's picture)"
          % (len(dedup), projects, len(rows) - len(dedup)))
    if a.dry or not dedup:
        return 0

    import duckdb, random
    # Other sessions build the truth store from this same file, and DuckDB allows one writer. Wait
    # for them rather than lose the recovery.
    for attempt in range(30):
        try:
            con = duckdb.connect(DB)
            break
        except Exception as e:
            if "another process" not in str(e) and "lock" not in str(e).lower():
                raise
            wait = min(30, 2 ** min(attempt, 5) * 0.5) + random.random()
            print("  truth store busy (another job is writing); waiting %.0fs" % wait)
            time.sleep(wait)
    else:
        print("could not get the truth store; the files are on disk, re-run this when it frees up")
        return 1
    cols = [c[0] for c in con.execute("describe media").fetchall()]
    have = {r[0] for r in con.execute("select media_id from media").fetchall()}
    fresh = [r for r in dedup if r["media_id"] not in have]
    con.executemany("insert into media (%s) values (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                    [[r.get(c) for c in cols] for r in fresh])
    total = con.execute("select count(*) from media").fetchone()[0]
    con.close()
    print("inserted %d (skipped %d already present); media now holds %d rows"
          % (len(fresh), len(dedup) - len(fresh), total))
    return 0


if __name__ == "__main__":
    sys.exit(main())

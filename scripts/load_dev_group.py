"""Load the DEVELOPER AVAILABILITY WhatsApp group into the truth store.

Everything Naj's listener captures from that group - inventory sheets, brochures, links - has until now
stopped at data/avail/*.json and the Worker KV. The unit rows, which are the actual payload, existed
nowhere queryable: sheet_project holds per-project totals built from board/remaining.json, so a question
as ordinary as "what two-beds does Arada still claim under 2m" could not be answered from the graph.

Four tables, rebuilt from scratch on every run (the JSON files are the record; this is a projection):

  dev_sheet        one row per parsed sheet file      - who, when, how read, current or superseded
  dev_sheet_unit   one row per unit                   - the payload: code, type, size, price, project
  dev_doc          one row per captured document      - every PDF the listener pulled, parsed or not
  dev_link         one row per captured link          - URLs posted to the group

"Current" follows the same rule as the board strip (scripts/build_avail_index.py): units first, then
newest sheet date, then hand-verified over auto-read. A brochure parses to zero units and never
supersedes real inventory.

Run standalone, or let graph_build.py call it at the end of a graph run.
"""
import datetime as dt, glob, hashlib, json, os, re, sys

import duckdb

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AVAIL = os.path.join(ROOT, "data", "avail")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
CAPTURE = r"C:\Dev\azimuth-listener-naj\docs\developer_availability"
GROUP = "DEVELOPER AVAILABILITY"

SHEET_RX = re.compile(r"([a-z0-9]+)_(\d{4}-\d{2}-\d{2})(_auto)?\.json$")


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def jload(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def readlines(path):
    """One JSON object per line, bad lines skipped."""
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


# Documents the listener dropped BEFORE v33.1 started recording them. The log line carried no name, size or
# group - only a timestamp - so this is everything that can honestly be said about them. Each one is a hole
# someone has to close by hand: scroll the group to that minute and re-send the file.
# Group attributed from what the listener captured in the same second.
MISSED = [
    ("2026-09-07T13:57:00", "FN Realty Main Group"),
    ("2026-09-09T14:44:16", "DEVELOPER AVAILABILITY"),
    ("2026-09-09T15:17:43", "DEVELOPER AVAILABILITY"),
    ("2026-09-09T15:17:45", "DEVELOPER AVAILABILITY"),
    ("2026-09-04 or earlier", "unknown"),
    ("2026-09-04 or earlier", "unknown"),
]


def sheet_files():
    """Every parsed sheet in data/avail, keyed by file, with the developer and date from its name."""
    out = []
    for p in sorted(glob.glob(os.path.join(AVAIL, "*.json"))):
        b = os.path.basename(p)
        if b.startswith("_"):
            continue
        m = SHEET_RX.match(b)
        d = jload(p)
        if not isinstance(d, dict) or "projects" not in d:
            continue
        if not m:
            # Say so - for a SHEET only. A silent skip is how 43 Prestige One units sat unloaded for
            # three days; a warning on group_links.json every run would teach people to ignore it.
            print("  ! SKIPPED %s - a sheet whose name is not <developer>_<date>.json" % b)
            continue
        out.append({"file": b, "path": p, "dev": m.group(1), "date": m.group(2), "auto": bool(m.group(3)), "doc": d})
    return out


def pick_current(sheets):
    """(developer, project, file) triples that are the live view.

    Decided per PROJECT, not per developer. A developer posts partial sheets: Arada's 11 Sep sheet
    covered Inaura alone, and a per-developer rule made those 19 units "current" while a fifteen-
    project sheet two days older went to superseded. The newest sheet that LISTS a project wins for
    that project; units first, so a render booklet never wins anything."""
    best = {}
    for s in sheets:
        for p in s["doc"].get("projects") or []:
            n = len(p.get("units") or [])
            key = (s["dev"], p.get("p"))
            rank = (1 if n else 0, s["date"], 0 if s["auto"] else 1)
            if key not in best or rank > best[key][0]:
                best[key] = (rank, s["file"])
    return {(dev, proj, f) for (dev, proj), (_, f) in best.items()}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    sheets = sheet_files()
    current = pick_current(sheets)

    srows, urows = [], []
    for s in sheets:
        d, projects = s["doc"], s["doc"].get("projects") or []
        units = sum(len(p.get("units") or []) for p in projects)
        src = d.get("source_file")
        src = [src] if isinstance(src, str) else list(src or [])
        srows.append((s["file"], d.get("developer") or s["dev"].title(), s["date"], d.get("received"),
                      d.get("channel") or GROUP, d.get("extraction"), "auto" if s["auto"] else "verified",
                      "current" if any((s["dev"], p.get("p"), s["file"]) in current for p in projects) else "superseded",
                      len(projects), units, json.dumps(src, ensure_ascii=False)))
        for p in projects:
            for u in p.get("units") or []:
                u = list(u) + [None] * (5 - len(u))
                size, price = num(u[2]), num(u[3])
                urows.append((s["file"], d.get("developer") or s["dev"].title(), s["date"],
                              "current" if (s["dev"], p.get("p"), s["file"]) in current else "superseded",
                              p.get("p"), p.get("block"), p.get("master"), p.get("completion"), p.get("plan"),
                              str(u[0]) if u[0] is not None else None, u[1], size, price,
                              round(price / size, 2) if (size and price) else None, u[4]))

    # Which capture produced which sheet: extract_avail records a sha1 of the PDF it read.
    proc = jload(os.path.join(AVAIL, "_processed.json"), {}) or {}
    manual = {}
    for line in readlines(os.path.join(CAPTURE, "manual.jsonl")):
        manual[line.get("sha1")] = line
    drows = []
    if os.path.isdir(CAPTURE):
        for f in sorted(os.listdir(CAPTURE)):
            if not f.lower().endswith(".pdf"):
                continue
            fp = os.path.join(CAPTURE, f)
            raw = open(fp, "rb").read()
            h = hashlib.sha1(raw).hexdigest()
            r = proc.get(h) or {}
            # The listener prefixes each capture with the WhatsApp message timestamp in ms.
            mts = re.match(r"^(\d{13})_", f)
            posted = iso(int(mts.group(1)) / 1000) if mts else None
            drows.append((f, h, len(raw), posted, iso(os.path.getmtime(fp)),
                          r.get("out"), r.get("units"), bool(r), GROUP,
                          "manual" if h in manual else "listener", "held"))

    # A document the listener refused is a KNOWN HOLE, and the store has to carry it: a question answered
    # from a shelf with a gap in it should say so. v33.1 records these; anything skipped before that is
    # only a timestamp in a log, so it lands here with no name to show.
    for k in readlines(os.path.join(CAPTURE, "skipped.jsonl")):
        drows.append((k.get("file_name") or "(name not recorded)", None, k.get("bytes"), k.get("ts"),
                      k.get("captured_at"), None, None, False, k.get("group") or GROUP,
                      "listener", "skipped: " + (k.get("reason") or "unknown")))
    for k in MISSED:
        drows.append(("(name not recorded)", None, None, k[0], None, None, None, False, k[1],
                      "listener", "skipped: over the 20 MB cap in force at the time"))

    links = (jload(os.path.join(AVAIL, "group_links.json"), {}) or {}).get("links") or []
    lrows = [(l.get("ts"), l.get("group"), l.get("sender_name"), l.get("url"), l.get("host"),
              l.get("title"), (l.get("text") or "")[:300], l.get("captured_at"))
             for l in links if l.get("group") == GROUP]
    # links.jsonl in the capture folder is the primary record; group_links.json only keeps a rolling window.
    lj = os.path.join(CAPTURE, "links.jsonl")
    if os.path.exists(lj):
        have = {r[3] for r in lrows}
        for line in open(lj, encoding="utf-8"):
            try:
                l = json.loads(line)
            except Exception:
                continue
            if l.get("url") in have:
                continue
            have.add(l.get("url"))
            lrows.append((l.get("ts"), l.get("group") or GROUP, l.get("sender_name"), l.get("url"),
                          (l.get("url") or "").split("/")[2] if "//" in (l.get("url") or "") else None,
                          l.get("title"), (l.get("text") or "")[:300], l.get("captured_at")))

    # Launch offers: type-level starting prices from a brochure or a caption. Not a unit list - a developer
    # announcing a pre-launch gives you a price per bedroom count and a unit tally, never the unit codes.
    # Kept apart from dev_sheet_unit so nobody mistakes "from 1.9M" for a unit they can hold.
    orows = []
    for p in sorted(glob.glob(os.path.join(AVAIL, "offers", "*.json"))):
        o = jload(p) or {}
        for r in o.get("rows") or []:
            orows.append((os.path.basename(p), o.get("developer"), o.get("project"), o.get("master"),
                          o.get("posted"), o.get("channel"), o.get("sender"), o.get("source_kind"),
                          o.get("stage"), o.get("phase"), o.get("completion"), o.get("commission"),
                          r.get("unit_type"), r.get("configuration"), r.get("levels"), r.get("units"),
                          num(r.get("start_area_sqft")), num(r.get("start_price_aed")),
                          num(r.get("promo_price_aed")), r.get("promo"), o.get("source_note")))

    # A link that was checked by hand. Without this a URL sits in dev_link looking like inventory, and the
    # Imtiaz Virtual one is a vendor demo whose 34 projects do not exist - a broker could quote from it.
    for p in sorted(glob.glob(os.path.join(AVAIL, "offers", "_link_*.json"))):
        o = jload(p) or {}
        for i, r in enumerate(lrows):
            if r[3] == o.get("url"):
                lrows[i] = r + (o.get("verdict"), o.get("so_what"), o.get("checked"))
                break
        else:
            lrows.append((o.get("posted"), o.get("channel"), o.get("sender"), o.get("url"), None,
                          o.get("billed_as"), None, o.get("checked"),
                          o.get("verdict"), o.get("so_what"), o.get("checked")))
    lrows = [r if len(r) == 11 else r + (None, None, None) for r in lrows]

    con = duckdb.connect(DB)
    con.execute("""create or replace table dev_offer (offer_file varchar, developer varchar, project varchar, master varchar,
                   posted varchar, channel varchar, sender varchar, source_kind varchar, stage varchar, phase varchar,
                   completion varchar, commission varchar, unit_type varchar, configuration varchar, levels varchar,
                   units integer, start_area_sqft double, start_price_aed double, promo_price_aed double, promo varchar,
                   provenance varchar)""")
    con.executemany("insert into dev_offer values (" + ",".join("?" * 21) + ")", orows)
    con.execute("""create or replace table dev_sheet (sheet_file varchar primary key, developer varchar, sheet_date varchar,
                   received varchar, channel varchar, extraction varchar, read_as varchar, status varchar,
                   projects integer, units integer, source_files varchar)""")
    con.executemany("insert into dev_sheet values (?,?,?,?,?,?,?,?,?,?,?)", srows)
    con.execute("""create or replace table dev_sheet_unit (sheet_file varchar, developer varchar, sheet_date varchar,
                   status varchar, project varchar, block varchar, master varchar, completion varchar, payment_plan varchar,
                   unit_code varchar, unit_type varchar, size_sqft double, price_aed double, aed_per_sqft double, note varchar)""")
    con.executemany("insert into dev_sheet_unit values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", urows)
    con.execute("""create or replace table dev_doc (file_name varchar, sha1 varchar, bytes bigint, posted_at varchar,
                   captured_at varchar, parsed_into varchar, units integer, parsed boolean, channel varchar,
                   supplied_by varchar, state varchar)""")
    con.executemany("insert into dev_doc values (?,?,?,?,?,?,?,?,?,?,?)", drows)
    con.execute("""create or replace table dev_link (posted_at varchar, channel varchar, sender varchar, url varchar,
                   host varchar, title varchar, text varchar, captured_at varchar,
                   verdict varchar, so_what varchar, checked varchar)""")
    con.executemany("insert into dev_link values (?,?,?,?,?,?,?,?,?,?,?)", lrows)

    # A live view is what the app and any question should read: superseded sheets stay for the audit trail.
    con.execute("create or replace view v_dev_units as select * from dev_sheet_unit where status = 'current'")
    con.execute("""create or replace view v_dev_availability as
                   select developer, sheet_date, project, unit_type, count(*) units,
                          min(price_aed) from_aed, max(price_aed) to_aed,
                          round(avg(aed_per_sqft), 0) avg_aed_sqft
                   from v_dev_units group by 1,2,3,4 order by 1,3,4""")

    print("dev_sheet       %4d   (%d current)" % (len(srows), len(current)))
    print("dev_sheet_unit  %4d   (%d current)" % (len(urows), sum(1 for r in urows if r[3] == "current")))
    held = [r for r in drows if r[10] == "held"]
    gaps = [r for r in drows if r[10] != "held"]
    print("dev_doc         %4d   (%d on disk, %d parsed, %d NEVER DOWNLOADED)"
          % (len(drows), len(held), sum(1 for r in held if r[7]), len(gaps)))
    print("dev_link        %4d" % len(lrows))
    print("dev_offer       %4d   (%d project launches)" % (len(orows), len({r[0] for r in orows})))
    for g in gaps:
        print("   gap  %-22s %-24s %s" % (g[3] or "?", g[8], g[0]))
    for r in con.execute("select developer, sheet_date, count(*) from v_dev_units group by 1,2 order by 1").fetchall():
        print("  %-12s %-12s %5d units" % r)
    con.close()


if __name__ == "__main__":
    main()

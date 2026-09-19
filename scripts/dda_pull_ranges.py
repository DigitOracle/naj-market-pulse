"""dda_pull_ranges.py -- pull ONE big dataset with several processes at once, then merge the pieces.

A single stream is latency-bound (~200 rows/s, one 1,000-row page every ~5 s): dld_transactions is ~1.8M rows, three hours alone.
Once a dataset is sorted by a unique key (order_by, see dda_pull_all.py) every page is reproducible, so disjoint page ranges can be
fetched by separate processes and merged. The shared rate limiter (dda_api.py) keeps the total under the request budget.

    adopt  <entity/dataset>                       turn the running/stopped dda_pull_all checkpoint into range 1-P (pages already done)
    work   <entity/dataset> --order-by K --start A --end B [--samples 4,7]
                                                  fetch pages A..B, checkpointed per page; safe to re-run after a failure
    merge  <entity/dataset> --order-by K --last-page L --samples 4,7
                                                  ranges must cover 1..L exactly; re-fetch the sample pages and require an exact
                                                  match, then write the final file and set the manifest entry to ok

Files (prod dir):  <file>.range-A-B.part (one record a line, de-duplicated within the range), .state, .done.
"""
import argparse, glob, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dda_api as api
from dda_pull_all import fetch_page, parse_page, rec_hash, ORDER_V, CAT

ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod")
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def setup():
    c = api.cfg(); c["DDA_BASE_URL"] = c["DDA_BASE_URL_PROD"]; c["DDA_ENV"] = "PROD"
    for k in ("APP_ID", "SECURITY_APP_IDENTIFIER", "CLIENT_ID", "CLIENT_SECRET"): c["DDA_" + k] = c["DDA_PROD_" + k]
    return c


def base_url(c, ent, ds):
    return f"{c['DDA_BASE_URL']}/secure/ddads/openapi/1.0.0/{ent}/{ds}"


def range_paths(fn, a, b):
    stem = os.path.join(OUT, f"{fn}.range-{a}-{b}")
    return stem + ".part", stem + ".state", stem + ".done"


def ranges_of(fn):
    out = []
    for p in glob.glob(os.path.join(OUT, glob.escape(fn) + ".range-*-*.done")):
        m = re.search(r"\.range-(\d+)-(\d+)\.done$", p)
        out.append((int(m.group(1)), int(m.group(2)), p))
    return sorted(out)


def cmd_adopt(args):
    ent, ds = args.dataset.split("/"); fn = f"{ent}__{ds}.json"
    part, pstate = os.path.join(OUT, fn + ".part"), os.path.join(OUT, fn + ".part.state")
    st = json.load(open(pstate, encoding="utf-8"))
    if st.get("order_v") != ORDER_V or not st.get("order_by"): sys.exit("checkpoint is not an ordered (order_v 3) pull")
    p = int(st["page"]); rp, rs, rd = range_paths(fn, 1, p)
    os.replace(part, rp)
    n = sum(1 for _ in open(rp, encoding="utf-8"))
    json.dump({"order_v": ORDER_V, "order_by": st["order_by"], "page_size": st["page_size"], "page": p, "raw_rows": st.get("raw_rows", 0), "samples": {}}, open(rs, "w"))
    json.dump({"start": 1, "end": p, "last_page": p, "raw_rows": st.get("raw_rows", 0), "rows": n, "samples": {}, "order_by": st["order_by"],
               "page_size": st["page_size"]}, open(rd, "w"))
    os.remove(pstate)
    for extra in (os.path.join(OUT, fn + ".part.samples"),):
        if os.path.exists(extra): os.remove(extra)
    api.log(f"adopted {ent}/{ds}: pages 1-{p} ({n:,} rows, order_by={st['order_by']}, last page estimate {st.get('last_page_est')}); continue at page {p + 1}")


def cmd_work(args):
    ent, ds = args.dataset.split("/"); fn = f"{ent}__{ds}.json"
    part, pstate, done = range_paths(fn, args.start, args.end)
    if os.path.exists(done): api.log(f"range {args.start}-{args.end} already done"); return
    c = setup(); base = base_url(c, ent, ds); tok = api.token(c)
    sample_set = {int(x) for x in args.samples.split(",") if x}
    seen = set(); raw_rows = 0; samples = {}; first = args.start
    if os.path.exists(part) and os.path.exists(pstate):
        st = json.load(open(pstate, encoding="utf-8"))
        if st.get("order_by") == args.order_by and st.get("page_size") == args.page_size:
            with open(part, encoding="utf-8") as pf:
                for line in pf:
                    try: seen.add(rec_hash(json.loads(line)))
                    except Exception: break
            first = int(st["page"]) + 1; raw_rows = int(st.get("raw_rows", 0)); samples = st.get("samples", {})
            api.log(f"range {args.start}-{args.end}: resuming at page {first} with {len(seen):,} rows")
    if first == args.start:
        for p_ in (part, pstate):
            if os.path.exists(p_): os.remove(p_)
    end_hit = args.end
    for page in range(first, args.end + 1):
        code, raw, tok = fetch_page(c, base, page, args.page_size, args.order_by, tok, f"{ds} {args.start}-{args.end}")
        got, st_, nt_ = parse_page(code, raw)
        if got is None:
            api.log(f"range {args.start}-{args.end}: page {page} failed ({st_}: {nt_[:60]}); checkpoint kept, re-run to resume"); sys.exit(2)
        hs = [rec_hash(r) for r in got]; raw_rows += len(got); new = []
        for rec, h in zip(got, hs):
            if h in seen: continue
            seen.add(h); new.append(rec)
        if page in sample_set: samples[str(page)] = hs
        if new:
            with open(part, "a", encoding="utf-8") as pf:
                for rec in new: pf.write(json.dumps(rec, ensure_ascii=False) + chr(10))
        with open(pstate + ".tmp", "w", encoding="utf-8") as sf:
            json.dump({"order_v": ORDER_V, "order_by": args.order_by, "page_size": args.page_size, "page": page, "raw_rows": raw_rows, "samples": samples}, sf)
        os.replace(pstate + ".tmp", pstate)
        if len(got) < args.page_size and page < args.end: end_hit = page; break     # the dataset ended inside this range
        if page % 25 == 0: api.log(f"range {args.start}-{args.end}: page {page} ({len(seen):,} rows)")
    json.dump({"start": args.start, "end": end_hit, "last_page": end_hit, "raw_rows": raw_rows, "rows": len(seen), "samples": samples,
               "order_by": args.order_by, "page_size": args.page_size}, open(done + ".tmp", "w"))
    os.replace(done + ".tmp", done)
    api.log(f"range {args.start}-{args.end} done: {len(seen):,} rows")


def cmd_merge(args):
    ent, ds = args.dataset.split("/"); fn = f"{ent}__{ds}.json"; key = f"{ent}/{ds}"
    rngs = ranges_of(fn)
    if not rngs: sys.exit("no finished ranges")
    expect = 1
    for a, b, _ in rngs:
        if a != expect: sys.exit(f"ranges do not cover the dataset: gap or overlap at page {expect} (next range starts at {a})")
        expect = b + 1
    if expect - 1 != args.last_page: sys.exit(f"ranges end at page {expect - 1}, expected {args.last_page}")
    infos = [json.load(open(p, encoding="utf-8")) for _, _, p in rngs]
    if any(i.get("order_by") != args.order_by or i.get("page_size") != args.page_size for i in infos): sys.exit("ranges were pulled with a different order_by / page size")
    stored = {}
    for i in infos: stored.update(i.get("samples", {}))
    def records():
        seen = set()
        for a, b, _ in rngs:
            with open(range_paths(fn, a, b)[0], encoding="utf-8") as pf:
                for line in pf:
                    rec = json.loads(line); h = rec_hash(rec)
                    if h in seen: continue
                    seen.add(h); yield rec
    n = 0; cols = set()
    for rec in records():
        n += 1
        if n <= 200: cols.update((rec or {}).keys())
    c = setup(); base = base_url(c, ent, ds); tok = api.token(c)
    bad = []
    for p_ in sorted({int(x) for x in args.samples.split(",") if x}):
        code, raw, tok = fetch_page(c, base, p_, args.page_size, args.order_by, tok, ds)
        got, st_, nt_ = parse_page(code, raw)
        if got is None: bad.append(f"page {p_}: {st_}"); continue
        if str(p_) not in stored: bad.append(f"page {p_} was not captured by any range"); continue
        if [rec_hash(r) for r in got] != stored[str(p_)]: bad.append(f"page {p_} changed")
    mp = os.path.join(OUT, "MANIFEST.json")
    cat = next(r for r in json.load(open(CAT, encoding="utf-8"))["rows"] if r["entity"] == ent and r["dataset"] == ds)
    raw_rows = sum(i.get("raw_rows", 0) for i in infos)
    entry = {"id": cat["id"], "title": cat["title"], "entity": ent, "dataset": ds, "rows": n, "columns": len(cols), "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "seconds": 0, "pages": args.last_page, "last_page": args.last_page, "raw_rows": raw_rows, "order_by": args.order_by}
    if bad:
        entry.update({"status": "unstable", "file": "", "selfcheck": "mismatch", "ended_by": "unstable", "note": "self-check failed: " + "; ".join(bad)})
    else:
        tmp = os.path.join(OUT, fn + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            head = {"id": cat["id"], "title": cat["title"], "organization": cat.get("organization", ""), "entity": ent, "dataset": ds, "env": "prod",
                    "pulled": entry["pulled"], "rows": n, "columns": sorted(cols), "order_by": args.order_by}
            f.write(json.dumps(head, ensure_ascii=False)[:-1] + ', "results": [')
            first = True
            for rec in records():
                f.write(("" if first else ",") + json.dumps(rec, ensure_ascii=False)); first = False
            f.write("]}")
        os.replace(tmp, os.path.join(OUT, fn))
        entry.update({"status": "ok", "file": fn, "selfcheck": "ok", "ended_by": "last_page", "note": "pulled as parallel page ranges, merged"})
        for a, b, p in rngs:
            for x in range_paths(fn, a, b):
                if os.path.exists(x): os.remove(x)
    man = json.load(open(mp, encoding="utf-8")); man[key] = entry
    tmp = mp + f".{os.getpid()}.tmp"; json.dump(man, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, mp)
    api.log(f"merge {key}: {entry['status']} rows={n:,} raw_rows={raw_rows:,}" + (f" ({entry['note'][:80]})" if bad else ""))
    if bad: sys.exit(3)


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("adopt", "work", "merge"):
        sp = sub.add_parser(name); sp.add_argument("dataset")
        if name != "adopt":
            sp.add_argument("--order-by", required=True); sp.add_argument("--page-size", type=int, default=1000); sp.add_argument("--samples", default="")
        if name == "work": sp.add_argument("--start", type=int, required=True); sp.add_argument("--end", type=int, required=True)
        if name == "merge": sp.add_argument("--last-page", type=int, required=True)
    args = ap.parse_args()
    {"adopt": cmd_adopt, "work": cmd_work, "merge": cmd_merge}[args.cmd](args)


if __name__ == "__main__":
    main()

"""Copy Azimuth's edge-only state back to disk every night, so nothing lives only in Cloudflare's key-value store.

Data Spine Phase 1 (13 Sep 2026). The 13 Sep inventory found state that exists nowhere but the edge: the merged market record
(mkt_latest - the daily build rewrites public/pulse.json without cityLife, and the block survives only because /ingest_market
merges into the previous value), news and feed history, polls and her answers, the assistant's ledgers, chat ingest, the
outbox, and the style photos she sent. A bad deploy, a wrong delete or an overwritten key would lose them for good.

Reads both namespaces - meeting-capture (Kendall) and azimuth-2 (Naj) - through the Cloudflare REST API with the deploy token
in C:\\Users\\kwils\\.cf_token. Read calls only; nothing is written to Cloudflare. Two kinds of key are skipped on purpose:
  credentials   anything named like a token, auth, session or secret - a backup must not become a second copy of a credential
  rebuildable   images, 3D models and videos this repo pushes (img_*, sky_*, vid_*) - the build scripts regenerate them;
                her style photos (img_style*) and the generated plates (img_plate*) are edge-only and ARE kept
Writes data/edge_backup/<date>/<instance>/<family>.jsonl (one {"key","meta","text"|"b64"|"blob"} per line) + MANIFEST.json
with key counts, bytes and a sha256 per file. Binary values of 64 KB and over (her photos, the plates) are stored once in
data/edge_backup/blobs/<sha256> and referenced by hash, so a night costs megabytes, not a fresh copy of every photo.
Keeps 14 days of folders and the blobs they refer to. data/ is git-ignored, so none of this can reach GitHub.
Usage: python scripts/edge_backup.py [--keep 14] [--list]
Exit 0 = backed up; 1 = error (the run ledger reports it).
"""
import argparse, base64, datetime as dt, hashlib, json, os, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "edge_backup")
TOKEN_FILE = r"C:\Users\kwils\.cf_token"
WRANGLER = r"C:\Dev\azimuth-worker\wrangler.toml"
API = "https://api.cloudflare.com/client/v4/accounts/%s/storage/kv/namespaces/%s"

CREDENTIAL_RX = re.compile(r"(token|auth|secret|oauth|session|cookie|apikey|api_key|password|refresh|esri_tok)", re.I)
REBUILDABLE_RX = re.compile(r"^(img_(?!style|plate|ct_img_style|at_img_style|ct_img_plate|at_img_plate)|sky_|vid_|vidposter_)")
MAX_VALUE = 8 * 1024 * 1024
BLOBS = os.path.join(OUT, "blobs")           # binary values of 64 KB and over, stored once by sha256 and referenced by hash
BLOB_MIN = 64 * 1024
PACE = 0.22                                  # the account API allows 1,200 calls per 5 minutes; stay well under it


def config():
    w = open(WRANGLER, encoding="utf-8").read()
    acct = re.search(r'account_id\s*=\s*"([0-9a-f]+)"', w).group(1)
    ids = re.findall(r'kv_namespaces\s*=\s*\[\s*\{\s*binding\s*=\s*"MEETINGS",\s*id\s*=\s*"([0-9a-f]+)"', w)
    return acct, dict(zip(["meeting-capture", "azimuth-2"], ids))       # top-level block first, then [env.azimuth2]


def call(url, token, method="GET", body=None, raw=False, tries=4):
    for k in range(tries):
        req = urllib.request.Request(url, data=body, method=method,
                                     headers={"Authorization": "Bearer " + token, "User-Agent": "najma-market-pulse/1.0",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and k < tries - 1:
                time.sleep(5 * (k + 1))
                continue
            raise
        except urllib.error.URLError:
            if k < tries - 1:
                time.sleep(5 * (k + 1))
                continue
            raise


def list_keys(acct, nid, token):
    keys, cursor = [], ""
    while True:
        url = API % (acct, nid) + "/keys?limit=1000" + ("&cursor=" + urllib.parse.quote(cursor) if cursor else "")
        d = call(url, token)
        keys += d.get("result") or []
        cursor = (d.get("result_info") or {}).get("cursor") or ""
        if not cursor:
            return keys


def family(name):
    m = re.match(r"img_(ct_|at_)?img_([a-z]+)", name) or re.match(r"img_([a-z]+)", name)
    if name.startswith("img_") and m:
        return "img_" + m.groups()[-1]
    m = re.match(r"([A-Za-z]+_?)", name)
    return m.group(1) if m else "other"


def wanted(name):
    if CREDENTIAL_RX.search(name):
        return False, "credential"
    if REBUILDABLE_RX.match(name):
        return False, "rebuildable"
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=14)
    ap.add_argument("--list", action="store_true", help="count what would be kept and skipped, fetch no values")
    a = ap.parse_args()
    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    acct, spaces = config()
    day = dt.date.today().isoformat()
    root = os.path.join(OUT, day)
    manifest = {"taken": dt.datetime.now().isoformat(timespec="seconds"), "instances": {}}

    for inst, nid in spaces.items():
        keys = list_keys(acct, nid, token)
        keep = [k for k in keys if wanted(k["name"])[0]]
        skipped = {}
        for k in keys:
            ok, why = wanted(k["name"])
            if not ok:
                skipped[why] = skipped.get(why, 0) + 1
        info = {"keys_total": len(keys), "kept": len(keep), "skipped": skipped, "families": {}, "too_large": 0, "failed": 0}
        if a.list:
            fams = {}
            for k in keep:
                fams[family(k["name"])] = fams.get(family(k["name"]), 0) + 1
            info["families"] = fams
            manifest["instances"][inst] = info
            continue
        os.makedirs(os.path.join(root, inst), exist_ok=True)
        handles = {}
        try:
            for k in keep:
                name = k["name"]
                try:
                    b = call(API % (acct, nid) + "/values/" + urllib.parse.quote(name, safe=""), token, raw=True)
                except urllib.error.HTTPError as e:
                    if e.code == 404:                        # deleted between the listing and the read
                        continue
                    info["failed"] += 1
                    continue
                time.sleep(PACE)
                if len(b) > MAX_VALUE:
                    info["too_large"] += 1
                    continue
                rec = {"key": name, "meta": k.get("metadata"), "expiration": k.get("expiration")}
                try:
                    rec["text"] = b.decode("utf-8")
                except UnicodeDecodeError:
                    if len(b) >= BLOB_MIN:                    # photos rarely change: store each once, by content
                        sha = hashlib.sha256(b).hexdigest()
                        blob = os.path.join(BLOBS, sha[:2], sha)
                        if not os.path.exists(blob):
                            os.makedirs(os.path.dirname(blob), exist_ok=True)
                            with open(blob, "wb") as fh:
                                fh.write(b)
                        rec["blob"] = sha
                        rec["bytes"] = len(b)
                    else:
                        rec["b64"] = base64.b64encode(b).decode()
                fam = family(name)
                if fam not in handles:
                    handles[fam] = open(os.path.join(root, inst, fam.rstrip("_") + ".jsonl"), "w", encoding="utf-8")
                handles[fam].write(json.dumps(rec, ensure_ascii=False) + "\n")
                info["families"][fam] = info["families"].get(fam, 0) + 1
        finally:
            for h in handles.values():
                h.close()
        files = {}
        for fn in sorted(os.listdir(os.path.join(root, inst))):
            p = os.path.join(root, inst, fn)
            files[fn] = {"bytes": os.path.getsize(p), "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()}
        info["files"] = files
        manifest["instances"][inst] = info

    if a.list:
        print(json.dumps(manifest, indent=1, ensure_ascii=False))
        return 0
    json.dump(manifest, open(os.path.join(root, "MANIFEST.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    folders = sorted(d for d in os.listdir(OUT) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d))
    for old in folders[:-a.keep] if len(folders) > a.keep else []:
        shutil.rmtree(os.path.join(OUT, old), ignore_errors=True)
    # a blob no kept day refers to any more is garbage
    live = set()
    for d in sorted(x for x in os.listdir(OUT) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x)):
        for dirpath, _, fns in os.walk(os.path.join(OUT, d)):
            for fn in fns:
                if fn.endswith(".jsonl"):
                    with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                        live.update(m.group(1) for m in re.finditer(r'"blob": "([0-9a-f]{64})"', fh.read()))
    if os.path.isdir(BLOBS):
        for dirpath, _, fns in os.walk(BLOBS):
            for fn in fns:
                if fn not in live:
                    os.remove(os.path.join(dirpath, fn))

    for inst, info in manifest["instances"].items():
        size = sum(f["bytes"] for f in info.get("files", {}).values())
        print("edge backup %s: %d of %d keys kept (%s skipped), %d families, %.1f MB, %d failed, %d too large"
              % (inst, sum(info["families"].values()), info["keys_total"],
                 ", ".join("%d %s" % (v, k) for k, v in info["skipped"].items()) or "none",
                 len(info["families"]), size / 1e6, info["failed"], info["too_large"]))
    failed = sum(i["failed"] for i in manifest["instances"].values())
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("edge backup error:", str(e)[:200])
        sys.exit(1)

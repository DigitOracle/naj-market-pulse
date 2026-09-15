"""Najma — weekly DLD open-data fetch.

Pulls transactions (trailing 56 days) and Ejari rents (trailing 28 days) from the
official DLD open-data gateway — the same source as the manual CSV download, no
captcha, READS ONLY. Writes date-stamped CSVs into data/ with the exact column
set the build_pulse.py readers expect.

The register back-fills: each weekly run re-pulls its whole trailing window and
dedupes, so late registrations are picked up rather than missed.

Run:  python scripts/fetch_dld.py
Env:  DLD_TX_DAYS (default 56) · DLD_RENT_DAYS (default 28)
"""
import csv, glob, json, os, sys, time
import requests
from datetime import date, timedelta

BASE = "https://gateway.dubailand.gov.ae/open-data/"
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/json",
    "Referer": "https://dubailand.gov.ae/en/open-data/real-estate-data/",
}
DATA = os.environ.get("PULSE_DATA_DIR", "data")
PAGE = 2000

# Column sets matching the manual CSV downloads (what build_pulse.py reads)
TX_COLS = ["TRANSACTION_NUMBER", "INSTANCE_DATE", "GROUP_EN", "PROCEDURE_EN", "IS_OFFPLAN_EN",
           "IS_FREE_HOLD_EN", "USAGE_EN", "AREA_EN", "PROP_TYPE_EN", "PROP_SB_TYPE_EN",
           "TRANS_VALUE", "PROCEDURE_AREA", "ACTUAL_AREA", "ROOMS_EN", "PARKING",
           "NEAREST_METRO_EN", "NEAREST_MALL_EN", "NEAREST_LANDMARK_EN", "TOTAL_BUYER",
           "TOTAL_SELLER", "MASTER_PROJECT_EN", "PROJECT_EN"]
RENT_COLS = ["REGISTRATION_DATE", "START_DATE", "END_DATE", "VERSION_EN", "AREA_EN",
             "CONTRACT_AMOUNT", "ANNUAL_AMOUNT", "IS_FREE_HOLD_EN", "ACTUAL_AREA",
             "PROP_TYPE_EN", "PROP_SUB_TYPE_EN", "ROOMS", "USAGE_EN", "NEAREST_METRO_EN",
             "NEAREST_MALL_EN", "NEAREST_LANDMARK_EN", "PARKING", "TOTAL_PROPERTIES",
             "MASTER_PROJECT_EN", "PROJECT_EN"]


_session = requests.Session()


def post(endpoint, payload, tries=8):
    """One POST to the gateway; retries with backoff. Read-only, always. The gateway is slow
    and occasionally times out on a paged window — retry generously before giving up."""
    for attempt in range(tries):
        try:
            r = _session.post(BASE + endpoint, headers=HDR, json=payload, timeout=150)
            if r.status_code == 200:
                d = r.json()
                if d.get("response") is not None:
                    return d["response"]["result"]
            print(f"  {endpoint} attempt {attempt + 1}: HTTP {r.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"  {endpoint} attempt {attempt + 1}: {e}", file=sys.stderr)
        time.sleep(min(30, 4 * (attempt + 1)))
    raise RuntimeError(f"gateway failed: {endpoint}")


def mdy(d):
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def tx_payload(frm, to, take="1", skip="0"):
    return {"P_FROM_DATE": frm, "P_TO_DATE": to, "P_GROUP_ID": "", "P_IS_OFFPLAN": "",
            "P_IS_FREE_HOLD": "", "P_AREA_ID": "", "P_USAGE_ID": "", "P_PROP_TYPE_ID": "",
            "P_TAKE": take, "P_SKIP": skip, "P_SORT": ""}


def rent_payload(frm, to, take="1", skip="0"):
    return {"P_FROM_DATE": frm, "P_TO_DATE": to, "P_DATE_TYPE": "1", "P_IS_FREE_HOLD": "",
            "P_VERSION": "", "P_AREA_ID": "", "P_USAGE_ID": "", "P_PROP_TYPE_ID": "",
            "P_TAKE": take, "P_SKIP": skip, "P_SORT": ""}


def pull(endpoint, make_payload, windows, cols, key_fn, max_passes=1):
    """Pull every window paged, dedupe by key_fn, return list of dicts limited to cols. With max_passes > 1 a window is
    paged again until a whole pass adds no new key; a window whose unique keys reach the reported total stops at once.
    The log line per window says how many keys each pass added."""
    rows, seen = [], set()
    for frm, to in windows:
        probe = post(endpoint, make_payload(mdy(frm), mdy(to)))
        total = probe[0]["TOTAL"] if probe else 0
        start, added = len(seen), []
        for p in range(max_passes):
            n = 0
            for skip in range(0, total, PAGE):
                page = post(endpoint, make_payload(mdy(frm), mdy(to), take=str(PAGE), skip=str(skip)))
                for r in page:
                    k = key_fn(r)
                    if k in seen:
                        continue
                    seen.add(k)
                    n += 1
                    rows.append({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
            added.append(n)
            if len(seen) - start >= total or (p > 0 and n == 0):
                break
        print(f"  {endpoint} {frm} -> {to}: {total} rows reported, {len(seen) - start} unique; "
              f"new per pass {'/'.join(str(x) for x in added)}")
    return rows


def windows(days_back, step):
    """Split the trailing window into <=step-day chunks (deep pagination drifts on the API)."""
    end = date.today()
    start = end - timedelta(days=days_back)
    out, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=step), end)
        out.append((cur, nxt))
        cur = nxt
    return out


def known_transactions(days):
    """Transaction numbers the last three window pulls held, for the days today's window fully covers (its first day is only
    partly inside the window), up to yesterday."""
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    today = date.today().isoformat()
    files = sorted(p for p in glob.glob(os.path.join(DATA, "transactions-20??-??-??*.csv")) if today not in os.path.basename(p))[-3:]
    keys = set()
    for p in files:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if since <= (r.get("INSTANCE_DATE") or "")[:10] < today:
                    keys.add(r["TRANSACTION_NUMBER"])
    return keys


def complete_transactions(tx, days, retries=2, wait=120):
    """A pull short of transactions the last pulls held is pulled again, and the union kept, before anything is written.

    14 Sep 2026: the 06:30 pull lacked 1,496 transactions the previous pull held; the vanish contract in register_versions.py
    held it, so the pulse stayed a day old. The same windows pulled again at 14:40 held all but one of them, and 99.8% of the
    portal register's copy against 95.0% for the morning pull. A second pass inside the same run had added nothing, so the
    shortfall belongs to a pull as a whole: wait, pull again, keep both. The limit is the contract's: 0.2%, at least 50."""
    known = known_transactions(days)
    for attempt in range(retries + 1):
        have = {r["TRANSACTION_NUMBER"] for r in tx}
        missing, limit = len(known - have), max(50, 0.002 * len(known))
        print(f"  transactions: {missing} of {len(known)} held by the last pulls are missing (limit {limit:.0f})")
        if missing <= limit or attempt == retries:
            return tx
        print(f"  pulling the transaction windows again in {wait}s (attempt {attempt + 2} of {retries + 1})")
        time.sleep(wait)
        again = pull("transactions", tx_payload, windows(days, 14), TX_COLS, key_fn=lambda r: r["TRANSACTION_NUMBER"])
        tx = tx + [r for r in again if r["TRANSACTION_NUMBER"] not in have]
    return tx


def write_csv(name, cols, rows):
    os.makedirs(DATA, exist_ok=True)
    stamp = date.today().isoformat()
    path = os.path.join(DATA, f"{name}-{stamp}.csv")
    if os.path.exists(path) and os.environ.get("DLD_OVERWRITE") != "1":
        # never clobber a manually captured file of the same date
        path = os.path.join(DATA, f"{name}-{stamp}-api.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}: {len(rows)} rows")
    return path


def main():
    tx_days = int(os.environ.get("DLD_TX_DAYS", "56"))
    rent_days = int(os.environ.get("DLD_RENT_DAYS", "28"))

    tx = pull("transactions", tx_payload, windows(tx_days, 14), TX_COLS,
              key_fn=lambda r: r["TRANSACTION_NUMBER"])
    tx = complete_transactions(tx, tx_days)
    write_csv("transactions", TX_COLS, tx)

    rents = pull("rents", rent_payload, windows(rent_days, 6), RENT_COLS,
                 key_fn=lambda r: json.dumps([r.get(c) for c in RENT_COLS], ensure_ascii=False))
    write_csv("rents", RENT_COLS, rents)


if __name__ == "__main__":
    main()

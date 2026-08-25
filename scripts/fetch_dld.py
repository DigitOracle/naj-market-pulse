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
import csv, json, os, sys, time
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


def post(endpoint, payload, tries=5):
    """One POST to the gateway; retries with backoff. Read-only, always."""
    for attempt in range(tries):
        try:
            r = _session.post(BASE + endpoint, headers=HDR, json=payload, timeout=120)
            if r.status_code == 200:
                d = r.json()
                if d.get("response") is not None:
                    return d["response"]["result"]
            print(f"  {endpoint} attempt {attempt + 1}: HTTP {r.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"  {endpoint} attempt {attempt + 1}: {e}", file=sys.stderr)
        time.sleep(4 * (attempt + 1))
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


def pull(endpoint, make_payload, windows, cols, key_fn):
    """Pull every window paged, dedupe by key_fn, return list of dicts limited to cols."""
    rows, seen = [], set()
    for frm, to in windows:
        probe = post(endpoint, make_payload(mdy(frm), mdy(to)))
        total = probe[0]["TOTAL"] if probe else 0
        print(f"  {endpoint} {frm} -> {to}: {total} rows")
        for skip in range(0, total, PAGE):
            page = post(endpoint, make_payload(mdy(frm), mdy(to), take=str(PAGE), skip=str(skip)))
            for r in page:
                k = key_fn(r)
                if k in seen:
                    continue
                seen.add(k)
                rows.append({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
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
    write_csv("transactions", TX_COLS, tx)

    rents = pull("rents", rent_payload, windows(rent_days, 6), RENT_COLS,
                 key_fn=lambda r: json.dumps([r.get(c) for c in RENT_COLS], ensure_ascii=False))
    write_csv("rents", RENT_COLS, rents)


if __name__ == "__main__":
    main()

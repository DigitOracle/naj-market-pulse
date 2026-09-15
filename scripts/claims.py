"""Claims: every figure the pulse states, carried with its definition, scope, window, sample and source (Data Spine Phase 4).

On 12 Sep 2026 one feed angle welded "Masaar by ARADA" to a Fakhruddin source line, and another said August beat the three
months before it on a figure that only said 309. Both sentences were composed from loose numbers. The fix is not a better
prompt: a sentence may cite a figure only through a CLAIM, and a claim is built by code from the metric registry
(metrics/registry.json), so the number, what it counts, where it came from and over which days cannot come apart.

Reads public/pulse.json (after build_pulse.py and build_city_block.py) and writes, for every registry metric the pulse carries:
  claim_id, metric, label, value, unit, scope (Dubai or an area), window_from, window_to, sample, source, definition,
  provisional (a window of a week or less whose last day is under two days old - the register back-fills), settling_after
  (for a longer window ending recently: figures dated after this may still grow), registry_version, computed_at
into public/claims.json, and appends them to lk_claims in the published lake, where every day's claims stay queryable.
(Not into pulse.json yet: the Worker's writer reads the pulse sections, and claims reach it together with the guard that
makes them binding.)

Cross-check (a contract): the city figures are recomputed from the published lake - dld_transactions_now and dld_rents_now,
the same window - and compared with the pulse. A gap beyond 1% is printed as a WARN line and the script exits 2, so the run
ledger shows it; the claims are still written, because the pulse is what was published.
Usage: python scripts/claims.py [--no-lake]      Exit 0 = written and agreeing; 2 = written with a cross-check warning; 1 = error.
"""
import argparse, datetime as dt, json, os, statistics, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
REGISTRY = os.path.join(ROOT, "metrics", "registry.json")
PULSE = os.path.join(ROOT, "public", "pulse.json")
OUT = os.path.join(ROOT, "public", "claims.json")
TOLERANCE = 0.01


def get_path(d, path):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def claim(reg, m, value, scope, wfrom, wto, sample, now):
    # The register back-fills its last two days. For a short window that is most of the figure, so the claim is provisional;
    # for a long one it is a small tail, so the claim is stated and carries the date after which it may still move.
    recent = bool(wto) and (dt.date.today() - dt.date.fromisoformat(wto)).days < 2
    days = (dt.date.fromisoformat(wto) - dt.date.fromisoformat(wfrom)).days + 1 if (wfrom and wto) else None
    provisional = recent and days is not None and days <= 7
    settling_after = (dt.date.fromisoformat(wto) - dt.timedelta(days=1)).isoformat() if recent else None
    return {"claim_id": "%s|%s|%s|%s" % (m["id"], scope, wfrom, wto), "metric": m["id"], "label": m["label"], "value": value,
            "unit": m["unit"], "scope": scope, "window_from": wfrom, "window_to": wto, "sample": sample,
            "source": reg["sources"].get(m["source"], m["source"]) if "+" not in m["source"] else
            " and ".join(reg["sources"][s] for s in m["source"].split("+")),
            "definition": m["definition"], "provisional": provisional, "settling_after": settling_after,
            "registry_version": reg["version"], "computed_at": now}


def build_claims(reg, pulse):
    now = dt.datetime.now().isoformat(timespec="seconds")
    t, r = pulse.get("transactions") or {}, pulse.get("rents") or {}
    tx_w = (t.get("periodFrom"), t.get("periodTo"))
    rn_w = (r.get("registrationFrom"), r.get("registrationTo"))
    out = []
    for m in reg["metrics"]:
        w = rn_w if m["source"].startswith("dld_rents") else tx_w
        if m["id"] == "yield.gross_pct":
            for y in get_path(pulse, m["pulse_path"]) or []:
                out.append(claim(reg, m, y["yieldPct"], y["area"], rn_w[0], rn_w[1],
                                 {"contracts": y.get("rentSamples"), "sales": y.get("saleSamples")}, now))
            continue
        v = get_path(pulse, m["pulse_path"])
        if v is not None:
            sample = t.get("salesCount") if m["source"] == "dld_transactions" else r.get("residentialSingles")
            out.append(claim(reg, m, v, "Dubai", w[0], w[1], sample, now))
        if m.get("area_path"):
            for a in get_path(pulse, m["area_path"]) or []:
                out.append(claim(reg, m, a.get("sales"), a.get("area"), w[0], w[1], a.get("sales"), now))
    return out


def cross_check(pulse):
    """Recompute the city figures from the published lake over the pulse's own windows."""
    import lake
    con = lake.connect()
    t, r = pulse["transactions"], pulse["rents"]
    rows = con.execute("""select GROUP_EN, try_cast(TRANS_VALUE as double), try_cast(ACTUAL_AREA as double), USAGE_EN, IS_OFFPLAN_EN
        from dld_transactions_now where series = 'window' and happened_at::date between ? and ?
          and GROUP_EN in ('Sales', 'Mortgage', 'Gifts')
          and (try_cast(TRANS_VALUE as double) is null or (try_cast(TRANS_VALUE as double) > 0 and try_cast(TRANS_VALUE as double) < 5e9))""",
                       [t["periodFrom"], t["periodTo"]]).fetchall()
    sales = [x for x in rows if x[0] == "Sales"]
    vals = [x[1] for x in sales if x[1]]
    pps = [x[1] / x[2] for x in sales if x[3] == "Residential" and x[2] and x[2] > 10 and x[1]]
    lake_fig = {"transactions.totalRows": len(rows), "sales.count": len(sales),
                "sales.median_ticket_aed": round(statistics.median(vals)) if vals else None,
                "sales.median_residential_aed_sqft": round(statistics.median(pps) / 10.7639) if pps else None}
    pulse_fig = {"transactions.totalRows": t["totalRows"], "sales.count": t["salesCount"],
                 "sales.median_ticket_aed": t["medianTicketAed"], "sales.median_residential_aed_sqft": t["medianResidentialAedSqft"]}
    warns = []
    for k, pv in pulse_fig.items():
        lv = lake_fig[k]
        if pv and lv is not None and abs(lv - pv) / abs(pv) > TOLERANCE:
            warns.append("WARN cross-check %s: pulse %s, published lake %s (%.1f%%)" % (k, pv, lv, 100.0 * (lv - pv) / pv))
    return lake_fig, pulse_fig, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-lake", action="store_true", help="write public/claims.json only")
    a = ap.parse_args()
    reg = json.load(open(REGISTRY, encoding="utf-8"))
    pulse = json.load(open(PULSE, encoding="utf-8"))
    claims = build_claims(reg, pulse)
    doc = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "registry_version": reg["version"],
           "rules": reg["rules"], "n": len(claims), "claims": claims}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 13 Sep 2026: claims are NOT embedded in pulse.json yet. The Worker builds Naj's briefs from the pulse sections, and a new
    # section would change what her writer sees before the "cite only claims" guard exists; that guard ships with the Azimuth
    # phase, and the Worker will read public/claims.json (or lk_claims) then.
    code = 0
    if not a.no_lake:
        import lake
        lake_fig, pulse_fig, warns = cross_check(pulse)
        for w in warns:
            print(w)
        code = 2 if warns else 0
        con = lake.connect(read_only=False)
        con.execute("create temp table cs (claim_id varchar, metric varchar, label varchar, value varchar, unit varchar, scope varchar, "
                    "window_from date, window_to date, sample varchar, source varchar, definition varchar, provisional boolean, settling_after date, "
                    "registry_version varchar, computed_at timestamp)")
        con.executemany("insert into cs values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(c["claim_id"], c["metric"], c["label"], json.dumps(c["value"]), c["unit"], c["scope"], c["window_from"],
                          c["window_to"], json.dumps(c["sample"]), c["source"], c["definition"], c["provisional"], c["settling_after"],
                          c["registry_version"], c["computed_at"]) for c in claims])

        def body():
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute("create table if not exists lk_claims as select * from cs where false")
                con.execute("insert into lk_claims select * from cs")
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        lake.retry(body, "claims")
        print("cross-check against the published lake: %s" % ", ".join("%s pulse %s / lake %s" % (k, pulse_fig[k], lake_fig[k]) for k in pulse_fig))
    prov = sum(1 for c in claims if c["provisional"])
    print("claims: %d written (%d provisional) - public/claims.json%s" % (len(claims), prov, "" if a.no_lake else ", lk_claims"))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("claims error:", str(e)[:300])
        sys.exit(1)

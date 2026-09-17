"""The Najma chains as declared steps: run in order, record every exit code, skip what depends on a failure, tell Kendall.

Data Spine Phase 1 (13 Sep 2026). daily_refresh.ps1 used to run top to bottom with ErrorActionPreference Continue and read
one exit code (the listener check). When fetch_dld failed, build_pulse rebuilt from the previous capture and the result was
pushed as if fresh; when a build step failed, its push still ran; and the government loads, the realness gate, the golden
check and the graph export ran only when someone remembered. Each chain below is the old script's order, with:

  needs      a step whose inputs did not come through is SKIPPED, never run on stale or broken files
  contracts  the availability volume check, the governed-API contract and the portal contract hold feeds instead of failing
  ledger     data/runs/<date>/<chain>_<HHMMSS>.json records every step (run_ledger.py)
  one line   Kendall gets one WhatsApp line when anything failed, was held or needs his eye (notify_owner.py); never Naj

Chains and their scheduled tasks:
  daily         06:30 daily   Najma_Daily_Refresh   pulse, heat map, availability, cards, truth store, golden gate + export
  sweep         2-hourly      Najma_Avail_Sweep     new sheets -> volume check -> index, remaining, unit mix, search; twin audit
  gov-weekly    Fri 03:00     Najma_Gov_Weekly      governed API pull -> load -> contract -> realness gate; portal contract
  edge-nightly  02:30 daily   Najma_Edge_Backup     Azimuth's edge-only state copied to disk (edge_backup.py)

Usage: python scripts/refresh_runner.py <chain> [--dry] [--only step,step] [--no-ack] [--no-notify]
Exit 0 = no step failed (holds and warnings included); 1 = a step failed.
"""
import argparse, datetime as dt, glob, json, os, re, subprocess, sys, time, urllib.error, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import notify_owner                     # noqa: E402
from run_ledger import Run              # noqa: E402

PY = sys.executable
AZ2 = "https://azimuth-2.digitalchemy.workers.dev"
NAJ_ENV = r"C:\Dev\azimuth-listener-naj\.env"
SUCCESS = ("ok", "warn", "held")


RETRY_WAIT = 30    # seconds before a push is tried again
JOINED_REGISTERS = ("transactions,projects,lkp_areas,oa_service_charges,building_summary_information,"
                    "estimated_population_by_community,bus_network_coverage,customers_master_data,"   # read by register_joins.py
                    "buildings,units,land_registry")                                                   # read by identity_match.py
ALERTS_SENT = os.path.join(ROOT, "data", "runs", "alerts_sent.jsonl")
REPEAT_HOURS = 6   # the same failure again inside this many hours is logged, not re-sent


def alert_key(run):
    """What an alert is about: which steps failed, warned or were held. The note and the time are left out."""
    return "|".join(sorted("%s:%s" % (s["step"], s["status"]) for s in run.steps if s["status"] in ("failed", "held", "warn"))
                    + sorted("hold:%s" % h["feed"] for h in run.holds))


def repeated_alert(chain, key, now):
    """When this alert only says what one sent under REPEAT_HOURS ago said, the time that one went. 13 Sep: sweeps at 13:00 and
    13:44 each sent Kendall the same group_links failure."""
    try:
        with open(ALERTS_SENT, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return None
    for r in reversed(rows):
        if r.get("chain") == chain and r.get("key") == key:
            try:
                return r["at"] if now - dt.datetime.fromisoformat(r["at"]) < dt.timedelta(hours=REPEAT_HOURS) else None
            except (KeyError, ValueError):
                return None
    return None


def S(name, cmd=None, fn=None, needs=(), needs_ok=(), ok=(0,), held=(), warn=(), timeout=3600, env=None, when=None, after=None, retry=0):
    """needs: run when these succeeded, held or warned.  needs_ok: run ONLY when these were plainly ok - a held input is
    not good enough (the pulse is never built from a register pull its contract refused).  retry: extra attempts for an
    idempotent push - on 13 Sep a sweep started as the laptop woke and the twin audit push met a closed connection."""
    return {"name": name, "cmd": cmd, "fn": fn, "needs": tuple(needs), "needs_ok": tuple(needs_ok), "ok": ok, "held": held,
            "warn": warn, "timeout": timeout, "env": env or {}, "when": when, "after": after, "retry": retry}


def py(*args):
    return [PY] + list(args)


def env_token(path, name):
    try:
        for line in open(path, encoding="utf-8"):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


# ---------- function steps ----------

def ingest_pulse(ctx):
    """POST public/pulse.json to azimuth-2 /ingest_market - the same call daily_refresh.ps1 made with Invoke-RestMethod."""
    tok = env_token(NAJ_ENV, "INGEST_TOKEN")
    if not tok:
        return 1, "ingest FAILED: no INGEST_TOKEN in the Naj listener .env"
    body = open(os.path.join(ROOT, "public", "pulse.json"), "rb").read()
    req = urllib.request.Request(AZ2 + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json",
                                          "User-Agent": "najma-market-pulse/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return 0, "ingest ok: " + r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return 1, "ingest FAILED: http %s" % e.code
    except Exception as e:
        return 1, "ingest FAILED: %s" % str(e)[:200]


def snapshot_sheets(ctx):
    ctx["sheets_before"] = max((os.path.getmtime(p) for p in glob.glob(os.path.join(ROOT, "data", "avail", "*.json"))), default=0)
    return 0, "newest sheet file before the scan: %s" % dt.datetime.fromtimestamp(ctx["sheets_before"]).isoformat(timespec="seconds")


def push_twin_audit(ctx):
    """The sweep's inline push of the twin maturity audit, unchanged."""
    from build_avail_index import env_token as naj_token, push
    d = json.load(open(os.path.join(ROOT, "data", "board", "twin_audit.json"), encoding="utf-8"))
    r = push("twin_audit", {"generated": d["generated"], "districts": d["districts"]}, naj_token("INGEST_TOKEN"))
    return 0, "twin_audit -> %s" % r


def push_building_activity(ctx):
    """TWIN colour data to azimuth-2 as img_building_activity (no nationality; public at /img/building_activity by design,
    agreed with the app session 14 Sep 2026). Accepted is not delivered: read it back and compare before calling it done.
    The internal resident mix never goes this way - /img is public; it waits for the private route."""
    from build_avail_index import WORKER, env_token as naj_token, push
    d = json.load(open(os.path.join(ROOT, "data", "board", "building_activity.json"), encoding="utf-8"))
    r = push("building_activity", d, naj_token("INGEST_TOKEN"))
    req = urllib.request.Request(WORKER + "/img/building_activity?v=%d" % int(time.time()), headers={"User-Agent": "najma-market-pulse/1.0"})
    back = json.load(urllib.request.urlopen(req, timeout=120))
    same = back.get("generated") == d["generated"] and len(back.get("buildings", {})) == len(d["buildings"])
    return (0 if same else 1), "building_activity -> %s; read back %s buildings, %s" % (r, len(back.get("buildings", {})), "matches" if same else "DIFFERS")


def push_resident_mix(ctx):
    """The internal resident mix to azimuth-2's private store (v152.1 POST /ingest_private -> KV priv_community_resident_mix),
    read by the MAP Residents layer behind RESIDENTS_KEY - Kendall's decision, 14 Sep 2026. Never /ingest_market: /img is public.
    Account counts are removed before sending, so only rounded shares, bands, names and outlines leave this machine. The
    pipeline holds no residents key, so the check is the route's own answer: every community and every outline stored."""
    from build_avail_index import WORKER, env_token as naj_token
    d = json.load(open(os.path.join(ROOT, "data", "internal", "community_resident_mix.json"), encoding="utf-8"))
    for c in d["communities"]:
        c.pop("accounts", None)
    body = json.dumps({"name": "community_resident_mix", "json": d}, ensure_ascii=False).encode()
    req = urllib.request.Request(WORKER + "/ingest_private", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": naj_token("INGEST_TOKEN"), "Content-Type": "application/json",
                                          "User-Agent": "najma-market-pulse/1.0"})
    r = json.load(urllib.request.urlopen(req, timeout=600))
    good = bool(r.get("ok")) and r.get("communities") == len(d["communities"]) and r.get("outlines") == len(d["outlines"])
    return (0 if good else 1), "community_resident_mix -> %s (sent %d communities, %d outlines)%s" % (
        r, len(d["communities"]), len(d["outlines"]), "" if good else " - COUNTS DIFFER")


# ---------- after-hooks: turn an exit code and its output into a status and a note ----------

def after_listener(restart):
    def hook(code, out, ctx, status):
        if code == 3:
            if restart:
                subprocess.run(["schtasks", "/run", "/tn", "DA_Azimuth_Listener_Naj"], capture_output=True)
                return "warn", "listener was down at 06:30 and was restarted; sheets posted while it was down were not captured"
            return "ok", "listener not running (the daily refresh restarts it)"
        if code == 2:
            return ("warn" if restart else "ok"), "listener lost coverage in the last 24 h (data/avail/listener_health.json)"
        return status, ""
    return hook


def after_extract(code, out, ctx, status):
    zero = [l for l in out.splitlines() if re.match(r"^extracted: .* 0 units$", l.strip())]
    newest = max((os.path.getmtime(p) for p in glob.glob(os.path.join(ROOT, "data", "avail", "*.json"))), default=0)
    ctx["new_sheets"] = newest > ctx.get("sheets_before", 0)
    if zero and status == "ok":
        return "warn", "%d developer PDF(s) parsed to 0 units - a new sheet format?" % len(zero)
    return status, ("new sheet(s) parsed" if ctx["new_sheets"] else "no new sheets")


def after_volume(code, out, ctx, status):
    ctx["holds_changed"] = code == 4
    return status, ""


def rebuild_needed(ctx):
    return ctx.get("new_sheets") or ctx.get("holds_changed")


# ---------- the chains ----------

def daily(a):
    dld_env = {"DLD_TX_DAYS": "56", "DLD_RENT_DAYS": "28"}
    return [
        S("fetch_dld", py("scripts/fetch_dld.py"), env=dld_env, timeout=2700),
        # Phase 2: today's windows become dated versions; a pull that shrank or silently lost rows is held, and then
        # neither the pulse nor the analytical cache is rebuilt from it - yesterday's stays live
        S("register_versions", py("scripts/register_versions.py"), needs=["fetch_dld"], held=(4,)),
        S("build_duck", py("scripts/build_duck.py"), needs=["fetch_dld"], needs_ok=["register_versions"]),
        S("identity_match", py("scripts/identity_match.py"), needs=["register_versions"], held=(4,)),   # Phase 4: sales project names -> project_id
        S("build_pulse", py("scripts/build_pulse.py"), needs=["fetch_dld"], needs_ok=["register_versions"]),
        S("city_block", py("scripts/build_city_block.py"), needs=["build_pulse"]),   # cityLife back into pulse.json before it leaves
        S("claims", py("scripts/claims.py"), needs=["build_pulse"], warn=(2,)),                         # Phase 4: every pulse figure as a claim
        S("ingest_pulse", fn=ingest_pulse, needs=["build_pulse"], retry=1),
        S("push_heatmap", py("scripts/push_heatmap.py"), needs=["build_pulse"], retry=1),
        S("listener_health", py("scripts/listener_health.py", "--hours", "24"), warn=(2, 3), after=after_listener(True)),
        S("extract_avail", py("scripts/extract_avail.py", "--scan"), timeout=5400),
        S("avail_volume", py("scripts/avail_volume_check.py"), needs=["extract_avail"], held=(4,)),
        S("avail_intervals", py("scripts/avail_intervals.py"), needs=["avail_volume"]),          # Phase 2: units as dated intervals in the lake
        S("avail_drill", py("scripts/build_avail_drill.py"), needs=["avail_volume"]),
        S("avail_index", py("scripts/build_avail_index.py"), needs=["avail_volume"]),
        S("remaining_inventory", py("scripts/remaining_inventory.py"), needs=["avail_index"], timeout=5400),
        S("search_index", py("scripts/build_search_index.py"), needs=["remaining_inventory"]),
        S("developer_dna", py("scripts/build_developer_dna.py"), needs=["avail_index"]),
        S("board", py("scripts/build_board.py"), needs=["developer_dna"]),
        S("projfacts", py("scripts/build_projfacts.py"), needs=["board"]),
        S("compare", py("scripts/build_compare.py"), needs=["projfacts"]),
        S("unit_cards", py("scripts/build_unit_cards_v4.py"), needs=["compare"]),
        S("push_cards", py("scripts/push_cards.py"), needs=["unit_cards"], retry=1),
        S("building_meta", py("scripts/build_building_meta.py", "goldensymphony"), needs=["avail_index"]),
        S("graph_build", py("scripts/graph_build.py"), timeout=5400),
        S("graph_export", py("scripts/graph_export.py"), needs=["graph_build"]),   # golden gate -> lake publish -> export from the lake
        S("gov_contract", py("scripts/gov_contract_check.py"), needs=["graph_build"], held=(4,)),
        S("lake_expire", py("scripts/lake.py", "expire", "--days", "30")),
    ]


def sweep(a):
    steps = [
        S("listener_health", py("scripts/listener_health.py"), warn=(2, 3), after=after_listener(False)),
        S("snapshot_sheets", fn=snapshot_sheets),
        S("extract_avail", py("scripts/extract_avail.py", "--scan"), timeout=5400, after=after_extract),
        S("group_links", py("scripts/group_links.py"), retry=1),      # re-reads and re-pushes the same register: safe to repeat
        S("avail_volume", py("scripts/avail_volume_check.py"), needs=["extract_avail"], held=(4,), after=after_volume),
        S("avail_intervals", py("scripts/avail_intervals.py"), needs=["avail_volume"], when=rebuild_needed),
        S("avail_index", py("scripts/build_avail_index.py"), needs=["avail_volume"], when=rebuild_needed),
        S("remaining_inventory", py("scripts/remaining_inventory.py"), needs=["avail_index"], when=rebuild_needed, timeout=5400),
        S("unit_mix", py("scripts/build_unit_mix.py"), needs=["avail_index"], when=rebuild_needed),
        S("search_index", py("scripts/build_search_index.py"), needs=["remaining_inventory"], when=rebuild_needed),
        S("twin_audit", py("scripts/twin_audit.py"), retry=1),      # 13 Sep 15:00: an SSL EOF as the laptop dozed; rewrites one file, safe to repeat
        S("push_twin_audit", fn=push_twin_audit, needs=["twin_audit"], retry=1),
    ]
    if not a.no_ack:        # approved by Kendall 08 Sep 2026: acknowledge to Naj what was parsed; it sends only when something new was
        steps.append(S("sweep_ack", py("scripts/sweep_ack.py", "--send"), needs=["extract_avail"]))
    return steps


def gov_weekly(a):
    return [
        # 15 Sep 2026: without --force the pull skipped every dataset it had ever pulled, so the week refreshed nothing; a full pull is
        # ~13.6 h of API time. Rotate instead: re-pull what is 6+ days old, stalest first, start nothing new after 150 min, give up on
        # one dataset after 80 min (at most ~230 min, inside the 4 h timeout); exit 3 = PARTIAL, recorded as a warning so the load runs.
        S("dda_pull", py("scripts/dda_pull_all.py", "--stale-days", "6", "--budget-minutes", "150", "--dataset-minutes", "80"),
          timeout=4 * 3600, warn=(3,)),
        S("load_gov", py("scripts/load_gov_datasets.py"), needs=["dda_pull"], timeout=2 * 3600),
        S("gov_contract", py("scripts/gov_contract_check.py", "--full"), needs=["load_gov"], held=(4,)),
        S("realness_gate", py("scripts/gate_gov_realness.py"), needs=["load_gov"]),
        S("lake_publish", py("scripts/lake.py", "publish", "--note", "gov-weekly after the realness gate"), needs=["realness_gate"], held=(4,)),
        # 14 Sep 2026: the registers the key joins read, every part of each newest extract, before the contract counts parts
        S("portal_pull_joined", py("scripts/datadubai_pull_all.py", "--only", JOINED_REGISTERS), timeout=2 * 3600, env={"DD_PAUSE": "5"}),
        S("portal_contract", py("scripts/portal_manifest_check.py"), held=(4,)),
        S("register_joins", py("scripts/register_joins.py", "all"), needs=["portal_pull_joined"], held=(4,)),
        S("dewa_accounts", py("scripts/dewa_accounts.py"), needs=["portal_pull_joined"]),   # keeps each new DEWA extract once
        S("dewa_views", py("scripts/build_dewa_views.py"), needs=["register_joins"]),       # twin colours + the internal resident mix (14 Sep)
        S("push_building_activity", fn=push_building_activity, needs=["dewa_views"], retry=1),
        S("push_resident_mix", fn=push_resident_mix, needs=["dewa_views"], retry=1),        # private route, v152.1 (15 Sep)
        # 16 Sep: Naj's logged questions (worker v153 /questions/export) -> bank match -> weekly list to Kendall -> bank to the private store
        S("question_bank", py("scripts/question_bank.py", "weekly"), retry=1),
    ]


def edge_nightly(a):
    return [S("edge_backup", py("scripts/edge_backup.py"), timeout=1800)]


CHAINS = {"daily": daily, "sweep": sweep, "gov-weekly": gov_weekly, "edge-nightly": edge_nightly}


def log_path(chain):
    if chain == "daily":
        return os.path.join(ROOT, "daily_refresh.log")
    stem = {"sweep": "avail_sweep", "gov-weekly": "gov_weekly", "edge-nightly": "edge_backup"}[chain]
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    return os.path.join(ROOT, "logs", "%s_%s.log" % (stem, dt.date.today().strftime("%Y%m%d")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chain", choices=sorted(CHAINS))
    ap.add_argument("--dry", action="store_true", help="print the plan, run nothing, notify nobody")
    ap.add_argument("--only", default="", help="comma-separated step names; the rest are not run and not recorded")
    ap.add_argument("--no-ack", action="store_true", help="sweep: do not send Naj the acknowledgement")
    ap.add_argument("--no-notify", action="store_true", help="record, but send Kendall nothing")
    a = ap.parse_args()

    steps = CHAINS[a.chain](a)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    run = Run(a.chain)
    ctx = {}
    log = open(os.devnull if a.dry else log_path(a.chain), "a", encoding="utf-8")     # a dry run leaves no trace

    def L(msg):
        line = "[%s] %s" % (dt.datetime.now().isoformat(timespec="seconds"), msg)
        log.write(line + "\n"); log.flush()
        print(line)

    L("=== %s start (refresh_runner, run %s)%s ===" % (a.chain, run.id, " DRY" if a.dry else ""))
    for st in steps:
        if only and st["name"] not in only:
            continue
        if any(run.status_of(d) == "not-needed" for d in st["needs"]):
            run.record(st["name"], "not-needed")                  # nothing new upstream, so nothing to rebuild
            L("--- %s not needed" % st["name"])
            continue
        blocked = [d for d in st["needs"] if run.status_of(d) is not None and run.status_of(d) not in SUCCESS]
        blocked += [d for d in st["needs_ok"] if run.status_of(d) is not None and run.status_of(d) != "ok"]
        if blocked:
            run.record(st["name"], "skipped", note="needs " + ", ".join(blocked))
            L("--- %s SKIPPED (needs %s)" % (st["name"], ", ".join(blocked)))
            continue
        if st["when"] is not None and not a.dry and not st["when"](ctx):
            run.record(st["name"], "not-needed")
            L("--- %s not needed" % st["name"])
            continue
        if a.dry:
            run.record(st["name"], "ok", note="dry run")
            L("--- %s (dry) %s" % (st["name"], " ".join(st["cmd"][1:]) if st["cmd"] else st["fn"].__name__))
            continue

        L("--- %s" % st["name"])
        t0 = time.time()
        for attempt in range(1 + st["retry"]):
            try:
                if st["fn"]:
                    code, out = st["fn"](ctx)
                else:
                    env = dict(os.environ, PYTHONIOENCODING="utf-8", **st["env"])
                    p = subprocess.run(st["cmd"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       timeout=st["timeout"])
                    code, out = p.returncode, p.stdout.decode("utf-8", "replace")
            except subprocess.TimeoutExpired as e:
                code, out = -1, (e.stdout or b"").decode("utf-8", "replace") + "\nTIMEOUT after %ss" % st["timeout"]
            except Exception as e:
                code, out = -2, "EXCEPTION %s" % str(e)[:300]
            if code in st["ok"] + st["held"] + st["warn"] or attempt == st["retry"]:
                break
            if out:
                log.write(out if out.endswith("\n") else out + "\n"); log.flush()
            L("--- %s failed (exit %s), trying again in %ss" % (st["name"], code, RETRY_WAIT))
            time.sleep(RETRY_WAIT)
        secs = time.time() - t0
        if out:
            log.write(out if out.endswith("\n") else out + "\n"); log.flush()

        status = ("ok" if code in st["ok"] else "held" if code in st["held"] else
                  "warn" if code in st["warn"] else "failed")
        note = ""
        if st["after"]:
            status, note = st["after"](code, out, ctx, status)
        for line in out.splitlines():
            if line.startswith(("HELD ", "PARTIAL ")):
                run.hold(st["name"], line.split(" ", 1)[1])
        if status == "failed" and not note:
            tail = [l for l in out.strip().splitlines() if l.strip()][-1:] or [""]
            note = tail[0][:200]
        run.record(st["name"], status, code, secs, note)
        L("--- %s %s (exit %s, %.0fs)%s" % (st["name"], status.upper(), code, secs, (" - " + note) if note else ""))

    if a.dry:
        L("=== %s dry run: %d steps would run ===" % (a.chain, len(run.steps)))
        log.close()
        return 0
    doc = run.finish()
    L("=== %s done: %s; ledger %s ===" % (a.chain, doc["counts"], os.path.relpath(run.path, ROOT)))
    if not a.dry and not a.no_notify:
        key = alert_key(run) if run.needs_alert() else ""
        told = repeated_alert(a.chain, key, dt.datetime.now()) if key else None
        if key and told:
            L("alert not repeated: Kendall was sent the same at %s; again after %d h if it persists" % (told[11:16], REPEAT_HOURS))
            notify_owner.flush()
        elif key:
            sent = notify_owner.send(run.headline())
            with open(ALERTS_SENT, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "chain": a.chain, "run": run.id,
                                    "key": key, "sent": bool(sent)}) + "\n")
            L("kendall notified" if sent else "alert queued (data/runs/alerts_pending.jsonl)")
        else:
            notify_owner.flush()
    log.close()
    return 1 if any(s["status"] == "failed" for s in run.steps) else 0


if __name__ == "__main__":
    sys.exit(main())

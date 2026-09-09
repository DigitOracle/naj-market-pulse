"""Score a Najma yes/no poll answered by Naj through Azimuth (KV poll_<id>, written by the Worker's /poll_send + button replies).

Pass = Yes. A No is a data defect against the claim in data/board/<poll>.json; Not sure is neither. Prints the sheet and writes
Operations/Quality_Audits/DA-AUD-004_beach_poll_08SEP2026_RESULT.md when at least one answer exists.
Usage: python scripts/poll_score.py [--id beach01] [--claims data/board/beach_poll_08sep2026.json]
"""
import json, os, subprocess, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    pid = arg("--id", "beach01"); claims = json.load(open(arg("--claims", os.path.join(ROOT, "data", "board", "beach_poll_08sep2026.json")), encoding="utf-8"))
    raw = subprocess.run(["npx", "wrangler", "kv", "key", "get", "--binding", "MEETINGS", "--env", "azimuth2", "poll_" + pid], cwd=r"C:\Dev\azimuth-worker", capture_output=True, text=True, shell=True).stdout
    rec = None
    for line in reversed(raw.splitlines()):          # wrangler prints notices before the value; the record is the last JSON line
        line = line.strip()
        if line.startswith("{"):
            try: rec = json.loads(line); break
            except Exception: pass
    if rec is None:
        try: rec = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        except Exception: print("no poll record yet"); return
    ans = rec.get("answers") or {}
    # keep the field answers on disk so the truth store's golden set survives a rebuild (data/board/<poll id>_answers.json)
    ap = os.path.join(ROOT, "data", "board", f"{pid}_answers.json")
    try:
        prev = ((json.load(open(ap, encoding="utf-8")) or {}).get("answers") or {}) if os.path.exists(ap) else {}
        prev.update(ans); json.dump({"poll": pid, "sent": rec.get("sent"), "answers": prev}, open(ap, "w", encoding="utf-8"), indent=1)
    except Exception as e: print("answers file:", e)
    rows = []; yes = no = unsure = 0
    for q in claims["questions"]:
        a = ans.get(str(q["n"]), {}).get("ans")
        if a == "yes": yes += 1
        elif a == "no": no += 1
        elif a: unsure += 1
        rows.append((q["n"], q["prop"], q.get("claim_beach") or q.get("claim_park") or q.get("claim") or "", q.get("claim_access") or "", q.get("claim_m") or "", a or "—"))
    print(f"poll {pid} · sent {rec.get('sent')} · answered {len(ans)}/{len(claims['questions'])} · yes {yes} · no {no} · not sure {unsure}")
    for r in rows: print(f"  {str(r[0]):>2}  {r[1][:34]:34s} {r[2][:28]:28s} {str(r[3]):9s} {str(r[4]):>5} m   -> {r[5]}")
    if ans:
        md = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "DigitAlchemy_31MAY2026", "Operations", "Quality_Audits", f"DA-AUD-004_{pid}_poll_RESULT.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write(f"# Poll {pid} — Naj's answers ({time.strftime('%d %b %Y %H:%M')})\n\nSent {rec.get('sent')} · answered {len(ans)} of {len(claims['questions'])} · **yes {yes} · no {no} · not sure {unsure}**\n\n| # | Property | Our claim | Naj |\n|---|---|---|---|\n")
            for r in rows: f.write(f"| {r[0]} | {r[1]} | {r[2]} · {r[3]} · {r[4]} m | {r[5]} |\n")
            f.write("\nEvery No is a defect to fix in the beach register (`scripts/beaches_register.py`) or the property position (`data/board/map_prices.json`).\n")
        print("->", md)


if __name__ == "__main__":
    main()

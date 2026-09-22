"""When a building filled up: DEWA meter connections per building, merged into stack_<district>.json.

Everything else the building page holds is a TRANSACTION. Sales say what changed hands, Ejari says what was let, percent
complete says what a developer filed. None of them says anyone lives there. A DEWA meter connected in someone's name is the
closest any Dubai register gets to occupancy, and with the first and last connection months it gives a building's filling
history: when it opened, and whether it is still filling.

It needs no identity work at all - the DDA session's cut (dewa_moveins_<slug>.json, 22 Sep 2026) is already keyed on the duid
our own identity files carry, matched at 14 m median from the building's anchor.

WHAT THIS MUST NOT SAY, and the page has to carry all four:

  * a connection is NOT a household. One home relet three times is three connections, so this can never be divided by the
    unit count to make an occupancy rate. Someone will try; the wording has to stop them.
  * no rows means NOT RECORDED, never "empty". 17,080 buildings citywide are bound, which is real coverage and not universal.
  * buildings under the disclosure floor are withheld entirely. The floor is 5 connections: below that it stops being a
    statistic and becomes a household's move-in date, and 11,998 of the bound buildings have exactly one connection - a villa,
    a family, a date. The district total says how many were withheld so a page can say so rather than under-report silently.
  * dates are months. The day never leaves the lake.

  python scripts/build_occupancy.py businessbay [--push]
  python scripts/build_occupancy.py --all --push
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def build(district, tok):
    sp = os.path.join(BOARD, "stack_%s.json" % district)
    if not os.path.exists(sp):
        print("%-26s no stack" % district)
        return False
    doc = json.load(open(sp, encoding="utf-8"))
    mv = load(os.path.join(BOARD, "dewa_moveins_%s.json" % district))
    if not mv:
        print("%-26s no move-ins cut" % district)
        return False
    by_duid = {str(r.get("duid")): r for r in (mv.get("buildings") or []) if r.get("duid")}

    ident = load(os.path.join(ROOT, "data", "identity", "identity_%s.json" % district)) or {}
    duid_of = {i: v.get("duid") for i, v in (ident.get("by_index") or {}).items() if v.get("duid")}

    n = 0
    for i, rec in doc.get("buildings_by_id", {}).items():
        r = by_duid.get(str(duid_of.get(i) or ""))
        if not r:
            continue
        rec["occupancy"] = {
            "connections": r.get("move_ins"), "y2024": r.get("move_ins_2024"), "y2025": r.get("move_ins_2025"),
            "y2026": r.get("move_ins_2026"), "residential": r.get("residential"), "commercial": r.get("commercial"),
            "first": r.get("first_move_in_month"), "last": r.get("last_move_in_month"),
            "doors": r.get("makani_points"), "entrance_m": r.get("nearest_entrance_m"),
        }
        n += 1
    # the district's own honesty line: how many buildings were held back, so a page can say so
    doc["district_occupancy"] = {"published": mv.get("buildings_published"),
                                 "withheld": mv.get("buildings_withheld_below_floor"),
                                 "floor": mv.get("disclosure_floor"), "note": mv.get("note")}
    json.dump(doc, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    tot = len(doc.get("buildings_by_id") or {})
    print("%-26s occupancy on %4d of %4d buildings | district: %s published, %s withheld below %s"
          % (district, n, tot, mv.get("buildings_published"), mv.get("buildings_withheld_below_floor"),
             mv.get("disclosure_floor")))
    if tok:
        from build_avail_index import push
        print("   push stack_%s -> %s" % (district, push("stack_" + district, doc, tok).get("ok")))
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        args = sorted(f[6:-5] for f in os.listdir(BOARD) if f.startswith("stack_") and f.endswith(".json"))
    tok = None
    if "--push" in sys.argv:
        from build_avail_index import env_token
        tok = env_token("INGEST_TOKEN")
    for d in (args or ["businessbay"]):
        build(d, tok)
    return 0


if __name__ == "__main__":
    sys.exit(main())

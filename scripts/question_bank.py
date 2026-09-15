"""The question bank: what clients and developers ask Naj that the app does not answer yet (Kendall, 15 Sep 2026).

Kendall: "a way for her to provide feedback for any questions that we're missing, almost like we're building up a question
bank... even from a developer perspective as well, not only from a broker perspective."

Naj logs a question from her private link (a button, typed or hold-to-talk) or on WhatsApp (a text starting "?" or a voice
note starting "question"); searches that find nothing log themselves. The worker keeps each note as qn_<id> and exports them
to this script. Here each note is matched to a canonical question in questions/bank.json, and every week Kendall gets the
most-asked questions the app does not answer yet - the build list.

  pull      GET /questions/export?since=<last> (X-Azimuth-Ingest) -> data/questions/notes.jsonl (local only: notes may
            carry names)
  match     each note -> the closest bank question (words and phrases, no model), or "unmatched" -> data/questions/matches.json
  report    the weekly list -> data/questions/weekly_<date>.md, and one WhatsApp message to Kendall (notify_owner)
  push      the bank with counts, never note text, to the app's private store (/ingest_private, name question_bank)
  validate  the bank file: ids, statuses, where/source filled, nothing personal
  weekly    pull + match + report + push

Options: --dry (write files, send and push nothing), --notes <file.jsonl> (use these notes instead of pulling; for tests).
"""
import datetime as dt, difflib, json, os, re, sys, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

BANK = os.path.join(ROOT, "questions", "bank.json")
QDIR = os.environ.get("QB_DIR") or os.path.join(ROOT, "data", "questions")   # QB_DIR: a test folder, so test notes never mix with hers
NOTES = os.path.join(QDIR, "notes.jsonl")
MATCHES = os.path.join(QDIR, "matches.json")
STATE = os.path.join(QDIR, "state.json")

STATUSES = {
    "answered": "the app answers it today (where says the screen)",
    "held": "we hold the data but no screen shows it (source says which)",
    "needs_data": "we would need new data to answer it (source names the likely one)",
    "by_rule": "we do not answer it by rule (note says which rule)",
}
ASKERS = ("buyer", "tenant", "investor", "developer")
MATCH_MIN = 0.6
PERSONAL = re.compile(r"(\+?971[\s-]?\d|\b05\d[\s-]?\d{3}[\s-]?\d{4}\b|@[a-z0-9-]+\.[a-z]|\b784-?\d{4}-?\d{7}-?\d\b)", re.I)
STOP = set("a an the is are was were be to of in on at for from by with and or near nearest closest how what which where when "
           "who why do does did can could would will i we you they it this that there here my our your their any much many "
           "far close is's there's me us about get nearby client ask asked asking want know please tell".split())


def norm(text):
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]


def content(words):
    return [w for w in words if w not in STOP]


def load_bank():
    return json.load(open(BANK, encoding="utf-8"))


def validate(bank):
    problems, seen = [], set()
    for q in bank["questions"]:
        qid = q.get("id")
        if not qid or qid in seen:
            problems.append("%s: missing or duplicate id" % qid)
        seen.add(qid)
        if q.get("status") not in STATUSES:
            problems.append("%s: status %r" % (qid, q.get("status")))
        if not q.get("question") or not q.get("topic"):
            problems.append("%s: question and topic are required" % qid)
        if any(a not in ASKERS for a in q.get("askedBy", [])) or not q.get("askedBy"):
            problems.append("%s: askedBy must be some of %s" % (qid, ", ".join(ASKERS)))
        if q.get("status") == "answered" and not q.get("where"):
            problems.append("%s: answered needs where" % qid)
        if q.get("status") in ("held", "needs_data") and not q.get("source"):
            problems.append("%s: %s needs source" % (qid, q.get("status")))
        if q.get("status") == "by_rule" and not q.get("note"):
            problems.append("%s: by_rule needs the rule in note" % qid)
        if PERSONAL.search(json.dumps(q, ensure_ascii=False)):
            problems.append("%s: looks like a phone number, email or ID" % qid)
    return problems


def match_note(text, bank):
    """Best bank question for one note: phrase hits on the question's keys, else close wording. (id, score) or (None, score)."""
    words = content(norm(text))
    joined = " " + " ".join(norm(text)) + " "
    best, best_score = None, 0.0
    for q in bank["questions"]:
        # a key starting "~" is a common word ("balcony", "marina"): alone it is not enough to call a match
        keys = [(k.startswith("~"), " " + " ".join(norm(k.lstrip("~"))) + " ") for k in q.get("keys", [])]
        found = [(weak, k) for weak, k in keys if k.strip() and k in joined]
        # more phrases, and longer ones, are stronger: "school fee" beats "school" for a note about fees
        longest = max((len(k.split()) for _, k in found), default=0)
        wording = max([difflib.SequenceMatcher(None, " ".join(words), " ".join(content(norm(p)))).ratio()
                       for p in [q["question"]] + q.get("aliases", [])] or [0.0])
        by_keys = 0.0
        if found:
            by_keys = min(0.95, 0.55 + 0.15 * len(found) + 0.03 * (longest - 1))
            if all(weak for weak, _ in found) and len(found) == 1:
                by_keys = MATCH_MIN - 0.02
        score = max(wording, by_keys)
        if score > best_score:
            best, best_score = q["id"], score
    return (best, round(best_score, 3)) if best_score >= MATCH_MIN else (None, round(best_score, 3))


def read_notes(path=NOTES):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def pull(dry):
    """The export (worker v153) gives at most 2000 notes a call with "more": true; since is inclusive, so ids are deduped."""
    from build_avail_index import WORKER, env_token
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    since = state.get("since", "2026-09-01T00:00:00Z")
    got, cursor = [], since
    for _ in range(50):
        req = urllib.request.Request(WORKER + "/questions/export?since=" + urllib.parse.quote(cursor, safe=""),
                                     headers={"X-Azimuth-Ingest": env_token("INGEST_TOKEN"), "User-Agent": "najma-market-pulse/1.0"})
        page = json.load(urllib.request.urlopen(req, timeout=120))
        notes = page.get("notes", [])
        got += notes
        if not page.get("more") or not notes or notes[-1].get("at") == cursor:
            break
        cursor = notes[-1]["at"]
    have = {n["id"] for n in read_notes()}
    new = []
    for n in got:                      # pages overlap at their boundary (since is inclusive): one copy of each id
        if n.get("id") and n["id"] not in have:
            have.add(n["id"])
            new.append(n)
    if new and not dry:
        os.makedirs(QDIR, exist_ok=True)
        with open(NOTES, "a", encoding="utf-8") as f:
            for n in new:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")
        state["since"] = max(n.get("at", since) for n in new)
        json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)
    print("pull: %d notes from the app since %s, %d new" % (len(got), since, len(new)))
    return new


def match(notes, bank):
    out = {}
    for n in notes:
        qid, score = match_note(n.get("text", ""), bank)
        out[n["id"]] = {"question": qid, "score": score}
    os.makedirs(QDIR, exist_ok=True)
    json.dump(out, open(MATCHES, "w", encoding="utf-8"), indent=1)
    print("match: %d notes, %d matched, %d unmatched" % (len(out), sum(1 for v in out.values() if v["question"]),
                                                     sum(1 for v in out.values() if not v["question"])))
    return out


def counts(notes, matches, bank, days=None):
    since = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=days)).isoformat() + "Z" if days else ""
    per = {q["id"]: {"asked": 0, "askedBy": {}, "communities": {}, "last": None} for q in bank["questions"]}
    unmatched = []
    for n in notes:
        if since and n.get("at", "") < since:
            continue
        m = matches.get(n["id"], {})
        if not m.get("question"):
            unmatched.append(n)
            continue
        c = per[m["question"]]
        c["asked"] += 1
        who = n.get("askedBy") or "not said"
        c["askedBy"][who] = c["askedBy"].get(who, 0) + 1
        comm = (n.get("context") or {}).get("community")
        if comm:
            c["communities"][comm] = c["communities"].get(comm, 0) + 1
        c["last"] = max(c["last"] or "", n.get("at", ""))
    return per, unmatched


def report(notes, matches, bank, dry):
    per_week, unmatched = counts(notes, matches, bank, days=7)
    per_all, _ = counts(notes, matches, bank)
    byid = {q["id"]: q for q in bank["questions"]}
    week = sum(1 for n in notes if n.get("at", "") >= (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=7)).isoformat() + "Z")
    open_q = sorted([(c["asked"], qid) for qid, c in per_all.items() if c["asked"] and byid[qid]["status"] != "answered"], reverse=True)
    lines = ["Question bank, week to %s" % dt.date.today().isoformat(),
             "%d notes this week, %d in all; %d did not match a bank question." % (week, len(notes), len(unmatched))]
    if open_q:
        lines.append("Most asked, not answered yet:")
        for n, qid in open_q[:8]:
            q = byid[qid]
            lines.append("- %s (%dx, %s)%s" % (q["question"], n, q["status"].replace("_", " "),
                                                ": " + q["source"] if q.get("source") else ""))
    if unmatched:
        lines.append("New questions to add:")
        groups = {}
        for n in unmatched:            # the same words asked twice are one candidate, with a count
            k = " ".join(norm(n.get("text", "")))
            g = groups.setdefault(k, {"text": n.get("text", ""), "n": 0, "askedBy": set()})
            g["n"] += 1
            if n.get("askedBy"):
                g["askedBy"].add(n["askedBy"])
        for g in sorted(groups.values(), key=lambda g: -g["n"])[:8]:
            extra = ", ".join(filter(None, ["%dx" % g["n"] if g["n"] > 1 else "", ", ".join(sorted(g["askedBy"]))]))
            lines.append("- \"%s\"%s" % (g["text"][:120], " (%s)" % extra if extra else ""))
    text = "\n".join(lines)
    os.makedirs(QDIR, exist_ok=True)
    out = os.path.join(QDIR, "weekly_%s.md" % dt.date.today().isoformat())
    open(out, "w", encoding="utf-8").write(text + "\n")
    print(text)
    if not dry and notes:
        import notify_owner
        print("sent to Kendall:", notify_owner.send(text))
    return per_all


def push(bank, per_all, dry):
    """Bank + counts to the private store. Note text never leaves: it can carry a client's words."""
    doc = dict(bank)
    doc["questions"] = [dict(q, asked=per_all.get(q["id"], {}).get("asked", 0), lastAsked=per_all.get(q["id"], {}).get("last"))
                        for q in bank["questions"]]
    doc["generated"] = dt.datetime.now().isoformat(timespec="seconds")
    if dry:
        print("push (dry): %d questions" % len(doc["questions"]))
        return
    from build_avail_index import WORKER, env_token
    body = json.dumps({"name": "question_bank", "json": doc}, ensure_ascii=False).encode()
    req = urllib.request.Request(WORKER + "/ingest_private", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": env_token("INGEST_TOKEN"), "Content-Type": "application/json",
                                          "User-Agent": "najma-market-pulse/1.0"})
    print("push:", json.load(urllib.request.urlopen(req, timeout=300)))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    notes_file = sys.argv[sys.argv.index("--notes") + 1] if "--notes" in sys.argv else None
    cmd = args[0] if args else "weekly"
    bank = load_bank()
    problems = validate(bank)
    if cmd == "validate" or problems:
        print("bank: %d questions, %s" % (len(bank["questions"]), "valid" if not problems else "%d problems" % len(problems)))
        for p in problems[:40]:
            print("  " + p)
        sys.exit(1 if problems else 0)
    if cmd in ("pull", "weekly") and not notes_file:
        pull(dry)
    notes = read_notes(notes_file) if notes_file else read_notes()
    matches = match(notes, bank) if cmd in ("match", "report", "weekly", "push") else {}
    per_all = report(notes, matches, bank, dry) if cmd in ("report", "weekly") else counts(notes, matches, bank)[0]
    if cmd in ("push", "weekly"):
        push(bank, per_all, dry)


if __name__ == "__main__":
    main()

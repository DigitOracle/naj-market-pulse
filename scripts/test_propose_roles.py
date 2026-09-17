"""Every case propose_roles.py has got WRONG, kept as a test.

Each entry is a real manifest and the verdict a scout gave it in their own written report. The point
of the list is not that the patterns pass today - it is that each line once FAILED, and the comment
says how. A check that has never been seen to fail proves nothing.

  python scripts/test_propose_roles.py
"""
import glob, io, json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from propose_roles import propose  # noqa: E402

SOURCES = os.path.join(ROOT, "data", "media", "_sources")

# slug -> (expected, why this line exists)
CASES = {
    # --- MUST BE HELD: the scout looked and said there is no usable exterior -------------------
    "hillmont_residences": ("HELD",
        "Note reads 'BEST AVAILABLE EXTERIOR - podium pool deck with the tower flank ... Partial'. "
        "The word EXTERIOR is there; the endorsement is not. Passed until 'best available'/'partial' "
        "were treated as the refusals they are."),
    "claydon_house": ("HELD", "Same Ellington phrasing as Hillmont; same failure."),
    "riverton_house": ("HELD",
        "A balcony the scout annotated 'NOT the building'. Passed when EXTERIOR accepted any mention "
        "of 'the building'."),
    "studio_one": ("HELD", "Offered a LOBBY as the hero on the same fault."),
    "the_point": ("HELD", "Offered a PROMENADE as the hero on the same fault."),

    # --- MUST PASS: the scout verified a real exterior and the patterns threw it away ----------
    "sobha_seahaven": ("PASS",
        "'from the Dubai Marina waterfront' is where a photographer STANDS. Rejecting every 'from' "
        "cost this building its hero; only a vantage inside or on the building disqualifies."),
    "windsor_house": ("PASS",
        "'aerial of the whole building ... ELLINGTON sign on the flank'. Rejected while 'flank' was "
        "disqualifying on its own - it is the hedge that disqualifies, not the anatomy."),
    "windsor_house_ii": ("PASS", "Same as Windsor House."),
    "hameni": ("PASS",
        "Every clean exterior here is PORTRAIT - a tower is a tall subject - and the hero test "
        "required landscape. Also lost the word 'exterior' to a semicolon used as ordinary "
        "punctuation, back when positive evidence was only read after one."),
    "sanctuary_residences": ("PASS",
        "'FILENAME IS WRONG - not an apartment. A wide aerial EXTERIOR render of the whole tower' - "
        "the negation belongs to the NAME. Also 'stacked white balcony bands' is a facade described "
        "by its balconies, not a shot taken from one."),
}


# Two rules carry nothing on the corpus above, because the notes that motivated them ALSO contain a
# pool deck or a lobby, which FROM_INSIDE catches first. They are kept because the judgement is
# right and the next scout will phrase it without the pool deck - so they are exercised here on the
# sentence itself. This is a unit test of a text rule, where the sentence IS the input; it says
# nothing about whether any real building is right, which is what the CASES above are for.
SENTENCES = [
    (False, "LOOKED: BEST AVAILABLE EXTERIOR - street-level shot of the entrance canopy only.",
     "A scout hedging is a scout saying no."),
    (False, "LOOKED: wide exterior, but the tower is barely visible behind hoarding.", "hedged"),
    (False, "LOOKED: exterior elevation, tight crop, frame edge cuts the roof.", "hedged"),
    (True,  "LOOKED: wide aerial exterior of the whole tower from the street.", "a plain yes"),
    (True,  "LOOKED: FILENAME IS WRONG - not a bedroom. A full-height exterior elevation at dusk.",
     "the negation belongs to the NAME; what follows is the truth"),
]


def test_sentences():
    from propose_roles import EXTERIOR, FROM_INSIDE, NEGATED, WEAK, FILENAME_LIE
    wrong = 0
    for want, note, why in SENTENCES:
        n = FILENAME_LIE.sub("", note, count=1)
        got = bool(EXTERIOR.search(n)) and not (FROM_INSIDE.search(n) or NEGATED.search(n)
                                                or WEAK.search(n))
        wrong += got != want
        print("  %-5s %-5s %s" % ("want " + ("yes" if want else "no"), "got " + ("yes" if got else "no"),
                                  note[:62] if got == want else note[:44] + "  <<< " + why))
    return wrong


def main():
    wrong = 0
    for slug, (want, why) in sorted(CASES.items()):
        f = os.path.join(SOURCES, slug + ".json")
        if not os.path.exists(f):
            print("  %-26s MANIFEST MISSING" % slug); wrong += 1; continue
        got = "PASS" if propose(json.load(io.open(f, encoding="utf-8")))["hero"] else "HELD"
        ok = got == want
        wrong += not ok
        print("  %-26s want %-4s got %-4s %s" % (slug, want, got, "" if ok else "<<< " + why))
    print("\n%d wrong out of %d buildings" % (wrong, len(CASES)))
    print("\nrule sentences:")
    wrong += test_sentences()
    print("\n%d wrong in total" % wrong)
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())

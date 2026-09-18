"""Read a scout's notes and PROPOSE picture roles. Proposes only; a person still says yes.

The scouts opened several hundred images and wrote down what each one actually shows, precisely
because filenames lie on every developer we have met. That prose is the evidence, so this reads the
notes rather than the filenames - and it reads them conservatively:

  * a note that says an image is NOT what its name claims disqualifies it, because the scouts write
    exactly that ("filename says 'pool_view'; the image is a wide EXTERIOR render");
  * anything shot FROM a building - a balcony, a terrace, a view out - can never be the hero, which
    is the single most common trap (OMNIYAT, Emaar, Iman and Select all publish one);
  * a room is only claimed when the note names that room and no other.

Usage:
  python scripts/propose_roles.py                 # every manifest without a facts file
  python scripts/propose_roles.py --slug saria    # one
  python scripts/propose_roles.py --write         # write the facts files it proposes
"""
import argparse, glob, io, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_client_sheet import FACTS, slugify  # noqa: E402

SOURCES = os.path.join(ROOT, "data", "media", "_sources")

# These patterns were wrong on the first pass in the worst possible direction: the exterior test
# accepted any mention of "the building", so it read "community context, NOT the building" as a
# match, and offered a lobby and a promenade as heroes. Each rule below earns its place by a case it
# actually got wrong, and test_patterns() re-checks all of them.

# Shot FROM the building, or of something beside it. Never a hero however it is named.
# The vantage point is what matters, not the word "from": "from the waterfront", "from the water",
# "from the street" and "from below" are where a photographer stands to shoot a building, and
# rejecting them cost Sobha SeaHaven its hero on the first pass. Only a vantage INSIDE or ON the
# building disqualifies.
FROM_INSIDE = re.compile(
    r"(\b(balcony|terrace) (view|shot|render|photo)|\bon (a|the|its) (balcon|terrace)|"
    r"\bfrom (inside |within )?(a|an|the|its) (balcon|terrace|window|apartment|suite|room|"
    r"podium|pool|rooftop|lobby|deck|courtyard|atrium)|looking (out|onto)\b|\bview out\b|"
    r"\boverlooking\b|\bwindow\b|\bpodium pool|\bpool deck|lap[- ]pool|rooftop pool|"
    r"\bpromenade\b|\bcommunity context|\blobby\b|\bfoyer\b|\bcorridor\b)", re.I)

# The scouts write a correction in plain words and often capitalise the NOT. Anything that says the
# picture is not what it claims, or is a building site rather than a building, is out.
NEGATED = re.compile(
    r"(\bis not\b|\bare not\b|\bnot the\b|\bnot an?\b|\bno building\b|\bdoes not\b|"
    r"\binstead of\b|construction (photo|progress|site)|\bhoarding\b|\bcrane|"
    r"\bmislabel|\bwrong\b|\bdifferent building\b|\bcut[- ]?out\b|\blifestyle\b)", re.I)

# Positive evidence only: words that can only describe the building seen from outside. "The building"
# on its own is NOT evidence - it appears in "the building lobby" and "NOT the building" alike.
EXTERIOR = re.compile(
    r"(\bexterior\b(?!\s+(space|area|areas|spaces))|\belevation\b|\baerial\b|\bstreet[- ]level\b|"
    r"\bfull[- ]height\b|\bmassing\b|"
    r"(tower|towers|building|buildings|blocks?)\s+(standing|rising|seen against|across the water|"
    r"on the waterfront|from the (water|street|waterfront))|\bfrom below against\b)", re.I)

# A scout hedging is a scout saying no. Ellington's notes on Hillmont and Claydon read "BEST
# AVAILABLE EXTERIOR - podium pool deck with the tower flank ... Partial", and the scout's own report
# listed both under "NO - only podium pool decks showing a partial flank; flagged". The word EXTERIOR
# was there; the endorsement was not. A hero has to show the building, so a note that admits it shows
# only part of one disqualifies the image however it is labelled. It is the HEDGE that disqualifies,
# not the anatomy: 'flank' on its own threw out Windsor House's genuine wide aerial, whose note
# mentions a flank only because that is where the ELLINGTON sign is.
# The scouts flag a misleading filename in a standard way, and the clause that flags it carries a
# negation that belongs to the name rather than the photograph.
FILENAME_LIE = re.compile(
    r"(FILE ?NAME (IS WRONG|LIES|IS A LIE)|MISLABELLED|MISLABELED)\b[^.]*\.\s*", re.I)

WEAK = re.compile(
    r"(\bbest available\b|\bpartial\b|\bsliver\b|\bglimpse\b|\bbarely\b|\bobscured\b|"
    r"\bappears only\b|\bonly as a\b|\bas a backdrop\b|"
    r"\bframe edge\b|\bedge of (the )?frame\b|\bflagged\b|\btight (exterior )?crop\b|"
    r"\bcropped\b|\bnot ideal\b|\bfragment\b)", re.I)

# "wide exterior PHOTOGRAPH (not a render)" is a scout being PRECISE about the medium, and the
# sentence is an endorsement. NEGATED read the "not a" and threw the picture away - the only exterior
# Boulevard Point has. A negation about whether something is a render or a photo says nothing about
# WHICH BUILDING it shows, which is the only thing NEGATED exists to judge.
NOT_MEDIUM = re.compile(
    r"\(?\b(?:not|no)\s+an?\s+(?:render|rendering|cgi|photo|photograph|drawing|illustration|"
    r"sketch|mock[- ]?up|balcony view|balcony shot|interior|interior shot|community park scene|"
    r"community shot|community scene|lifestyle shot|lifestyle image|floor ?plan|amenity shot|"
    r"amenity aerial|close[- ]?up)\b\)?|\bnot the (subject|focus|point|main thing)\b", re.I)

ROOMS = [("bedroom", re.compile(r"\bbed\s?room\b", re.I)),
         ("kitchen", re.compile(r"\bkitchen\b", re.I)),
         ("bath", re.compile(r"\bbath\s?room\b|\bshower room\b|\bensuite\b", re.I)),
         ("living", re.compile(r"\bliving\b|\blounge\b|\bdining\b", re.I))]
AMENITY = re.compile(r"\b(pool|gym|gymnasium|spa|lobby|garden|beach|cinema|padel|playground)\b", re.I)


def load_media(project, developer):
    """Read the pictures off DISK, not out of the truth store.

    The media_id is the first field of every filename, so the register adds nothing here - and
    depending on it meant this could not run while another session held the database, which is most
    of the time. It also means a proposal survives the index being rebuilt, which it was."""
    from PIL import Image
    folder = os.path.join(ROOT, "data", "media", slugify(developer or ""), slugify(project or ""))
    out = []
    if not os.path.isdir(folder):
        return out
    for f in sorted(os.listdir(folder)):
        m = re.match(r"(m_[0-9a-f]{12})_(.*)\.jpg$", f)
        if not m:
            continue
        try:
            with Image.open(os.path.join(folder, f)) as im:
                w, h = im.size
        except Exception:
            w = h = 0
        out.append((m.group(1), m.group(2), w, h))
    return out


def propose(man):
    import urllib.parse
    project = man["project"]
    media = load_media(project, man.get("developer"))
    # Files on disk are named <media_id>_<slugified source name>, so match the manifest's URL the
    # same way the fetcher named it rather than hoping the raw filename survives unchanged.
    by_key = {stem: (mid, w, h) for mid, stem, w, h in media}

    def find(url):
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        key = slugify(os.path.splitext(name)[0])[:28]
        return by_key.get(key)

    heroes, rooms, amen, rejected, excluded = [], {}, None, [], []
    for im in man.get("images", []):
        note = im.get("note") or ""
        got = find(im["url"])
        if not got:
            continue
        mid, w, h = got
        # The whole note is read, for evidence and for disqualifiers alike. An earlier version read
        # positive evidence only AFTER a semicolon, on the theory that a scout corrects a filename
        # there ("filename says 'pool_view'; it is the towers"). Scouts also use a semicolon as
        # ordinary punctuation, and that cost Hameni its hero: "...exterior photograph of the slab
        # tower from ground level...; upscaled" put the word "exterior" on the wrong side of it. The
        # split is unnecessary now that EXTERIOR needs a word only an outside view carries - a
        # filename like "pool_view" cannot match it - and every disqualifier below beats a match.
        # A scout who opens with "FILENAME IS WRONG - not an apartment." is negating the NAME, not
        # the image; what follows the full stop is the truth about the picture. Judging the whole
        # sentence threw away Sanctuary Residences' wide aerial on the strength of "not an
        # apartment".
        note = FILENAME_LIE.sub("", note)
        note = NOT_MEDIUM.sub("", note)
        body = note
        if FROM_INSIDE.search(note) or NEGATED.search(note) or WEAK.search(note):
            # Write the disqualification down, not just the refusal to lead with it. The wiring
            # assigns roles from the media register and has never read these notes, so a picture
            # this rejected as a hero was still free to turn up as "interior_1".
            excluded.append(mid)
            if EXTERIOR.search(note):
                rejected.append((im["url"].rsplit("/", 1)[-1][:34], note.strip()[:70]))
        elif EXTERIOR.search(note):
            # Keep every clean exterior and choose at the end. Taking the first one in manifest order
            # and requiring it to be landscape threw away Windsor House and Hameni outright: a tower
            # is a tall subject and developers publish it portrait. Landscape still wins where one
            # exists, because the sheet's hero band is wide.
            heroes.append((0 if (w or 0) >= (h or 1) else 1, len(heroes), mid, note))

        hits = [r for r, rx in ROOMS if rx.search(body)]
        if len(hits) == 1 and hits[0] not in rooms and not NEGATED.search(body):
            rooms[hits[0]] = (mid, note)
        elif amen is None and AMENITY.search(body) and not NEGATED.search(body):
            amen = (mid, note)

    hero = None
    if heroes:
        _, _, mid, note = sorted(heroes)[0]
        hero = (mid, note)

    return {"project": project, "developer": man.get("developer"), "area": man.get("area"),
            "page": man.get("page"), "hero": hero, "rooms": rooms, "amenity": amen,
            "rejected": rejected, "excluded": excluded}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    files = ([os.path.join(SOURCES, a.slug + ".json")] if a.slug
             else sorted(glob.glob(os.path.join(SOURCES, "*.json"))))
    ready = held = 0
    for f in files:
        slug = os.path.basename(f)[:-5]
        if not a.slug and os.path.exists(os.path.join(FACTS, slug + ".json")):
            continue
        try:
            man = json.load(io.open(f, encoding="utf-8"))
        except Exception as e:
            print("  %-34s bad manifest: %s" % (slug[:34], e)); continue
        p = propose(man)
        if not p["hero"]:
            held += 1
            print("  %-34s HELD - no verified exterior in the notes" % slug[:34])
            for nm, why in p["rejected"][:2]:
                print("       rejected %-30s %s" % (nm, why))
            continue
        ready += 1
        print("  %-34s hero + %s" % (slug[:34], ", ".join(sorted(p["rooms"])) or "no named rooms"))
        if a.write:
            write_facts(slug, p)
    print("\n%d proposable, %d held for want of an exterior" % (ready, held))


def write_facts(slug, p):
    dev = p["developer"] or "the developer"
    over = {"hero": p["hero"][0]}
    caps = {}
    for role, (mid, note) in p["rooms"].items():
        over[role] = mid
        caps[role] = {"bedroom": "Bedroom", "kitchen": "Kitchen", "bath": "Bathroom",
                      "living": "Living room"}[role]
    # A role a picture may never hold is as much a decision as one it does hold, and it belongs in
    # the tracked facts file so it survives the next rebuild.
    keep = set(over.values())
    ex = [m for m in dict.fromkeys(p.get("excluded") or []) if m not in keep]
    if p["amenity"] and "amenity" not in over and p["amenity"][0] not in over.values():
        over["amenity"] = p["amenity"][0]
        caps["amenity"] = "Amenities"
    d = {
      "_source": "%s project page, read 17 September 2026 (manifest: data/media/_sources/%s.json)." % (dev, slug),
      "_assets_from": "Images published openly on that page. Anything behind an enquiry form was not fetched.",
      "developer": dev,
      "strapline": "%s%s" % (dev, ", " + p["area"] if p.get("area") else ""),
      "asset_overrides": over,
      "asset_exclude": ex,
      "_exclude_note": ("Pictures a scout opened and disqualified in writing - shot from a balcony "
                        "or terrace, a lobby under an exterior's filename, or a different building. "
                        "They are out of the running for EVERY role, not merely the hero."),
      "_override_note": ("Roles proposed from a scout's written record of what each image ACTUALLY "
                         "SHOWS, after opening it - not from filenames, which misdescribe the picture "
                         "on every developer we have checked. The hero is an exterior of the building "
                         "itself; anything shot from a balcony, terrace or window was refused."),
      "captions": caps,
      "image_note": ("Images are published by %s on its own project page, and are reproduced here for "
                     "a buyer considering the building. Where they are computer renders they show the "
                     "developer's intended specification, not any particular apartment, and the finish "
                     "of an individual unit may differ. Ask to view before relying on them." % dev),
    }
    json.dump(d, io.open(os.path.join(FACTS, slug + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(main())

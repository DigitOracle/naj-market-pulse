"""Turn the media register into sheet-ready pictures, so a client sheet is not a hand-curated thing.

Bellevue's pictures were placed by a person who opened the brochure and looked. That does not scale
to the hundred-odd buildings that already clear the numbers bar, and the pack cover shows what the
gap costs: The EDGE and Peninsula Four come out as grey boxes beside Bellevue's photograph.

The media register already holds the hard part - every picture we have, bound to its developer and
project, classified render / plan / cover, with the quality metrics the classifier used. What it does
not hold is which ROLE a picture plays on a sheet: which render is the building seen from outside,
which floor plan is the two-bed. This assigns those.

What is inferred, and what is refused:
  plans   labelled by reading the text on their own page in the source document. A plan that does
          not say how many bedrooms it is does not become "One bedroom" - it is skipped and
          reported. A page showing two layouts at once is ambiguous and is skipped too.
  hero    the widest, most detailed landscape render from the front of the document. Brochures open
          with the building; this is a convention, not a fact, so the choice is recorded.
  interiors  taken as neutral `interior_1..3`, NOT as "bedroom" or "kitchen". Nothing here can tell
          a bedroom from a living room, and a sheet that captions a kitchen "Bedroom" is worse than
          one that says "Interior". A person who has actually looked can override the caption in
          data/sheets/_facts/<slug>.json, which is what was done for Bellevue.

Every assignment is written to _provenance.json beside the pictures: source document, page, and the
reuse basis the register recorded. That is what lets the sheet keep saying where its images came
from.

Usage
  python scripts/wire_sheet_assets.py --all
  python scripts/wire_sheet_assets.py --project "Imtiaz Symphony Tower" [--slug symphony]
  python scripts/wire_sheet_assets.py --all --dry
"""
import argparse, json, os, re, shutil, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import fitz
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_client_sheet import slugify, find_building, ASSETS, facts_for  # noqa: E402

DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
SOURCE_DIRS = [r"C:\Dev\azimuth-listener-naj\docs\developer_availability",
               os.path.join(ROOT, "data", "brochure"),
               os.path.join(ROOT, "data", "brochure_inbox")]

# Budget per role: (max width, target KB). The sheet inlines these as base64, so a fat picture costs
# every page it rides on.
BUDGET = {"hero": (900, 70), "plan_1br": (760, 60), "plan_2br": (760, 60), "plan_3br": (760, 60),
          "interior_1": (820, 45), "interior_2": (620, 35), "interior_3": (620, 35)}

BR_RX = re.compile(r"\b(\d)\s*(?:-|\u2013)?\s*(?:BED\s*ROOMS?|BEDROOMS?|B\s*/?\s*R)\b", re.I)
STUDIO_RX = re.compile(r"\bSTUDIO\b", re.I)


def match_building(project):
    """The register carries the developer's marketing name ("Imtiaz Symphony Tower"); the Land
    Department carries a shorter registered one ("Symphony"). Try the full name, then progressively
    stripped forms, and match in both directions - a substring test only one way round misses
    exactly the case where the marketing name is the longer string."""
    tried = []
    forms = [project,
             re.sub(r"^(imtiaz|palma|fakhruddin|select|arada|beyond|prestige one|damac|emaar)\s+", "",
                    project, flags=re.I),
             re.sub(r"\s+by\s+.+$", "", project, flags=re.I),
             re.sub(r"\s+(tower|towers|residences?|district|vision)\s*$", "", project, flags=re.I)]
    for f in dict.fromkeys(x.strip() for x in forms if x and x.strip()):
        tried.append(f)
        hits = find_building(f)
        if hits:
            return hits
        # reverse direction: the registered name sits inside the marketing name
        want = slugify(f)
        from build_client_sheet import districts, DLD
        import json as _json
        for dist in districts():
            p = os.path.join(DLD, "tx_buildings_%s.json" % dist)
            if not os.path.exists(p):
                continue
            for b in _json.load(open(p, encoding="utf-8")).get("buildings", []):
                ps = slugify(b.get("project"))
                if ps and len(ps) >= 5 and ps in want:
                    return [dict(b, _district=dist)]
    return []


def contact_sheet(rows, project, dest):
    """One numbered grid of every candidate plan, so a person labels a building in a single glance
    instead of opening a brochure. Needed because a rasterised plan carries its bedroom count in
    pixels and this machine has no OCR."""
    cands = [r for r in rows if r["project"] == project and r["kind"] == "plan" and is_real_plan(r)]
    if not cands:
        return None
    cands.sort(key=lambda r: r["page"])
    from PIL import ImageDraw
    cell, cols = 320, 4
    rowsn = (len(cands) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rowsn * (cell + 26)), "white")
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(cands):
        src = os.path.join(ROOT, r["path"]) if not os.path.isabs(r["path"]) else r["path"]
        if not os.path.exists(src):
            continue
        im = Image.open(src).convert("RGB")
        im.thumbnail((cell - 8, cell - 8), Image.LANCZOS)
        x, y = (i % cols) * cell, (i // cols) * (cell + 26)
        sheet.paste(im, (x + 4, y + 4))
        d.text((x + 6, y + cell + 6), "p%d  %s" % (r["page"], r["media_id"][:10]), fill="black")
    os.makedirs(dest, exist_ok=True)
    p = os.path.join(dest, "_plans_contact.png")
    sheet.save(p)
    return p


def source_path(name):
    for d in SOURCE_DIRS:
        p = os.path.join(d, name or "")
        if os.path.exists(p):
            return p
    return None


def bedrooms_on_page(pdf_path, page_no):
    """Read the plan's own label. Returns an int, 0 for studio, or None when it does not say / says
    more than one thing."""
    try:
        doc = fitz.open(pdf_path)
        if page_no < 1 or page_no > doc.page_count:
            return None
        text = doc[page_no - 1].get_text()
    except Exception:
        return None
    found = {int(m.group(1)) for m in BR_RX.finditer(text) if m.group(1).isdigit()}
    if STUDIO_RX.search(text):
        found.add(0)
    if len(found) == 1:
        n = found.pop()
        return n if 0 <= n <= 5 else None
    return None


def fit_budget(src, dst, max_w, target_kb):
    im = Image.open(src).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    for q in (78, 72, 66, 60, 54, 48):
        im.save(dst, quality=q, optimize=True, progressive=True)
        if os.path.getsize(dst) <= target_kb * 1024:
            return os.path.getsize(dst), q
    return os.path.getsize(dst), 48


def is_real_plan(r):
    """The register's `plan` class means "image-dominant, pale, unsaturated", which also catches a
    dark section divider and a colourful full-page photo. A drawn floor plan is genuinely pale AND
    full of line work: white >= 0.25, plenty of grey-level spread, and not strongly coloured.
    Measured on what we hold: real plans sit at white 0.33-0.58 / detail 80-93, the two Serenia
    dividers at white 0.07 / detail 13-15, and an Imtiaz photo page at saturation 67."""
    return ((r["whiteness"] or 0) >= 0.25 and (r["detail"] or 0) >= 40
            and (r["saturation"] or 0) < 50)


def pick(rows, project):
    """Assign roles. Returns {role: media_row} plus a list of notes about what was refused."""
    mine = [r for r in rows if r["project"] == project]
    notes, out = [], {}

    # --- plans, labelled from their own page
    claimed = [r for r in mine if r["kind"] == "plan"]
    plans = [r for r in claimed if is_real_plan(r)]
    if len(claimed) != len(plans):
        notes.append("%d page(s) classed as plan are dividers or photos, not drawings - dropped"
                     % (len(claimed) - len(plans)))
    labelled, unlabelled, raster = {}, 0, 0
    for r in plans:
        sp = source_path(r["source_file"])
        n = bedrooms_on_page(sp, r["page"]) if sp else None
        if n is None:
            unlabelled += 1
            if (r["text_chars"] or 0) == 0:
                raster += 1
            continue
        labelled.setdefault(n, []).append(r)
    for n, cands in labelled.items():
        if n == 0 or n > 3:
            continue
        # the cleanest drawing: most white page, least clutter
        cands.sort(key=lambda r: (-(r["whiteness"] or 0), r["page"]))
        out["plan_%dbr" % n] = cands[0]
    if unlabelled:
        how = (" (%d of them have no text layer at all - the label is drawn into the image, so it "
               "needs OCR or one human glance; run --contact)" % raster) if raster else ""
        notes.append("%d floor plan(s) carry no readable bedroom label - skipped, not guessed%s"
                     % (unlabelled, how))
    if not labelled and plans:
        notes.append("no plan could be labelled for this project")

    # --- hero: brochures open with the building. Widest, most detailed landscape render up front.
    renders = [r for r in mine if r["kind"] == "render" and (r["w"] or 0) and (r["h"] or 0)]
    land = [r for r in renders if r["w"] >= r["h"] * 1.2]
    if land:
        front = [r for r in land if r["page"] <= max(6, min(r2["page"] for r2 in land) + 4)] or land
        front.sort(key=lambda r: (-((r["detail"] or 0) + (r["edge_density"] or 0) * 1.5), r["page"]))
        out["hero"] = front[0]
        notes.append("hero chosen by convention (earliest wide, detailed render) - worth a human glance")

    # --- interiors: neutral roles, spread through the document, never the hero again
    used = {out.get("hero", {}).get("media_id")}
    rest = [r for r in renders if r["media_id"] not in used]
    rest.sort(key=lambda r: (-((r["detail"] or 0) + (r["edge_density"] or 0)), r["page"]))
    chosen = []
    for r in rest:
        if any(abs(r["page"] - c["page"]) < 2 for c in chosen):
            continue                      # adjacent pages are usually the same room twice
        chosen.append(r)
        if len(chosen) == 3:
            break
    for i, r in enumerate(chosen, 1):
        out["interior_%d" % i] = r
    return out, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--slug", help="sheet slug to write into (default: resolved from the Land Department name)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--contact", action="store_true",
                    help="write a numbered grid of candidate floor plans for a human glance")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("no truth store at %s" % DB)
        return 2
    con = duckdb.connect(DB, read_only=True)
    cols = [c[0] for c in con.execute("describe media").fetchall()]
    rows = [dict(zip(cols, r)) for r in con.execute("select * from media").fetchall()]
    projects = sorted({r["project"] for r in rows}) if a.all else ([a.project] if a.project else [])
    if not projects:
        print("give --project NAME or --all")
        return 2

    for project in projects:
        print("\n%s" % project)
        slug = a.slug if (a.slug and not a.all) else None
        if not slug:
            hits = match_building(project)
            if hits:
                slug = slugify(hits[0].get("project"))
                print("  -> Land Department record: %s (%s)" % (hits[0].get("project"), hits[0]["_district"]))
            else:
                slug = slugify(project)
                print("  -> no Land Department record found; writing under %s (sheet will not build "
                      "until the numbers side matches)" % slug)

        if a.contact:
            cp = contact_sheet(rows, project, os.path.join(ASSETS, slug))
            print("  contact sheet: %s" % (os.path.relpath(cp, ROOT) if cp else "no plan candidates"))

        assigned, notes = pick(rows, project)

        # A recorded human choice beats a heuristic. The hero rule ("earliest wide, detailed
        # render") picked a robot serving a drink by a pool for Treppan Vision - fine marketing,
        # absurd as the lead image on a fact sheet. Overrides live in the tracked facts file so the
        # decision survives the next rebuild.
        over = (facts_for(slug) or {}).get("asset_overrides") or {}
        by_id = {r["media_id"]: r for r in rows}
        for role, mid in over.items():
            if mid in by_id:
                assigned[role] = by_id[mid]
                notes.append("%s set by hand to %s (overrides the heuristic)" % (role, mid))
            else:
                notes.append("override for %s names unknown media_id %s - ignored" % (role, mid))

        # Dedupe AFTER overrides: an override can re-introduce a picture the heuristic had already
        # spent on another role, which is how the hero ended up repeated as interior_2.
        seen, drop = set(), []
        for role in ["hero"] + ["interior_%d" % i for i in (1, 2, 3)]:
            r = assigned.get(role)
            if not r:
                continue
            if r["media_id"] in seen:
                drop.append(role)
            else:
                seen.add(r["media_id"])
        for role in drop:
            assigned.pop(role, None)
            notes.append("%s dropped - same picture as another role" % role)
        if not assigned:
            print("  nothing assignable")
            continue

        dest = os.path.join(ASSETS, slug)
        dev = next((r["developer"] for r in rows if r["project"] == project and r.get("developer")), None)
        prov = {"project": project, "slug": slug, "developer": dev, "assigned": {}}
        if not a.dry:
            os.makedirs(dest, exist_ok=True)
            # Clear roles this run does not assign. The sheet reads the FOLDER, not this script's
            # output, so a file left behind from a previous run silently keeps appearing - which is
            # how a dropped duplicate hero stayed on the page as interior_2.
            for f in os.listdir(dest):
                stem, ext = os.path.splitext(f)
                if ext.lower() in (".jpg", ".jpeg", ".png") and stem not in assigned:
                    os.remove(os.path.join(dest, f))
                    print("  %-11s removed (no longer assigned)" % stem)
        for role, r in sorted(assigned.items()):
            src = os.path.join(ROOT, r["path"]) if not os.path.isabs(r["path"]) else r["path"]
            if not os.path.exists(src):
                print("  %-11s source missing: %s" % (role, r["path"]))
                continue
            mw, kb = BUDGET.get(role, (760, 55))
            out = os.path.join(dest, role + ".jpg")
            if a.dry:
                print("  %-11s p%-3d %s" % (role, r["page"], os.path.basename(r["path"])))
            else:
                size, q = fit_budget(src, out, mw, kb)
                print("  %-11s p%-3d %5.0f KB  q%d  <- %s" % (role, r["page"], size / 1024, q,
                                                              r["source_file"][:40]))
            prov["assigned"][role] = {"media_id": r["media_id"], "source_file": r["source_file"],
                                      "page": r["page"], "reuse_basis": r["reuse_basis"],
                                      "kind": r["kind"]}
        for n in notes:
            print("  note: %s" % n)
        prov["notes"] = notes
        if not a.dry:
            json.dump(prov, open(os.path.join(dest, "_provenance.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Handover — indicative floor plates on the building page

**From:** the Najma question-bank video session · **To:** the session that owns `src/building_page.js` and the twin's floor block
(branch `twin-floor-stack` in `C:\Dev\azimuth-worker-stack`) · **21 Sep 2026**

**Why:** Kendall, 20 Sep, looking at the floor card's current bare outline: *"the floor plate should look something like this"* —
with a marketing floor plate beside it: every unit a coloured cell, studio / one-bed / two-bed, lifts, stairs, LEVEL 5. Built and
checked; it needs to go on the page. **Kendall has asked for this to be implemented.** Deploying still goes through the Azimuth
session on his own go, as usual — this spec is the build, not the release.

The current plate draws as a straight bar even for a curved building (Binghatti Aquarise), which is its own bug; this replaces it.

---

## 1. What exists already

| File | What |
|---|---|
| `scripts/build_floor_plates.py` | the builder. `python scripts/build_floor_plates.py businessbay damachills` |
| `data/board/plates_businessbay.json` | 1.8 MB · 164 buildings · 3,933 floors with cells |
| `data/board/plates_damachills.json` | 0.1 MB · 24 buildings · 146 floors with cells |
| `data/board/plates_sample_businessbay_574.json` | **73 KB, one building (Al Habtoor Tower) — read this first** |
| `data/stack/plates_viewer.html` | a working reference renderer: district → building → floor, with the legend and caveats |
| `scripts/plates_viewer_template.html` | its source; §5 below is lifted from it |

Nothing is pushed to KV and nothing is deployed. The builder reads only files you already produce
(`stack_<district>.json`, `unitmix_<district>.json`, `units_<district>.json`, `data/ce/<district>/buildings.geojson`).

**Coverage as built:**

| | buildings | floors with cells | of those, with **real unit numbers** |
|---|---|---|---|
| Business Bay | 164 | 3,933 | 2,465 floors in 95 buildings · 32,373 units |
| DAMAC Hills | 24 | 146 | 33 floors in 2 buildings · 789 units |

Per-building payload: **median 10 KB**, largest 86 KB (Al Habtoor Tower, 91 floors). Small enough to serve per building.

---

## 2. The data contract

```
plates_<district>.json
  district, slug, generated, note          note = the caveat sentence, verbatim, for any surface that shows a plate
  buildings: { "<footprint id>": BUILDING }
```

`<footprint id>` is the same id you use everywhere: the feature index in `data/ce/<district>/buildings.geojson`, the key in
`unitmix_<district>.buildings_by_id`, and `window.BYFP` in the twin.

```
BUILDING
  name      string
  levels    int      how many floors the stack has
  lifts     int|null from unitmix.elevators
  north     float    DEGREES. The plate is drawn in a frame rotated so the building's long axis lies flat.
                     Rotate the north arrow by -north to point at true north. Do NOT rotate the geometry.
  area      int      footprint m²
  outline   [x,y,...] flat pairs, METRES, the footprint in that rotated frame
  conflict  bool     the map and the register disagree about which building stands here
  fits      bool     false = the model stands far shorter than the register building (probably a podium)
  plates    [PLATE]  distinct drawings; floors that carry the same homes share one
  floors    { "<floor label>": <index into plates> }     label as the stack gives it: "G", "1", "2", "75-R"…
  labels    { "<floor label>": ["3001","3002",…] }       ONLY where basis === "units". Absent otherwise.

PLATE
  use     "homes" | "hotel" | "office" | "retail" | "services"
  basis   "units"        real DLD unit rows: unit number, type and size per unit          ← the good case
          "municipality" the DM count of homes for that floor, split by the register's type proportions
          "register"     the register's units per type, spread evenly over that type's floor range
          "none"         nothing to draw (services, parking)
  counts  [[code, n, sqm_median], …]     for the legend
  cells   [[code, [x,y,…], runIndex], …] one home. runIndex indexes labels[floor] — see §3
  blocks  [["lift"|"stair", [x,y,…]], …] cores
  tower   [x,y,…] | null   present when the footprint was read as a PODIUM: draw `outline` dashed and `tower` solid
  skip    "small" | "many" | null   not drawn, and why (§4)
  dm_use  string | null    the Municipality calls this floor something else (usually "services") but the units
                           register lists homes on it, so the homes are drawn. Must be said on screen (§4)
  scale   float | null     band area ÷ the area the homes want. Diagnostic only; do not show it
```

Type codes and the colours (already the app's): `studio` `#B9A6C9` · `1` `#C5A56A` · `2` `#7FA8C9` · `3` `#8FC7B9` ·
`4` `#D9A441` · `office` `#8FA39B` · `retail` `#D98C6A` · `other` `#8A8F96`. Lifts `#5B6662`, stairs `#9A95D6`,
plate ground `#2B3532`, cell stroke `#0E1613`.

---

## 3. Unit numbers — index by `runIndex`, never by position

`cells[i][2]` is the index into `labels[floor]`. **`cells` is sometimes shorter than `labels`** (a home at a tight corner can fail
to get a drawable wedge — e.g. Al Habtoor Tower level 30: 27 units, 26 cells). So:

```js
const lab = labels && labels[cell[2]] !== undefined ? labels[cell[2]] : SHORT[cell[0]];
```

Falling back to the type letter (`S`, `1`, `2`…) when there is no label is what the reference renderer does. Never assume
`cells.length === labels.length`, and never renumber.

---

## 4. What must appear on screen

Non-negotiable — it is what makes the plate defensible. The reference wording, which you can reuse verbatim:

> **Indicative layout.** The outline is this building's surveyed footprint; the sizes of the homes against each other are the
> register's. *[basis sentence]* Where each home sits, and where the lifts and stairs are, is not published for this building —
> that comes from a Revit model or the developer's stacking plan, as on The Symphony.

**Basis sentence**, by `basis`:

- `units` — "The unit numbers, types and sizes are the Land Department units register's, one row per unit; they are laid round the
  facade in unit-number order."
- `municipality` — "How many homes this floor carries is the Municipality's count for the floor, shared between the types the Land
  Department register puts on it."
- `register` — "How many homes of each type this floor carries is the Land Department register's units for the type, spread evenly
  over the floors the register gives it."

Plus, when the flag is set:

- `basis !== "units"` — "No unit numbers are shown: the units register does not cover this building well enough."
- `dm_use` — "The Municipality records this floor as {dm_use}; the Land Department register lists these homes on it, so they are
  drawn."
- `tower` — "The footprint (dashed) is far larger than the floor the register describes, so it is read as a podium: the floor is
  drawn inside it at the size the register implies."
- `skip === "small"` — "Not drawn: the register puts more homes on this floor than this footprint can hold — several buildings are
  probably bound to one record." (127 Business Bay floors, 135 DAMAC Hills floors. Most of DAMAC Hills is this: one permit over
  several blocks.)
- `skip === "many"` — "Not drawn: too many units on one floor to draw."
- `conflict` / `fits === false` — keep whatever the card already says for these; they are your flags, not mine.

**The line that must never appear:** anything implying a unit's position, orientation or view is known. It is not. The DDA session
confirmed on 21 Sep that the units register carries no view, no orientation, no compass or stack code and nothing saying which side
of a corridor a unit sits on. Balcony area (88% filled) is the nearest hint and is **not** to be labelled as orientation.

---

## 5. Reference renderer

Lifted from `scripts/plates_viewer_template.html`, where it is running. Pure SVG, no dependency. `p` = PLATE, `b` = BUILDING,
`labels` = `b.labels[floor]` or undefined.

```js
function plateSVG(b, p, labels) {
  const o = b.outline, xs = [], ys = [];
  for (let i = 0; i < o.length; i += 2) { xs.push(o[i]); ys.push(o[i + 1]); }
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = Math.max(3, (x1 - x0) * 0.03), W = 1000, k = W / (x1 - x0 + 2 * pad), H = (y1 - y0 + 2 * pad) * k;
  const T = a => { let s = ""; for (let i = 0; i < a.length; i += 2)
    s += ((a[i] - x0 + pad) * k).toFixed(1) + "," + ((y1 - a[i + 1] + pad) * k).toFixed(1) + " "; return s; };   // y flips
  let h = `<svg viewBox="0 0 ${W} ${H.toFixed(0)}" xmlns="http://www.w3.org/2000/svg">`;
  if (p.tower)                                                             // podium: footprint dashed, the floor inside it
    h += `<polygon points="${T(o)}" fill="${PLATE}" fill-opacity=".3" stroke="#C5A56A" stroke-opacity=".45"
           stroke-width="1.4" stroke-dasharray="7 6"/><polygon points="${T(p.tower)}" fill="${PLATE}"
           stroke="#C5A56A" stroke-opacity=".6" stroke-width="1.8"/>`;
  else
    h += `<polygon points="${T(o)}" fill="${p.cells.length ? PLATE : (COL[p.use] || PLATE)}"
           fill-opacity="${p.cells.length ? 1 : .35}" stroke="#C5A56A" stroke-opacity=".6" stroke-width="1.8"/>`;
  for (const [c, a, idx] of p.cells) {
    const lab = labels && labels[idx] !== undefined ? labels[idx] : (SHORT[c] || "");
    h += `<polygon points="${T(a)}" fill="${COL[c] || COL.other}" stroke="${INK}" stroke-width="1.5"
           stroke-linejoin="round"/>`;
    let cx = 0, cy = 0, mnx = 1e9, mxx = -1e9, mny = 1e9, mxy = -1e9;
    for (let i = 0; i < a.length; i += 2) { cx += a[i]; cy += a[i + 1];
      mnx = Math.min(mnx, a[i]); mxx = Math.max(mxx, a[i]); mny = Math.min(mny, a[i + 1]); mxy = Math.max(mxy, a[i + 1]); }
    cx /= a.length / 2; cy /= a.length / 2;
    if (Math.max(mxx - mnx, mxy - mny) * k > 16 && Math.min(mxx - mnx, mxy - mny) * k > 9)   // only if it fits
      h += `<text x="${((cx - x0 + pad) * k).toFixed(1)}" y="${((y1 - cy + pad) * k + 4).toFixed(1)}"
             font-size="${(labels ? Math.min(12, Math.max(7.5, k * 1.5)) : Math.min(15, Math.max(9, k * 2.2))).toFixed(1)}"
             font-weight="600" text-anchor="middle" fill="${INK}" fill-opacity=".8">${esc(lab)}</text>`;
  }
  for (const [kind, a] of p.blocks)
    h += `<polygon points="${T(a)}" fill="${kind === "lift" ? LIFT : STAIR}" stroke="${INK}" stroke-width="1.3"/>`;
  if (!p.cells.length)
    h += `<text x="${W / 2}" y="${H / 2 + 5}" font-size="17" letter-spacing="3" text-anchor="middle"
           fill="#E8E4D8" fill-opacity=".8">${esc((USE[p.use] || p.use).toUpperCase())}</text>`;
  h += `<g transform="translate(${W - 40},38) rotate(${(-b.north).toFixed(1)})"><circle r="17" fill="${INK}"
         fill-opacity=".6" stroke="#C5A56A" stroke-opacity=".6"/><path d="M0,-12 L5,7 L0,3 L-5,7 Z" fill="#C5A56A"/>
         <text y="-21" font-size="11" fill="#C5A56A" text-anchor="middle">N</text></g></svg>`;
  return h;
}
```

Under it: `LEVEL {floor}` centred in gold with wide letter-spacing, then the legend from `counts` — a swatch, the type name, the
count, and the median size in sq ft (`Math.round(sqm * 10.7639)`) — then lifts (`b.lifts`) and stairs if `blocks` is non-empty,
then the caveat block from §4.

---

## 6. Where it goes

1. **The building page's floor card** — replace the current `.plate` SVG (the straight bar) with this. Same place, same heading
   *The floor plate*, same position above *The types the register puts on this floor*. On a floor with `basis === "units"` the
   type table below it can stay as it is or be dropped, since the cells now carry the numbers; your call.
2. **The twin's FLOOR LAYOUT panel** — the bar chart is what a client sees today on Binghatti Aquarise. When a floor is tapped
   there, the same plate is the natural thing to show. Optional, second.

**Serving.** Per building, not per district — 1.9 MB of district file against a 10 KB median building. Either fold `BUILDING` into
the payload the building page already fetches for that id, or push per building to KV the way `build_avail_index.push` does
(`plates_<district>_<id>`). If you want the builder to emit per-building files instead of one district file, say so and I will
change it — it is a small change at the end of `run()`.

---

## 7. Worth fixing while you are in there

Found filming the building page on 20–21 Sep. All four are the page, not the data.

1. **The floor plate draws as a straight bar** for a curved building. Fixed by this handover.
2. **Roof z-fighting** — the roof speckles while the camera moves.
3. **The title disappears in the phone layout.** `#title` is `position:static` under `@media(max-width:820px)`, so it sits under
   the fixed canvas. A fixed position at `top:52px` fixes it.
4. **The plans open in a new tab** (`target=_blank`). A phone can't follow that, and neither can a screen recording — a lightbox
   in the card would read better and would film.

Two more, which I injected as film-only CSS to shoot video 04 and which are worth making real phone-layout fixes:

- **A card opens at the top, over the model**, so the floor you just tapped is hidden behind its own card. Opening it at the
  bottom, over the filter panel, keeps the tapped floor in view.
- **The 3D scene is centred exactly where the phone panel begins**, so the building sits behind the panel. Drawing the scene
  ~330 px higher puts it in the clear top half.

---

## 8. Checks before it ships

- `plates_sample_businessbay_574.json`, floor `"30"`: 26 cells, `labels["30"]` 27 entries, `basis === "units"`, first label
  `"3001"`, central `lift` + `stair` blocks, `tower === null`, `dm_use === null`.
- Al Habtoor Tower floor `"8"`: `dm_use === "services"` — the Municipality calls it services, the units register lists homes.
  The sentence must appear.
- Binghatti Aquarise (id `650`) any homes floor: `basis === "register"`, **no** `labels` — no unit numbers may render.
- DAMAC Hills id `5` (Golf Veduta) floor `"3"`: `skip === "small"` — nothing drawn, the reason shown. (135 such floors
  in DAMAC Hills, 127 in Business Bay.)
- Business Bay id `7` (DAMAC Towers By Paramount) floor `"1"`: `tower` non-null — the dashed footprint **and** the solid
  inner plate both drawn. (2,087 such floors in Business Bay.)
- No plate anywhere renders a number that is not in `labels`.

---

## 9. Not mine to decide

- **Whether an indicative layout belongs on a client-facing page at all.** Your `docs/TWIN_FLOOR_LAYOUT.md` says a unit is placed
  on its floor, never on the plate, and that is a deliberate rule. This spec puts real units on a plate at indicative positions,
  labelled as such on every view. Kendall has asked for the plate and has seen it; if you think the rule should still hold,
  raise it with him rather than with me.
- **The deploy.** Azimuth session, on Kendall's own go.

Questions to me in this session — I built the data and will change it. I am not touching the worker, the page, or anything under
the DDA session's ownership (`dda_api.py`, `dda_pull_all.py`, `load_gov_datasets.py`, the `gov_*` tables).

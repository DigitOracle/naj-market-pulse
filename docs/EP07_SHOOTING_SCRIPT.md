# EPISODE 07 — SHOOTING SCRIPT, cradle to grave

**"Is there anything left in it?"** · AL HABTOOR TOWER, Business Bay 574 · filmed 22 Sep 2026

Kendall, 22 Sep: *"I need the angle and the data and the buttons to be clear, I need to know the opening plate, and
client asking the query, and Naj walkthrough of the demo draft, cradle to grave."*

**Every control and every number below was read off the live page before it was written down.** Where something was
tried and failed it says so, because the failures cost more than the successes.

---

## 0 · HOW THE FILM IS ASSEMBLED

```
[ CLIENT'S QUESTION 10 s ]  →  [ OPENER 10 s ]  →  [ EPISODE 72 s ]
   HeyGen Cinematic,            HeyGen Cinematic,      the app, filmed by the harness
   a different face             FIXED, every film      + Naj over it
   every episode                never regenerated
```

Published length ≈ **92 seconds**. That is past the 45–60 s Reels band and the episode earns it, but **a shorter
Instagram cut is worth making from the same master** — trim the dossier from six stops to three.

The opener is `assets/brand/najma_opener_9x16.mp4`, approved final 22 Sep. Its prompts are in
`docs/NAJMA_OPENER_HEYGEN_CINEMATIC.md`. **Hard cut between all three parts, no dissolves.**

---

## 1 · THE CLIENT'S QUESTION — 10 s

Generated in HeyGen Cinematic with **no avatar reference**, so the face differs every episode. That is deliberate: it
reads as a question, not a recurring character.

> **"I keep walking past Al Hab-toor Tower. Is there anything left in it? And what's Business Bay actually like to
> live in?"**

**The three-part shape is the template and only the words inside it change per episode:**

    "I keep walking past [TOWER]. Is there anything left in it? And what's [DISTRICT] actually like to live in?"

**Two questions, deliberately.** The app answers the first. The dossier answers the second. That is what makes the
close the second half of the reply rather than a flourish.

**Pronunciation must be written phonetically.** "Marina Pinnacle" came back as *"Marina Pinedic"* and "Al Habtoor"
needs the same treatment. The full prompt, with the pronunciation block, is in this doc's companion message and in
`docs/NAJMA_OPENER_HEYGEN_CINEMATIC.md` §3's pattern.

---

## 2 · THE WALKTHROUGH — 17 shots, 72 s

Filmed by `NAJMA_VIDEO=8 python scripts/demo_capture.py all`. Shots 1–3 are the **district page**; 4–11 the **building
page**; 12–17 the **dossier**, scrolled.

| # | in · dur | ANGLE | BUTTON | DATA on screen | NAJ says |
|---|---|---|---|---|---|
| 1 | 0.0 · 4.0 | Business Bay from above, turning. **Real facades, nothing selected** | — | the district, its towers named | *(silent)* |
| 2 | 4.0 · 4.0 | the turn continuing | — | **AL HABTOOR TOWER** label arrives | "A client asked me about Al Habtoor Tower." |
| 3 | 8.0 · 3.5 | closing on the tower | — | 345 m of glassbronze among its neighbours | "Ninety-one levels, and a thousand seven hundred homes." |
| 4 | 11.5 · 3.0 | the building page. **Static** | **`ABOUT THE BUILDING`** | the card opens | "So I opened it." |
| 5 | 14.5 · 4.5 | **Dead still**, data dominant | — | **443 LEFT OF 1,739** | "Four hundred and forty-three of them are still unsold." |
| 6 | 19.0 · 3.5 | the type table | — | 1 bed 8–75 · 2 bed 8–82 · 3 bed 25–85 | "One beds, two beds, three beds — and which floors." |
| 7 | 22.5 · 4.5 | **the floor picker, pressed in frame** | **`fpick` → Floor 86** | *Level 86 of 91 · Homes on it 4* · **8601 · 5 B/R · 9,081 sq ft · 4,819 sq ft balcony** | "Then floor eighty-six. One flat. Nine thousand square feet." |
| 8 | 27.0 · 2.0 | **THE TURN** | — | the question turns | "But what is it like?" |
| 9 | 29.0 · 5.0 | the plate | — | **THE FLOOR PLATE · LEVEL 86**, drawn, with lifts and stairs | "Every home on the floor, drawn — by type, by size, with the lifts." |
| 10 | 34.0 · 4.5 | back out among its neighbours, **easing to a full stop** | — | the tower in Business Bay | "Fifty-two percent built, due at the end of this year." |
| 11 | 38.5 · 3.5 | held on the tower | — | clean | "And when she asks me to send her something —" |
| 12 | 42.0 · 3.5 | **the dossier**, scrolling | — | *The building · The stack, 91 levels + 3 below* | "I send her this. The stack, floor by floor." |
| 13 | 45.5 · 3.5 | scrolling | — | *What it sells for* | "What it sells for." |
| 14 | 49.0 · 3.5 | scrolling | — | **Designed and built by** | "Who designed it. Who built it." |
| 15 | 52.5 · 3.5 | scrolling | — | *Around it · Shops and groceries* | "What is around it. Where the shops are." |
| 16 | 56.0 · 3.5 | scrolling | — | *Who lives in Business Bay* — Europe 24%, Arab world 22%, South Asia 21% | "Who lives in Business Bay." |
| 17 | 59.5 · 3.5 | scrolling, then held 9 s | — | *The floor plate · level 9* | "And the floor plan itself." + sign-off |

**Shot 10 is the only shot allowed to come to a complete stop.** Motion into stillness is the full stop — the
signature move that replaced the occlusion reveal when that proved unfilmable.

### The controls, by their real names

| Control | id | Used | Note |
|---|---|---|---|
| **`ABOUT THE BUILDING`** | `about` | shot 4 | **Dead until 22 Sep** — the handler threw `K is not defined` and took the whole card with it. Fixed v245.1 |
| **floor picker** | `fpick` | shot 7 | pressed **in frame** with the drawn cursor; the tower's band then jumps to level 86 |
| bedroom chips `1/2/3 BHK` | — | not used | |
| compass `N…NW` | — | not used | this is not the views episode |
| `THE DOSSIER · PDF` | `dossbtn` | not used | the dossier is scrolled instead, shots 12–17 |
| `THE PLANS` | `plansbtn` | **absent** | correctly — see §4 |

### Two things tried that do not work

- **Tapping a floor on the tower.** Raycast at eight heights up Al Habtoor: the card opened every time and selected
  **Ground floor** every time. The tower is not floor-tappable. Reported, not chased.
- **Opening on the building page.** Deep-linking selects the building and repaints it by home type, so the hero shot
  was a mustard block and the 345 m glass facade was never seen. Shots 1–3 now use the district page.

---

## 3 · EVERY NUMBER, AND WHERE IT COMES FROM

| Naj says | on screen | register |
|---|---|---|
| ninety-one levels | *Level 86 of 91*; dossier *91 levels + 3 below ground* | Dubai Municipality floor register |
| a thousand seven hundred homes | *1,739 registered — 1,739 residential* | DLD units register |
| four hundred and forty-three still unsold | **443 LEFT OF 1,739** | DLD units + transactions |
| which floors | 1 bed 8–75 · 2 bed 8–82 · 3 bed 25–85 | DM floor register × DLD units |
| floor 86, one flat, nine thousand sq ft | *8601 · 5 B/R · 9,081 sq ft · 4,819 sq ft balcony* | DLD units register |
| 52% built, due end of this year | dossier *ACTIVE · Built 52% · Due 2026-12-31* | DLD project register |
| who designed it, who built it | dossier *Designed and built by* | DM contractor and consultant registers |
| who lives in Business Bay | Europe 24% · Arab world 22% · South Asia 21% | DEWA customer register, community level |

### ⚠️ The number that needs care

**443 LEFT OF 1,739 is TRUE on this building** because its sales have not exceeded its units.

It is **not** true everywhere. The same block computes `Math.max(0, units − sales)`, and against resale history that
floors to zero: **304 buildings citywide were reading sold out and were not.** Marina Pinnacle showed *8 LEFT OF 772*
against 2,278 sales on 772 homes. Fixed in v246 on 22 Sep, and **Al Habtoor was checked specifically before filming.**
**If this episode is ever re-cut on another building, check that first.**

### Never said, because nothing supports it

- Which individual homes are unsold — the register publishes counts by type, never a list.
- That the 443 are **available**. Unsold is not available; availability needs a developer sheet and we hold none for
  this building. We do hold live sheets for ten developers — Arada, Beyond, Binghatti, Fakhruddin, Imtiaz, Palma,
  PrestigeOne, Select — but those are off-plan schemes.
- The contractor as **this building's**. The dossier says it on its own face: the plot carries 64 buildings.
- A per-type yield. One building-level figure repeated across rows is not a per-type yield.
- **66 as the building's height.** 66 is the count of *residential* floors and it appears on the page legitimately. The
  height is 91 levels. Saying "72 floors" over a line reading "66 residential floors" looks like an error to anyone
  reading.

---

## 4 · WHAT WENT WRONG ON THIS BUILDING'S PAGE, AND WHEN

All found by opening the page rather than by any test, all fixed the same day:

| | |
|---|---|
| **Wrong developer's floor plans** | Marina Pinnacle served Sobha's *The Pinnacle* layouts — ten buildings citywide. Fixed |
| **ABOUT dead** | `K is not defined` on click. Dead on **every building with a dossier since v220**. Fixed v245.1 |
| **DEWA never rendered** | it lives *inside* the About handler; the throw killed it first. Shipped 22 Sep, never seen until 22 Sep |
| **Black triangle** | the pillars radar drew `fill: rgb(0,0,0)` — a pillar stylesheet shipped as literal characters because `' + PILLAR_CSS + '` was concatenated inside a template literal. Fixed |
| **Sold out when not** | `Math.max(0, units − sales)`. 304 buildings. Fixed v246 |

**The pattern worth keeping:** every one was caught by someone about to *use* the output, not by anything testing it.
A test can prove markup is present; it cannot prove styling arrived, a handler runs, or a number means what it says.

---

## 5 · AFTER THE CUT

1. **HeyGen** — paste `NAJMA_EP07_HABTOOR_HEYGEN_SCRIPT.txt`. **143 words ≈ 52 s.** Short means the voice is faster
   than measured: nudge the speed down, **never trim the video**.
2. **Composite** — head above y 1600, ≤20% of frame, no bubble, fades in at 3.4 s. One grain pass over the flattened
   frame; light wrap; contact shadow; drift her 0.5–1% with the camera.
3. **Captions** burned in, neutral face, bottom band.
4. **Caption copy** ends with a keyword comment CTA **and** a question.
   > *Comment HABTOOR and I'll send you the floor-by-floor list. Which building should I check next?*
5. **Publish** — Instagram: no hashtags or one. TikTok: the 12–15 set. **AI label on both.**
6. **File** — `Demo_Videos\Najma_Market_Pulse\`, `Visualization_Engine\`, mirror to `Downloads\31DigitAlchemy\Azimuth\`,
   audit line in the root README.
7. **Answer comments for the first three hours.**

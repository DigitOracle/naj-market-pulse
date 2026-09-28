# EPISODE 08 — SHOOTING SCRIPT

**"Can we walk to a pharmacy, a clinic, and a good school?"** · BUSINESS BAY · filmed 28 Sep 2026

Kendall picked this on 28 Sep as the everyday-life episode. It answers five bank questions in one film: Q002
pharmacy, Q004 clinic, Q028/Q029 schools and their ratings, Q013 what is within reach.

**Every figure below was read off the live map before a word of narration was written**, and the answer changed
because of it: Business Bay has **no school inside it**. The honest reply is two out of three, and the film says so.
That is the episode — a broker who tells you the part you did not want to hear.

---

## 0 · HOW THE FILM IS ASSEMBLED

```
[ OPENER 10 s ]  ->  [ CLIENT'S QUESTION ~8 s ]  ->  [ EPISODE ~32 s ]
  fixed, every film     HeyGen Cinematic,           the live map, filmed by the harness,
                        a new face                  Naj composited over it by HeyGen
```

Order as settled 23 Sep: the opener first, then the stranger's question, then Naj. Hard cuts, no dissolves.

**Screen capture:** `NAJMA_VIDEO=10 python scripts/demo_capture.py all` (harness journey 10 = episode 08).
7 shots, 35.6 s including a 9 s hold on the last frame for the sign-off. HeyGen fits the background to the
narration, so the delivered episode will run to the ~32 s of voice, not the raw 35.6 s.

**Filmed in a quiet window.** Several rebuilds were running on 28 Sep, so every active session was asked first:
Rings (no deploy, no KV push), DDA (paused), LOD 3 CityEngine (held its lock through the take), the Unreal
rebuild (paused), Sobha (idle). The machine had 12.9 GB free during the capture. A real-time capture under
memory pressure stutters — check with the rebuild sessions before any re-shoot.

**Research only** (Kendall, 28 Sep): not for publication, so no on-screen AI disclosure. If a cut is ever
published, template §0.1 applies in full.

---

## 1 · THE CLIENT'S QUESTION

Generated in HeyGen Cinematic with **no avatar reference** — a different face every episode.

**Spoken line:**

> **"We're moving to Business Bay with two kids. Can we walk to a pharmacy, a clinic, and a good school?"**

20 words, about 7.3 s at the measured 0.364 s/word.

This departs from the ep07 template ("I keep walking past [TOWER]…") because the question is about a district,
not a tower. The shape that carries over: a real person, first person, one breath, a question the app can answer.

### The full shot description — paste into "Describe your shot"

```
A cinematic vertical 9:16 shot, about eight seconds long, of a woman in her mid-thirties
speaking directly to camera, as if asking a trusted friend a practical question.

THE SETTING. A bright, modern Dubai apartment in the late afternoon, mid-move: two sealed
cardboard moving boxes on a pale wooden floor behind her, a large window with soft,
out-of-focus towers beyond it, warm natural light from the side. Calm, lived-in, real.
Not a showroom and not a studio.

THE WOMAN. A mother in her mid-thirties, casual and put-together: a plain light top, hair
tied back. Warm, a little tired from the move, practical. She is framed from the chest up,
centred, eye line to the lens.

THE ACTION. She is already in frame when the shot begins. She looks into the lens and asks
her question in one natural breath, with a slight rise of hope on the last few words, as
if this is the thing that will decide it. She speaks EXACTLY these words and no others:
"We're moving to Business Bay with two kids. Can we walk to a pharmacy, a clinic, and a
good school?"
When she finishes she holds the look for about half a second, eyebrows slightly raised,
waiting for the answer. She does not nod, smile broadly or speak again.

PRONUNCIATION. "Business Bay" is said BIZ-niss BAY, two clear words.

DIALOGUE, stated once more because it matters: she says only "We're moving to Business
Bay with two kids. Can we walk to a pharmacy, a clinic, and a good school?" Nothing
before it, nothing after it, no other words.

CAMERA. Locked off on a tripod for the whole shot. No pan, tilt, push, pull, handheld
drift or rack focus. 50mm lens, shallow depth of field: her face sharp, the room softly
out of focus.

GRADE. Natural daylight colour, warm but not orange. Skin looks like skin. Like a
documentary interview, not an advert.

DO NOT: add any text, captions, subtitles, logos, watermarks or on-screen graphics. Do
not add children, other people or pets in frame. Do not have her gesture with her hands,
hold a phone, or point. Do not add a second line of dialogue, a greeting, or a
reaction after the question. Do not change the words of the question in any way. Do not
move the camera. Do not add music cues, lens flares or particles.
```

The dialogue is stated three times — before the action, inside it, and in the DO NOT — because Cinematic mode
invents its own lines otherwise (bible §9.2). **Check the render for exact words before using it.**

---

## 2 · THE WALKTHROUGH — 7 shots

Filmed on `/map`, Business Bay picked from the search box, nothing selected. **Map only**: the building page's
LOCATION axis carries a different DHA guard, so the two surfaces never share a frame (bible 14.3).

| # | shot | on screen | NAJ says |
|---|---|---|---|
| 1 | 2.6 s | Business Bay, no layer lit | "Business Bay, with two children." |
| 2 | 4.5 s | **PHARMACIES** chip pressed with the drawn cursor | "Pharmacies first. Seventy-eight within three kilometres of the heart of Business Bay." |
| 3 | 3.3 s | held on the list: *Shefaa Al Madeena · 418 m* at the top | "The nearest is about four hundred metres away." |
| 4 | 4.5 s | pharmacies off, **CLINICS** pressed | "Clinics. More than a hundred and twenty." |
| 5 | 3.3 s | held: *Covent Clinic · 264 m* at the top | "The closest, under three hundred metres." |
| 6 | 4.5 s | clinics off, **SCHOOLS** pressed — the pins land at the edges, none inside | "Schools are the honest part." |
| 7 | 4.1 s + 9 s | held: *16 within 3 km*, nearest 2.0 km, *Good* and *Very good* ratings | "There isn't one inside Business Bay. The nearest are two kilometres out, and several are rated Good or Very Good." + close |

**Close:** "So walk to the pharmacy and the clinic, and drive to school. Welcome to Azimuth. Dubai, decoded, one tap
at a time. Complexity into clarity."

88 words, about 32 s.

---

## 3 · EVERY NUMBER, AND WHERE IT COMES FROM

Read from the live `azimuth-2` map on 28 Sep 2026, Business Bay picked, radius 3 km from the district centre.

| said | on screen | source | check |
|---|---|---|---|
| seventy-eight pharmacies | chip PHARMACIES 78, header "78 within 3.0 km · nearest 40 shown" | DHA facility register, walk-in pharmacies only | header fixed 27 Sep (b10ec83) — chip and header agree |
| about four hundred metres | Shefaa Al Madeena 418 m | DHA, **exact** position (no ≈) | verified exact 24 Sep |
| more than a hundred and twenty clinics | chip CLINICS 124 | DHA facility register | |
| under three hundred metres | Covent Clinic 264 m | DHA, no ≈ on the row | |
| no school inside Business Bay | chip SCHOOLS 16, "0 in community" | KHDA + ESE registers | |
| nearest two kilometres out | Clarion, GEMS Our Own Indian School, Global Indian, Dubai International Private School, all 2.0 km | KHDA positions | |
| Good or Very Good | GEMS Our Own Indian School and JSS Private School *Very good*; Clarion, Global Indian, DIPS, Japanese School *Good* | KHDA inspection ratings | |

### What must not be said

- **Not "from your door".** Every distance is from the centre of Business Bay, and the panel header says so. A
  family's own walk depends on their building.
- **Not an exact distance for a row marked ≈.** Those are DHA positions rounded to about 555 m. Only the two
  distances quoted above are exact, and both were checked.
- **Not "the best school".** Ratings are KHDA inspection grades; two nearby schools are *not yet inspected*, which
  says nothing about their quality.
- **Not a pharmacy count from business licences.** A licence records a registered office, not a shop
  (blockers.licence_address_is_not_premises). These are licensed premises from DHA.

---

## 4 · AFTER THE CUT

1. Generate the client question (section 1) and check the words.
2. Generate Naj's episode over `data/demo/demo01_businessbay_screen.mp4` with the narration in section 2.
3. Assemble: opener → question → episode, hard cuts.
4. Captions burned in, low centred band beneath Naj. The transcriber is the timing source, never the text source
   (bible §8): check "Shefaa", "Covent", "Business Bay" and every number at word level before grouping.
5. File to `Visualization_Engine\`, mirror to `Downloads\31DigitAlchemy\Azimuth\` and `Downloads\`.

# EPISODE 08 — SHOOTING SCRIPT

**"A day in Business Bay"** · a UK family with two small children · narrative approved by Kendall, filmed 28 Sep 2026

The first film made under the rule Kendall set on 28 Sep: **write the narrative (~1:30), get it approved, then
build.** An earlier draft was filmed before its narrative existed; it was discarded and re-shot to the approved words.

Every figure was read off the live map before the narrative went to Kendall, and two of them changed the story:
**Business Bay has no school inside it**, and **no official source places a park in or near it**. The film says both.

---

## 0 · HOW THE FILM IS ASSEMBLED

```
[ SEEDANCE OPENER 10 s ] -> [ FLY-THROUGH 20 s ] -> [ CLIENT'S QUESTION ~11 s ] -> [ EPISODE ~70-85 s ]  ~2:00 all-in
  fixed: gold N, Naj        Sobha's Unreal          HeyGen Cinematic,            live map + residents page,
  walks in (bible 9.3)      Business Bay, no text   new face                     Naj composited by HeyGen
```

**Order set by Kendall, 28 Sep:** the Seedance opener first, then the fly-through, then this episode. The opener is
the fixed master `assets/brand/najma_opener_9x16.mp4` (10.05 s, 720x1280, 24 fps): used unchanged, scaled to
1080x1920 at assembly. The opener still comes first, as the bible requires; the fly-through is the new second slot.

**The fly-through** (via the Sobha session): 20 s of the Unreal Business Bay fly-through. A high establishing orbit
(~7 s), a descent to the canal and towers with trees, cars and boats (~8 s), then a steady closing frame (~5 s) on the
Marasi Drive canal side. 1080x1920, 25 fps, no text, logos or voice. File: `data/media/ep08/teaser_businessbay_9x16.mp4`.

**Screen capture:** `NAJMA_VIDEO=10 python scripts/demo_capture.py all` (harness journey 10 = episode 08).
18 shots, 84.5 s cut including a 9 s hold for the sign-off (re-shot 28 Sep with the zoom beats).
HeyGen fits the background to the narration.

**Filmed in a window arranged with every running session** (Rings, DDA, the LOD 3 CityEngine bridge, the Unreal
L_Dubai rebuild, Sobha). Free RAM fell to 0.6 GB during the take while Unreal imported; the frame timing was checked
afterwards and held. Check with those sessions before any re-shoot.

**Research only, internal only** (Kendall, 28 Sep): not for social media or publication, so no on-screen AI disclosure. Reopen template §0.1 if a
cut is ever published.

**No 3D beat.** The approved narrative has none. If Kendall wants B-roll, the natural slot is the hospital line: an
existing Business Bay aerial (Sobha session's option b), a generic ambulance small in frame, and no rendering of the
real hospital or any red crescent or cross emblem.

---

## 1 · THE CLIENT'S QUESTION

Generated in HeyGen Cinematic with **no avatar reference** — a different face every episode.

> **"We're moving to Business Bay from the UK with two little ones. Is there a good British school, a clinic, a park —
> and what can we actually walk to?"**

30 words, about 11 s at the measured 0.364 s/word.

### The full shot description — paste into "Describe your shot"

```
A cinematic vertical 9:16 shot, about eleven seconds long, of a British woman in her
mid-thirties speaking directly to camera, as if asking a trusted friend a practical question.

THE SETTING. A bright, modern Dubai apartment in the late afternoon, mid-move: two sealed
cardboard moving boxes on a pale wooden floor behind her, a large window with soft,
out-of-focus towers beyond it, warm natural light from the side. Calm, lived-in, real. Not a
showroom and not a studio.

THE WOMAN. A mother in her mid-thirties with a natural British accent, casual and put-together:
a plain light top, hair tied back. Warm, a little tired from the move, practical. Framed from
the chest up, centred, eye line to the lens.

THE ACTION. She is already in frame when the shot begins. She looks into the lens and asks her
question naturally, in two short breaths, with a slight rise of hope on the last line, as if
this is what will decide it. She speaks EXACTLY these words and no others:
"We're moving to Business Bay from the UK with two little ones. Is there a good British school,
a clinic, a park — and what can we actually walk to?"
When she finishes she holds the look for about half a second, eyebrows slightly raised, waiting
for the answer. She does not nod, smile broadly or speak again.

PRONUNCIATION. "Business Bay" is said BIZ-niss BAY, two clear words.

DIALOGUE, stated once more because it matters: she says only "We're moving to Business Bay from
the UK with two little ones. Is there a good British school, a clinic, a park — and what can we
actually walk to?" Nothing before it, nothing after it, no other words.

CAMERA. Locked off on a tripod for the whole shot. No pan, tilt, push, pull, handheld drift or
rack focus. 50mm lens, shallow depth of field: her face sharp, the room softly out of focus.

GRADE. Natural daylight colour, warm but not orange. Skin looks like skin. Like a documentary
interview, not an advert.

DO NOT: add any text, captions, subtitles, logos, watermarks or on-screen graphics. Do not add
children, other people or pets in frame. Do not have her gesture with her hands, hold a phone or
point. Do not add a second line of dialogue, a greeting, or a reaction after the question. Do not
change the words of the question in any way. Do not move the camera. Do not add music cues, lens
flares or particles.
```

The dialogue is stated three times, because Cinematic mode invents lines otherwise (bible §9.2). **Check the render
word for word before using it.**

---

## 2 · THE WALKTHROUGH — approved narrative over 18 shots

Map shots on `/map` with Business Bay picked; shots 13–14 on the residents page. **Map only** for amenities: the
building page's LOCATION axis never shares a frame with the map layer (bible 14.3). **The park layer is never lit**:
its rows are OpenStreetMap, unconfirmed by any official source.

**Every list gets a zoom** (Kendall, 28 Sep): the nearest row is clicked, the map flies to it, the card opens, and the
map wheels in to street level. Distances in the next list stay measured from the centre of Business Bay (probed: a
row click does not move the reference point). Between beats, off camera, the card is closed, the layer cleared and
Business Bay re-picked. **Schools are the exception**, see the correction below.

| # | on screen | NAJ says |
|---|---|---|
| 1 | Business Bay, nothing lit | "Let's walk through a day, from the middle of Business Bay." |
| 2 | **SCHOOLS** pressed — pins land at the edges, none inside | "The school run first. There's no school inside Business Bay." |
| 3 | held: the list, *Horizons English School · Outstanding · UK · 2.4 km* | "The best-rated British one nearby is Horizons English School, rated Outstanding, about two and a half kilometres away. A drive. Harrow is as close, but not yet inspected." |
| 4 | **CLINICS** pressed | "If one of them wakes up with a temperature: a clinic under three hundred metres away," |
| 5 | held: *Covent Clinic · 264 m* | |
| 6 | row clicked: the map flies to Westburry Tower 1, Marasi Drive; card open | |
| 7 | **PHARMACIES** pressed | "a pharmacy about four hundred." |
| 8 | held: *Shefaa Al Madeena · 418 m* | "Both walkable." |
| 9 | row clicked: zoom to U-Bora Tower 4, Marasi Drive; card open | |
| 10 | **HOSPITALS** pressed | "The nearest hospital, Emirates Hospital, is about a kilometre and a half." |
| 11 | held: *Emirates Hospital · 1.6 km* | "A short drive." |
| 12 | row clicked: zoom to Emirates Hospital, Jumeirah; card open | |
| 13 | the map pulls back to a wider view, no layer | "After school, the park. The nearest one on the Municipality's own list is Al Safa Park, about two kilometres away. Smaller green spaces closer aren't on any official list, so I won't promise one." |
| 14 | **METRO** pressed | "And for you, the Red Line." |
| 15 | held: *Business Bay Metro Station · Red line · 1.5 km* | "Business Bay station is about a kilometre and a half," |
| 16 | row clicked: zoom to the station; card open | "around twenty minutes on foot." |
| 17 | residents page: UK chip on, Business Bay card, Europe expanded | "You won't be the only Brits. About a quarter of your neighbours are European," |
| 18 | held on the card | "and the British are among the four biggest nationalities. So the clinic and the pharmacy, you walk to. School, the hospital and the park, you drive." + sign-off |

**Sign-off:** "Welcome to Azimuth. Dubai, decoded, one tap at a time. Complexity into clarity."

Naj: about 194 words, ~70 s, over an 84.5 s background. The zoom shots add no words, so either HeyGen's fit or a
trim of the holds closes the gap.

### CORRECTION NEEDED — the school line (found 28 Sep, after approval; needs Kendall's OK)

Zooming on Horizons put its ring on a pin labelled **"Japanese School"**. The KHDA register gives school positions to 2
decimal places, and Horizons, Harrow, the Japanese School, JSS and DBS Mira all share one point (55.25, 25.19). The DDA
session confirmed nothing official is finer. **Harrow's own KHDA address is in Al Barsha Second**, far from that point,
so *"Harrow is as close"* is false. Horizons' KHDA area is Al Wasl, so "a couple of kilometres, a drive" still holds, but
2.4 km is not exact. Bank blocker: `khda_school_positions_rounded`.

Proposed replacement for shot 3 (drops the Harrow sentence, softens the distance):

> "The best-rated British one nearby is Horizons English School, in Al Wasl, rated Outstanding. A couple of
> kilometres. A drive."

Shot 3 stays a hold on the list with no zoom. The take already filmed works with either wording.

---

## 3 · EVERY NUMBER, AND WHERE IT COMES FROM

Read from the live `azimuth-2` map on 28 Sep 2026, Business Bay picked, straight-line from the district centre
(55.2726, 25.18358).

| said | on screen | source |
|---|---|---|
| no school inside Business Bay | SCHOOLS chip "16 · 0 in community" | KHDA + ESE registers |
| Horizons English School, Outstanding, a couple of km (proposed) | 2.4 km, Outstanding · UK, position rounded to 2 dp | KHDA inspection rating; area Al Wasl |
| ~~Harrow as close~~ (FALSE, cut) | Harrow's pin sits at the shared rounded point; its address is Al Barsha Second | KHDA school_search |
| clinic under 300 m | Covent Clinic 264 m (no ≈) | DHA facility register, exact position |
| pharmacy ~400 m | Shefaa Al Madeena 418 m (no ≈) | DHA, exact position |
| Emirates Hospital ~1.5 km | 1.6 km, General Hospital | DHA facility register |
| Al Safa Park ~2 km | not shown — the park layer stays off | Dubai Municipality parks table: nearest listed park 2,099 m (checked by the DDA session) |
| Business Bay station ~1.5 km, ~20 min | Business Bay Metro Station, Red line, 1.5 km | RTA stations |
| a quarter European; British among the four biggest | residents page, Business Bay | DEWA account holders: Europe 24% (largest region); UK 6%, fourth nationality |

### What must not be said

- **Not "from your door".** Every distance is from the centre of Business Bay. Real walks are longer than the
  straight line; "around twenty minutes" is 1.5 km at a normal pace.
- **Not a park count or distance from the map layer.** Those rows are OpenStreetMap; the DDA session found no official
  source placing any park in or near Business Bay. The Al Safa Park distance is to a point inside a large park.
- **Not A&E or emergency.** The register says General Hospital; nothing on emergency capability.
- **Not "families" for the neighbours.** The figures count utility-account holders, never households.
- **Not an exact distance for any row marked ≈.**

---

## 4 · AFTER THE CUT

1. Generate the client question (section 1); check the words.
2. Generate Naj over `data/demo/demo01_businessbay_screen.mp4` with the section 2 narration.
3. Assemble Seedance opener → fly-through → question → episode, hard cuts; scale the 720x1280 opener to 1080x1920 and resample everything to 25 fps.
4. Burn captions in the low centred band beneath Naj; fix at word level before grouping: "Horizons", "Harrow",
   "Covent", "Shefaa", "Al Safa", "Business Bay", every number.
5. File to `Visualization_Engine\` and `Downloads\` (the `Downloads\31DigitAlchemy\Azimuth\` mirror no longer exists).

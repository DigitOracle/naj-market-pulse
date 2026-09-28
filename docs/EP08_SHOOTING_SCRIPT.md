# EPISODE 08 — SHOOTING SCRIPT (v2)

**"Business Bay, as a whole"** · a UK family with two small children · narrative v2 approved by Kendall, filmed 28 Sep 2026

**Internal only, research only** (Kendall, 28 Sep): not for social media or publication, so no on-screen AI disclosure.
Reopen template §0.1 if a cut is ever published.

**Why v2.** v1 quoted distances from the centre of Business Bay to single places ("a clinic under three hundred
metres"). Kendall, 28 Sep: *"we were talking about Business Bay on a whole … we shouldn't be saying kilometres …
just say how many clinics, how many hospitals, how many schools and the closest metro station, and then we end with
the nationality."* v2 counts, and uses the map's **count within** filter to widen or narrow the circle on camera.

---

## 0 · HOW THE FILM IS ASSEMBLED

```
[ SEEDANCE OPENER 10 s ] -> [ CLIENT'S QUESTION 8-10 s ] -> [ FLY-THROUGH 20 s ] -> [ EPISODE ~87 s ]   ~2:05
  fixed master               Seedance: UK mother,            Sobha's Unreal         live map + residents page,
  (bible 9.3)                two small children              Business Bay           Naj composited by HeyGen
```

**Order, Kendall 28 Sep:** the Seedance opener first, then the Seedance client question, then this video.

- **Opener:** `assets/brand/najma_opener_9x16.mp4`. Kendall put the same file at the top of Downloads as
  `Najma_Property's_Golden_Star.mp4`: md5 identical, 10.05 s, 720x1280, 24 fps, with audio. Used unchanged and scaled
  to 1080x1920 at assembly.
- **Fly-through placement is an assumption.** Kendall's latest order does not mention it. Placed after the question,
  it becomes the episode's first image: Naj's opening line ("Let's look at Business Bay as a whole") plays over it,
  then the map takes over. If Kendall wants it before the question, swap the two clips; nothing else changes.
  Spec (Sobha session): 20 s. A high orbit (~7 s), a descent to the canal and towers (~8 s), then a steady close
  (~5 s). 1080x1920, 25 fps, no text, logos or voice. File: `data/media/ep08/teaser_businessbay_9x16.mp4`.

**Screen capture:** `NAJMA_VIDEO=10 python scripts/demo_capture.py all` (harness journey 10 = episode 08).
16 shots, 87.2 s cut, including a 9 s hold for the sign-off. Filmed with 12 GB free and the Unreal render not yet
running.

---

## 1 · THE CLIENT'S QUESTION — Seedance, 8-10 s

> **"We're moving to Business Bay from the UK with two little ones. What's nearby — schools, clinics, a park,
> the metro?"**

20 words, about 7.5 s spoken, and the clip runs 8-10 s with a beat either side.

### The prompt — paste into Seedance

```
Vertical 9:16, about nine seconds, cinematic, natural daylight.

A British mother in her mid-thirties sits on a pale sofa in a bright, newly rented Dubai
apartment, mid-move: two sealed cardboard boxes behind her, a big window with soft,
out-of-focus towers beyond. A small girl of about four leans against her side; a boy of
about two sits on her lap, holding a toy. The children are calm and do not speak.

She looks straight into the lens and asks, warmly, with a natural British accent, in one
easy breath:
"We're moving to Business Bay from the UK with two little ones. What's nearby — schools,
clinics, a park, the metro?"
She finishes with a small hopeful smile and holds the look for a second.

Camera locked off, chest-up framing of the mother with both children in frame, 50mm, shallow
depth of field. Warm natural grade, skin looks like skin, documentary rather than advert.

No text, captions, logos or watermarks. No other adults. The children do not talk. She says
only those words, nothing before and nothing after.
```

**Check the render word for word**, and check that the children stay silent and that the hands and faces hold up.
Generated people are fictional; no real family is depicted.

---

## 2 · THE WALKTHROUGH — approved narrative v2 over 16 shots

Map shots on `/map`, with Business Bay picked, then the residents page. The **count within** strip (`#scw`:
community / 1 / 2 / 3 / 5 / 10 km) is set to "community" off camera before each layer, then stepped on camera.
Resets between beats happen off camera (`cut()` drops everything between shots). **The park layer is never lit.**

Only the two places Naj names get a zoom. The map wheels in nine ticks to building level, and the cut adds a
push-in: 1.9x for the hospital, 2.5x for the station, whose label the map draws smaller. Kendall, 28 Sep: at three
ticks the labels could not be read on a phone.

| # | on screen | NAJ says |
|---|---|---|
| 1 | Business Bay, nothing lit (or the fly-through's close) | "Let's look at Business Bay as a whole, from its centre." |
| 2 | **SCHOOLS**, community: *0 in Business Bay* | "Schools first. Inside Business Bay itself, there are none." |
| 3 | filter → 3 km: *16* | "Widen the circle to three kilometres and there are sixteen," |
| 4 | held: the list, Horizons English School · Outstanding · UK | "including Horizons English School, rated Outstanding. So the school run is a drive." |
| 5 | **CLINICS**, community: *61* | "Clinics are the opposite. Sixty-one inside Business Bay," |
| 6 | filter → 1 km: *27* | "and twenty-seven within a kilometre of the centre." |
| 7 | **PHARMACIES**, community: *26* | "Pharmacies too: twenty-six in the district," |
| 8 | filter → 1 km: *19* | "nineteen within a kilometre." |
| 9 | **HOSPITALS**, community: *1* | "There's one hospital inside Business Bay," |
| 10 | zoom: Emirates Hospital L.L.C, beside Sobha SkyParks on Sheikh Zayed Road | "Emirates Hospital," |
| 11 | hospitals at 3 km: *4* | "and four within three kilometres." |
| 12 | the map pulls back, no layer | "For the park, the nearest on the Municipality's own list is Al Safa Park, a short drive. Smaller green spaces aren't on any official list, so I won't promise one." |
| 13 | **METRO**, community: *1* | "And for you, the Red Line." |
| 14 | zoom: Business Bay Metro Station | "Business Bay has its own station, on the district's edge." |
| 15 | residents page: UK chip on, Business Bay card, Europe expanded | "You won't be the only Brits. About a quarter of your neighbours are European," |
| 16 | held on the card | "and the British are among the four biggest nationalities. So clinics and pharmacies are all around you. School and the park mean a drive." + sign-off |

**Sign-off:** "Welcome to Azimuth. Dubai, decoded, one tap at a time. Complexity into clarity."

Naj: 179 words, ~65 s, over an 87 s background. HeyGen fits the background to the narration, or the holds are
trimmed; the fly-through can take the first line.

---

## 3 · EVERY NUMBER, AND WHERE IT COMES FROM

Read from the live `azimuth-2` map on 28 Sep 2026, Business Bay picked. "Community" means inside the Business Bay
boundary. The radii are measured from the district centre (55.2726, 25.18358). All counts were checked on the
filmed frames.

| said | community | 1 km | 3 km | source |
|---|---|---|---|---|
| schools: none inside, sixteen within 3 km | 0 | 0 | 16 | KHDA + ESE registers |
| clinics: 61 inside, 27 within 1 km | 61 | 27 | 124 | DHA facility register |
| pharmacies: 26 inside, 19 within 1 km | 26 | 19 | 78 | DHA facility register |
| one hospital inside (Emirates Hospital), four within 3 km | 1 | 0 | 4 | DHA facility register |
| Business Bay has its own station | 1 | 0 | 2 | RTA stations |
| Al Safa Park, the nearest on the Municipality's list | — | — | — | DM parks table (checked by the DDA session) |
| a quarter European; British among the four biggest | — | — | — | DEWA account holders: Europe 24%; UK 6%, fourth |

### Caveats behind the numbers

- **Schools at 3 km are soft.** KHDA gives positions to 2 decimal places (bank blocker `khda_school_positions_rounded`),
  so a school near the 3 km line can fall either side of it. "None inside Business Bay" is safe. Harrow's pin sits at
  a shared rounded point while its address is Al Barsha Second, so **never say Harrow is nearby**.
- **Emirates Hospital counts as inside** by its DHA register position, which the zoom shows beside Sobha SkyParks on
  Sheikh Zayed Road. Its licence address reads Jumeirah Second: a registered address is not the premises (bank
  blocker `licence_address_is_not_premises`).
- **Clinic and pharmacy counts** include rows whose DHA position is approximate (marked ≈ in the list); a few near a
  boundary could fall either side.

### What must not be said

- **No distances to single places.** That was v1's mistake. Radii are "within a kilometre of the centre", never
  "from your door".
- **No park count or distance from the map layer.** Those rows are OpenStreetMap, and no official source places a park
  in Business Bay.
- **Not A&E or emergency.** The register says General Hospital, and nothing on emergency capability.
- **Not "families" for the neighbours.** The figures count utility-account holders, never households.

---

## 4 · AFTER THE CUT

1. Generate the client question in Seedance (section 1); check the words and the children.
2. Generate Naj over `data/demo/demo01_businessbay_screen.mp4` with the section 2 narration.
3. Assemble: Seedance opener → question → fly-through → episode, hard cuts. Scale the 720x1280 opener to 1080x1920
   and resample everything to one frame rate.
4. Burn captions in the low centred band beneath Naj. Fix at word level before grouping: "Horizons", "Emirates
   Hospital", "Al Safa", "Business Bay", and every number.
5. File to `Visualization_Engine\` and `Downloads\`.

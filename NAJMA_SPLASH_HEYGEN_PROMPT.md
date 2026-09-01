# NAJMA SPLASH — HeyGen Avatar Shot prompt (v2, 1 Sep 2026)

**Purpose:** ~11s Hollywood opening for the Najma board splash — her twin talking to HER.
This is the demo moment that sells the app.
**Refs (2 only, already in Downloads TOP, 9:16 pre-cropped):**
- `NAJMA_SPLASH_REF1.jpg` — FIRST FRAME plate (Dubai Marina at night, warm golden waterfront)
- `NAJMA_SPLASH_REF2.jpg` — LAST FRAME plate (the landmark tower at night, clean dark sky in the
  upper third — the app fades the "Najma نجمة" wordmark into that sky; NO text in the render)
**Steps:** upload both refs → select her Digital Twin in the UI → paste the block.
**After render:** save as `splash.mp4` → `python scripts\push_assets.py --splash path\to\splash.mp4`
(env AZIMUTH_URL, INGEST_TOKEN). The board splash activates automatically once `/img/splash` exists.
**Timing:** 25 words / 4 sentences ≈ 11s (0.36w + 0.5s). Avatar Shot cap is 15s — comfortable.

---

```
UI SETTINGS — Avatar Shot (Seedance) · vertical 9:16 · target ~11s (length set by voice track) · Digital Twin: select her twin in the UI · voice: the twin's own · quality: highest · references: REF1 = first frame, REF2 = last frame

PROJECT — "Najma splash": the cinematic cold-open of her own market app. Her digital twin greets HER by nickname — playful, confident, movie-trailer energy. The city carries the glamour; she carries the frame. Ends held and calm so the app can fade its wordmark into the final frame's dark sky (NO text, NO logos in this render).

REFERENCES — use the avatar / reference twin provided; inherit everything from the twin. REF1 is the opening background: Dubai Marina at night, golden tower lights doubled in black water, promenade glow. REF2 is the closing background: the landmark tower soaring at night in a champagne-on-black grade, vast clean dark sky above it.

GRADE — one grade across all shots: deep black night, city lights in warm champagne gold, faint teal cast in the shadows, gentle anamorphic-style flares on the brightest lights, soft gold rim light on the presenter. Luxurious, calm, expensive. Low cinematic underscore with soft night-city ambience under the voice.

SCRIPT (lipsynced, warm and playful, a knowing smile — she is talking to herself in the mirror and loving it):
"Good morning, Black Coffee. While you were sleeping, Dubai kept score — and the numbers are juicy. Grab your coffee, superstar. Let's go run this town."

SHOT PLAN — the avatar continuous in the foreground; backgrounds hard-cut behind her; motion intensity moderate and controlled, never jittery:

SHOT 1 (0–4s) — THE WAKE-UP. Background: REF1, the marina at night, tower lights shimmering on the water, a slow drift of reflections. Framing: waist-up, right third, slightly low angle — hero framing. Camera: slow confident push-in. Light: warm gold key from the city side, soft rim. Direction: on "Good morning, Black Coffee" she gives a small knowing smirk straight down the lens, one eyebrow tick on "Coffee."

SHOT 2 (4–8s) — THE SCORE. Hard cut. Background: the same night city closer in — a wall of lit windows and bokeh streaks, light trails sliding past like slow traffic far below, subtle parallax drifting left to right. Framing: a touch tighter, chest-up, still right third. Camera: continue the push-in with a gentle lateral drift. Direction: on "Dubai kept score" a slight lean toward camera, conspiratorial; on "the numbers are juicy" the smile widens — she knows something we don't.

SHOT 3 (8–11s) — THE CROWN. Hard cut. Background: REF2 — the landmark tower rising behind her, champagne lights on black, huge clean dark sky filling the upper third. Framing: she sits lower in the frame, the tower and sky above her. Camera: settle from the push into a locked, planted shot. Direction: on "Grab your coffee, superstar" a light shrug of mock modesty; on "Let's go run this town" a small chin lift and a single slow nod, then hold — face calm, eyes on the lens. The final 1.5 seconds are a completely stable held frame, dark sky clean above her for the app's wordmark.

GLOBAL — photoreal, cinematic, sharp focus, clean rendering, shallow depth of field: backgrounds stay softly defocused so the presenter owns the frame. City lights bloom gently, never blown out. No on-screen text, no captions, no logos, no other people, no cars in the foreground.
```

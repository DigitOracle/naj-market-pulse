# The Najma opener — HeyGen

**A fixed ~5-second opener that plays before EVERY video.** Made once, reused unchanged. Not part of any episode.

Kendall, 22 Sep: *"the N appears, then she walks up to the N, rests her arm, like leans on the N on the left hand side,
and then as the star appears she says the word, 'Welcome to Najma, Provenance for Property'."*
And: *"HeyGen resolves all of this."* — so it is built in HeyGen, not generated and composited.

---

## 1 · The beat

| t | what happens | sound |
|---|---|---|
| 0.0–1.0 | **The N appears** on the deep green field. Gold, still, monumental | low warm swell |
| 1.0–2.2 | **Naj walks in** from frame left and comes to rest against the N's left stroke, arm resting on it | footfall, then quiet |
| 2.2–2.6 | **The star ignites** above the monogram | one clean bell strike on the ignition |
| 2.6–4.8 | She says the line, settled and still | her voice, bed underneath |
| 4.8–5.0 | Held. Everything static | tail decays into the film's ambience |

**The line, spoken:**

> **"Welcome to Najma. Provenance for property."**

Six words ≈ **2.2 s** at the measured 0.364 s/word. The beat above is built around that.

**The last half-second is completely static.** The episode's shot 1 opens on a *moving* camera, so the opener must end
on stillness — stillness into motion is the cut.

---

## 2 · What HeyGen needs

| Input | File |
|---|---|
| **Background plate** | `assets/brand/najma_opener_plate_9x16.jpg` — 1080 × 1920 |
| Avatar | Naj, the same avatar as every episode |
| Script | `Welcome to Najma. Provenance for property.` |
| Output | 1080 × 1920, 9:16, no watermark → save as `assets/brand/najma_opener_9x16.mp4` |

**The plate is built for the lean.** The monogram sits **right of centre**, its tall left stroke standing clear with
open green to the left of it — that is her space to walk into and the edge her arm rests on. The wordmark and tagline
are already on the plate, low, below where she stands.

### Direction for the avatar

- **Three-quarter or full body**, not head-and-shoulders. The lean only reads if the arm and the contact are in frame.
- She enters from **frame left**, walks a short distance, and **settles**. She does not keep shifting once she arrives.
- **Her arm rests on the N's left stroke.** This is the shot. If HeyGen cannot land the contact convincingly — the arm
  floating just off the edge, or passing through it — **fall back to her standing beside it, close, one shoulder turned
  toward it.** A confident stand beside the mark beats a bad lean.
- She looks to camera for the line, not at the logo.
- Warm low key from frame left, matching the gold. She must not be brighter than the monogram.

---

## 3 · The naming question this raises — ⚠️ Kendall's call

The opener says **"Welcome to Najma."** The episode sign-off, unchanged since 18 Sep, says **"Welcome to Azimuth. Dubai,
decoded — one tap at a time. Complexity into clarity."**

So as it stands a viewer is welcomed to **Najma** at 0:03 and to **Azimuth** at 0:45, in the same film. One of these
needs to change, and it is a brand decision rather than a production one. Three coherent ways out:

1. **Najma is the brand, Azimuth is the product.** The opener welcomes you to Najma; the sign-off keeps Azimuth as the
   thing on screen. Defensible, but it asks the viewer to hold two names in 45 seconds.
2. **One name throughout.** The sign-off becomes *"Welcome to Najma. Dubai, decoded — one tap at a time."* Simplest, and
   "Provenance for property" then does the work Azimuth was doing.
3. **The opener carries the brand, the sign-off drops its welcome** — ends on *"Dubai, decoded — one tap at a time.
   Complexity into clarity."* No second welcome, no collision. **This is my recommendation**; it costs one word and
   nothing else.

This is bible §16 open decision 3 — *series name and spelling* — finally forced. It cannot stay open now that both names
are spoken in the same film.

---

## 4 · The assets

| File | What it is |
|---|---|
| `assets/brand/najma_opener_plate_9x16.jpg` | **The HeyGen background plate.** 1080 × 1920 |
| `assets/brand/najma_lockup_dark_1080.jpg` | Square lockup on the app's dark green |
| `assets/brand/najma_lockup_cream_1080.jpg` | Square lockup on cream, as the logo was designed |
| `assets/brand/najma_mark.png` | The monogram alone, transparent, 815 × 1055, star centre preserved |
| `assets/brand/najma_lockup_src.png` | The supplied lockup, 327 × 322 — reference only, too small to use |

**Palette, taken from the logo:** dark green `#122A22` · cream `#FAF8F3` · gold `#B28C42`.

> ⚠️ **The wordmark is typeset, not your original.** Your lockup is 327 × 322 — seeding a 1080 × 1920 plate from it
> would be a 3× upscale, soft in the one asset that appears on every film. The **monogram is your artwork at full
> resolution**; **NAJMA** and **PROVENANCE FOR PROPERTY** are set in Bookman Old Style as a close stand-in.
> **If a vector exists, send it and I will rebuild the plate from it.**

---

## 5 · The rule that makes an opener work

> **It is identical on every single video.** Same walk, same lean, same line, same length, same last frame. Never
> re-cut, never "freshened", never made bespoke for an episode.

An opener earns its seconds through recognition. Variety destroys the only thing it does.

```
[ OPENER ~5 s ]  →  [ EPISODE 45 s ]  →  post
  static last frame    shot 1 opens on a moving camera
                       HARD CUT — no dissolve
```

The opener is **not** in `scripts/demo_capture.py` and never will be — the harness films the app. This is a fixed asset
concatenated at assembly.

**Total published length ≈ 50 s**, which is inside the 45–60 s Reels optimum rather than outside it.

---

## 6 · Disclosure

The opener is the **first exposure**, which is where the EU AI Act requires disclosure. The episode carries its
persistent on-screen line throughout, and the platform AI labels are set on upload. **If the opener is ever used alone —
as a profile video, a story, a bumper — it must carry the line itself**, because then it is the whole film.

---

## 7 · Before it is approved as final

- [ ] The lean reads as contact, not as floating. If not, use the fallback stand.
- [ ] Every letter of **NAJMA** and **PROVENANCE FOR PROPERTY** is correct and sharp.
- [ ] The last 0.5 s is static.
- [ ] It reads at phone size with sound off.
- [ ] The gold does not clip on a bright phone screen.
- [ ] Judged **cut against shot 1 of a real episode**, not alone.
- [ ] **The naming collision (§3) is resolved** — this cannot ship with two welcomes.
- [ ] Kendall has approved it as final, because after this it does not change.

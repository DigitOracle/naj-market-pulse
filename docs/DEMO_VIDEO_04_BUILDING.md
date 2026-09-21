# NAJMA DEMO 04 — the building page: "What's actually left, and on which floor?" (20 Sep 2026)

**Why this one:** Kendall recorded a 55 s walkthrough of the new building page (SLS Dubai) with the Snipping Tool,
which only records landscape — *"no good for social media"* — and said: if cropping loses things, revisit the page and
take a new video; *"this new one also has floor plans in it."* So this is the same page filmed as a native 9:16 by
`scripts/demo_capture.py` (`NAJMA_VIDEO=5`, `journey5`), on Binghatti Aquarise — the building in his second
screenshot, where the floors are drawn on the model and the developer's plans are in the card.

**Screen file:** `NAJMA_DEMO04_AQUARISE_BUILDING_SCREEN_9x16_20SEP2026.mp4` — 1:16, 1080×1920, 30 fps, take 5.

## As cut — take 5

Kendall on take 4 (1:10, the building small in a wide view throughout): *"why doesn't the video ever zoom in or cue
into the building itself? … when you say tap on the building … I don't feel like the building is highlighted."* From
that distance the app's highlight for a tapped floor was a hairline. Take 5 moves in first.

| time | beat | on screen |
|---|---|---|
| 0:00–0:13 | the hook | Binghatti Aquarise from above; the camera moves in and drops beside the long face until the floors read one by one |
| 0:13–0:23 | a floor | the face is tapped: floor 15 lights as a gold band; *Floor 15* — use, level, *sees over the roofs E · SE · S · SW · W*; the card scrolls to the floor plate and the types on the floor, with sizes and prices |
| 0:23–0:33 | the filters | *Hide All* (the face goes grey) → *2 BHK*: the face turns blue, *23 floors* → *SW*: *20 floors* |
| 0:33–0:41 | what's left | the panel scrolls to *SOLD SO FAR · 1,266 LEFT*: the ring and the left-of counts by type |
| 0:41–0:54 | about the building | the camera pulls back to the building in its setting; floors, units, parking, lifts; *sold, from the register*; *what it sees over* |
| 0:54–0:59 | who lives here | Business Bay's nine-region ring |
| 0:59–1:09 | the plans | *THE PLANS · Binghatti Aquarise Business Bay* — twelve developer plans, two to a row, scrolling |
| 1:09–1:16 | sign-off | the plans, held |

## How it was filmed — and what is film-only

- **The page is on the preview build, not production.** Production answers 401 to the client key for
  `/building/…`; the take reads `60715ca6-azimuth-2…` with the CLIENT_KEY (never the owner key). When the Azimuth
  session ships the page on Kendall's go, `AZIMUTH_URL` points the same journey at production.
- **Layout:** the page's own phone layout (its `max-width:820px` rules), applied at 1080 wide and drawn at twice the
  size, so text is sharp at 1080×1920. Playwright's recorder ignores device scale, so a 540-wide phone viewport
  would have recorded soft.
- **Two film-only changes (CSS injected by the harness, not app features):** (1) a card opens at the bottom, over the
  filter panel, instead of at the top over the model — so the tapped floor stays in view; (2) the 3D scene is drawn
  330 px higher, because the page centres the building exactly where the phone panel begins. Both are worth
  handing to the Azimuth session as real phone-layout fixes.
- **GPU:** the three.js scene needs it — headless without it took 28 s a screenshot; with ANGLE/D3D11 the orbit
  records in real time, so nothing in this cut is sped up.

## Seen while filming — for the Azimuth session

- The **floor plate** in the floor card draws as a straight bar; the model (and the building) is a long curve.
- A speckled **z-fight on the roof** while the camera moves.
- The **title** disappears in the phone layout (`position:static` puts it under the fixed canvas).
- The plans open in a new tab (`target=_blank`), which a phone recording cannot follow — a lightbox in the card
  would film, and would read better on a phone.

## Also filed — Kendall's SLS Dubai recording, recomposed

`NAJMA_DEMO04_SLS_WALKTHROUGH_RECOMPOSED_9x16_20SEP2026.mp4` (0:55): the landscape recording rebuilt as 9:16
without losing a panel — the title, the 3D view on top, and the active panel (filters, then the About card) enlarged
beneath it, with a column left clear on the right for the avatar. Same timing as the original, so the narrative
already in HeyGen fits. The on-screen caveat box ("the floors are not drawn on the model here…") falls outside the
recomposed frame. Source kept: `20SEP2026-DemoVideo.mp4` in Downloads.

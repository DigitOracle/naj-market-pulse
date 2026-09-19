# Naj's morning feed: what must change so 19 Sep never repeats

> **Superseded, 19 Sep 2026.** Azimuth Rings built this as worker v184 (the five-floor, the 2-3/2-3 split, plan facts exempt from the repeat locks, content guards) and v185 (daily scene cards with style_ref_21, `fbg_<n>` saved, off switch `FEED_SCENES`) on dewa-screens. Both await Kendall's go to deploy. This file is kept as the record of the 19 Sep diagnosis only.

**For:** the Azimuth Rings session (sole deployer of azimuth-2). Deploy with Kendall's own go.
**From:** the data session, 19 Sep 2026. Line numbers are from `C:\Dev\azimuth-worker-dewa\src\index.js` (branch dewa-screens) as read that day.

## What happened on 19 Sep
- At 06:00 Naj received **one** angle, and it reused "6,500 km", a figure she already had.
- A dry run (`/feed_test?dry=1`) after a fresh data refresh returned: *"every angle repeated a figure she already had, even after 3 repair passes, so nothing would be sent"*.
- Kendall had today's five rebuilt by hand and sent. **What he approved is the standard for every morning.**
  - The mix is **3 Dubai 2040 angles and 2 real-estate angles** (2–3 of each is acceptable).
  - Every figure she hasn't used in the last 14 days.
  - One **scene picture** per angle: her photo `style_ref_21` drawn into a place that fits the angle, in a pose that belongs there, with no cut-out composite. Each comes as a post (square) and a story.

## Kendall's standard, as rules
1. **Five angles, every morning, never fewer.**
2. **2–3 Dubai 2040 angles plus 2–3 register/real-estate angles.** Not "2040 frames all five".
3. **Fresh figures.** No register figure from the last 14 days.
4. **A picture of her IN the scene** (the `/scene_test` path), not the cut-out (`plateRun` with `withMe`). Kendall and Naj, 19 Sep: the cut-out "looks like a very shitty cut, copy, paste"; "whatever was in place yesterday was better".

## Changes needed (worker)
| # | Where | Change |
|---|---|---|
| 1 | `feedQA` ~L5060 | **Add a floor of 5.** After the 3 repair passes, do NOT drop the remaining overlaps below 5. Keep the best 5, preferring angles whose only fault is a shared 2040 plan figure. The v179 comment "with NO floor" is the direct cause of the one-angle morning. |
| 2 | `feedAudit` ~L5031-5040 | **2040 plan figures must not starve.** There are only 16 `DUBAI_2040.facts`, so a plan figure should block only if the same plan fact was used in the last 3 days (already the intent of `PLAN_WINDOW`). But `numKeys` also bans the plan's numbers (6500, 105, 160...) through the **14-day** `seenNum` whenever `isPlan()` misses, and it misses whenever the model rewords the figure string. Match plan facts by number, not by string. |
| 3 | system prompt ~L5230 | **The split.** Replace "THE SPINE... frames all five" with: exactly 2–3 angles whose family is growth_plan / transit / city_life **from dubai2040**, and 2–3 whose figure comes from the **register** (dldSales, monthly, rents, trends). Keep the honesty rules as they are. |
| 4 | `LENSES_2040` / lens B ~L5206 | Keep, but lens A must be a **register** lens every day. |
| 5 | morning pictures | **The morning plates must use the scene path**: `sceneGenerate` with her last-chosen photo (`style_me_used`, most recent = `style_ref_21` on 19 Sep), not `plateRun` with `withMe`. Choose the backdrop per angle (a beach/marina angle gets H, Waterfront walk; skyline/urban centre gets A; market/volume gets D, Lobby; yield/home gets C, Balcony; transit gets B, Street). |
| 6 | `fbg_<n>` | **Write `fbg_1..5` from the new feed every morning.** On 19 Sep `/scene_test` read stale angles from `fbg_<n>` (City of Arabia, Beyond, R Evolution) before `mkt_briefctx`. Four of five cards carried last week's text until the slots were overwritten by hand. |
| 7 | `plate_run ?use=&me=0` | `me=0` was ignored when `use=` is set: the blue cut-out was still pasted over the scene. |
| 8 | plate cache | `plate_run ?fresh=1&place=...` returned the cached card for angle 2 unchanged. `fresh` should bypass the cache. |
| 9 | `FEED_HOUR_GST` | Fine at 6 **now that the refresh runs at 05:00** (changed 19 Sep, with a 10-minute network wait). Keep it. |

## Already done on the laptop side (19 Sep)
- `Najma_Daily_Refresh` now runs at **05:00** (was 06:30, after the feed) and waits for the network. The 06:30 run on 19 Sep failed with `getaddrinfo failed`.
- New `Najma_Feed_Watch` runs at **06:20**, via `scripts/feed_watch.py`. If the feed didn't complete, gave her fewer than 5 angles, or ran on stale data, Kendall gets one WhatsApp line. Never Naj.
- KV state changed by hand on 19 Sep, with backups in `%TEMP%`:
  - `mkt_briefctx`: today's five, replacing the single angle. Backup: `briefctx_before_19sep.json`.
  - `fbg_1..4`: today's angles. Backups: `fbg_<n>_before_19sep.json`.

## How to verify after deploying
1. Run `/feed_test?dry=1` three mornings in a row. It must return 5 angles each time: 2–3 from 2040 and 2–3 from the register.
2. Check the first live morning's pictures. Each must show her drawn into the scene, with the correct day's text, in both sizes.
3. `Najma_Feed_Watch` must stay silent.

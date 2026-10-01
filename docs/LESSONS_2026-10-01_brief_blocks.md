# Lessons: the Brief, Blocks and the overnight run (30 Sep - 1 Oct 2026)

What went live: v275 (the Brief + Blocks), v276 (CityEngine origin), and v278 (v277 simple Brief + v278 blocks-first map and twin).
Data published: beds_left (37 districts), brochures, brief map layers, and blocks (45 districts). The Amber fix is on JVC 1503.

## Product decisions Kendall made after seeing it live
1. **Availability comes only from the developers' own sheets** (the WhatsApp developer group). The Ejari "no running tenancy" estimate looked precise but wasn't availability. Kendall: "this isn't helpful". The DDA session checked all 523 governed datasets: no government source records vacancy. Don't re-propose it.
2. **START is the Brief alone.** The five "ways in" cards and the cheat sheet were noise. A new card goes on START only when its page exists, so there are no dead controls.
3. **Start simple, then one question per screen.** Two buttons (RENT / BUY), then bedrooms, budget, where and must-haves.
4. **Blocks are the middle layer between the map and the twin.** The map must never auto-jump into the twin at district zoom. The twin opens in blocks and loads detail on tap or close zoom.
5. **Every client document carries the new style:** Najjuko with the N in the header, and "Curated by Najjuko · Dubai Decoded" with WhatsApp +971 56 548 4397 in the footer. The building page button was still serving the old /sheet/ PDF until v277.

## Engineering lessons
- **A fixture only proves what you already believed.** The PDF agent re-implemented the estimate on its own, so the list and the PDF disagreed. The fix was ONE exported function (estimateLeft) plus a parity test that uses the real register.
- **Estimated heights need a sanity cap.** A "community median" fill turned kiosks into 90 m needles. Rule: a community_median height on a footprint under 60 m² becomes 4 m, and under 400 m² becomes 10 m (scripts/blocks/cap_median.py). Never apply an area-typical height without looking at footprint size. Typical heights by building type (villa 8 m, warehouse 10 m) are fine.
- **Name matching on a shared word binds the wrong building.** "Binghatti" placed Binghatti Circle (and Amberhall) on Amber's footprint 1503. The bind scripts now honour hand decisions (data/identity/decisions.json, job footprint_binding) and reject rejected placements on every run.
- **A full rebuild drifts unrelated rows.** Rebuilding resolve_identity, apply_identity or map_prices for one building changed hundreds of others. For a single-building fix, regenerate in a copy and write back only that building's records, then push exactly the files on disk (scratchpad push_amber.py pattern).
- **Deploy scripts:**
  - Under `MSYS_NO_PATHCONV=1`, `cmd //c` is NOT converted to `/c`, so it opens an interactive cmd and the script hangs silently. Use `cmd /c` there.
  - Never capture `wrangler versions upload` output into a variable. A hidden prompt (e.g. "install wrangler?") then hangs forever with nothing on screen. Use `| tee`.
  - Check that `node_modules/wrangler` exists in the deploy worktree before uploading.
  - In PowerShell, plain `bash` is WSL and cannot see C:/ paths. Use `& "C:\Program Files\Git\bin\bash.exe" <script>`.
  - Guard the morning feed TWICE: at the start AND just before the deploy step. A slow upload can run into 06:00.
  - Keep code deploys and slow data uploads separable (`SKIP_BLOCKS=1`), so a flaky network doesn't hold back a code release.
- **Push-routing in the shared repo:** cherry-pick each requested commit alone onto origin/main in a scratch worktree. Lane commits can depend on earlier lane commits, so check `git cherry -v origin/main main` for what's really missing. Verify who owns a commit before declining it (430b78c was CityEngine's).
- **Never edit a script while someone may be running it.** Kendall ran deploy_v278.sh in his terminal while I patched it. Bash reads scripts as it goes, so his run finished the blocks upload (all 45 MATCHES) and then died on a half-written line. Copy to a new file name instead.
- **Overpass is unreliable at night:** expect 504s. Overture's road and building layers give the same OSM data in one download.

## Open after this run
- The Ejari "contracts signed" search: the second START card (DDA builds lk_ejari_daily).
- Tap cards for about 370k footprints (DDA builds tapcard_<slug>.json). For full coverage the GeoDubai request needs a sponsor.
- The 203 city communities (data/blocks_city) are built, not published. Their type hints are still landing.
- The Liwan buildings.geojson spans about 18 km (stray footprints). Not fixed.

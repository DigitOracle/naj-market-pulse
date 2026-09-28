# THE GLOBE — "One day in Dubai" · SHOOTING SCRIPT

**Research only, internal only** (Kendall, 28 Sep 2026). A 29 s globe segment: Dubai's daily property sales set
against London, Paris and Monaco. Built in ArcGIS Pro by the Sobha session (`scripts/globe_transactions.py`,
`data/globe/cities.csv`). The story was proposed by the DDA session; the figures were verified and corrected by the
DDA session and this session; the narration merges Sobha's draft with this session's timing. Kendall released the build
and asked for it to be finished on 28 Sep.

---

## 1 · THE FILMS

`data/media/globe/`, 29.0 s, 25 fps, silent. Same beat timings in every version.

| File | What |
|---|---|
| `globe_transactions_9x16_overlay.mp4` | **The one to use**: globe, pins and the comparison card, 1080x1920 |
| `globe_transactions_9x16.mp4` | clean: globe and pins only, no text |
| `globe_transactions_16x9[_overlay].mp4` | landscape versions |
| `*_share.mp4` | small copies for sending |
| `clips/` | one clip per beat |
| `globe_cue_sheet.json` | beat in/out points |

The comparison card is Naj-style: "PROPERTY SALES · PER DAY", a bar per city, a source line per beat. New York is
not shown. Singapore is not in the default film (new-launch sales only, so not comparable).

---

## 2 · THE BEATS AND THE NARRATION

Measured rate 0.364 s a word. Every spoken number matches the card on screen.

| Beat | Time | On screen | Naj says (starts at) |
|---|---|---|---|
| 1 | 0-6 | Earth → push to Dubai; card: Dubai 460 | 0.4 "Picture an average day in Dubai: about four hundred and sixty property sales." |
| 2 | 6-10 | London pin; 221 | 6.2 "London, a global heavyweight, manages about two hundred and twenty." |
| 3 | 10-12 | Paris; 96 | 10.1 "Paris, under a hundred." |
| 4 | 12-14 | Monaco; 1.35 | 12.1 "Monaco? Just over one." |
| 5 | 14-19 | pull-back, "Four markets compared", combined 318 / day | 14.4 "Put all three together, and they still fall short of Dubai." |
| 6 | 19-24 | Dubai spikes: **1,307 · busiest day · 9 Feb 2026**, held from ~20.5 s | 19.3 "On its busiest day this year, Dubai recorded over thirteen hundred sales." |
| 7 | 24-27.8 | still the busiest-day card, 1,307 | 24.1 "More than Monaco sees in two and a half years." |
| 7b | 27.8-29 | snap to "Four markets compared", 460 | "That's Dubai's pace." (ends 28.8) |

### Paste into HeyGen (background: `globe_transactions_9x16_overlay.mp4`; HeyGen should show about 0:29)

```
<break time="0.4s"/> Picture an average day in Dubai: about four hundred and sixty property sales. <break time="1.1s"/> London, a global heavyweight, manages about two hundred and twenty. Paris, under a hundred. <break time="0.5s"/> Monaco? Just over one. <break time="0.8s"/> Put all three together, and they still fall short of Dubai. <break time="0.9s"/> On its busiest day this year, Dubai recorded over thirteen hundred sales. <break time="0.4s"/> More than Monaco sees in two and a half years. That's Dubai's pace.
```

If the segment stands alone, add the sign-off after a short pause: "This is Najma, presenting Dubai Decoded, turning
complexity into clarity." (~4 s). The globe's last frame then needs holding about 4 s longer.

---

## 3 · EVERY NUMBER

| Said / shown | Figure | Source |
|---|---|---|
| Dubai, about 460 sales a day | 119,204 sales, 1 Jan-17 Sep 2026, 259 days | Dubai Land Department transactions, `trans_group_en = 'Sales'` only (no mortgages 28,778, no gifts 6,311); off-plan 81,496 + existing 37,708 |
| London, about 220 | 80,688 sales, 2025 → 221 / day | HM Land Registry, via Statista |
| Paris, under a hundred | ~35,000 sales, 2025 (range 33,000-37,000) → 96 / day | Notaires du Grand Paris |
| Monaco, just over one | 493 sales, 2025 → 1.35 / day | IMSEE (Monaco statistics office) |
| Together, short of Dubai | 221 + 96 + 1.35 = 318 < 460 | calculated |
| Busiest day, over thirteen hundred | 1,307 sales, 9 Feb 2026; largest single project 3.5% of the day, so not one developer's bulk filing | DLD, sales only |
| More than two and a half years of Monaco | 1,307 / 493 = 2.65 | calculated |

**Dropped:** New York (the only figure found was New York State, not the city). Singapore (new-launch units only).
**Corrected on the way:** the first Dubai figures (596 a day, 736 busiest) counted mortgages and gifts; "736 beats a
year and a half of Monaco" was false (1.5 × 493 = 739.5).

### What must not be said

- Not "properties are worth more" or any value claim: this is pace (count of sales), not price.
- Not "homes": these are sales transactions.
- Not "every day": 460 is an average; the busiest day is one day.
- The years differ (Dubai 2026 to date, the others 2025 in full). Fine for "a day"; never present them as the same year.

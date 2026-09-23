# NAJMA EPISODE 07 - HeyGen narrative

**"Is there anything left in it?"** - AL HABTOOR TOWER, Business Bay 574. Filmed 22 Sep 2026.

**Screen cut:** `NAJMA_EP07_HABTOOR_SCREEN_9x16_22SEP2026.mp4` - 69 s, 17 shots, average shot 3.5 s.
**Paced to the cut read back from `data/demo/raw/shots.json`**, not to the storyboard: the two differ, and the cut wins.

---

## The narrative, as one paragraph

> A client asked me about Al Habtoor Tower. Ninety-one levels, and a thousand seven hundred homes. So I
> opened it. Four hundred and forty-three of them are still unsold. One beds, two beds, three beds - and
> which floors. Then floor eighty-six. One flat. Nine thousand square feet. But what is it like? Every
> home on the floor, drawn - by type, by size, with the lifts. Fifty-two percent built, due at the end of
> this year. And when she asks me to send her something - I send her this. The stack, floor by floor. What
> it sells for. Who designed it. Who built it. What is around it. Where the shops are. Who lives in
> Business Bay. And the floor plan itself. Every figure naming the register it came from. Dubai, decoded -
> one tap at a time. Complexity into clarity.

**Check in HeyGen before rendering: the duration should read about 52 seconds.** If it comes up short the voice is
faster than the one measured on 20 Sep - nudge the voice speed down a step rather than touching the video.

## Paced to the cut - this voice, measured at 0.364 s a word

| # | in | dur | words allowed | words used | line |
|---|---|---|---|---|---|
| 1 | 0.0 | 4.0 | 11 | 0 | - |
| 2 | 4.0 | 4.0 | 11 | 8 | A client asked me about Al Habtoor Tower. |
| 3 | 8.0 | 3.5 | 10 | 8 | Ninety-one levels, and a thousand seven hundred homes. |
| 4 | 11.5 | 3.0 | 8 | 4 | So I opened it. |
| 5 | 14.5 | 4.5 | 12 | 9 | Four hundred and forty-three of them are still unsold. |
| 6 | 19.0 | 3.5 | 10 | 10 | One beds, two beds, three beds - and which floors. |
| 7 | 22.5 | 4.5 | 12 | 9 | Then floor eighty-six. One flat. Nine thousand square feet. |
| 8 | 27.0 | 2.0 | 5 | 5 | But what is it like? |
| 9 | 29.0 | 5.0 | 14 | 14 | Every home on the floor, drawn - by type, by size, with the lifts. |
| 10 | 34.0 | 4.5 | 12 | 10 | Fifty-two percent built, due at the end of this year. |
| 11 | 38.5 | 3.5 | 10 | 10 | And when she asks me to send her something - |
| 12 | 42.0 | 3.5 | 10 | 9 | I send her this. The stack, floor by floor. |
| 13 | 45.5 | 3.5 | 10 | 4 | What it sells for. |
| 14 | 49.0 | 3.5 | 10 | 6 | Who designed it. Who built it. |
| 15 | 52.5 | 3.5 | 10 | 8 | What is around it. Where the shops are. |
| 16 | 56.0 | 3.5 | 10 | 5 | Who lives in Business Bay. |
| 17 | 59.5 | 3.5 | 10 | 5 | And the floor plan itself. |
| 18 | 63.0 | 9.0 | 25 | 19 | Every figure naming the register it came from. Dubai, decoded - one tap at a time. Complexity into clarity. |

143 words = 52 seconds of speech over 72 seconds of picture. 

---

## Every claim, and where it is on screen

| Naj says | on screen at that second | register |
|---|---|---|
| ninety-one levels | *Level 86 of 91*; the dossier's *The stack - 91 levels + 3 below ground* | Dubai Municipality floor register |
| a thousand seven hundred homes | *1,739 registered - 1,739 residential* | DLD units register |
| four hundred and forty-three still unsold | *443 LEFT OF 1,739* | DLD units + transactions |
| which floors they sit on | the type table: 1 bed 8-75, 2 bed 8-82, 3 bed 25-85 | DM floor register x DLD units |
| floor eighty-six, one flat, nine thousand square feet | *Level 86 of 91 - Homes on it 4*; *8601 - 5 B/R - 9,081 sq ft - 4,819 sq ft balcony* | DLD units register |
| fifty-two percent built, due at the end of this year | dossier: *Status ACTIVE - Built 52% - Due 2026-12-31* | DLD project register |
| who designed it, who built it | dossier: *Designed and built by* | DM contractor and consultant registers |
| who lives in Business Bay | dossier: Europe 24%, Arab world 22%, South Asia 21% | DEWA customer register, community level |

### The one number that needs care

**443 LEFT OF 1,739 is a true count on THIS building**, because its sales have not exceeded its units. On 304 buildings
citywide the same block was reading sold out when it was not - `Math.max(0, units - sales)` against resale history -
and that was fixed in v246 on 22 Sep. **Al Habtoor was checked specifically before it was filmed.** If this episode is
ever re-cut on a different building, check that first.

### Not said, because nothing supports it

- Which individual homes are unsold. The register publishes counts by type, never a list.
- Anything about who the 443 belong to, or whether they are for sale today. Unsold is not the same as available; that
  needs a developer availability sheet, and we do not hold one for this building.
- The contractor as **this building's**. The dossier says it on its own face: the plot carries 64 buildings, so the
  firms are the plot's.
- A per-type yield.

---

## Notes for the render

- **Avatar placement:** head above y 1600, at most 20% of frame height, no bubble, no border, fading in at 3.4 s. She
  is the narrator, not the subject. The left-hand card carries the register for most of the film and she must not
  cross it.
- **Background:** cast to the market this cut is aimed at (bible section 9). Business Bay's own mix is Europe 24%,
  Arab world 22%, South Asia 21% - a London window or a Mumbai one both defensible; pick one and keep it.
- **Disclosure line on screen from frame 1.** Both platform AI labels set on upload.
- **The opener plays first**, unchanged, and the client's question before that. Published length lands near 90 s, which
  is past the Reels band - a shorter Instagram cut is worth making from the same master.

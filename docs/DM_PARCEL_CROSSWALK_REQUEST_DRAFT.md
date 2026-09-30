# Request for a masterplan-parcel to final-plot crosswalk — draft, not sent

**To:** Dubai Municipality building/GIS team (via GeoDubai or the equivalent DM channel)
**Status:** DRAFT. Held for Kendall's decision on whether to send.
**Prepared:** 30 September 2026

---

## 1. What we're asking for

**Primary ask (b):** if Dubai Municipality holds, in any form, a crosswalk between the
interim/masterplan-level parcel numbers its building register currently uses in newer
communities and the final, individually-subdivided freehold plot numbers the Land
Department has already registered for the same land, we would like access to it.

**Secondary ask (a), only if (b) does not exist:** if no crosswalk exists because the
building register itself has not yet been re-issued at final-plot granularity in these
communities, we would ask whether Dubai Municipality plans to do so, and on what timeline,
so we can plan around it rather than treat the gap as permanent.

We believe (b) is the likelier ask to succeed: a crosswalk is administrative data DM may
already hold internally even where the building register itself has not been rebuilt, and
it is the piece that would actually unlock the affected communities for us.

**Additional ask (c), plot geometry, independent of (a)/(b):** the plot (parcel) polygon
layer carrying the DM plot number (community number + plot number, e.g. 681-6177), via
GeoDubai service 2165. (Free, about 5 working days, needs a government, semi-government or
university sponsor; the sponsor is for Kendall to arrange.) No cadastral layer exists in
the DDA open-data subscription (509 datasets checked, re-verified 22 Sep and 1 Oct 2026), and
none is available through the Esri basemaps. Everything we hold with coordinates (194,882 DM
makani entrance points, about 64,000 building footprints, community outlines) lacks a plot
number, and every register keyed by plot number lacks coordinates. On 1 Oct 2026, DEWA
move-ins reached only 638 of 230,475 registered plots (0.3%), because makani can only be tied
to a plot through name-matched buildings. With plot polygons, a point-in-polygon join puts
makani (and so DEWA) and building footprints onto plots directly, for the 74,854 DEWA
makani that already have entrance coordinates.

## 2. What we measured, not assumed

We hold two parcel numbering systems for the same land: the Land Department's own property
registration (individually subdivided, freehold-ready plots) and Dubai Municipality's
building register (parcel-keyed, used for floors, permits and usages). In most of Dubai
these agree closely enough to join directly. In a specific, identifiable set of newer or
still-developing communities, they diverge sharply — not because either side is missing
data, but because Dubai Municipality's register in these areas is still keyed to an earlier,
coarser parcel grid than the one the Land Department already uses.

Measured directly, three communities as examples:

| Community | Land Department parcels (individually registered) | DM building-register parcels (same community) | Parcel numbers matching exactly |
|---|---|---|---|
| Al Yelayiss 1 | 7,505 | 44 | 2 |
| Madinat Hind 4 | 13,406 | 580 | 6 |
| Al Yufrah 1 | 3,758 | 5 | 3 |

In Al Yelayiss 1, DM's 44 parcels each cover an average of 214 buildings — consistent with
a masterplan-stage subdivision that has not been broken down to individual plot level, while
the Land Department has already registered plots at that finer level.

We also checked whether a location-based match (coordinates or the Makani addressing system)
could bridge the gap instead of a parcel match. It cannot, for a specific reason: Dubai
Municipality's own building summary record carries no coordinate field and no Makani number
at all — only a parcel identifier and community number. A separate DM layer (building
entrances) does carry real coordinates and Makani references, but keys on entrance ID, not
building ID, so it cannot be used to reach a building record either. This is not a fixable
join; the building record itself has nowhere for a location key to attach.

## 3. Full picture, not just the extremes

Across 81 communities with 500 or more buildings, the match rate between the two parcel
systems runs as a smooth gradient from 0% to 99.9%, correlated with how built-out and
re-platted each community is on Dubai Municipality's side — not a hard line between "covered"
and "uncovered." The worst-matching communities (Al Hebiah Sixth, Palm Deira, Al Barsha
South Fifth, Palm Jabal Ali, Madinat Hind 4, Al Yufrah 1, Al Yelayiss 1 and 4) are newer
outskirts or reclaimed-land masterplan areas; the best-matching (Al Thanayah Fourth, Al
Merkadh, Wadi Al Safa 6, Dubai Investment Park First) are established, fully-platted areas.
The full table is available on request.

## 4. What this affects

Where the two parcel systems don't match, we hold no floor count, no permit history and no
usage record for the building — not because Dubai Municipality lacks the data everywhere,
but because we cannot currently connect our record of the building to theirs. We are careful
to present this as an absence of a link, not as a fact about the building (a building with no
matched DM record is not the same as a building with no floors).

## 5. Research use only

Per Kendall's standing ruling, any data reached through this request would be for research
use only, on the same terms as our existing DDA and GeoDubai access — no commercial or
third-party use, no redistribution.

---

*This draft is not to be sent without Kendall's explicit go-ahead.*

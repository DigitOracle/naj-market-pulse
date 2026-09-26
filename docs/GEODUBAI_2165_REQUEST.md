# Request for Geospatial Maps and Data — Service 2165

**To:** GIS Centre, Dubai Municipality — GeoDubai
**Service:** 2165 — Request Geospatial Maps and Data
**Applicant category:** Researcher
**Date:** 23 September 2026

---

## 1. Applicant

**Dr. Kendall Wilson**, DBA
Adjunct Professor, Golden Gate University
Doctorate in Business Administration, Golden Gate University (conferred June 2026)
Email: kwilson376@my.ggu.edu
Telephone: _[insert contact number]_

I hold a current adjunct professorial appointment and deliver CIOB and LUBM curricula in
the built-environment field. This request supports research into the completeness and
linkage of municipal spatial records in Dubai.

## 2. Research question

**How completely can a city-scale building model be linked to the municipal cadastral
record, and what is lost where that linkage is absent?**

This is not a hypothetical concern. Working from Dubai's own published open data, I have
assembled a building register of **63,594 distinct building footprints**, each with a
stable identifier, and measured the following on that single base:¹

| Measurement (base: 63,594 distinct footprints) | Result |
|---|---|
| Buildings linkable, one to one, to the municipal building record | 434 — **0.68%** |
| Buildings carrying a height other than the modelling default | 12,968 — 20.4% |
| Buildings on the modelling default of exactly 12.0 m | 50,626 — 79.6% |

The problem this research addresses is **linkage, not absence**. Real heights exist:
a fifth of the model already carries one from other sources, and the municipal record
itself holds far more (below). What is missing is the ability to connect a given
building to its municipal record: fewer than one building in a hundred can be matched
one to one. Where that match fails and no other source exists, a model can only fall
back to a default — which is what four buildings in five currently do.

I have verified that this is not a defect in my own method. The municipal building
summary holds 276,940 plausible building heights and 407,171 floor counts — the
information exists. The obstacle is that the only shared key between a building
footprint and that record is the **parcel**, and parcel geometry is not among the
published open datasets. Where a parcel holds more than one building — 82,856 parcels
do — even the parcel key resolves only to the tallest structure on the plot, not to an
individual building.

I have tested the alternative routes rather than assuming they fail:

- **Land Department floor counts.** Deriving height from registered floor counts yields
  a usable value for **397 buildings — 0.6%**. Real, and I use it, but it does not
  close the gap.
- **Makani.** The Makani–entrance layer does link to individual buildings, and is how a
  separate occupancy linkage in this work succeeded. The municipal building record,
  however, carries no Makani number, so the two cannot be joined.
- **Coordinates.** The municipal building record carries no point geometry, so a
  building footprint cannot be matched to it spatially either.

Each of these was measured, not presumed. The parcel is the only remaining join.

The absence of a cadastral layer is therefore not one gap among many. It is the single
structural discontinuity in Dubai's otherwise exceptionally complete open spatial
record, and characterising it is the substance of this research.

---

¹ *How the base is derived.* The model is organised as 44 district files holding 67,780
footprint features. Three districts were added after the building register was compiled
and are not in it (1,052 + 671 + 1,827 = 3,550 features), leaving 64,230. Adjacent
district files overlap at their boundaries, so 636 footprints appear in two files;
counting each footprint once gives 63,594. All three percentages above are identical, to
one decimal place, whether the base is taken as 64,230 or 63,594, and all 434 linked
buildings are distinct footprints.

## 3. Data requested

Parcel (cadastral plot) polygon geometry for the Emirate of Dubai, with:

- parcel identifier, as used in Dubai Municipality records
- community number and community name
- polygon boundary geometry

**Coverage:** Emirate-wide preferred. If emirate-wide is not appropriate for a request
of this kind, I would welcome a subset — any twenty communities of the Centre's choosing
would be sufficient to characterise linkage rates and would allow the method to be
validated before any wider request.

**Format:** Esri File Geodatabase, Shapefile or GeoJSON — whichever is standard for the
Centre. Coordinate reference system as issued; I will not reproject for analysis.

**Attributes:** Only the identifier, community and geometry are needed. No ownership,
valuation, occupancy or personal data is requested, and none is required for the
research.

## 4. Undertakings

I confirm and undertake that:

1. The data will be used solely for the research described above. It will **not** be
   used for any commercial product, service or offering.
2. The data will not be redistributed, resold, sublicensed or published, in whole or
   in part. Derived geometry will not be published in a form from which parcel
   boundaries could be reconstructed.
3. Any published output will report aggregate findings only — linkage rates,
   completeness statistics and methodology — and will credit Dubai Municipality GIS
   Centre as the source of the cadastral data.
4. The data will be held on encrypted storage, access restricted to me, and deleted at
   the conclusion of the research or on request by the Centre, whichever is sooner.
5. I will comply with the Geospatial Information Usage Policy in full and will seek
   written permission before any use not described in this request.
6. I will share the research findings with the GIS Centre before any external
   publication.

## 5. Why this may be of interest to the Centre

The linkage measurements above are a direct, quantified assessment of how far Dubai's
published open data can be joined into a coherent city model by an external party using
only public sources. Whatever the findings, they describe where the published record
holds together and where it does not — which may be of use to the Centre independently
of my own purposes. I am glad to share the full measurement set, including the
methodology and the negative results, whether or not this request is granted.

---

**Dr. Kendall Wilson**
kwilson376@my.ggu.edu

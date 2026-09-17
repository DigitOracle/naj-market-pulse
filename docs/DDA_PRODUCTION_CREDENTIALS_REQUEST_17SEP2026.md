# Request: data.dubai production API credentials

Drafted 17 Sep 2026 for submission through the data.dubai **Contact Us** form.
Test/staging credentials were issued to contact@digitalabbot.io on 10 Sep 2026; this asks for the
production tier. **Quote the Application Id from `C:\Users\kwils\digitalchemy-dda.env` (`DDA_APP_ID`)
in the form — it is deliberately not reproduced in this repo.**

---

## Why this is being requested

The staging environment cannot support a production service. Three findings, all reproducible:

1. **Staging serves a partial extract.** `dewa_ev_green_charger-open-api` returns **177 charge
   points**. DEWA told the Emirates News Agency (WAM) on **23 June 2026** that Dubai has **2,223 EV
   charging stations**, against a
   10,000 target for end-2026. Staging carries under 8% of the live network.

2. **Staging is not stable.** The same dataset returned **186 rows on 12 Sep 2026** and **177 rows on
   17 Sep 2026** — it is shrinking, not growing. DEWA's own `load_timestamp` on every row is frozen
   at **7 Oct 2025**, so staging is serving a snapshot roughly a year stale.

3. **Staging serves scrambled values.** Documented in our own methodology notes: some rows of
   otherwise genuine datasets carry fill values (visitor-region fields of fifty random letters
   followed by fifty random digits; Salik tariff months reading `HAU`, `OBZ`, `ZGN`). We run a
   per-row realness gate to quarantine these, but the gate is a workaround for a staging artefact.

Production access replaces all three workarounds with the real register.

## What is being built

**Academic research, non-commercial.** A research mapping application studying the distribution of
Dubai's EV charging infrastructure — charge point locations, connector types and charging capacity —
to make the network legible and to support planning analysis. The work is led by **Dr. Kendall
Wilson, professor at Golden Gate University**, and hosted on DigitAlchemy's Azimuth platform.

Attribution to DEWA and Digital Dubai is carried on the application surface, and each figure is
rendered with its source dataset and publication date.

This is one application over a broader Digital Dubai data integration already in use across DLD,
RTA, DEWA, Dubai Municipality and DET registers.

Independent verification of the coverage gap: OpenChargeMap, the largest open charge point registry,
carries only **139 points for the entire UAE — 83 in Dubai, and just 8 attributed to DEWA**. No open
source reflects the real network. Only the production register does.

## Credentials requested

| Item | Detail |
|---|---|
| Application Id | *(quote `DDA_APP_ID` from the credentials file)* |
| Current tier | Test / staging — `stg-apis.data.dubai` |
| Requested tier | Production — `apis.data.dubai` |
| Issued to | contact@digitalabbot.io, 10 Sep 2026 |
| Use | Academic research, non-commercial |
| Researcher | Dr. Kendall Wilson, professor, Golden Gate University |
| Organisation | DigitAlchemy Tech Limited (ADGM-registered) |
| Contact | contact@digitalabbot.io · +971 56 227 6093 |
| Source addresses | UAE-only, as required by the issuing pack |

## Priority datasets

| Entity | Dataset | Use |
|---|---|---|
| DEWA | `dewa_ev_green_charger-open-api` | **Primary** — charge point locations, connector types, capacity |
| DEWA | `dewa_water_supply_points-open-api` | Utility infrastructure context |
| RTA | parking rates, taxi stand locations, metro/tram stations | Multi-modal context around charge points |
| DLD | transactions, projects, land registry, area lookup | Existing production integration |
| Dubai Municipality | building permits, building usages | Existing production integration |

## Technical conformance

Our client already implements the constraints in the issuing pack and has run against staging since
10 Sep 2026 without a rate-limit breach:

- OAuth 2.0 client credentials → bearer token, refreshed on the 3,600 s expiry with a 60 s margin
- **60 requests/minute**, enforced client-side at a 1.05 s floor between calls
- 1,000 records per page, with pagination terminating on a short page
- 30–40 s timeouts with bounded retry and backoff on transport failure
- Credentials held outside version control, never logged or printed
- Requests originate from UAE addresses

No change to our integration is needed beyond the base URL and the production credentials.

## Confirmed blocker

Production currently rejects the staging credentials, as expected:

```
POST https://apis.data.dubai/secure/ssis/dubaiai/gatewaytoken/1.0.0/getAccessToken
→ HTTP 403  "Unauthorized application request."
   Service - SDG-SSIS-DubaiAI-GatewayToken, Operation - /getAccessToken

POST https://stg-apis.data.dubai/secure/ssis/dubaiai/gatewaytoken/1.0.0/getAccessToken
→ HTTP 200  (token issued)
```

Verified 17 Sep 2026. The integration is complete and tested; only the credential tier is
outstanding.

---

### Suggested covering message (paste into the form)

> We hold test credentials for the data.dubai API, issued to contact@digitalabbot.io on 10 September
> 2026 under Application Id [QUOTE ID]. We would like to request production credentials.
>
> This is non-commercial academic research led by Dr. Kendall Wilson, professor at Golden Gate
> University, studying the distribution of Dubai's EV charging network using DEWA's Electric Vehicles
> Green Charger Points dataset. The staging environment returns 177 charge points against DEWA's
> reported figure of 2,223 EV charging stations (to WAM, 23 June 2026), with row timestamps frozen at October 2025, so it cannot
> support the analysis. We also checked open sources: OpenChargeMap lists only 83 charge points for
> Dubai, so no public dataset reflects the real network.
>
> Our client is built and tested against staging and already conforms to the production
> constraints — OAuth 2.0 client credentials, 60 requests per minute, 1,000 records per page, UAE
> source addresses, credentials held outside version control. Moving to production requires only the
> base URL and the new credentials.
>
> We would also like production access to the DLD, RTA and Dubai Municipality registers listed in
> our attached request, which we already integrate from staging.
>
> Please let us know if you need any further detail on the application or our technical setup.
>
> Dr. Kendall Wilson
> DigitAlchemy Tech Limited
> contact@digitalabbot.io · +971 56 227 6093

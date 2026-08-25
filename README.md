# Najma نجمة — Market Pulse

Dubai property market pulse + content engine for Naj, built ONLY on official data.
**Read [HANDOVER.md](HANDOVER.md) before changing anything** — it carries the sanity-gate
doctrine, the data schemas, and the licence rules. This README is the operating guide.

## The loop

```
DLD open data (official gateway / manual CSV)          MEED corpus (FIXED snapshot,
        │                                              via Digital Abbot Cloud API)
        ▼                                                        │
scripts/fetch_dld.py  ── weekly, read-only ──► data/*.csv        │
        ▼                                                        ▼
scripts/build_pulse.py ── sanity gates, FAIL CLOSED ──► public/pulse.json
        │
        ├─► dashboard (public/mockup.html → production page)
        ├─► weekly Azimuth WhatsApp update to Naj
        └─► content angles → HeyGen podcast · LinkedIn · Instagram
```

## Cadence: WEEKLY (Mondays 07:30 Dubai)

`.github/workflows/pulse.yml` fetches trailing windows from the official DLD open-data
gateway (`gateway.dubailand.gov.ae/open-data/` — same source as the manual CSV download,
no captcha), rebuilds `pulse.json`, commits it. The register **back-fills**, so each run
re-pulls its whole window and dedupes — late registrations are caught, not missed.

## Running locally

```bash
python scripts/fetch_dld.py        # optional: refresh data/ from the API (reads only)
python scripts/build_pulse.py      # gates + aggregates -> public/pulse.json
```

- `build_pulse.py` uses the **newest** `data/transactions-YYYY-MM-DD.csv` (pin with `PULSE_STAMP`).
- §9 known-good validation runs only against the pinned 2026-08-25 capture.
- MEED/handover blocks come from the local snapshot dir (`MEED_SNAPSHOT_DIR`) or are
  **carried forward** from the previous `pulse.json` — the MEED layer is deliberately static.

## Hard rules (from HANDOVER.md — do not relax)

1. **Every source passes a fail-closed sanity gate.** Quarantined sources never ship.
2. **Reads only, always.** No write to any endpoint, ever.
3. **No raw-row redistribution** — publish aggregates + attribution only. `data/` is gitignored.
4. **No individual is ever named** — brokers file is counts-only; Ejari rows singles-only.
5. **Every published figure carries source + period.**
6. Rent rows with `TOTAL_PROPERTIES > 1` are bulk leases — excluded (the 48.9% phantom-yield lesson).
7. The official DLD price index (RPPI) is **cite-only** — its terms exclude commercial repackaging.

## Secrets

| Name | Where | Purpose |
|---|---|---|
| `DAC_KEY` | local `.env` (gitignored) · GitHub Actions secret | Digital Abbot Cloud — MEED corpus freshness. Fails soft if absent. |

## Attribution (must appear on every published surface)

> Source: Dubai Land Department (DLD) Open Data. Contains information from the Government of Dubai.
> Project data licensed from MEED Projects (GlobalData), served via Digital Abbot Cloud.

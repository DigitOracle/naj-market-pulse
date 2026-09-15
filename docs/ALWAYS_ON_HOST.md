# The always-on host inside the UAE (Data Spine Phase 6)

Everything in this repo, and both WhatsApp listeners, runs on Kendall's laptop, which sleeps. The deep dive counted 22
sleeps on 7 Sep. On 13 Sep, the 11:37 sweep started as the laptop woke: its listener check reported lost coverage in the
last 24 hours, and its twin-audit push met a closed connection (retried by hand at 11:54, fine in 2 s). The runner now
retries pushes once. The governed Dubai Digital Authority API answers UAE addresses only, so the host must be in the UAE.

**Where it lives is Kendall's decision.** Option 1 is the office computer: on mains, wired internet, battery backup.
Option 2 is a UAE-region cloud virtual machine (AWS, Microsoft Azure and Oracle run UAE regions); opening that account
is Kendall's step. If the production grant ties access to a registered address (ask on ticket 876938549), the host
also needs a fixed address. A cloud machine has one; an office line usually needs one from the provider.

## What the host needs

- Windows 11 Pro or Windows Server. The tasks, wrappers and listener launchers are Windows; the Python runner is not.
- 4 cores, 16 GB memory. The heaviest steps are the DuckDB builds over about 6 million government rows and the Splink
  match. Confirm against the first week's ledger (`data/runs/runs.jsonl`, seconds per step).
- 250 GB SSD. Raw downloads are 83 GB today and grow with every weekly pull.
- Python 3.12 (`ops/requirements-host.txt`), Node 20 or later (both listeners), Git.
- Never sleeps; restarts itself after a power cut; Windows Update restarts kept outside 02:00–08:00.

## What moves

| What | Where on the laptop | Size | How |
|---|---|---|---|
| This repo | `C:\Dev\naj-market-pulse` | code | `git clone https://github.com/DigitOracle/naj-market-pulse` |
| Published store | `data/lake/` | 0.36 GB | copy |
| Truth store + graph | `data/graph/` | 0.61 GB | copy |
| Identity, metrics, availability, run ledger | `data/identity/`, `metrics/`, `data/avail/`, `data/runs/` | small | copy |
| Edge copy of the key–value store | `data/edge_backup/` | 0.08 GB | copy, or let the first night rebuild it |
| Portal extracts, 9 Sep | `data/raw_downloads/dd/` | 60 GB | copy, or re-pull on the host |
| Governed API pulls | `data/raw_downloads/dda/` | 5.8 GB | re-pull on the host (UAE address) |
| Loose DLD exports, 4 Sep | `data/raw_downloads/*.json`, `*.csv` | ~13 GB | retention decision; the 9 Sep extracts carry the same registers. Check no script still reads them before retiring |
| Kendall's listener | `C:\Dev\azimuth-listener` | 0.02 GB (no remote) | copy without `node_modules`, then `npm ci` |
| Naj's listener | `C:\Dev\azimuth-listener-naj` | 0.44 GB (no remote) | copy without `node_modules`, then `npm ci`; the five retired `auth_*` folders stay behind |
| Scheduled tasks (8) | exported to `ops/scheduled_tasks/*.xml` | — | `ops/scheduled_tasks/restore_tasks.ps1` |

Secrets travel by a private channel, never chat or email. Locations only:
- both listeners' `.env`
- the governed API environment file (outside the repos)
- `C:\Users\kwils\.cf_token`
- this repo's `.env` (`DAC_KEY`)

## Cutover, in order

1. **Prove the address.** From the candidate network, make one read-only call to the governed API. No UAE answer, no host.
2. Install Python, Node, Git; clone; `python -m pip install -r ops/requirements-host.txt`; `python -m playwright install chromium`.
3. Copy the data and the secrets listed above.
4. `powershell -ExecutionPolicy Bypass -File ops\scheduled_tasks\restore_tasks.ps1 -WhatIf`. Every task must resolve with
   nothing missing. Then run it again, elevated, without `-WhatIf`. On the laptop these tasks run only while Kendall is
   signed in; the restored copies run with nobody signed in.
5. `python scripts/refresh_runner.py daily --dry` and `sweep --dry`: the plans must list every step.
6. **Listeners, one at a time.** Stop the laptop task, move the `auth` folder, start the task on the host, and watch
   `health.json` update every minute. A WhatsApp session must never run in two places.
7. First real sweep, then the 06:30 daily, on the host. Check the ledger, then disable (not delete) the laptop tasks.
8. After a clean week: the Friday government pull, and move the lake catalogue from SQLite to PostgreSQL on the host
   (deep dive, move 1) if more than one writer needs it.

## Notes

- `Najma_Avail_Sweep` has a 40-minute limit in Task Scheduler, but its availability scan may run for 90 minutes. Raise the
  limit on the host if a large developer pack ever arrives.
- The sweep's resume-from-sleep trigger does nothing on a machine that never sleeps. It is harmless and kept.

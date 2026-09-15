# The question bank

What buyers, tenants, investors and developers ask Naj, and whether the Najma app answers it. Started 15 Sep 2026 at
Kendall's request: "a way for her to provide feedback for any questions that we're missing, almost like we're building up a
question bank... even from a developer perspective as well, not only from a broker perspective."

## How questions arrive

- **In the app**, on Naj's private link only: a small button opens a strip at the bottom of any page. She types, or holds
  the mic while she speaks; it records only while held, so it never picks up the client or the room, and the audio is
  deleted once it is turned into text. What is on screen (tab, community, project, search) is attached for her. One
  optional tap says who asked: buyer, tenant, investor or developer.
- **On WhatsApp**, when the app is not open: a text to Azimuth starting with `?`, or a voice note starting with the word
  "question". Azimuth reacts with ✅ instead of replying.
- **By themselves**: a search on her private link that finds nothing.

Phone numbers, emails and Emirates ID numbers are stripped from notes. Notes stay in the app's private store and on this
laptop (`data/questions/`, never committed); only the bank and its counts are pushed back to the app.

## The bank

`bank.json` holds one entry per canonical question. The starter list (15 Sep 2026) was written from what Dubai clients and
developers routinely ask, then checked against the app; Naj's notes add what it missed.

| field | meaning |
|---|---|
| `id` | `Q001`... never reused |
| `topic` | location, transport, schools_health, community, building_unit, prices_rents, costs_fees, availability, developer, market, legal_finance, investment, environment, residents |
| `askedBy` | who asks it: buyer, tenant, investor, developer |
| `question` | the canonical wording |
| `keys` | phrases that mark a note as this question ("nursery", "service charge") |
| `aliases` | other ways people put it |
| `status` | `answered` (the app answers it today), `held` (we hold the data but no screen shows it), `needs_data` (new data needed), `by_rule` (not answered, by rule) |
| `where` | for answered: the screen, and on which links |
| `source` | the dataset that answers it or would |
| `note` | coverage limits, or the rule for by_rule |

## Every week

`python scripts/question_bank.py weekly`: pull new notes from the app, match each to a bank question, write
`data/questions/weekly_<date>.md` and send Kendall the most-asked questions the app does not answer yet, plus notes that
matched nothing (new questions to add). `validate` checks the bank; `--dry` sends and pushes nothing; `--notes <file>`
tests with a file of notes instead of pulling.

When a question moves to `answered`, a note to Naj is drafted for Kendall's approval; nothing is sent to her directly.

# NAJMA نجمة — Operator's Handover

**For: Najjuko ("Naj") — and any Claude session helping her run this.**
Written 25 August 2026. This document assumes no prior context. Read it top to bottom once;
after that it works as a reference.

---

## 1. What you have

**Najma** (نجمة — Arabic for *star*, from the root "to rise into view") is your market
intelligence system for Dubai property. It exists so you never again quote another brokerage's
market report on camera — you quote **your own figures, from the official government register,
under your own name**.

It is three connected things, and you already use all of them through WhatsApp:

| Piece | What it is | How you reach it |
|---|---|---|
| **Azimuth** | Your personal assistant inside WhatsApp — files your tasks and meetings, reads photos, watches the groups you choose, answers questions | Message it like a person |
| **Your board** | One live page: today, this week, your plate, and the Najma market strip | Send the word **board** — or your saved home-screen icon |
| **Najma market pulse** | The full market dashboard: sales, rents, yields, handovers, developments | Send the word **market** |

There is nothing to install. WhatsApp is the whole interface. The links Azimuth sends you are
**yours** — they contain your private access key, so don't post them publicly or forward them.

---

## 2. Your commands (send these as normal WhatsApp messages)

| Say | Get |
|---|---|
| **help** | The full menu, any time |
| **board** | Your live board link |
| **market** | Your Najma market dashboard link |
| **market brief** | Your weekly market brief, on demand — three sourced story angles |
| **draft podcast 1** (or 2, 3) | A 60–90 second to-camera script drafted from that angle |
| **draft linkedin 2** (or 1, 3) | A LinkedIn post drafted from that angle |
| *(any task)* "call the Vespi broker tomorrow 3pm" | Filed to your plate, reminder set |
| *(any meeting, text or voice note)* | Filed, with nudges before it starts |
| *(a photo — flyer, invite, whiteboard)* | Read; whatever's in it offered for filing |
| *(a photo captioned "this is me")* | Becomes your board backdrop |
| **who owes me** / **what do I owe** | Your commitment ledger |
| **status with [name]** | Everything on record with that person |
| **list groups** / **watch [name]** / **stop watching [name]** | Which WhatsApp groups Azimuth listens to |

Every Sunday morning (~09:00) the weekly brief arrives on its own, with three buttons:
**🎙 Podcast — Angle 1 · ✍️ LinkedIn — Angle 2 · 📊 Dashboard**. Tap and the draft comes back
in the chat.

---

## 3. Where the numbers come from — and why you can say them on camera

Everything on your dashboard comes from **official, public, government-published data**:

- **Sales** — the Dubai Land Department (DLD) open register of every recorded sale. These are
  **settled registrations**, not asking prices.
- **Rents and yields** — registered Ejari rental contracts (Ejari is Dubai's mandatory
  rental-contract register). Real signed contracts, not listing rates.
- **Project pipeline** — the MEED Projects construction database (licensed to DigitAlchemy and
  served through their Digital Abbot Cloud service), a fixed reference layer for what is being
  built and when it hands over.

Before any figure reaches your dashboard or a draft, it passes a **sanity gate** — an automatic
check that rejects malformed, implausible, or suspicious data outright. A source that fails is
quarantined, never blended in. This exists because during the build a public data feed was found
serving deliberately poisoned numbers; the gate is why your figures are defensible.

**The one rule above all others: every figure you say out loud carries its source and period.**
"Dubai registered AED 57.3 billion in sales — that's the Land Department's own register, thirtieth
of June to the twenty-fifth of August." That sentence survives any challenge. A number without
its source does not.

---

## 4. The content engine — from figure to post

**How a draft is created:** the Sunday brief is written by DigitalAbbot's drafting engine from
that week's gated figures only — it is instructed to use nothing else, to tag every figure with
its source and period, and to end with a **what-not-to-claim** line listing the claims that
week's data cannot support. When you tap a button, the engine re-reads that stored brief and its
exact figures and writes your draft from one angle. It cannot invent a number.

**What you do with a draft — the three-step habit:**

1. **Make it yours.** The draft is deliberately labelled *"a draft to make your own, not to post
   as-is."* Read it aloud once; change anything that doesn't sound like you. Your voice is the
   product — the draft is scaffolding.
2. **Keep the sources.** Edit freely, but never detach a figure from its source line, and never
   sharpen a number beyond what it says. If you cut a figure, cut its claim too.
3. **Respect the what-not-to-claim line.** It's computed from what the data can actually
   support that week. If it says no rent claims, there are no rent claims — even in a caption.

**Timing for video:** you speak at roughly **142 words per minute** presenting solo (measured,
not guessed). A 90-second piece is ~210 words; 60 seconds is ~140. The podcast drafts are sized
to this already.

**Standing language rules for anything published:**
- Say "the last eight weeks" or "last month" — never "this week." Registration lags the deal.
- Settled prices, not asking prices — and the gap between them is itself a good story.
- When the market moves, say what it **coincided with**, never what **caused** it. "Sales dipped
  in a week that coincided with…" is defensible; "because of" is not.
- Regional or global turbulence moves money **into** Dubai as often as out — never assume the
  direction.
- Never name any individual from any register, ever.
- Carry the attribution line wherever a figure is published:
  > *Source: Dubai Land Department (DLD) Open Data. Contains information from the Government of Dubai.*
  And where project-pipeline data appears:
  > *Project data licensed from MEED Projects (GlobalData), served via Digital Abbot Cloud.*

---

## 5. The weekly rhythm

| When | What happens (automatically) |
|---|---|
| Daily, morning | The project-pipeline section of your dashboard refreshes |
| Weekdays ~09:00 | A short alert **only if something actually moved** — quiet days stay quiet |
| **Sunday ~09:00** | Your weekly brief + the three content buttons |
| Weekly | The sales and rents sections refresh from the register |

Your dashboard shows its freshness stamps. If it ever warns that data is old, **don't quote it**
— the system would rather be silent than stale, and so should you.

---

## 6. Running this with your own Claude

You can paste any draft into your own Claude session to polish it. Give it this document once,
then work naturally. Good asks:

- *"Tighten this to 60 seconds at 142 words a minute, keep every source line."*
- *"Give me three caption options for this post — same figures, same sources."*
- *"Rewrite this in my voice"* — paste an example of something you've written that sounds like you.
- *"Turn this podcast script into an Instagram caption + a story slide text."*

Two boundaries for any Claude session helping you:

1. **It edits and repackages — it never adds figures.** If a draft lacks a number you want,
   the answer is "check the dashboard," not "estimate one." A Claude that invents a Dubai
   statistic is producing something you cannot say on camera.
2. **It never needs keys, tokens, logins, or deployments.** Everything technical lives with
   DigitAlchemy. If something looks broken, see §7 — don't let any session "fix" the system.

---

## 7. If something breaks

| Symptom | What it means | What to do |
|---|---|---|
| Azimuth stops answering | Its connection dropped | Message **contact@digitalabbot.io** — takes minutes to restore |
| WhatsApp says a linked device was removed | The link needs re-pairing | Same — it's a five-minute fix done with you present |
| Dashboard warns data is stale | A refresh didn't run | Don't quote the stale figures; flag it and it will be re-run |
| A draft cites something odd | Never publish it | Reply in chat what looked wrong; the figure trail is auditable |

Your board and dashboard links keep working even when the chat side hiccups — they're served
independently.

---

## 8. Glossary (no unexplained acronyms)

- **DLD** — Dubai Land Department, the government land registry. The source of record for sales.
- **Ejari** — "my rent" in Arabic; Dubai's mandatory rental-contract registration system.
- **MEED Projects** — a commercial database of construction projects across the Gulf; the
  supply-side reference layer, licensed via DigitAlchemy.
- **Off-plan** — sold before the building is complete. Roughly 7 of 10 Dubai sales.
- **Gross yield** — a year's registered rent divided by the sale price of comparable property in
  the same area; before service charges and costs.
- **Handover** — the developer delivering the finished unit; handover waves become resale and
  rental supply.
- **Azimuth** — your assistant. **Najma** — your market intelligence brand: the star you
  navigate by, and the star presenting it.

---

*Najma · Market Pulse — powered by DigitalAbbot · DigitAlchemy Tech Limited*
*Support: contact@digitalabbot.io · +971 56 227 6093*

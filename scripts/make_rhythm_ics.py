"""Najjuko's operating rhythm as a calendar file she can import into Google or Apple Calendar (Asia/Dubai).

Weekly recurring slots (proposals to fit her diary; the automatic ones are fixed) plus the dated one-offs.
Usage: python scripts/make_rhythm_ics.py <out.ics>
"""
import sys, uuid, datetime as dt

OUT = sys.argv[1] if len(sys.argv) > 1 else "NAJMA_RHYTHM.ics"
TZ = "Asia/Dubai"
# (weekday code, HHMM start, minutes, title, description)
WEEKLY = [
    ("MO,TU,WE,TH,FR", "0700", 20, "Najma: pick + post (the five)", "07:00 the feed arrives. Pick with feed:3 or feed:3+7 (or type the numbers). Read the draft once, keep the source line, post the LinkedIn piece, save the Instagram draft. Then decide: deeper dive, or not today."),
    ("MO,TU,WE,TH,FR", "0705", 5, "Najma: trend radar (open if you want)", "A separate short message with one link. What people are talking about today. Say trend 3 to draft from item 3."),
    ("MO,TU,WE,TH,FR", "1730", 10, "Najma: second post", "Type more, pick, post."),
    ("MO", "1000", 60, "Record this week's Instagram reels", "From the saved drafts. Two reels. Hook first."),
    ("TU", "0900", 30, "Career: scanner matches + applications", "Review the 07:30 scanner results, send tailored applications (up to 20 a week)."),
    ("WE", "1100", 60, "Video slot: approve or record one piece", "Queue order: Najjuko Edit reels 1-4 first, then Wellness Real Estate. Wednesday evening is the wellness release."),
    ("TH", "1000", 60, "Clients: reports + floor plans", "report <area> for <client> in Azimuth; floor plans from the PLANS tab; send."),
    ("FR", "1200", 20, "Close the week", "who owes me / what do I owe; forward any developer PDFs into the group."),
    ("SU", "2000", 20, "Plan the week", "Read the Sunday brief (arrives ~09:00), tap the content buttons, note Monday's reels."),
]
ONEOFF = [
    ("2026-09-06", "1000", 180, "Videographer shoot: five pieces", "Ten minutes of real Najjuko in five two-minute pieces + three minutes of in-between footage. Plan: NAJ_SHOOT_PLAN_06SEP2026.pdf. No numbers, no names on camera."),
    ("2026-09-08", "0900", 30, "The Valley: permit, agent pack, final cut", "Advertiser permit and RERA card current; Emaar agent pack + asset consent requested; choose the 1:19 or 1:15 cut."),
    ("2026-09-10", "1930", 30, "The Valley: publish", "#ThisIsTheValley - tag and follow @EmaarInsider - 60 to 90 s - Emaar visuals only - no capital-appreciation claim."),
    ("2026-09-11", "1300", 15, "Valley amplification: TikTok", ""),
    ("2026-09-12", "1100", 15, "Valley amplification: LinkedIn", ""),
    ("2026-09-13", "1930", 15, "Valley amplification: cut-down", ""),
    ("2026-09-14", "1300", 15, "Valley amplification: stories (optional live 20:00)", ""),
    ("2026-09-15", "1800", 15, "Emaar District Ambassador window closes", ""),
    ("2026-12-30", "1000", 30, "EYWA handover: one piece prepared in advance", ""),
]
DAYMAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

def esc(t): return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
def stamp(d, hhmm): return f"{d.strftime('%Y%m%d')}T{hhmm}00"

lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DigitAlchemy//Najma rhythm//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Najma rhythm", "X-WR-TIMEZONE:" + TZ,
         "BEGIN:VTIMEZONE", "TZID:" + TZ, "BEGIN:STANDARD", "DTSTART:19700101T000000", "TZOFFSETFROM:+0400", "TZOFFSETTO:+0400", "TZNAME:GST", "END:STANDARD", "END:VTIMEZONE"]
now = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
start_week = dt.date(2026, 9, 6)  # the Sunday the rhythm starts
for days, hhmm, mins, title, desc in WEEKLY:
    first_code = days.split(",")[0]
    first = start_week + dt.timedelta(days=(DAYMAP[first_code] - start_week.weekday()) % 7)
    end = (dt.datetime.combine(first, dt.time(int(hhmm[:2]), int(hhmm[2:]))) + dt.timedelta(minutes=mins)).strftime("%Y%m%dT%H%M%S")
    lines += ["BEGIN:VEVENT", "UID:" + str(uuid.uuid4()) + "@najma", "DTSTAMP:" + now, f"DTSTART;TZID={TZ}:" + stamp(first, hhmm), f"DTEND;TZID={TZ}:" + end,
              "RRULE:FREQ=WEEKLY;BYDAY=" + days, "SUMMARY:" + esc(title), "DESCRIPTION:" + esc(desc), "END:VEVENT"]
for d, hhmm, mins, title, desc in ONEOFF:
    day = dt.date.fromisoformat(d)
    end = (dt.datetime.combine(day, dt.time(int(hhmm[:2]), int(hhmm[2:]))) + dt.timedelta(minutes=mins)).strftime("%Y%m%dT%H%M%S")
    lines += ["BEGIN:VEVENT", "UID:" + str(uuid.uuid4()) + "@najma", "DTSTAMP:" + now, f"DTSTART;TZID={TZ}:" + stamp(day, hhmm), f"DTEND;TZID={TZ}:" + end,
              "SUMMARY:" + esc(title), "DESCRIPTION:" + esc(desc), "END:VEVENT"]
lines.append("END:VCALENDAR")
open(OUT, "w", encoding="utf-8", newline="\r\n").write("\n".join(lines) + "\n")
print("wrote", OUT, "-", len(WEEKLY), "weekly +", len(ONEOFF), "dated events")

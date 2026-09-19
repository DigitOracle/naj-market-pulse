"""Naj's replacement morning feed, 19 Sep 2026 (the 06:00 run sent one angle; Kendall approved these five in chat)."""
import urllib.error, urllib.parse, urllib.request

TEXT = """\u2600\ufe0f Your five for today \u2014 fresh figures, none used before.

DUBAI 2040
1. Beaches (move) \u2014 Dubai's public beaches are set to grow by up to 400% by 2040. That's the difference between a city by the sea and a city that lives on it: for a family choosing a neighbourhood now, that's where weekends are heading.
Source: Dubai Media Office, 13 Mar 2021 (target).

2. Blue Line (invest) \u2014 The Metro Blue Line: 30 km, 14 stations, projected to serve 1 million residents by 2040. New stations change what a neighbourhood is worth to live in \u2014 I'm watching where it runs.
Source: Dubai Media Office, 4 Mar 2025 (announced).

3. Urban centres (authority) \u2014 The 2040 plan names Downtown and Business Bay among Dubai's 5 main urban centres, each built for 1 to 1.5 million people. On the register, Business Bay recorded 774 sales from 25 Jul to 18 Sep. The plan says where Dubai is going; the register shows buyers already there.
Sources: UAE Government portal, 13 Mar 2021; DLD Open Data, 25 Jul-18 Sep.

REAL ESTATE
4. Market (invest) \u2014 22,777 homes changed hands between 25 Jul and 18 Sep, worth AED 55.8B. Summer usually goes quiet. This one didn't.
Source: DLD Open Data, 25 Jul-18 Sep.

5. Yield (invest) \u2014 Al Warsan First is returning a 7.8% gross rental yield, the highest in the register's area list, on 1,399 rent contracts. If you buy to let, that's the number to start from.
Source: DLD rent register to 19 Sep.

\u2014 Papi"""

key = next(l.split("=", 1)[1].strip() for l in open(r"C:\Dev\azimuth-listener-naj\.env") if l.startswith("READ_KEY="))
url = "https://azimuth-2.digitalchemy.workers.dev/note?" + urllib.parse.urlencode({"key": key, "text": TEXT})
try:
    print(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "najma/1.0"}), timeout=60).read().decode())
except urllib.error.HTTPError as e:
    print("NOT SENT", e.code, e.read().decode())

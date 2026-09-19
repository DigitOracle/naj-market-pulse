"""Send Naj today's five approved cards (square + story), via Azimuth /sendimg. Kendall approved in chat, 19 Sep 2026."""
import json, urllib.error, urllib.parse, urllib.request

RES = r"C:\Users\kwils\AppData\Local\Temp\claude\C--Users-kwils-Downloads\181e34aa-da15-4def-871c-af5c1810593b\scratchpad\plate_run5.json"
LABEL = {1: "Dubai 2040 \u00b7 beaches", 2: "Dubai 2040 \u00b7 Metro Blue Line", 3: "Dubai 2040 \u00b7 Business Bay",
         4: "Real estate \u00b7 the market", 5: "Real estate \u00b7 yield"}
key = next(l.split("=", 1)[1].strip() for l in open(r"C:\Dev\azimuth-listener-naj\.env") if l.startswith("READ_KEY="))
res = json.load(open(RES))


def send(name, caption):
    u = "https://azimuth-2.digitalchemy.workers.dev/sendimg?" + urllib.parse.urlencode({"key": key, "name": name, "caption": caption})
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "najma/1.0"}), timeout=90).read().decode()
    except urllib.error.HTTPError as e:
        return "NOT SENT %s %s" % (e.code, e.read().decode()[:200])


for n in range(1, 6):
    r = res[str(n)]
    sq = r["square"].rsplit("/img/", 1)[1]; st = r["story"].rsplit("/img/", 1)[1]
    print(n, send(sq, "%d/5 \u2014 %s (post)" % (n, LABEL[n])))
    print(n, send(st, "%d/5 \u2014 %s (story)" % (n, LABEL[n])))

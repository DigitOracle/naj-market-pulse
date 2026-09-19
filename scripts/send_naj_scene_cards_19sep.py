"""Send Naj the five approved scene cards (square + story), replacing the cut-out set. Kendall approved in chat, 19 Sep 2026."""
import json, urllib.error, urllib.parse, urllib.request

RES = r"C:\Users\kwils\AppData\Local\Temp\claude\C--Users-kwils-Downloads\181e34aa-da15-4def-871c-af5c1810593b\scratchpad\scene_v2.json"
LABEL = {1: "Dubai 2040 \u00b7 beaches", 2: "Dubai 2040 \u00b7 Metro Blue Line", 3: "Dubai 2040 \u00b7 Business Bay",
         4: "Real estate \u00b7 the market", 5: "Real estate \u00b7 yield"}
B = "https://azimuth-2.digitalchemy.workers.dev"
key = next(l.split("=", 1)[1].strip() for l in open(r"C:\Dev\azimuth-listener-naj\.env") if l.startswith("READ_KEY="))
res = json.load(open(RES))


def get(path, **q):
    q["key"] = key
    try:
        return urllib.request.urlopen(urllib.request.Request(B + path + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "najma/1.0"}), timeout=90).read().decode()
    except urllib.error.HTTPError as e:
        return "NOT SENT %s %s" % (e.code, e.read().decode()[:200])


print("note", get("/note", text="Black Coffee \u2615 \u2014 better versions of today's five: you're in the scene this time, not pasted on. Use these instead of the earlier set. \u2014 Papi"))
for n in range(1, 6):
    r = res[str(n)]
    for kind, u in (("post", r["square"]), ("story", r["story"])):
        print(n, kind, get("/sendimg", name=u.rsplit("/img/", 1)[1], caption="%d/5 \u2014 %s (%s)" % (n, LABEL[n], kind)))

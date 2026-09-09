"""Geocoders shared by the binders and the amenity builders. Esri World Geocoder via the Worker's token endpoint (READ_KEY);
Google Places Text Search (GOOGLE_KEY) where a street geocoder is weak. Pure functions - importing this never runs anything."""
import json, os, urllib.parse, urllib.request
WORKER = "https://azimuth-2.digitalchemy.workers.dev"


def token():
    key = os.environ.get("READ_KEY")
    if not key: raise SystemExit("READ_KEY not set")
    return json.load(urllib.request.urlopen(urllib.request.Request(f"{WORKER}/esri_token?key={key}", headers={"User-Agent": "najma-bind/1.0"}), timeout=30))["token"]

def geocode(tok, q):
    p = urllib.parse.urlencode({"f": "json", "token": tok, "langCode": "en", "singleLine": q, "maxLocations": "1", "outFields": "Score,Addr_type,Type", "searchExtent": "54.9,24.7,55.7,25.4", "countryCode": "ARE"})
    j = json.load(urllib.request.urlopen(urllib.request.Request("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?" + p, headers={"Referer": WORKER, "User-Agent": "najma-bind/1.0"}), timeout=30))
    c = (j.get("candidates") or [None])[0]
    if not c: return None
    a = c.get("attributes", {})
    return {"lon": c["location"]["x"], "lat": c["location"]["y"], "score": c.get("score", 0), "address": c.get("address", ""), "addr_type": a.get("Addr_type"), "type": a.get("Type")}

def geocode_google(key, name, area):
    """Google Places Text Search (New) - resolves developer project names far better than a street geocoder. Needs GOOGLE_KEY."""
    body = json.dumps({"textQuery": f"{name} {area} Dubai".strip(), "locationBias": {"circle": {"center": {"latitude": 25.12, "longitude": 55.25}, "radius": 45000.0}}, "maxResultCount": 1}).encode()
    req = urllib.request.Request("https://places.googleapis.com/v1/places:searchText", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.displayName,places.location,places.types,places.formattedAddress"})
    j = json.load(urllib.request.urlopen(req, timeout=30)); pl = (j.get("places") or [None])[0]
    if not pl: return None
    return {"lon": pl["location"]["longitude"], "lat": pl["location"]["latitude"], "score": 90, "address": pl.get("formattedAddress", ""), "addr_type": "POI", "type": ",".join(pl.get("types", [])[:3]), "name": (pl.get("displayName") or {}).get("text"), "via": "google"}

# A footprint that already carries its own name is evidence. If the register scheme we are about to pin on it shares no
# distinctive word with that name, the geocoder has landed us on the wrong building - which is exactly how "23 Marina" ended up
# labelled as somebody else's scheme and "Ciel Tower" as somebody else's tower. District words carry no evidence at all here:
# every third building in Dubai Marina has "Marina" in its name. Reject the pin rather than publish a wrong owner.


def places_contact(key, name, area):
    """Google Places Text Search with the contact fields: phone, website, address, opening hours. Used only on a place we have
    already verified against a register; cached by the caller, never re-paid."""
    body = json.dumps({"textQuery": f"{name} {area} Dubai".strip(), "locationBias": {"circle": {"center": {"latitude": 25.12, "longitude": 55.25}, "radius": 45000.0}}, "maxResultCount": 1}).encode()
    req = urllib.request.Request("https://places.googleapis.com/v1/places:searchText", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Goog-Api-Key": key,
                                          "X-Goog-FieldMask": "places.displayName,places.location,places.formattedAddress,places.internationalPhoneNumber,places.websiteUri,places.regularOpeningHours.weekdayDescriptions"})
    j = json.load(urllib.request.urlopen(req, timeout=30)); pl = (j.get("places") or [None])[0]
    if not pl: return None
    hrs = ((pl.get("regularOpeningHours") or {}).get("weekdayDescriptions") or [])
    return {"name": (pl.get("displayName") or {}).get("text"), "lon": pl["location"]["longitude"], "lat": pl["location"]["latitude"],
            "address": pl.get("formattedAddress", ""), "tel": pl.get("internationalPhoneNumber"), "web": pl.get("websiteUri"), "hours": hrs[:7]}


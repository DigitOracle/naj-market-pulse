"""What KIND of name is this? The classifier that decides whether a string may ever become a building's name.

The resolver used to ask "is 'Apple Office' good enough to replace 'B4'?" and answered it with an ever-growing blacklist.
That question is unanswerable and the blacklist never ends. This asks a different question - what ROLE does this string play? -
and then a tenant simply is not eligible to be a building name, whatever its confidence or its source.

Three separate steps, deliberately not one (a single clean_name() that both normalised and judged is what deleted 'A1',
'B4' and 'B5' from the twin - normalisation must never destroy evidence):

    normalize(raw)                 -> a tidy string, or None only when there is nothing there at all
    classify(normalized, category) -> a NAME_ROLE
    eligible(role)                 -> whether that role may become the canonical display name

ROLES
    BUILDING_NAME    the building's own published name          "Marina Gate 1", "Palazzo Versace Dubai"
    STRUCTURAL_ID    what the site plan calls it                 "A1", "B4", "Building 6", "Tower 3"
    PROJECT_NAME     the scheme it belongs to                    "Belgravia Heights I"
    PLOT_ID          cadastral identity                          "Plot 3460672"
    ADDRESS          a street address                            "Villa 32, Street 14"
    TENANT           a business trading inside it                "Apple Office", "Primavera Dry Cleaning"
    VENUE            a bar/restaurant/venue inside it            "Vanitas Restaurant at Palazzo Versace"
    AMENITY          a facility OF the building                  "Jam Tower Car Parking", "reception"
    INFRASTRUCTURE   transport and public works                  "Burj Khalifa/Dubai Mall Metro Station"
    ADVERTISEMENT    a listing, not a place                      "City Walk 1BR, Stunning Burj Khalifa view"
    FRAGMENT         not a whole name                            "Group", "Dubai The"
    PERSON           a practitioner, not a place                 "Dr. Michael Roger"
    UNKNOWN          none of the above

Only BUILDING_NAME, STRUCTURAL_ID, PROJECT_NAME, PLOT_ID and ADDRESS may ever be canonical. Everything else is kept
against the building as evidence - a tenant list is genuinely useful - but can never be what the building is called.
"""
import re, unicodedata

CANONICAL_ROLES = ("BUILDING_NAME", "STRUCTURAL_ID", "PROJECT_NAME", "PLOT_ID", "ADDRESS")

# --- the vocabulary each role is recognised by
BUILDINGISH = re.compile(r"\b(tower|towers|residence|residences|building|plaza|heights|court|mansion|villa|villas|"
                         r"apartments?|complex|centre|center|mall|hotel|suites|lofts|gate|house|palace|palazzo|"
                         r"boulevard|arcade|terrace|terraces|lodge|manor|pavilion|wing|block)\b", re.I)
STRUCTURAL = re.compile(r"^(?:(?:building|bldg|tower|block|plot|phase|wing|cluster)\s*)?[A-Z]{0,2}[- ]?\d{1,4}[A-Z]?$", re.I)
PLOT = re.compile(r"^(?:plot|parcel|land)\s*(?:no\.?\s*)?[\d./-]+$", re.I)
ADDRESSY = re.compile(r"^(?:villa|no\.|house|unit)\s*[\w-]+(?:,\s*.+)?$", re.I)
AMENITY = re.compile(r"\b(car\s?park(ing)?|parking|valet|reception|lobby|entrance|gate\s*\d|atm|kiosk|food court|"
                     r"toilet|prayer room|taxi|loading bay|service (entrance|lift)|swimming pool|pool bar|gym|"
                     r"health club|spa|business centre|business center|concierge)\b", re.I)
INFRA = re.compile(r"\b(metro station|metro|tram|bus (station|stop|depot)|station|interchange|substation|"
                   r"pumping station|water tank|sewage|power plant|helipad|bridge|tunnel)\b", re.I)
TENANT = re.compile(r"\b(restaurant|cafe|coffee|bar|pub|lounge|bistro|grill|kitchen|bakery|butcher|salon|spa|barber|"
                    r"clinic|dental|dentist|doctor|medical|pharmacy|laundry|dry[- ]cleaning|cleaners|grocery|"
                    r"supermarket|hypermarket|market|insurance|bank|exchange|travel|tourism|agency|agent|"
                    r"consultanc\w*|contracting|trading|general trading|gym|fitness|yoga|pilates|studio|nursery|"
                    r"kindergarten|academy|training|showroom|furniture|boutique|tailor|optic\w*|garage|workshop|"
                    r"car wash|rent a car|typing|photocopy|stationery|florist|veterinary|law firm|advocates)\b", re.I)
VENUE_AT = re.compile(r"\b(at|in|inside|by)\s+(the\s+)?[A-Z]", re.U)
LISTING = re.compile(r"(\b\d\s*(br|bed|bedroom|bhk)\b|\bstudio apt\b|\bapartment with\b|\bwith .*\bview\b|\bstunning\b|"
                     r"\bluxur\w*\b|\bcosy\b|\bcozy\b|\bspacious\b|\bsophisticated\b|\bhosted by\b|\bshort[- ]term\b|"
                     r"\bholiday home\b|\bfor rent\b|\bfor sale\b|\bper night\b|\|)", re.I)
PERSON = re.compile(r"^(dr|mr|mrs|ms|prof|eng)\.?\s|\s[-–]\s.*\b(coach|consultant|therapist|trainer|specialist|"
                    r"designer|photographer|adviser|advisor|broker|realtor|practitioner)\b", re.I)
FILLER_ONLY = re.compile(r"^(the|a|an|of|and|dubai|uae|group|company|llc|fz|fze)"
                         r"(\s+(the|a|an|of|and|dubai|uae|group|company|llc|fz|fze))*$", re.I)


def normalize(raw):
    """Tidy the string. Returns None ONLY when there is genuinely nothing - never as a judgement about quality."""
    if raw is None: return None
    v = unicodedata.normalize("NFKC", str(raw)).strip().strip("-–—,;:·|")
    v = re.sub(r"\s+", " ", v)
    v = re.sub(r"\s*\((?:LLC|L\.L\.C|FZE|FZ-?LLC|Branch)\)\s*$", "", v, flags=re.I).strip()
    return v or None


# A name written ON a building polygon is a building name. A name attached to a POINT has to earn that status, because a
# point sits wherever a business registered itself. Treating both alike is what turned "Dubai Gate 1" into an amenity and
# "Green Lakes 1" into UNKNOWN - both are exactly what OpenStreetMap calls those towers.
POLYGON_SOURCES = {"osm", "osm_en", "overture", "wikidata", "dld", "register", "binding", "dld_unit", "dm_building"}


def classify(name, category=None, source=None):
    """The role this string plays. `category` is the source's own category where it has one; `source` says whether the
    name was written on the building itself or merely found near it."""
    n = (name or "").strip()
    if not n: return "UNKNOWN"
    cat = (category or "").lower()
    on_the_building = source in POLYGON_SOURCES
    if LISTING.search(n): return "ADVERTISEMENT"
    if PERSON.search(n): return "PERSON"
    if FILLER_ONLY.match(n): return "FRAGMENT"
    if PLOT.match(n): return "PLOT_ID"
    if ADDRESSY.match(n) and re.search(r"\d", n): return "ADDRESS"
    if STRUCTURAL.match(n): return "STRUCTURAL_ID"
    if on_the_building:
        # the survey drew this polygon and named it; the only things it still cannot be are an advert or a person
        return "BUILDING_NAME"
    # the source's own category is decisive for the two roles a string cannot betray
    if "parking" in cat or AMENITY.search(n): return "AMENITY"
    if any(k in cat for k in ("transit", "metro", "bus_", "train", "station")) or INFRA.search(n): return "INFRASTRUCTURE"
    # "Vanitas Restaurant at Palazzo Versace" is a venue INSIDE a building, never the building
    if VENUE_AT.search(n) and (TENANT.search(n) or "restaurant" in cat or "bar" in cat): return "VENUE"
    if TENANT.search(n) and not BUILDINGISH.search(n): return "TENANT"
    if BUILDINGISH.search(n): return "BUILDING_NAME"
    if cat in ("apartment_building", "apartment_complex", "condominium_complex", "housing_complex", "residential_building",
               "premise", "subpremise", "building", "office_building", "hotel", "resort_hotel", "shopping_mall",
               "landmark_and_historical_building"):
        return "BUILDING_NAME"
    if TENANT.search(n): return "TENANT"
    words = [w for w in re.split(r"\s+", n) if w]
    if len(words) < 2 and not re.search(r"\d", n): return "FRAGMENT"
    return "UNKNOWN"


def eligible(role):
    return role in CANONICAL_ROLES


def parent_of(name, role):
    """The building a non-canonical string is pointing AT. 'Jam Tower Car Parking' -> 'Jam Tower';
    'Vanitas Restaurant at Palazzo Versace' -> 'Palazzo Versace'. Returns None when there is nothing to lift."""
    n = (name or "").strip()
    if not n: return None
    if role in ("AMENITY", "INFRASTRUCTURE"):
        p = AMENITY.sub("", n) if role == "AMENITY" else INFRA.sub("", n)
        p = re.sub(r"\s*[-–,]\s*$", "", re.sub(r"\s+", " ", p)).strip(" -–,")
        if p and BUILDINGISH.search(p) and len(p.split()) >= 2: return p
        return None
    if role in ("VENUE", "TENANT"):
        m = re.search(r"\b(?:at|in|inside)\s+(?:the\s+)?(.+)$", n, re.I)
        if m:
            p = m.group(1).strip(" .,-–")
            if p and len(p.split()) >= 2: return p
        m = re.search(r"^(.*?)\s*[-–]\s*(building\s*\d+|tower\s*\d+|block\s*[A-Z0-9]+)$", n, re.I)
        if m: return m.group(2).strip()
    return None

"""Nationality -> region for the internal resident mix (Kendall, 15 Sep 2026: "instead of individual countries, continents,
then a further breakdown"). Names are the DEWA customer register's own spellings (227 on the 2026-01-06 extract).

A nationality counts under the region of the passport the account holder registered with, so second passports count
where they were issued: Saint Kitts and Nevis, Dominica, Grenada and Antigua under Americas, Vanuatu under Oceania.
Arab League members, North Africa included, are the Arab world; "Sub-Saharan Africa" is the rest of Africa. Israel and
the register's non-country entries (United Nations, NATO, Blue, Orange, British Indian Ocean Territory) are Rest of the world.

regions_for() applies the store's floor (methodology section 11: no figure below 20 accounts leaves the store) at every
level, including remainders a reader could work out by subtraction. Its output carries whole percents only, no accounts.
"""
import math

REST = "Rest of the world"

_GROUPS = {
    "Arab world": [
        "United Arab Emirates", "Egypt", "Lebanon", "Syria", "Jordan", "Saudi Arabia", "Sudan", "Morocco", "Iraq", "Palestine",
        "Tunisia", "Algeria", "Yemen", "Kuwait", "Oman", "Bahrain", "Djibouti", "Libya", "Qatar", "Comoros", "Somalia",
        "Mauretania", "West Sahara"],
    "South Asia": ["India", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal", "Afghanistan", "Maldives", "Bhutan"],
    "Europe": [
        "United Kingdom", "France", "Germany", "Italy", "Netherlands", "Ireland", "Spain", "Romania", "Cyprus", "Portugal",
        "Serbia and Montenegro", "Belgium", "Poland", "Sweden", "Greece", "Switzerland", "Denmark", "Austria", "Hungary",
        "Bulgaria", "Malta", "Latvia", "Slovakia", "Czech Republic", "Croatia", "Norway", "Bosnia and Herzegovina", "Albania",
        "Finland", "Macedonia", "Lithuania", "Slovenia", "Estonia", "Luxembourg", "Liechtenstein", "European Union", "Iceland",
        "Andorra", "Greenland", "San Marino", "Monaco", "Republic of Kosovo", "Gibraltar", "ALAND ISLANDS"],
    "Russia & Central Asia": [
        "Russian Federation", "Ukraine", "Kazakhstan", "Uzbekistan", "Belarus", "Azerbaijan", "Armenia", "Kyrgyzstan",
        "Turkmenistan", "Tajikistan", "Georgia", "Moldova"],
    "Iran & Türkiye": ["Iran", "Turkey"],
    "East & Southeast Asia": [
        "Philippines", "China", "South Korea", "Malaysia", "Singapore", "Burma", "Japan", "Indonesia", "Vietnam", "Thailand",
        "Taiwan", "Hong Kong", "Cambodia", "Mongolia", "Macau", "Brunei Darussalam", "Laos", "North Korea", "East Timor"],
    "Sub-Saharan Africa": [
        "South Africa", "Nigeria", "Kenya", "Ethiopia", "Tanzania", "Uganda", "Zimbabwe", "Cameroon", "Eritrea", "Ghana",
        "Mauritius", "Sierra Leone", "Senegal", "Democratic Republic of the Congo", "Angola", "Mali", "Guinea", "Cote d'Ivoire",
        "Madagascar", "Chad", "Mozambique", "Zambia", "Seychelles", "Gabon", "Burundi", "Republic of the Congo", "Gambia",
        "Niger", "Malawi", "Rwanda", "Swaziland", "Burkina Faso", "Botswana", "Liberia", "Benin", "Namibia", "Togo",
        "Guinea-Bissau", "Reunion", "Central African Republic", "Lesotho", "Mayotte", "Saint Helena", "Equatorial Guinea",
        "Sao Tome and Principe", "Cape Verde"],
    "Americas": [
        "Canada", "USA", "Brazil", "Saint Kitts and Nevis", "Dominica", "Colombia", "Mexico", "Argentina", "Venezuela", "Guyana",
        "Grenada", "Cuba", "Peru", "Antigua and Barbuda", "Chile", "Ecuador", "Panama", "Jamaica", "Trinidad and Tobago",
        "St. Lucia", "Uruguay", "Dominican Republic", "British Virgin Islands", "Costa Rica", "American Virgin Islands",
        "Dutch Antilles", "Paraguay", "Belize", "El Salvador", "Suriname", "Bolivia", "Honduras", "Barbados", "Guatemala",
        "Nicaragua", "Bahamas", "Cayman Islands", "Turks and Caicos Islands", "Puerto Rico", "Guadeloupe",
        "St. Vincent and the Grenadines", "French Guyana", "Aruba", "St. Pierre and Miquelon", "Montserrat", "Martinique",
        "Haiti", "Falkland Islands", "Anguilla", "Bermuda"],
    "Oceania": [
        "Australia", "New Zealand", "Vanuatu", "Fiji", "American Samoa", "French Polynesia", "Papua New Guinea", "Nauru", "Tonga",
        "Palau", "Pitcairn Islands", "Tuvalu", "Tokelau Islands", "Guam", "Coconut Islands"],
    REST: [
        "Israel", "British Indian Ocean Territory", "United Nations", "Blue", "American Minor Outlying Islands", "Orange",
        "South Georgia and the Southern Sandwich Islands", "NATO"],
}

# counted in their region's share, never named as a country
NOT_A_COUNTRY = {"European Union", "United Nations", "NATO", "Blue", "Orange", "British Indian Ocean Territory"}

REGION = {}
for _region, _names in _GROUPS.items():
    for _n in _names:
        if _n in REGION:
            raise ValueError("%s is in both %s and %s" % (_n, REGION[_n], _region))
        REGION[_n] = _region


def pct(n, total):
    """Whole percent, halves up - the same rounding as the mix's SQL round() on positive shares."""
    return int(math.floor(100.0 * n / total + 0.5))


def regions_for(counts, total, min_accounts=20, country_min_pct=1):
    """One community. counts: [(nationality, accounts)]; total: its residential accounts carrying a nationality.

    Returns (regions, unmapped). Each region is {"name", "pct", "countries": [[nationality, pct], ...], "others": pct},
    sorted by share with Rest of the world last. A country is named only with 20+ accounts and a share rounding to 1%+.
    A region is listed only with 20+ accounts and 1%+; smaller regions count in Rest of the world. A region's unnamed
    remainder under 20 accounts also moves to Rest of the world, or subtraction would reveal it (Iran & Türkiye has two
    countries: with Iran named, "others" would be Türkiye). Unmapped spellings count in Rest of the world and are reported."""
    unmapped = sorted({nat for nat, _ in counts if nat not in REGION})
    groups = {}
    for nat, n in counts:
        groups.setdefault(REGION.get(nat, REST), []).append((nat, n))
    rest = list(groups.pop(REST, []))

    def nameable(nat, n):
        return nat not in NOT_A_COUNTRY and n >= min_accounts and pct(n, total) >= country_min_pct

    shown = []
    for name, items in groups.items():
        region_n = sum(n for _, n in items)
        if region_n < min_accounts or pct(region_n, total) < 1:
            rest += items
            continue
        named = sorted([(nat, n) for nat, n in items if nameable(nat, n)], key=lambda x: (-x[1], x[0]))
        others_n = region_n - sum(n for _, n in named)
        if named and 0 < others_n < min_accounts:
            keep = {nat for nat, _ in named}
            rest += [(nat, n) for nat, n in items if nat not in keep]
            others_n = 0
        region_n = sum(n for _, n in named) + others_n
        shown.append((-region_n, name, {"name": name, "pct": pct(region_n, total),
                                        "countries": [[nat, pct(n, total)] for nat, n in named], "others": pct(others_n, total)}))
    out = [g for _, _, g in sorted(shown, key=lambda s: (s[0], s[1]))]

    rest_n = sum(n for _, n in rest)
    if rest_n and pct(rest_n, total) >= 1:
        named = sorted([(nat, n) for nat, n in rest if REGION.get(nat) == REST and nameable(nat, n)], key=lambda x: (-x[1], x[0]))
        out.append({"name": REST, "pct": pct(rest_n, total), "countries": [[nat, pct(n, total)] for nat, n in named],
                    "others": pct(rest_n - sum(n for _, n in named), total)})
    return out, unmapped


if __name__ == "__main__":
    # the Iran & Türkiye case, a folded small region, and a remainder big enough to stay
    demo = [("Iran", 40), ("Turkey", 8), ("India", 300), ("Pakistan", 60), ("Nepal", 25), ("Fiji", 5), ("Israel", 30), ("Blue", 2)]
    for g in regions_for(demo, sum(n for _, n in demo))[0]:
        print(g)

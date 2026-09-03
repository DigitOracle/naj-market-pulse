#!/bin/bash
# geocode-bind DLD project names onto footprints for the districts where map names are thin (READ_KEY = azimuth2 read key -> Worker /esri_token)
cd /c/Dev/naj-market-pulse
export READ_KEY="$(grep '^GROUPS_URL=' /c/Dev/azimuth-listener-naj/.env | sed 's/.*key=//' | tr -d '\r')"
while IFS='|' read -r area slug; do
  echo "=== $area -> $slug"
  python scripts/bind_buildings.py --area "$area" --slug "$slug" 2>&1 | tail -6
done <<'LIST'
Al Khairan First|alkhairanfirst
Madinat Dubai Almelaheyah|dubaimaritimecity
Hadaeq Sheikh Mohammed Bin Rashid|dubaihills
Jumeirah Village Circle|jumeirahvillagecircle
Al Wasl|alwasl
Marsa Dubai|dubaimarina
Palm Jumeirah|palmjumeirah
Burj Khalifa|burjkhalifa
Al Barsha South Fourth|arjan
Palm Deira|palmdeira
Wadi Al Safa 5|wadialsafa5
Al Thanyah Fifth|althanyahfifth
Jabal Ali First|jabalalifirst
Al Hebiah Fifth|alhebiahfifth
Jumeirah Village Triangle|jumeirahvillagetriangle
Al Merkadh|meydanone
Nad Al Shiba First|sobhaheartland
Madinat Al Mataar|madinatalmataar
Dubai Investment Park First|dubaiinvestmentparkfirst
Al Hebiah Fourth|dubaisportscity
LIST
echo BIND_ALL_DONE

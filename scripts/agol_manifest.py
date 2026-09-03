"""Assemble data/board/scenelayers.json from the per-package publish sidecars.

scripts/agol_publish_scene.py writes <slpk>.agol.json next to every package it
publishes; scripts/ce_export_slpk.py writes data/ce/_slpk/_export_summary.json with
the shape counts.  This joins the two into the one manifest the viewer reads:

    { "<slug>": { "item_id", "service_url", "layer_url", "published", "private", "features" } }

`item_id` is the HOSTED SCENE LAYER item (not the package item - that one is kept in
`package_item_id` so the pair can be found again).  Nothing here changes sharing:
`private` simply reports the access level the sidecar recorded at publish time.

Usage:  python scripts/agol_manifest.py            # plain python is enough, no arcgis import
        python scripts/agol_manifest.py --check    # also re-read access live (needs propy)
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SLPK = os.path.join(ROOT, "data", "ce", "_slpk")
OUTP = os.path.join(ROOT, "data", "board", "scenelayers.json")
SUMMARY = os.path.join(SLPK, "_export_summary.json")


def main():
    shapes = {}
    if os.path.exists(SUMMARY):
        for r in json.load(open(SUMMARY, encoding="utf-8")).get("results", []):
            if "shapes" in r:
                shapes[r["slug"]] = r["shapes"]

    manifest = {}
    for side in sorted(glob.glob(os.path.join(SLPK, "*.slpk.agol.json"))):
        slug = os.path.basename(side)[:-len(".slpk.agol.json")]
        d = json.load(open(side, encoding="utf-8"))
        # the proof publish and the lane publish can both leave a sidecar; keep the newest
        manifest[slug] = {
            "item_id": d.get("scene_layer_item_id"),
            "service_url": d.get("scene_layer_url"),
            "layer_url": d.get("layer0_url") or ((d.get("scene_layer_url") or "") + "/layers/0"),
            "published": d.get("published_at"),
            "private": (d.get("access") or "private") == "private",
            "features": shapes.get(slug),
            # provenance, not read by the viewer
            "title": d.get("title"),
            "package_item_id": d.get("package_item_id"),
            "item_page": d.get("item_page"),
            "owner": d.get("owner"),
        }

    if "--check" in sys.argv:
        from arcgis.gis import GIS  # noqa: E402
        gis = GIS("pro")
        for slug, e in manifest.items():
            try:
                it = gis.content.get(e["item_id"])
                e["private"] = getattr(it, "access", "private") == "private"
                e["access"] = getattr(it, "access", None)
                print("%-24s access=%s" % (slug, e["access"]))
            except Exception as ex:
                print("%-24s could not re-read: %s" % (slug, str(ex)[:80]))

    os.makedirs(os.path.dirname(OUTP), exist_ok=True)
    with open(OUTP, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("manifest ->", OUTP)
    for slug, e in manifest.items():
        print("  %-24s %s  %s features  private=%s"
              % (slug, e["item_id"], e["features"], e["private"]))


if __name__ == "__main__":
    main()

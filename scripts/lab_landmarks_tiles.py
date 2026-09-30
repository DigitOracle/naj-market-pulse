"""LAB (landmarks, research only): draw the Facade Wizard LOD 0 tile for each landmark family - procedurally.

The Facade Wizard starts from a facade photograph and its LOD 0 simply projects that photo. We hold no licensed
photograph of these buildings, so the "photo" here is drawn from the same module numbers the split rules use
(panel widths, spandrel heights, fin / column / screen positions), in the v2 in-family palette. Nothing is traced
or sampled from an image. One tile = the repeating unit the gen_ rule's setupProjection maps:
  spiral_setback  2 panels x 1 floor   (2.74 x 3.80 m)
  twist           2 bays   x 2 floors  (12.4 x 8.18 m, so the staggered screens repeat)
  void_cube       2 panels x 1 floor   (3.0 x 4.43 m), dotted frit

  python scripts/lab_landmarks_tiles.py   -> <CE workspace>/najma/assets/lab/landmarks/lm_<family>_tile.png
"""
import os
import sys

from PIL import Image, ImageDraw

ASSETS = r"C:\Users\kwils\OneDrive\Documents\CityEngine\Default Workspace\najma\assets\lab\landmarks"
PX = 100  # pixels per metre

GLASS, CLEAR, METAL, SLAB, CROWN, STONE, WINDOW = "#485665", "#555C64", "#4F5257", "#303943", "#363E47", "#515656", "#313C49"
LIGHT = "#8C97A3"   # a highlight line so the fins read at a distance (tile only)


def m(v):
    return int(round(v * PX))


def spiral_setback():
    W, H, pw, sp, fw = 2.74, 3.80, 1.37, 1.05, 0.14
    im = Image.new("RGB", (m(W), m(H)), GLASS); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, m(W), m(sp)], fill=METAL)                       # spandrel at the bottom of the floor (y down)
    d.rectangle([0, 0, m(W), m(sp)], fill=METAL)
    for k in range(2):
        x0 = m(k * pw)
        d.rectangle([x0, 0, x0 + m(fw), m(H)], fill=CROWN)             # tubular fin
        d.line([x0 + m(fw) // 2, 0, x0 + m(fw) // 2, m(H)], fill=LIGHT, width=2)
    return im.transpose(Image.FLIP_TOP_BOTTOM)                          # image row 0 = top of the floor


def twist():
    W, H, bay, cw, sill = 12.4, 8.18, 6.2, 0.9, 1.0
    fh = H / 2
    im = Image.new("RGB", (m(W), m(H)), GLASS); d = ImageDraw.Draw(im)
    for f in range(2):
        y0 = m(f * fh)
        d.rectangle([0, y0, m(W), y0 + m(sill)], fill=METAL)            # deep sill
        for b in range(2):
            x0 = m(b * bay)
            d.rectangle([x0, y0, x0 + m(cw), y0 + m(fh)], fill=METAL)  # perimeter column
            if (b + f) % 2 == 0:                                        # staggered screen, middle 60 % of the glazing
                gy0 = y0 + m(sill + 0.2 * (fh - sill)); gy1 = y0 + m(sill + 0.8 * (fh - sill))
                d.rectangle([x0 + m(cw), gy0, x0 + m(bay), gy1], fill=STONE)
                for yy in range(gy0 + 6, gy1, 12):                      # perforation rows
                    for xx in range(x0 + m(cw) + 6, x0 + m(bay), 12):
                        d.point((xx, yy), fill=SLAB)
    return im.transpose(Image.FLIP_TOP_BOTTOM)


def void_cube():
    W, H, pw, tr, mw = 3.0, 4.43, 1.5, 0.35, 0.08
    im = Image.new("RGB", (m(W), m(H)), CLEAR); d = ImageDraw.Draw(im)
    for yy in range(m(tr) + 8, m(H), 9):                                # dotted frit
        off = 4 if (yy // 9) % 2 else 0
        for xx in range(off, m(W), 9):
            d.ellipse([xx, yy, xx + 3, yy + 3], fill="#9AA3AD")
    d.rectangle([0, 0, m(W), m(tr)], fill=SLAB)                         # transom
    for k in range(2):
        d.rectangle([m(k * pw), 0, m(k * pw) + m(mw), m(H)], fill=SLAB)   # mullion
    return im.transpose(Image.FLIP_TOP_BOTTOM)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    for name, fn in (("spiral_setback", spiral_setback), ("twist", twist), ("void_cube", void_cube)):
        p = os.path.join(ASSETS, "lm_%s_tile.png" % name)
        fn().save(p)
        print("wrote %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())

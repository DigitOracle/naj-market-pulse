"""Ten 9:16 background stills for HeyGen scenes.

Pulled from the Emaar Valley lifestyle clip, chosen frame by frame for one reason: they
are the only beats with NO burned-in marketing copy. Roughly half that clip carries lines
like "A masterplan designed for..." or a THE VALLEY title card, which would read straight
through from behind the presenter.

Treatment: cover-fit to 1080x1920, then a moderate gaussian blur and a slight dim. The
source is only 1024x576, so filling a 9:16 frame is a 3.3x upscale - the blur is not a
style choice, it is what makes that upscale invisible. It also keeps the presenter the
sharpest thing in frame, which is the point of a background.

Run:  python -X utf8 scripts/valley_backgrounds.py
Out:  Downloads/VALLEY_BG_01..10_*.png
"""
import pathlib, subprocess

DL = pathlib.Path(r"C:\Users\kwils\Downloads")
LAND = DL / "VALLEY_USE_2_lifestyle_WINDOWED_ONLY_45s.mp4"
VERT = DL / "VALLEY_USE_1_vertical_fullbleed_13s.mp4"
W, H = 1080, 1920

# (index, source, seconds, slug) - every one visually confirmed free of burned-in copy
PICKS = [
    (1,  LAND,  1.0, "aerial_community"),
    (2,  LAND,  7.0, "park_benches"),
    (3,  LAND, 11.0, "sports_courts"),
    (4,  LAND, 15.0, "golden_hour_walk"),
    (5,  LAND, 17.2, "golden_beach_pool"),
    (6,  LAND, 19.0, "skate_park"),
    (7,  LAND, 21.0, "yoga_pergola"),
    (8,  LAND, 23.0, "aerial_playing_fields"),
    (9,  LAND, 27.0, "child_on_shoulders"),
    (10, VERT,  0.8, "lavender_lawn"),
]

BLUR = 7          # enough to hide a 3.3x upscale, not so much the place is unreadable
DIM = -0.10       # she has to be the brightest thing in frame


def main():
    for i, src, at, slug in PICKS:
        out = DL / f"VALLEY_BG_{i:02d}_{slug}.png"
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"gblur=sigma={BLUR},eq=brightness={DIM}:saturation=0.96")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(src),
                        "-frames:v", "1", "-vf", vf, str(out)], check=True)
        print(f"  {out.name}")
    print(f"{len(PICKS)} backgrounds written to Downloads")


if __name__ == "__main__":
    main()

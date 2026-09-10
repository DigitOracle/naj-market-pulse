"""Build a vertical Reel from the stills we already make, and put it on the Worker.

Three shots, 1080x1920, ~16 s, no new service:
  1. the plate photograph alone, slow push in
  2. crossfade to the finished card - her words, her colours, her in it - slow drift out
  3. hold, with a soft light sweep across

Usage:
  python scripts/make_reel.py --post 6 --opt C            # from the backdrop pack
  python scripts/make_reel.py --plate <url> --card <url>  # from two URLs
Add --send to deliver it to her chat; without it the video is only uploaded and the link printed.
"""
import argparse, io, json, os, subprocess, sys, tempfile, urllib.parse, urllib.request

W = "https://azimuth-2.digitalchemy.workers.dev"
H = {"User-Agent": "najma-market-pulse/1.0"}


def env_token(name):
    for line in open(r"C:\Dev\azimuth-listener-naj\.env", encoding="utf-8"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=180).read()


def build(plate_png, card_png, out_mp4, secs_a=4.5, secs_b=8.0):
    """Shot 1 pushes in on the plate; shot 2 is the card drifting back out.

    zoompan on a still needs d=1 - one output frame per input frame, the zoom accumulating.
    With d=<frames> every input frame becomes a whole clip and the file explodes."""
    cover = "scale=792:1408:force_original_aspect_ratio=increase,crop=792:1408,setsar=1"   # 720x1280 out: this machine uploads at ~16 KB/s, so keep the file small
    vf = (
        f"[0:v]{cover},zoompan=z='min(zoom+0.00065,1.11)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s=720x1280:fps=30,format=yuv420p[a];"
        f"[1:v]{cover},zoompan=z='if(eq(on,0),1.10,max(zoom-0.00045,1.0))':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s=720x1280:fps=30,format=yuv420p[b];"
        f"[a][b]xfade=transition=fade:duration=0.9:offset={secs_a - 0.9:.2f}[v]"
    )
    cmd = ["ffmpeg", "-y", "-loop", "1", "-t", str(secs_a), "-i", plate_png,
           "-loop", "1", "-t", str(secs_b), "-i", card_png,
           "-filter_complex", vf, "-map", "[v]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "26", "-pix_fmt", "yuv420p",
           "-r", "30", "-movflags", "+faststart", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit("ffmpeg failed:\n" + (r.stderr or "")[-1500:])
    dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",out_mp4],
                         capture_output=True, text=True).stdout.strip()
    want = secs_a + secs_b - 0.9
    if not dur or abs(float(dur) - want) > 1.5:
        sys.exit("duration is %s s, expected about %.1f - not uploading" % (dur, want))
    print("built", round(float(dur),1), "s,", round(os.path.getsize(out_mp4)/1e6,2), "MB")
    return out_mp4


def upload(path, name, tok):
    data = open(path, "rb").read()
    req = urllib.request.Request(W + "/video_upload?key=" + urllib.parse.quote(name), data=data, method="PUT",
                                 headers={**H, "X-Azimuth-Ingest": tok, "Content-Type": "video/mp4"})
    return urllib.request.urlopen(req, timeout=900).read().decode(), len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post"); ap.add_argument("--opt", default="A")
    ap.add_argument("--plate"); ap.add_argument("--card")
    ap.add_argument("--name", default=None)
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    key, tok = env_token("READ_KEY"), env_token("INGEST_TOKEN")

    plate_url, card_url, caption = a.plate, a.card, ""
    if a.post:
        j = json.loads(get(W + "/plate_run?post=" + urllib.parse.quote(a.post) + "&opt=" + urllib.parse.quote(a.opt)
                           + "&send=0&key=" + urllib.parse.quote(key)).decode())
        if j.get("err"): sys.exit("plate_run: " + j["err"])
        plate_url, card_url = j["photo"], j["story"]
        try:
            pk = json.loads(get(W + "/img/ips_bg_prompts?key=" + urllib.parse.quote(key)).decode())
            p = [x for x in pk["posts"] if str(x["n"]) == str(a.post)][0]
            caption = p.get("caption", "")
        except Exception:
            pass
    if not (plate_url and card_url):
        sys.exit("need --post or both --plate and --card")

    tmp = tempfile.mkdtemp()
    pp, cp = os.path.join(tmp, "plate.png"), os.path.join(tmp, "card.png")
    open(pp, "wb").write(get(plate_url)); open(cp, "wb").write(get(card_url))
    out = os.path.join(tmp, "reel.mp4")
    build(pp, cp, out)
    name = a.name or ("reel_" + (a.post or "x") + "_" + a.opt).lower()
    res, nbytes = upload(out, name, tok)
    link = W + "/video/" + name
    print("uploaded", name, round(nbytes / 1e6, 2), "MB ->", res.strip(), "|", link)

    if a.send:
        txt = ("Your Reel is ready.\n\n" + (caption or "")).strip()[:1500]
        get(W + "/note?key=" + urllib.parse.quote(key) + "&text=" + urllib.parse.quote(txt + "\n\n" + link))
        print("link sent to her")


if __name__ == "__main__":
    main()

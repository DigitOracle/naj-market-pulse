"""Cut out and grade every photo of herself she has sent, so "with you" pictures can use them.

Runs on the DigitAlchemy machine on a schedule (Najma_Style_Photos, every 30 min). For each
img_style_me_NN on the Worker that has no img_style_me_NN_cut yet: remove the background (rembg,
u2net_human_seg, alpha matting), erode 1 px and feather the edge, make four light grades
(warm / blue / day / soft) with a warm key from the right, darken toward the feet, and push
style_me_NN_cut and style_me_NN_cut_<grade>. Then refresh style_me_cut* from the newest photo, which
is the default look the Worker places. Idempotent: nothing to do -> exits quietly.

Usage: python scripts/cutout_style_photos.py [--force]
"""
import base64, io, json, sys, urllib.error, urllib.parse, urllib.request

W = "https://azimuth-2.digitalchemy.workers.dev"
H = {"User-Agent": "najma-market-pulse/1.0"}


def env_token(name):
    for line in open(r"C:\Dev\azimuth-listener-naj\.env", encoding="utf-8"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()


def exists(name):
    try:
        r = urllib.request.urlopen(urllib.request.Request(W + "/img/" + name, method="HEAD", headers=H), timeout=60)
        return r.status == 200
    except urllib.error.HTTPError:
        return False


def get(name):
    return urllib.request.urlopen(urllib.request.Request(W + "/img/" + name, headers=H), timeout=120).read()


def push(name, data, tok, ct="image/png"):
    body = json.dumps({"imageName": name, "image": base64.b64encode(data).decode(), "contentType": ct}).encode()
    req = urllib.request.Request(W + "/ingest_market", data=body, method="POST",
                                 headers={**H, "X-Azimuth-Ingest": tok, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300)).get("ok")


def grades(src_png):
    from PIL import Image, ImageFilter, ImageEnhance, ImageChops
    src = Image.open(io.BytesIO(src_png)).convert("RGBA")
    rgb = src.convert("RGB")
    a = src.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))

    def tint(img, r, g, b, bright=1.0, contrast=1.0, sat=1.0):
        im = img
        if bright != 1.0: im = ImageEnhance.Brightness(im).enhance(bright)
        if contrast != 1.0: im = ImageEnhance.Contrast(im).enhance(contrast)
        if sat != 1.0: im = ImageEnhance.Color(im).enhance(sat)
        return ImageChops.multiply(im, Image.new("RGB", im.size, (int(255 * r), int(255 * g), int(255 * b))))

    def right_key(img, warm=(255, 214, 170), strength=0.18):
        w, h = img.size
        grad = Image.linear_gradient("L").rotate(90, expand=True).resize((w, h)).point(lambda v: int(v * strength))
        return Image.composite(ImageChops.screen(img, Image.new("RGB", (w, h), warm)), img, grad)

    out = {
        "warm": right_key(tint(rgb, 1.0, 0.97, 0.90, 1.02, 1.03, 1.02), strength=0.22),
        "blue": right_key(tint(rgb, 0.94, 0.96, 1.03, 0.96, 1.04, 0.97), warm=(255, 205, 160), strength=0.36),   # her feedback 10 Sep: "too dark" - keep her lit, let the scene carry the hour
        "day": right_key(tint(rgb, 0.98, 1.0, 1.02, 1.05, 1.02, 0.98), warm=(255, 240, 225), strength=0.12),
        "soft": tint(rgb, 0.99, 0.99, 1.0, 0.97, 0.90, 0.94),
    }
    res = {}
    w, h = rgb.size
    feet = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(max(0, (v - 235)) / 20 * 70))
    for k, im in out.items():
        o = im.convert("RGBA"); o.putalpha(a)
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 0)); dark.putalpha(ImageChops.multiply(feet, a))
        o = Image.alpha_composite(o, dark)
        buf = io.BytesIO(); o.save(buf, "PNG", optimize=True); res[k] = buf.getvalue()
    base = src.copy(); base.putalpha(a)
    buf = io.BytesIO(); base.save(buf, "PNG", optimize=True); res["base"] = buf.getvalue()
    return res


def cutout(jpg):
    from PIL import Image
    from rembg import remove, new_session
    im = Image.open(io.BytesIO(jpg)).convert("RGB"); im.thumbnail((1400, 1400))
    out = remove(im, session=new_session("u2net_human_seg"), alpha_matting=True,
                 alpha_matting_foreground_threshold=240, alpha_matting_background_threshold=10, alpha_matting_erode_size=8)
    out = out.crop(out.getbbox())
    buf = io.BytesIO(); out.save(buf, "PNG"); return buf.getvalue()


def main():
    force = "--force" in sys.argv
    tok = env_token("INGEST_TOKEN")
    # read the pile itself rather than guessing slot names: the Worker's counter can go stale
    # under concurrent sends, so a photo can exist in the pile without a matching style_me_NN.
    names, key = [], env_token("READ_KEY")
    try:
        st = json.load(urllib.request.urlopen(urllib.request.Request(
            W + "/style_status?key=" + urllib.parse.quote(key), headers=H), timeout=120))
        names = [r["key"] for r in st.get("refs", []) if r.get("kind") == "me" and r.get("key")]
    except Exception as e:
        print("style_status unavailable (%s); falling back to slot names" % str(e)[:60])
        for n in range(1, 41):
            nm = "style_me_%02d" % n
            if exists(nm): names.append(nm)
            else: break
    if not names and exists("style_me"):
        names = ["style_me"]
    todo = [nm for nm in names if force or not exists(nm + "_cut")]
    if not todo:
        print("nothing new"); return
    for nm in todo:
        print("cutting", nm)
        png = cutout(get(nm))
        g = grades(png)
        push(nm + "_cut", g["base"], tok)
        for k in ("warm", "blue", "day", "soft"):
            push(nm + "_cut_" + k, g[k], tok)
        print("  done", nm, {k: round(len(v) / 1024) for k, v in g.items()}, "KB")
    def usable(name):
        """A cut-out can only be placed if it is colour and full-length standing.
        Seated or half-body shots come out wide; black-and-white cannot sit in a colour scene."""
        from PIL import Image
        try:
            im = Image.open(io.BytesIO(get(name + "_cut")))
        except Exception:
            return (False, "not cut")
        w, h = im.size
        ratio = w / float(h or 1)
        sm = im.convert("RGB").resize((60, 100))
        px = list(sm.get_flattened_data()) if hasattr(sm, "get_flattened_data") else list(sm.getdata())
        sat = sum(max(r, g, b) - min(r, g, b) for r, g, b in px) / float(len(px))
        if sat < 12: return (False, "black and white")
        if ratio > 0.46: return (False, "not full-length standing (%.2f wide)" % ratio)
        return (True, "ok %.2f" % ratio)

    newest = None
    for nm in reversed(names):
        ok_, why = usable(nm)
        print("  %-16s %s" % (nm, why))
        if ok_ and newest is None: newest = nm
    if not newest:
        print("no photo is usable as the default look; leaving the current one alone"); return
    print("default look <-", newest)
    push("style_me_cut", get(newest + "_cut"), tok)
    for k in ("warm", "blue", "day", "soft"):
        push("style_me_cut_" + k, get(newest + "_cut_" + k), tok)
    print("ok")


if __name__ == "__main__":
    main()

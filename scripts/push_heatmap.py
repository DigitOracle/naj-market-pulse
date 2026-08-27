"""Render the heat maps and push them into the azimuth-2 Worker for WhatsApp delivery.
Run after build_pulse.py. Env: AZIMUTH_URL, INGEST_TOKEN."""
import os, sys, json, base64, urllib.request, subprocess

HERE = os.path.dirname(__file__)
PUB = os.path.join(HERE, "..", "public")

def push(name, path, url, token):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = json.dumps({"imageName": name, "image": b64, "contentType": "image/png"}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/ingest_market", data=body,
        headers={"X-Azimuth-Ingest": token, "Content-Type": "application/json",
                 "User-Agent": "najma-market-pulse/1.0"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        print(name, "->", r.status, r.read().decode()[:120])

def main():
    subprocess.run([sys.executable, os.path.join(HERE, "render_heatmap.py")], check=True)
    url = os.environ["AZIMUTH_URL"]; token = os.environ["INGEST_TOKEN"]
    push("heatmap_story", os.path.join(PUB, "heatmap_story.png"), url, token)
    push("heatmap_square", os.path.join(PUB, "heatmap_square.png"), url, token)

if __name__ == "__main__":
    main()

"""SHIRO & PICO — episode-01 panel generation via an explicit Murakumo ComfyUI origin.

A simple, reliable txt2img path on the public ComfyUI gateway (no Flux/PuLID/LAN nodes).
Generates the key episode-1 beats as anime panels, saves PNGs to
data/ghosthacker-shiropico/resources/panels/ (git-ignored → DataLad/B2).

Character look is anchored by the design-spec prompts (SERIES-BIBLE / character-design-spec.json):
  shiro = white-hooded platinum-hair teal-eyed calm chibi hacker
  pico  = grey-green spiky-hair lime-eyed cocky chibi hacker
"""
from __future__ import annotations
import json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path

COMFY = (os.environ.get("MURAKUMO_COMFY_URL") or os.environ.get("COMFY_URL") or "").rstrip("/")
CKPT = "animagine-xl-4.0.safetensors"
OUT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico/resources/panels"
OUT.mkdir(parents=True, exist_ok=True)

STYLE = ("masterpiece, best quality, anime, clean thick lineart, flat cel shading, "
         "vibrant teal and cyan cyber palette, chibi 2.5 head, cute, ")
NEG = ("lowres, bad anatomy, bad hands, blurry, watermark, text, signature, "
       "realistic, 3d, horror, blood, gore, extra limbs, ugly, "
       "religious symbols, occult")

SHIRO = ("1boy, small chibi white-hat hacker SHIRO, white oversized hoodie deep hood, "
         "short platinum white hair, teal glowing eyes, calm sleepy expression")
PICO = ("1boy, small chibi mischievous hacker PICO, grey-green spiky hair, lime eyes, "
        "green hoodie with stickers, cocky grin")

PANELS = [
    ("p01-coldopen", f"{SHIRO}, and {PICO}, two boys peeking over a rooftop edge at night, "
                     "futuristic Dubai skyscrapers glowing teal below, self-driving cars with "
                     "closed sleepy eyes and Zzz on the streets, dramatic night cyber city, wide shot"),
    ("p02-pico-iki", f"{PICO} rolling up sleeves, cocky confident grin, casting a radial light pulse "
                     "from his hand, teal energy ring, dynamic action pose, night city street"),
    ("p03-shiro-fix", f"{SHIRO} calmly touching a sleepy self-driving car forehead with one finger, "
                      "the car waking up with a soft glow, protecting a parent and child nearby, "
                      "quiet wind, hair billowing, serene"),
    ("p04-henshin", f"{SHIRO} and {PICO} high-five, wrapped in a teal cocoon of light particles "
                    "spiraling up, scaling up from chibi to 5-head heroic proportions, transformation, "
                    "epic shonen henshin bank"),
    ("p05-ghost", "a faceless translucent cyan data-particle ghost sprite dissolving into noise on a "
                  "distant skyscraper at night, white heat afterimage, mysterious, "
                  + STYLE.split(',')[0]),
]

def _http(method, path, body=None, headers=None):
    if not COMFY:
        raise RuntimeError("MURAKUMO_COMFY_URL is required; the retired gftd.ai origin has no fallback")
    req = urllib.request.Request(f"{COMFY}{path}", data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, r.read()

def workflow(prompt, seed, w=832, h=1216):
    pos = STYLE + prompt
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 30, "cfg": 5.5, "sampler_name": "euler_ancestral",
            "scheduler": "normal", "denoise": 1.0,
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "shiropico", "images": ["6", 0]}},
    }

def submit(wf):
    s, b = _http("POST", "/prompt", json.dumps({"prompt": wf}).encode(), {"content-type": "application/json"})
    j = json.loads(b)
    if j.get("node_errors"):
        print("node_errors:", json.dumps(j["node_errors"])[:1500]); return None
    return j["prompt_id"]

def wait(pid, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s, b = _http("GET", f"/history/{pid}")
        e = (json.loads(b) or {}).get(pid)
        if e and e.get("outputs"):
            return e
        time.sleep(3)
    return {}

def fetch(filename, subfolder, typ):
    q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": typ})
    s, b = _http("GET", f"/view?{q}")
    return b

def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for i, (name, prompt) in enumerate(PANELS):
        if only and only not in name:
            continue
        seed = 70000 + i * 13
        print(f"[{name}] submitting (seed={seed})...")
        pid = submit(workflow(prompt, seed))
        if not pid:
            print(f"[{name}] submit failed"); continue
        e = wait(pid)
        imgs = []
        for node in (e.get("outputs") or {}).values():
            imgs += node.get("images", [])
        if not imgs:
            print(f"[{name}] no image (status={e.get('status')})"); continue
        im = imgs[0]
        data = fetch(im["filename"], im.get("subfolder", ""), im.get("type", "output"))
        dst = OUT / f"sp-ep01-{name}.png"
        dst.write_bytes(data)
        print(f"[{name}] -> {dst}  ({len(data)//1024} KB)")

if __name__ == "__main__":
    main()

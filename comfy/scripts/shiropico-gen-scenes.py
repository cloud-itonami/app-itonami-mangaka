"""Generate the distinct SCENE cut images for an episode shotlist (v2).

Reads episode-01-shotlist-v2.json, generates one image per distinct scene_key via
comfyui (animagine-xl + co-scientist neon-noir style), with per-scene retries
(robust against Modal flaps). Saves to resources/ep-scenes/<scene_key>.png.
"""
from __future__ import annotations
import json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path

COMFY = (os.environ.get("MURAKUMO_COMFY_URL") or os.environ.get("COMFY_URL") or "").rstrip("/")
CKPT = "animagine-xl-4.0.safetensors"
ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
EP = sys.argv[1] if len(sys.argv) > 1 else "01"
SHOTLIST = ROOT / f"episode-{EP}-shotlist-v2.json"
OUT = ROOT / "resources/ep-scenes"; OUT.mkdir(parents=True, exist_ok=True)
STYLE = ("masterpiece, best quality, anime cinematic key visual, very aesthetic, cyberpunk anime, "
         "neon noir lighting, high-contrast cel art, teal and cyan palette, dramatic, absurdres")
NEG = ("realistic, photorealistic, lowres, bad anatomy, text, watermark, signature, ugly, blurry, "
       "extra limbs, on-screen text, subtitles")
CFG, STEPS, SAMPLER = 7.0, 28, "dpmpp_2m"

def http(m, p, b=None, h=None):
    if not COMFY:
        raise RuntimeError("MURAKUMO_COMFY_URL is required; the retired gftd.ai origin has no fallback")
    r = urllib.request.Request(f"{COMFY}{p}", data=b, method=m, headers=h or {})
    with urllib.request.urlopen(r, timeout=200) as x: return x.status, x.read()
def wf(prompt, seed, w=832, h=1216):
    return {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
            "2": {"class_type": "CLIPSetLastLayer", "inputs": {"clip": ["1", 1], "stop_at_clip_layer": -2}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": STYLE + ", " + prompt, "clip": ["2", 0]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
            "6": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": STEPS, "cfg": CFG,
                  "sampler_name": SAMPLER, "scheduler": "karras", "denoise": 1.0,
                  "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0]}},
            "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
            "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "epscene", "images": ["7", 0]}}}

def gen_one(key, prompt, seed):
    for attempt in range(5):
        try:
            j = json.loads(http("POST", "/prompt", json.dumps({"prompt": wf(prompt, seed + attempt * 97)}).encode(),
                                {"content-type": "application/json"})[1])
        except Exception as exc:
            print(f"  {key} a{attempt}: submit exc {str(exc)[:60]}"); time.sleep(12); continue
        if j.get("node_errors"):
            print(f"  {key}: node_errors"); return False
        pid = j["prompt_id"]; e = None
        for _ in range(130):
            try: e = (json.loads(http("GET", f"/history/{pid}")[1]) or {}).get(pid)
            except Exception: e = None
            if e and e.get("outputs"): break
            if e and e.get("status", {}).get("status_str") == "error": e = None; break
            time.sleep(3)
        imgs = [im for n in (e.get("outputs") or {}).values() for im in n.get("images", [])] if e else []
        if imgs:
            im = imgs[0]; q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": "output"})
            (OUT / f"{key}.png").write_bytes(http("GET", f"/view?{q}")[1])
            print(f"  {key}: ok a{attempt}", flush=True); return True
        print(f"  {key} a{attempt}: NO IMAGE, retry", flush=True); time.sleep(12)
    print(f"  {key}: FAILED", flush=True); return False

def main():
    beats = json.loads(SHOTLIST.read_text())
    scenes = {}
    for b in beats:
        if b.get("type") == "scene":
            scenes.setdefault(b["scene_key"], b["scene_prompt"])
    print(f"generating {len(scenes)} distinct scenes")
    for i, (key, prompt) in enumerate(scenes.items()):
        if (OUT / f"{key}.png").exists():
            print(f"  {key}: cached"); continue
        gen_one(key, prompt, 4000 + i * 53)
    print("SCENES DONE")

if __name__ == "__main__":
    main()

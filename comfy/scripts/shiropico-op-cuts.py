"""Generate cinematic OP action cuts for SHIRO & PICO (Jujutsu/Kimetsu-style OP).

animagine-xl-4.0 via an explicit Murakumo ComfyUI origin, conditioned on the co-scientist shiro-pico
recipe style (neon-noir high-contrast cel art) + the canonical character design
baked into each prompt + battle-form (henshin 5-6 head) dynamic action direction.
"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.parse
from pathlib import Path

COMFY = (os.environ.get("MURAKUMO_COMFY_URL") or os.environ.get("COMFY_URL") or "").rstrip("/")
CKPT = "animagine-xl-4.0.safetensors"
OUT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico/resources/op-cuts"
OUT.mkdir(parents=True, exist_ok=True)
# co-scientist shiro-pico recipe (recipe-78c5ed52, score 92)
STYLE = ("very aesthetic, cyberpunk anime, dynamic action, neon noir lighting, high-contrast cel art, "
         "cinematic anime key visual, ufotable style, dramatic rim light, volumetric light, "
         "masterpiece, best quality, absurdres, detailed")
NEG = ("realistic, photorealistic, soft focus, motion blur on faces, over-saturation, flat aesthetic, "
       "muted palette, static posing, lowres, bad anatomy, bad hands, extra digits, text, watermark, ugly")
CFG, STEPS, SAMPLER = 7.0, 29, "dpmpp_3m_sde_gpu"

SHIRO = "1boy, white beret cap, short silver white hair, big bright glowing teal cyan eyes, white and teal hoodie, cute"
PICO = "1boy, messy grey green wavy hair, green hoodie, brown eyes, energetic"

# (name, prompt, w, h)
CUTS = [
    ("01-city", "epic wide establishing shot, futuristic neon cyber city at night, teal and cyan glow, "
                "dramatic storm clouds, towering skyscrapers, no humans, cinematic", 832, 1216),
    ("02-shiro-eye", f"extreme close-up of one eye, {SHIRO}, glowing teal iris reflecting streaming data code, "
                     "intense calm gaze, dramatic shadow, cinematic", 1024, 1024),
    ("03-shiro-action", f"{SHIRO}, dynamic full body battle pose, mid-air leap, wielding a glowing teal energy axe, "
                        "flowing motion, speed lines, neon noir city background, dramatic low angle, epic action", 832, 1216),
    ("04-pico-face", f"close-up, {PICO}, determined confident grin, lime green energy glow on face, "
                     "fast motion, dramatic lighting, cinematic", 1024, 1024),
    ("05-pico-action", f"{PICO}, dynamic action, dashing forward fingers on a glowing holographic keyboard, "
                       "lime green light trails, dutch angle, speed lines, neon city, energetic", 832, 1216),
    ("06-ghost", "ominous faceless translucent cyan data-particle ghost entity, looming giant over a neon city, "
                 "glitch fragments, swirling code, dramatic, stylish horror, cinematic", 832, 1216),
    ("07-duo", f"two boys back to back in heroic battle stance, ({SHIRO}) and ({PICO}), "
               "teal and lime energy auras clashing, explosion of light particles, epic finale, dramatic", 832, 1216),
]

def http(m, p, b=None, h=None):
    if not COMFY:
        raise RuntimeError("MURAKUMO_COMFY_URL is required; the retired gftd.ai origin has no fallback")
    r = urllib.request.Request(f"{COMFY}{p}", data=b, method=m, headers=h or {})
    with urllib.request.urlopen(r, timeout=200) as x: return x.read()
def wf(prompt, seed, w, h):
    return {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
            "2": {"class_type": "CLIPSetLastLayer", "inputs": {"clip": ["1", 1], "stop_at_clip_layer": -2}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": STYLE + ", " + prompt, "clip": ["2", 0]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
            "6": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": STEPS, "cfg": CFG,
                  "sampler_name": SAMPLER, "scheduler": "karras", "denoise": 1.0,
                  "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0]}},
            "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
            "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "spop", "images": ["7", 0]}}}

def main():
    import sys
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for i, (name, prompt, w, h) in enumerate(CUTS):
        if only and only not in name:
            continue
        j = json.loads(http("POST", "/prompt", json.dumps({"prompt": wf(prompt, 8000 + i * 11, w, h)}).encode(),
                            {"content-type": "application/json"}))
        if j.get("node_errors"):
            print(f"  {name}: node_errors {json.dumps(j['node_errors'])[:200]}"); continue
        pid = j["prompt_id"]
        e = None
        for _ in range(140):
            e = (json.loads(http("GET", f"/history/{pid}")) or {}).get(pid)
            if e and e.get("outputs"): break
            time.sleep(3)
        imgs = [im for n in (e.get("outputs") or {}).values() for im in n.get("images", [])] if e else []
        if not imgs:
            print(f"  {name}: NO IMAGE"); continue
        im = imgs[0]
        q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": "output"})
        (OUT / f"{name}.png").write_bytes(http("GET", f"/view?{q}"))
        print(f"  {name}: ok ({w}x{h})")

if __name__ == "__main__":
    main()

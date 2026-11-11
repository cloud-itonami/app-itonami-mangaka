"""On-model OP cuts v2 — IPAdapter-stabilised SHIRO & PICO (correct genders).

Character cuts reference the canonical emotions/{shiro,pico} 立ち絵 via IPAdapter
(PLUS) so they stay on-model; scene cuts (city/ghost) are text-only. Genders:
シロ=1girl (white beret, teal), ピコ=1boy (grey-green hair, green hoodie, ditzy
genius energy). Writes to resources/op-cuts/ (replacing the drifted v1 cuts).
"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.parse, sys
from pathlib import Path

COMFY = (os.environ.get("MURAKUMO_COMFY_URL") or os.environ.get("COMFY_URL") or "").rstrip("/")
CKPT = "animagine-xl-4.0.safetensors"
ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
EMO = ROOT / "character-refs/emotions"
OUT = ROOT / "resources/op-cuts"; OUT.mkdir(parents=True, exist_ok=True)
STYLE = ("very aesthetic, cyberpunk anime, dynamic action, neon noir lighting, high-contrast cel art, "
         "cinematic anime key visual, dramatic rim light, masterpiece, best quality, absurdres")
NEG = ("realistic, photorealistic, soft focus, lowres, bad anatomy, bad hands, extra digits, text, watermark, "
       "ugly, off-model, wrong hair color")
CFG, STEPS, SAMPLER = 7.0, 29, "dpmpp_3m_sde_gpu"
SHIRO = "1girl, white beret cap, short silver white hair, big glowing teal cyan eyes, white and teal hoodie, cute, calm"
PICO = "1boy, messy grey green wavy hair, green hoodie, brown eyes, cheerful goofy genius kid, energetic"

# (name, prompt, ref_char|None, weight, w, h)
CUTS = [
    ("01-city", "epic wide establishing shot, futuristic neon cyber city at night, teal cyan glow, "
                "storm clouds, towering skyscrapers, no humans, cinematic", None, 0, 832, 1216),
    ("02-shiro-eye", f"extreme close-up, {SHIRO}, glowing teal iris reflecting streaming data code, "
                     "intense calm gaze, dramatic shadow", "shiro", 0.85, 1024, 1024),
    ("03-shiro-action", f"{SHIRO}, dynamic full body battle pose, mid-air leap, wielding a glowing teal energy axe, "
                        "flowing motion, speed lines, neon noir city, dramatic low angle, epic", "shiro", 0.85, 832, 1216),
    ("04-pico-face", f"close-up, {PICO}, big goofy confident grin, sparkle in the eye, lime green energy glow, "
                     "fast motion, dramatic lighting", "pico", 0.85, 1024, 1024),
    ("05-pico-action", f"{PICO}, dynamic action, dashing forward fingers on a glowing holographic keyboard, "
                       "lime green light trails, dutch angle, speed lines, energetic, a little clumsy", "pico", 0.85, 832, 1216),
    ("06-ghost", "ominous faceless translucent cyan data-particle ghost entity, giant looming over a neon city, "
                 "glitch fragments, swirling code, dramatic, stylish, no humans", None, 0, 832, 1216),
    ("07-duo", f"two heroes standing together, a girl ({SHIRO}) and a boy ({PICO}), heroic battle stance, "
               "teal and lime energy auras, explosion of light particles, epic finale", "shiro", 0.5, 832, 1216),
]

def http(m, p, b=None, h=None):
    if not COMFY:
        raise RuntimeError("MURAKUMO_COMFY_URL is required; the retired gftd.ai origin has no fallback")
    r = urllib.request.Request(f"{COMFY}{p}", data=b, method=m, headers=h or {})
    with urllib.request.urlopen(r, timeout=200) as x: return x.status, x.read()
def upload(png: Path) -> str:
    bd = "----spv2"
    body = (f'--{bd}\r\nContent-Disposition: form-data; name="image"; filename="{png.name}"\r\n'
            f'Content-Type: image/png\r\n\r\n').encode() + png.read_bytes() + \
           (f'\r\n--{bd}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--{bd}--\r\n').encode()
    return json.loads(http("POST", "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={bd}"})[1])["name"]

def wf(prompt, seed, w, h, ref=None, weight=0.85):
    g = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
         "2": {"class_type": "CLIPSetLastLayer", "inputs": {"clip": ["1", 1], "stop_at_clip_layer": -2}},
         "3": {"class_type": "CLIPTextEncode", "inputs": {"text": STYLE + ", " + prompt, "clip": ["2", 0]}},
         "4": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}},
         "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
         "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
         "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "spv2", "images": ["7", 0]}}}
    model = ["1", 0]
    if ref:
        g["10"] = {"class_type": "LoadImage", "inputs": {"image": ref}}
        g["11"] = {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": ["1", 0], "preset": "PLUS (high strength)"}}
        g["12"] = {"class_type": "IPAdapterAdvanced", "inputs": {"model": ["11", 0], "ipadapter": ["11", 1], "image": ["10", 0],
                   "weight": weight, "weight_type": "style and composition", "combine_embeds": "concat",
                   "start_at": 0.0, "end_at": 1.0, "embeds_scaling": "V only"}}
        model = ["12", 0]
    g["6"] = {"class_type": "KSampler", "inputs": {"seed": seed, "steps": STEPS, "cfg": CFG,
              "sampler_name": SAMPLER, "scheduler": "karras", "denoise": 1.0,
              "model": model, "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0]}}
    return g

def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    refs = {c: upload(EMO / c / "normal.png") for c in ("shiro", "pico")}
    for i, (name, prompt, refc, weight, w, h) in enumerate(CUTS):
        if only and only not in name:
            continue
        ref = refs.get(refc) if refc else None
        ok = False
        for attempt in range(4):  # robust against Modal cold/flaky gaps
            try:
                j = json.loads(http("POST", "/prompt", json.dumps({"prompt": wf(prompt, 9300 + i * 13 + attempt * 101, w, h, ref, weight)}).encode(),
                                    {"content-type": "application/json"})[1])
            except Exception as exc:
                print(f"  {name} a{attempt}: submit exc {exc}"); time.sleep(15); continue
            if j.get("node_errors"):
                print(f"  {name}: node_errors {json.dumps(j['node_errors'])[:200]}"); break
            pid = j["prompt_id"]; e = None
            for _ in range(130):
                try:
                    e = (json.loads(http("GET", f"/history/{pid}")[1]) or {}).get(pid)
                except Exception:
                    e = None
                if e and e.get("outputs"): break
                if e and e.get("status", {}).get("status_str") == "error":
                    e = None; break
                time.sleep(3)
            imgs = [im for n in (e.get("outputs") or {}).values() for im in n.get("images", [])] if e else []
            if imgs:
                im = imgs[0]; q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": "output"})
                (OUT / f"{name}.png").write_bytes(http("GET", f"/view?{q}")[1])
                print(f"  {name}: ok ({'IPA '+refc if ref else 'text'}) a{attempt}", flush=True); ok = True; break
            print(f"  {name} a{attempt}: NO IMAGE, retrying", flush=True); time.sleep(15)
        if not ok:
            print(f"  {name}: FAILED after retries", flush=True)

if __name__ == "__main__":
    main()

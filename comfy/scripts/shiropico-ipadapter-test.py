"""Stabilise SHIRO & PICO character consistency with IPAdapter (reference the real 立ち絵).

The OP cuts drifted because they were text-only. This conditions generation on the
canonical emotions/{shiro,pico} 立ち絵 via IPAdapter (PLUS, sdxl vit-h) so the
generated battle-form stays on-model. Also fixes gender (シロ=1girl). Generates a
test cut, then vision-scores how well it matches the reference.
"""
from __future__ import annotations
import base64, io, json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path
import httpx
from PIL import Image

COMFY = os.getenv("MURAKUMO_COMFY_URL", "").rstrip("/")
CKPT = "animagine-xl-4.0.safetensors"
ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
EMO = ROOT / "character-refs/emotions"
OUT = ROOT / "resources/op-cuts-v2"; OUT.mkdir(parents=True, exist_ok=True)
STYLE = ("very aesthetic, cyberpunk anime, dynamic action, neon noir lighting, high-contrast cel art, "
         "cinematic anime key visual, dramatic rim light, masterpiece, best quality, absurdres")
NEG = ("realistic, photorealistic, soft focus, lowres, bad anatomy, bad hands, extra digits, text, watermark, "
       "ugly, wrong hair color, off-model")
# character canon (gender corrected): both read as cute girls in the 立ち絵
CHARS = {
    "shiro": ("1girl, white beret cap, short silver white hair, big teal cyan eyes, white and teal hoodie, cute",
              "emotions/shiro/normal.png"),
    "pico":  ("1girl, messy grey green wavy hair, green hoodie, brown eyes, energetic",
              "emotions/pico/normal.png"),
}

def http(m, p, b=None, h=None):
    if not COMFY:
        raise RuntimeError("MURAKUMO_COMFY_URL is required; no retired-domain fallback is configured")
    r = urllib.request.Request(f"{COMFY}{p}", data=b, method=m, headers=h or {})
    with urllib.request.urlopen(r, timeout=200) as x: return x.status, x.read()

def upload(png_path: Path) -> str:
    """Upload a reference image to ComfyUI /upload/image (multipart) → server filename."""
    boundary = "----spref"; name = png_path.name
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + png_path.read_bytes() + \
           (f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n").encode()
    s, b = http("POST", "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(b).get("name", name)

def wf(prompt, ref_name, seed, weight=0.7, w=832, h=1216):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPSetLastLayer", "inputs": {"clip": ["1", 1], "stop_at_clip_layer": -2}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": STYLE + ", " + prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": ref_name}},
        "11": {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": ["1", 0], "preset": "PLUS (high strength)"}},
        "12": {"class_type": "IPAdapterAdvanced", "inputs": {
            "model": ["11", 0], "ipadapter": ["11", 1], "image": ["10", 0],
            "weight": weight, "weight_type": "style and composition", "combine_embeds": "concat",
            "start_at": 0.0, "end_at": 1.0, "embeds_scaling": "V only"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 29, "cfg": 7.0,
              "sampler_name": "dpmpp_3m_sde_gpu", "scheduler": "karras", "denoise": 1.0,
              "model": ["12", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "spipa", "images": ["7", 0]}},
    }

def gen(char, action, seed, weight):
    prompt, ref = CHARS[char]
    ref_name = upload(EMO.parent / "emotions" / Path(ref).relative_to("emotions"))
    j = json.loads(http("POST", "/prompt", json.dumps({"prompt": wf(prompt + ", " + action, ref_name, seed, weight)}).encode(),
                        {"content-type": "application/json"})[1])
    if j.get("node_errors"):
        print("node_errors:", json.dumps(j["node_errors"])[:400]); return None
    pid = j["prompt_id"]; e = None
    for _ in range(120):
        e = (json.loads(http("GET", f"/history/{pid}")[1]) or {}).get(pid)
        if e and e.get("outputs"): break
        if e and e.get("status", {}).get("status_str") == "error":
            print("exec error:", json.dumps(e["status"].get("messages", []))[:300]); return None
        time.sleep(3)
    imgs = [im for n in (e.get("outputs") or {}).values() for im in n.get("images", [])] if e else []
    if not imgs: return None
    im = imgs[0]; q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": "output"})
    return http("GET", f"/view?{q}")[1]

def vscore_match(ref_path, gen_bytes):
    ref = base64.b64encode(ref_path.read_bytes()).decode()
    gen = base64.b64encode(gen_bytes).decode()
    txt = ('Image 1 is the CANONICAL character reference. Image 2 is a newly generated action shot '
           'meant to be the SAME character. Reply JSON only: {"same_character":<0-100 how well image 2 '
           'matches image 1 design: hair color, outfit, accessories, eye color>,"note":"<what differs>"}.')
    p = {"model": os.getenv("MURAKUMO_VISION_MODEL", "murakumo-main"), "max_tokens": 200, "temperature": 0.2,
         "messages": [{"role": "user", "content": [{"type": "text", "text": txt},
             {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ref}"}},
             {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{gen}"}}]}]}
    base = os.getenv("MURAKUMO_LLM_URL", "https://api.murakumo.cloud/v1").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if key := (os.getenv("MURAKUMO_API_KEY") or os.getenv("GFTD_LLM_API_KEY")):
        headers["Authorization"] = f"Bearer {key}"
    r = httpx.post(f"{base}/chat/completions", json=p, headers=headers, timeout=90)
    t = r.json()["choices"][0]["message"]["content"]; return t[t.find("{"):t.rfind("}")+1]

def main():
    char = sys.argv[1] if len(sys.argv) > 1 else "shiro"
    action = "dynamic full body battle pose, mid-air leap, glowing energy weapon, speed lines, neon noir, epic action"
    for weight in [0.7, 0.9]:
        b = gen(char, action, 9100 + int(weight*10), weight)
        if not b:
            print(f"weight={weight}: gen failed"); continue
        out = OUT / f"{char}-ipa-w{weight}.png"; out.write_bytes(b)
        score = vscore_match(EMO / char / "normal.png", b)
        print(f"weight={weight} → {out.name}  match={score[:170]}")

if __name__ == "__main__":
    main()

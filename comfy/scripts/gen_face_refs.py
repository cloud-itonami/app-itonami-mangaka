"""Generate clean character face references for IPAdapter FaceID.

For each of 5 characters (Yuto/Ren/Nei/Akira/Saki), run a dedicated
SDXL Animagine portrait pass with detailed CHAR_PROMPTS to produce
a clean face image. Saved to /tmp/character-faces/{char}-face.png.

Used by img2img-stylize.py as IPAdapterFaceID reference for character
identity stability in subsequent panel renders.
"""
import json, sys, time, urllib.parse, urllib.request, base64
from pathlib import Path

COMFY = "http://192.168.1.22:8188"
OUT_DIR = Path("/tmp/character-faces")
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHAR_PORTRAITS = {
    "Yuto":  "1boy, 17 year old Japanese teen male, dark messy black hair, "
             "anxious worried expression, slim build, white short-sleeve "
             "school uniform shirt, frontal portrait close up, "
             "face center frame, clean line art, manga style, "
             "high quality character design sheet",
    "Ren":   "1boy, 17 year old Japanese teen male, dark hair with hoodie pulled up, "
             "sleepy droopy half-closed eyes, casual oversized black hoodie, "
             "frontal portrait close up, face center frame, clean line art, "
             "manga style, high quality character design sheet",
    "Nei":   "1girl, 16 year old Japanese teen girl, long platinum blonde hair, "
             "calm gentle perceptive expression, navy sailor blouse uniform "
             "with red ribbon tie, frontal portrait close up, face center frame, "
             "clean line art, manga style, high quality character design sheet",
    "Akira": "1boy, 17 year old Japanese teen male, short brown hair, "
             "energetic mischievous expression, smiling, fashionable streetwear, "
             "frontal portrait close up, face center frame, clean line art, "
             "manga style, high quality character design sheet",
    "Saki":  "1girl, 16 year old Japanese teen girl, shoulder-length brown hair, "
             "skeptical raised-eyebrow deadpan expression, navy sailor uniform "
             "with red ribbon, frontal portrait close up, face center frame, "
             "clean line art, manga style, high quality character design sheet",
}

NEG = ("low quality, blurry, deformed, multiple people, full body, "
        "side profile, back view, distant shot, dark, abstract, photograph, 3d render")


def http(m, p, b=None, h=None):
    r = urllib.request.Request(f"{COMFY}{p}", data=b, method=m, headers=h or {})
    with urllib.request.urlopen(r, timeout=120) as q:
        return q.status, q.read()


def submit(wf):
    s, b = http("POST", "/prompt", json.dumps({"prompt": wf}).encode(),
                 {"content-type": "application/json"})
    return json.loads(b).get("prompt_id")


def wait_for(pid, timeout=300):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _, b = http("GET", f"/history/{pid}")
        e = (json.loads(b) or {}).get(pid)
        if e and (e.get("outputs") or e.get("status", {}).get("status_str")
                   in ("error", "success")):
            return e
        time.sleep(3)
    return {}


def fetch_view(filename, subfolder=""):
    q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
    _, b = http("GET", f"/view?{q}")
    return b


def gen_portrait(char_name: str, prompt: str) -> Path | None:
    wf = {
        "ckpt":   {"class_type": "CheckpointLoaderSimple",
                   "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
        "pos":    {"class_type": "CLIPTextEncode",
                   "inputs": {"text": prompt, "clip": ["ckpt", 1]}},
        "neg":    {"class_type": "CLIPTextEncode",
                   "inputs": {"text": NEG, "clip": ["ckpt", 1]}},
        "lat":    {"class_type": "EmptyLatentImage",
                   "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
        "ks":     {"class_type": "KSampler",
                   "inputs": {"seed": hash(char_name) % 1000000, "steps": 30,
                               "cfg": 6.5, "sampler_name": "dpmpp_2m_sde",
                               "scheduler": "karras", "denoise": 1.0,
                               "model": ["ckpt", 0], "positive": ["pos", 0],
                               "negative": ["neg", 0], "latent_image": ["lat", 0]}},
        "dec":    {"class_type": "VAEDecode",
                   "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        "save":   {"class_type": "SaveImage",
                   "inputs": {"filename_prefix": f"face-ref-{char_name.lower()}",
                               "images": ["dec", 0]}},
    }
    pid = submit(wf)
    if not pid: return None
    e = wait_for(pid, timeout=180)
    outs = e.get("outputs") or {}
    fname = None
    for nid, no in outs.items():
        for img in no.get("images", []):
            fname = img.get("filename")
            sub   = img.get("subfolder", "")
            if fname:
                data = fetch_view(fname, sub)
                out = OUT_DIR / f"{char_name.lower()}-face.png"
                out.write_bytes(data)
                return out
    return None


if __name__ == "__main__":
    print(f"Generating {len(CHAR_PORTRAITS)} character face refs:")
    for char, prompt in CHAR_PORTRAITS.items():
        t0 = time.monotonic()
        out = gen_portrait(char, prompt)
        if out:
            print(f"  ✓ {char}: {out}  ({time.monotonic()-t0:.0f}s)")
        else:
            print(f"  ✗ {char}: FAILED")

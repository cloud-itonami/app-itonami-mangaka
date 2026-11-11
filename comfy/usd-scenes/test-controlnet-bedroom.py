"""Test ControlNet Union Pro Max with USD-rendered depth + canny on Yuto's
bedroom (yuto_at_desk view). Single panel, no LoRA, B&W manga style.

If this produces a coherent "Yuto sitting at his bedroom desk" image
that matches the USD scene geometry, the v3 pipeline works."""
from __future__ import annotations
import json, time, urllib.parse, urllib.request
from pathlib import Path

COMFY = "http://192.168.1.22:8188"


def _http(method, path, body=None, headers=None):
    req = urllib.request.Request(f"{COMFY}{path}", data=body, method=method,
                                  headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read()


def submit(wf):
    s, b = _http("POST", "/prompt", json.dumps({"prompt": wf}).encode(),
                  {"content-type": "application/json"})
    j = json.loads(b)
    if j.get("node_errors"):
        print("node_errors:", json.dumps(j["node_errors"], indent=2)[:2000])
    return j["prompt_id"]


def wait(pid, t=600):
    end = time.monotonic() + t
    while time.monotonic() < end:
        _, b = _http("GET", f"/history/{pid}")
        e = (json.loads(b) or {}).get(pid)
        if e and (e.get("outputs") or e.get("status", {}).get("status_str")
                  in ("error", "success")):
            return e
        time.sleep(5)
    return {}


CANNY_PATH = "arc01-scenes/yuto-bedroom-yuto_at_desk-canny.png"
DEPTH_PATH = "arc01-scenes/yuto-bedroom-yuto_at_desk-depth.png"
PROMPT_POS = (
    "anime illustration, yuto_persona, 1boy, 17 year old, "
    "Japanese teen boy, school uniform, sitting at desk, looking at smartphone, "
    "anxious expression, "
    "(monochrome inked manga panel:1.25), (sharp black ink lines:1.2), "
    "screentone, (high contrast B&W:1.2), shonen-jump style, "
    "detailed background, environment visible, professional manga page"
)
PROMPT_NEG = (
    "low quality, worst quality, blurry, deformed, color illustration, "
    "watercolor, sepia, cyan tint, multiple people, repeated faces, "
    "extra fingers, malformed hands"
)


def build():
    return {
        "1":  {"class_type": "CheckpointLoaderSimple",
               "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
        "5":  {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["1", 0], "lora_name": "yuto_persona.safetensors",
                          "strength_model": 0.55}},
        "10": {"class_type": "LoadImage", "inputs": {"image": CANNY_PATH}},
        "11": {"class_type": "LoadImage", "inputs": {"image": DEPTH_PATH}},
        "20": {"class_type": "ControlNetLoader",
               "inputs": {"control_net_name": "controlnet-union-sdxl-promax.safetensors"}},
        "30": {"class_type": "CLIPTextEncode",
               "inputs": {"text": PROMPT_POS, "clip": ["1", 1]}},
        "31": {"class_type": "CLIPTextEncode",
               "inputs": {"text": PROMPT_NEG, "clip": ["1", 1]}},
        # Apply Canny ControlNet — lower strength so character can be added
        "40": {"class_type": "ControlNetApply", "inputs": {
                  "conditioning": ["30", 0],
                  "control_net": ["20", 0],
                  "image": ["10", 0],
                  "strength": 0.40,
              }},
        # Depth at low strength — depth gives 3D anchor but allows soft fills
        "41": {"class_type": "ControlNetApply", "inputs": {
                  "conditioning": ["40", 0],
                  "control_net": ["20", 0],
                  "image": ["11", 0],
                  "strength": 0.25,
              }},
        "50": {"class_type": "EmptyLatentImage",
               "inputs": {"width": 1216, "height": 832, "batch_size": 1}},
        "60": {"class_type": "KSampler", "inputs": {
                  "seed": 42, "steps": 32, "cfg": 6.5,
                  "sampler_name": "dpmpp_2m_sde", "scheduler": "karras",
                  "denoise": 1.0,
                  "model": ["5", 0],
                  "positive": ["41", 0], "negative": ["31", 0],
                  "latent_image": ["50", 0],
              }},
        "70": {"class_type": "VAEDecode",
               "inputs": {"samples": ["60", 0], "vae": ["1", 2]}},
        "80": {"class_type": "SaveImage",
               "inputs": {"filename_prefix": "test-controlnet-bedroom",
                          "images": ["70", 0]}},
    }


def main():
    wf = build()
    print(f"submitting {len(wf)}-node workflow")
    pid = submit(wf)
    print(f"prompt_id: {pid}")
    t0 = time.monotonic()
    e = wait(pid)
    el = time.monotonic() - t0
    s = (e.get("status") or {}).get("status_str")
    outs = e.get("outputs") or {}
    if s == "error" or not outs:
        print(f"FAIL ({el:.0f}s) status={s}")
        for m in (e.get("status", {}).get("messages") or [])[-3:]:
            print(f"  {m}")
        return 1
    for nid, out in outs.items():
        for im in out.get("images", []):
            fname = im["filename"]
            print(f"output: {fname} ({el:.0f}s)")
            q = urllib.parse.urlencode({"filename": fname, "subfolder": "",
                                          "type": "output"})
            _, data = _http("GET", f"/view?{q}")
            Path("/tmp/test-controlnet-bedroom.png").write_bytes(data)
            break


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)

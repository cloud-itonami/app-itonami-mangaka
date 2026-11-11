import json, time, urllib.parse, urllib.request
from pathlib import Path

COMFY = "http://192.168.1.22:8188"

def _http(method, path, body=None, headers=None):
    req = urllib.request.Request(f"{COMFY}{path}", data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as r: return r.status, r.read()

def submit(wf):
    s, b = _http("POST", "/prompt", json.dumps({"prompt": wf}).encode(), {"content-type": "application/json"})
    j = json.loads(b)
    if j.get("node_errors"): print("err:", json.dumps(j["node_errors"], indent=2)[:1500])
    return j["prompt_id"]

def wait(pid, t=600):
    end = time.monotonic() + t
    while time.monotonic() < end:
        _, b = _http("GET", f"/history/{pid}")
        e = (json.loads(b) or {}).get(pid)
        if e and (e.get("outputs") or e.get("status",{}).get("status_str") in ("error","success")):
            return e
        time.sleep(5)
    return {}

PROMPT_POS = (
    "anime illustration, yuto_persona, 1boy, 17 year old, Japanese teen, "
    "school uniform, sitting at desk, holding smartphone, anxious face, "
    "(monochrome inked manga panel:1.25), (sharp black ink lines:1.2), "
    "screentone, (high contrast B&W:1.2), shonen-jump style, "
    "detailed background, environment visible"
)
PROMPT_NEG = (
    "low quality, worst quality, blurry, deformed, color illustration, "
    "watercolor, sepia, cyan tint, multiple people, repeated faces, "
    "extra fingers, malformed hands"
)
wf = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
    "5": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "yuto_persona.safetensors", "strength_model": 0.55}},
    "10": {"class_type": "LoadImage", "inputs": {"image": "arc01-scenes/yuto-bedroom-yuto_at_desk-canny.png"}},
    "11": {"class_type": "LoadImage", "inputs": {"image": "arc01-scenes/yuto-bedroom-yuto_at_desk-depth.png"}},
    "12": {"class_type": "LoadImage", "inputs": {"image": "arc01-scenes/yuto-bedroom-yuto_at_desk-openpose.png"}},
    "20": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "controlnet-union-sdxl-promax.safetensors"}},
    "30": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT_POS, "clip": ["1", 1]}},
    "31": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT_NEG, "clip": ["1", 1]}},
    "40": {"class_type": "ControlNetApply", "inputs": {"conditioning": ["30", 0], "control_net": ["20", 0], "image": ["10", 0], "strength": 0.35}},
    "41": {"class_type": "ControlNetApply", "inputs": {"conditioning": ["40", 0], "control_net": ["20", 0], "image": ["11", 0], "strength": 0.25}},
    "42": {"class_type": "ControlNetApply", "inputs": {"conditioning": ["41", 0], "control_net": ["20", 0], "image": ["12", 0], "strength": 0.65}},
    "50": {"class_type": "EmptyLatentImage", "inputs": {"width": 1216, "height": 832, "batch_size": 1}},
    "60": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 32, "cfg": 6.5, "sampler_name": "dpmpp_2m_sde", "scheduler": "karras", "denoise": 1.0, "model": ["5", 0], "positive": ["42", 0], "negative": ["31", 0], "latent_image": ["50", 0]}},
    "70": {"class_type": "VAEDecode", "inputs": {"samples": ["60", 0], "vae": ["1", 2]}},
    "80": {"class_type": "SaveImage", "inputs": {"filename_prefix": "test-bedroom-with-char", "images": ["70", 0]}},
}
pid = submit(wf)
print(f"prompt_id: {pid}")
t0 = time.monotonic()
e = wait(pid)
el = time.monotonic() - t0
s = (e.get("status") or {}).get("status_str")
outs = e.get("outputs") or {}
if s == "error" or not outs:
    print(f"FAIL ({el:.0f}s)")
    for m in (e.get("status",{}).get("messages") or [])[-3:]:
        print(f"  {m}")
else:
    for nid, out in outs.items():
        for im in out.get("images", []):
            fname = im["filename"]
            print(f"output: {fname} ({el:.0f}s)")
            q = urllib.parse.urlencode({"filename": fname, "subfolder": "", "type": "output"})
            _, data = _http("GET", f"/view?{q}")
            Path("/tmp/test-bedroom-with-char.png").write_bytes(data)
            break

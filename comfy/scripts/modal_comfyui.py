"""Modal ComfyUI deployment for mangaka pipeline.

Deploys ComfyUI + cubiq IPAdapter + ControlNet Union on H100, accepts
workflow JSON via run_workflow() and returns final PNG bytes.

Why ComfyUI over diffusers:
  - panel_hq_workflow already wires IPAdapter FaceID + ControlNet Union
  - LoRA chain support trivial (LoraLoader nodes)
  - Existing mangaka workflow library (character / scene / panel / page)
  - studio.gftd.ai compatible (same workflow JSON)

Deploy:
  modal deploy scripts/modal_comfyui.py

Test:
  modal run scripts/modal_comfyui.py
"""
from __future__ import annotations
import base64, io, json, os, subprocess, time, urllib.request, urllib.parse
import modal

app = modal.App("mangaka-comfyui")

# ── Image: ComfyUI + cubiq IPAdapter + ControlNet aux ──────────────────────
COMFY_REV = "v0.3.50"  # ComfyUI tag — newer for stable frontend-pkg pin

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget", "ffmpeg", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "torchaudio==2.5.1",
        "torchsde==0.2.6",
        "einops==0.8.0",
        "transformers==4.46.0",
        "tokenizers==0.20.3",
        "sentencepiece==0.2.0",
        "safetensors==0.4.5",
        "aiohttp==3.10.10",
        "pyyaml==6.0.2",
        "pillow==11.0.0",
        "scipy==1.14.1",
        "tqdm==4.66.6",
        "psutil==6.1.0",
        "kornia==0.7.4",
        "spandrel==0.4.0",
        "soundfile==0.12.1",
        "av==13.1.0",
        "trimesh==4.5.2",
        "onnxruntime==1.20.0",
        "insightface==0.7.3",
    )
    .run_commands(
        # ComfyUI core
        f"git clone https://github.com/comfyanonymous/ComfyUI.git /root/ComfyUI && "
        f"cd /root/ComfyUI && git checkout {COMFY_REV}",
        # ComfyUI core requirements (includes comfyui-frontend-package needed in v0.3+)
        "pip install -r /root/ComfyUI/requirements.txt",
        # cubiq IPAdapter Plus
        "cd /root/ComfyUI/custom_nodes && "
        "git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus.git",
        # ControlNet aux preprocessors (Canny etc.)
        "cd /root/ComfyUI/custom_nodes && "
        "git clone https://github.com/Fannovel16/comfyui_controlnet_aux.git && "
        "cd comfyui_controlnet_aux && pip install -r requirements.txt || true",
        # ComfyUI essential
        "cd /root/ComfyUI/custom_nodes && "
        "git clone https://github.com/cubiq/ComfyUI_essentials.git",
    )
)

vol_models = modal.Volume.from_name("mangaka-comfy-models", create_if_missing=True)

# ── Helper: HTTP client for ComfyUI on localhost ───────────────────────────
def _comfy_http(method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(f"http://127.0.0.1:8188{path}",
                                  data=body,
                                  headers={"Content-Type": "application/json"} if body else {},
                                  method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _wait_comfy_ready(timeout: int = 120) -> bool:
    """Poll /system_stats until ComfyUI is ready or timeout."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            code, _ = _comfy_http("GET", "/system_stats")
            if code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


_comfy_proc = None


def _ensure_comfy_running():
    """Start ComfyUI subprocess if not already running."""
    global _comfy_proc
    if _comfy_proc is not None and _comfy_proc.poll() is None:
        return
    # Symlink models from volume into ComfyUI/models
    os.makedirs("/cache/models", exist_ok=True)
    for sub in ("checkpoints", "controlnet", "ipadapter", "clip_vision",
                "loras", "vae", "insightface"):
        src = f"/cache/models/{sub}"
        os.makedirs(src, exist_ok=True)
        dst = f"/root/ComfyUI/models/{sub}"
        if os.path.islink(dst): os.unlink(dst)
        elif os.path.isdir(dst):
            for f in os.listdir(dst):
                fp = os.path.join(dst, f)
                if os.path.isfile(fp): os.unlink(fp)
            os.rmdir(dst)
        os.symlink(src, dst, target_is_directory=True)
    os.makedirs("/root/ComfyUI/input", exist_ok=True)
    print("[comfy] starting server...", flush=True)
    logf = open("/tmp/comfy.log", "wb")
    _comfy_proc = subprocess.Popen(
        ["python", "/root/ComfyUI/main.py",
         "--listen", "127.0.0.1", "--port", "8188",
         "--disable-auto-launch", "--disable-metadata"],
        stdout=logf, stderr=subprocess.STDOUT,
        cwd="/root/ComfyUI", env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    if not _wait_comfy_ready(180):
        try:
            tail = open("/tmp/comfy.log").read()[-3000:]
        except Exception as e:
            tail = f"(log read err: {e})"
        raise RuntimeError(f"ComfyUI failed to start within 180s. last log:\n{tail}")
    print("[comfy] ready", flush=True)


# ── Modal function: run a workflow ─────────────────────────────────────────
@app.function(
    image=image,
    gpu="H100",
    volumes={"/cache": vol_models},
    timeout=600,
    scaledown_window=300,
    secrets=[modal.Secret.from_name("huggingface-token", required_keys=["HF_TOKEN"])]
        if False else [],
)
def run_workflow(workflow: dict, refs: dict[str, str] | None = None) -> bytes:
    """Run a ComfyUI workflow on H100.

    Args:
      workflow: ComfyUI workflow JSON (prompt API format — keyed dict)
      refs: optional {filename: base64-encoded image bytes} — saved to
            ComfyUI input dir before execution.

    Returns:
      PNG bytes of the first SaveImage output.
    """
    _ensure_comfy_running()

    # Save reference images into input dir
    if refs:
        for fname, b64 in refs.items():
            data = base64.b64decode(b64)
            path = f"/root/ComfyUI/input/{fname}"
            with open(path, "wb") as f:
                f.write(data)
            print(f"[comfy] ref → {path} ({len(data)} bytes)", flush=True)

    # Submit
    code, body = _comfy_http("POST", "/prompt",
                              json.dumps({"prompt": workflow}).encode())
    if code != 200:
        raise RuntimeError(f"ComfyUI /prompt failed [{code}]: {body[:200]!r}")
    pid = json.loads(body).get("prompt_id")
    if not pid:
        raise RuntimeError(f"no prompt_id in response: {body[:200]!r}")
    print(f"[comfy] submitted pid={pid}", flush=True)

    # Poll
    end = time.time() + 300
    last_log = 0
    while time.time() < end:
        try:
            _, hist = _comfy_http("GET", f"/history/{pid}")
            d = json.loads(hist or b"{}") or {}
            entry = d.get(pid)
            if entry:
                outputs = entry.get("outputs", {})
                for nid, no in outputs.items():
                    for img in no.get("images", []):
                        fname = img.get("filename")
                        sub = img.get("subfolder", "")
                        if fname:
                            q = urllib.parse.urlencode({"filename": fname,
                                                         "subfolder": sub,
                                                         "type": "output"})
                            _, data = _comfy_http("GET", f"/view?{q}")
                            print(f"[comfy] returning {len(data)} bytes", flush=True)
                            return data
                # Done but no images
                if entry.get("status", {}).get("status_str") == "error":
                    raise RuntimeError(f"workflow error: {entry.get('status')}")
        except Exception as e:
            now = time.time()
            if now - last_log > 5:
                print(f"[comfy] poll: {e}", flush=True)
                last_log = now
        time.sleep(2)
    raise RuntimeError("workflow timeout after 300s")


@app.function(
    image=image,
    volumes={"/cache": vol_models},
    timeout=3600,
)
def download_models(hf_token: str | None = None) -> str:
    """Download SDXL Animagine + ControlNet + IPAdapter models to volume.
    One-shot bootstrap; idempotent.
    """
    import urllib.request as ur
    os.makedirs("/cache/models", exist_ok=True)
    for sub in ("checkpoints", "controlnet", "ipadapter", "clip_vision",
                "loras", "vae", "insightface/models/antelopev2"):
        os.makedirs(f"/cache/models/{sub}", exist_ok=True)

    headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}

    DOWNLOADS = [
        # SDXL Animagine XL 4.0
        ("checkpoints/animagine-xl-4.0.safetensors",
         "https://huggingface.co/cagliostrolab/animagine-xl-4.0/resolve/main/animagine-xl-4.0.safetensors"),
        # ControlNet Union SDXL PROMAX
        ("controlnet/controlnet-union-sdxl-promax.safetensors",
         "https://huggingface.co/xinsir/controlnet-union-sdxl-1.0/resolve/main/diffusion_pytorch_model_promax.safetensors"),
        # IPAdapter Plus SDXL ViT-H
        ("ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors",
         "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors"),
        # IPAdapter FaceID Plus v2 SDXL
        ("ipadapter/ip-adapter-faceid-plusv2_sdxl.bin",
         "https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl.bin"),
        ("loras/ip-adapter-faceid-plusv2_sdxl_lora.safetensors",
         "https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl_lora.safetensors"),
        # CLIP-ViT-H-14 (used by IPAdapter Plus SDXL ViT-H variant — packaged in h94 repo)
        ("clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
         "https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors"),
    ]

    errors = []
    for dst, url in DOWNLOADS:
        path = f"/cache/models/{dst}"
        if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
            print(f"[skip] {dst}", flush=True)
            continue
        print(f"[get ] {url} → {dst}", flush=True)
        try:
            req = ur.Request(url, headers=headers)
            with ur.urlopen(req) as r, open(path, "wb") as f:
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk: break
                    f.write(chunk)
            print(f"[done] {dst} ({os.path.getsize(path) / 1e6:.1f} MB)", flush=True)
        except Exception as e:
            msg = f"FAIL {dst}: {e!r}"
            errors.append(msg)
            print(f"[FAIL] {msg}", flush=True)
            if os.path.exists(path):
                try: os.unlink(path)
                except Exception: pass
    if errors:
        return "errors: " + " | ".join(errors)[:500]
    return "ok"


@app.local_entrypoint()
def test():
    """Quick smoke: download (idempotent) then run a tiny workflow."""
    print("=== downloading models (idempotent) ===")
    download_models.remote()
    print("=== smoke workflow (txt2img only, no IPA/CN) ===")
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "masterpiece, 1girl, sailor uniform, classroom",
                          "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "lowres, bad anatomy", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 896, "height": 1280, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": 42, "steps": 28, "cfg": 7.0,
                          "sampler_name": "dpmpp_2m_sde", "scheduler": "karras",
                          "denoise": 1.0,
                          "model": ["1", 0], "positive": ["2", 0],
                          "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "smoke", "images": ["6", 0]}},
    }
    t0 = time.time()
    png = run_workflow.remote(wf)
    dt = time.time() - t0
    out = "/tmp/modal-comfy-smoke.png"
    with open(out, "wb") as f:
        f.write(png)
    print(f"saved {out} ({len(png) // 1024} KB)  wall={dt:.1f}s")

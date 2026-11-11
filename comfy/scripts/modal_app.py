"""Modal kaizen pipeline — SDXL + IPAdapter + Gemma 4 vision QA on H100/B200.

Goal: replace gad-side bottleneck (~14 min/page) with Modal-hosted GPU.
Expected per-page: 30-60s on H100.

Functions:
  - render_panel(prompt, neg, ref_image_b64) → PNG bytes
  - score_image(png_b64, prompt) → axis scores dict
  - render_page(manifest_panels, scene_slug) → full page composite

Deploy:
  modal deploy scripts/modal_app.py

Invoke from Mac:
  from modal import App
  app = App.lookup("mangaka-kaizen")
  png_bytes = app.render_panel.remote(prompt, neg, ref_b64)
"""
from __future__ import annotations
import base64, io, os
import modal

app = modal.App("mangaka-kaizen")

# ── Image: PyTorch + diffusers + transformers (Gemma) ──────────────────────
SDXL_MODEL = "cagliostrolab/animagine-xl-4.0"
GEMMA_MODEL = "google/gemma-3-4b-it"   # smaller for cost; can swap to 26B A4B
IPA_MODEL_URL = (
    "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/"
    "ip-adapter-plus_sdxl_vit-h.safetensors"
)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("wget", "ffmpeg", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "diffusers==0.31.0",
        "transformers==4.46.0",
        "accelerate==1.1.0",
        "safetensors==0.4.5",
        "pillow==11.0.0",
        "numpy==2.1.0",
        "huggingface-hub==0.26.0",
    )
    .run_commands(
        # Pre-download models to image cache (faster cold start)
        "mkdir -p /models/ipadapter /models/clip_vision",
        f"wget -q -O /models/ipadapter/ip-adapter-plus_sdxl.safetensors {IPA_MODEL_URL}",
    )
)

vol_models = modal.Volume.from_name("mangaka-models", create_if_missing=True)

# ── render_panel: SDXL inference ────────────────────────────────────────────
@app.function(
    image=image,
    # 2026-05-30: switched to L40S — Ada Lovelace 48GB GDDR6, closest Modal
    # equivalent to RTX 5090 (consumer Blackwell). H100 is faster but ~3x cost.
    # L40S: ~91 TFLOPS FP16, $1.95/hr on Modal vs H100 $4-8/hr.
    gpu="L40S",
    volumes={"/cache": vol_models},
    timeout=300,
    scaledown_window=180,    # keep warm between calls
)
def render_panel(
    prompt: str,
    negative: str,
    width: int = 1024,
    height: int = 1024,
    steps: int = 24,
    cfg: float = 5.5,
    seed: int = 42,
    ref_image_b64: str | None = None,
    ipa_weight: float = 0.65,
) -> bytes:
    """Render a single panel with SDXL Animagine + optional IPAdapter (L40S)."""
    import torch
    from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler

    # Lazy-load pipeline (cached after cold start)
    global _pipe
    if "_pipe" not in globals():
        _pipe = StableDiffusionXLPipeline.from_pretrained(
            SDXL_MODEL,
            torch_dtype=torch.float16,
            use_safetensors=True,
            cache_dir="/cache/diffusers",
        ).to("cuda")
        _pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            _pipe.scheduler.config, algorithm_type="sde-dpmsolver++",
            use_karras_sigmas=True,
        )
        _pipe.set_progress_bar_config(disable=True)

    generator = torch.Generator(device="cuda").manual_seed(int(seed))

    # IPAdapter wiring (optional)
    if ref_image_b64:
        from PIL import Image
        try:
            ref_img = Image.open(io.BytesIO(base64.b64decode(ref_image_b64)))
            _pipe.load_ip_adapter(
                "/models/ipadapter/ip-adapter-plus_sdxl.safetensors",
                subfolder="", weight_name="ip-adapter-plus_sdxl.safetensors",
            )
            _pipe.set_ip_adapter_scale(ipa_weight)
            kwargs = {"ip_adapter_image": ref_img}
        except Exception as e:
            print(f"  [ipa] skipped: {e}")
            kwargs = {}
    else:
        kwargs = {}

    image = _pipe(
        prompt=prompt,
        negative_prompt=negative,
        width=width, height=height,
        num_inference_steps=steps,
        guidance_scale=cfg,
        generator=generator,
        **kwargs,
    ).images[0]

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


# ── render_panel_h100: H100 variant for A/B comparison ─────────────────────
@app.function(
    image=image,
    gpu="H100",
    volumes={"/cache": vol_models},
    timeout=300,
    scaledown_window=180,
)
def render_panel_h100(
    prompt: str, negative: str,
    width: int = 1024, height: int = 1024,
    steps: int = 24, cfg: float = 5.5, seed: int = 42,
    ref_image_b64: str | None = None, ipa_weight: float = 0.65,
) -> bytes:
    """Same as render_panel but on H100. Used for L40S vs H100 A/B benchmark."""
    import torch
    from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler
    global _pipe_h100
    if "_pipe_h100" not in globals():
        _pipe_h100 = StableDiffusionXLPipeline.from_pretrained(
            SDXL_MODEL, torch_dtype=torch.float16,
            use_safetensors=True, cache_dir="/cache/diffusers",
        ).to("cuda")
        _pipe_h100.scheduler = DPMSolverMultistepScheduler.from_config(
            _pipe_h100.scheduler.config, algorithm_type="sde-dpmsolver++",
            use_karras_sigmas=True,
        )
        _pipe_h100.set_progress_bar_config(disable=True)
    g = torch.Generator(device="cuda").manual_seed(int(seed))
    img = _pipe_h100(
        prompt=prompt, negative_prompt=negative,
        width=width, height=height, num_inference_steps=steps,
        guidance_scale=cfg, generator=g,
    ).images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── score_image: Gemma vision ────────────────────────────────────────────────
@app.function(
    image=image,
    gpu="A10G",   # cheaper for small Gemma; can swap to L4 / H100 if needed
    volumes={"/cache": vol_models},
    timeout=120,
)
def score_image(png_bytes: bytes, prompt: str, max_tokens: int = 500) -> str:
    """Score image with Gemma vision model. Returns raw text response."""
    import torch
    from transformers import AutoProcessor, AutoModelForVision2Seq
    from PIL import Image

    global _model, _processor
    if "_model" not in globals():
        _processor = AutoProcessor.from_pretrained(
            GEMMA_MODEL, cache_dir="/cache/gemma")
        _model = AutoModelForVision2Seq.from_pretrained(
            GEMMA_MODEL,
            torch_dtype=torch.float16,
            cache_dir="/cache/gemma",
        ).to("cuda")
        _model.eval()

    img = Image.open(io.BytesIO(png_bytes))
    messages = [{
        "role": "user",
        "content": [{"type": "image"}, {"type": "text", "text": prompt}],
    }]
    inputs = _processor.apply_chat_template(
        messages, add_generation_prompt=True,
        tokenize=True, return_tensors="pt", return_dict=True,
        images=[img],
    ).to("cuda")
    with torch.no_grad():
        gen = _model.generate(
            **inputs, max_new_tokens=max_tokens,
            do_sample=False, temperature=0.1,
        )
    text = _processor.decode(gen[0], skip_special_tokens=True)
    return text


# ── local entrypoint for quick test ──────────────────────────────────────────
@app.local_entrypoint()
def test():
    """Quick test: render a single panel (skip scoring; Gemma gated)."""
    import time
    prompt = ("professional Japanese manga panel, monochrome B&W only, "
              "1boy, 17yo japanese teen, intense expression, "
              "Shokugeki no Soma style by Saeki Shun, "
              "dramatic ink, heavy chiaroscuro, radial speed lines")
    negative = ("color, red, low quality, blurry, deformed, washed gray, "
                "pastel, cute chibi")
    t0 = time.time()
    print(f"rendering test panel on H100...")
    png = render_panel.remote(prompt, negative,
                               width=1024, height=1024, steps=24, seed=42)
    elapsed = time.time() - t0
    out = "/tmp/modal-test.png"
    with open(out, "wb") as f:
        f.write(png)
    print(f"saved {out} ({len(png)//1024} KB)  wall={elapsed:.1f}s")

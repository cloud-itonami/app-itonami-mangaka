"""ComfyUI recovery watchdog — polls health then auto-launches v8.

After ComfyUI host restart, this script runs a tiny test render every
60s. When the output is recognizable content (not rainbow noise), it
auto-launches v8_color_orchestrator on p0.

Detection: rainbow noise has uniform horizontal-stripe pattern → very
high variance between rows but tight within rows. A healthy SDXL
output has natural content with normal pixel statistics.

Heuristic: PIL → numpy → compute (mean per-row R/G/B std across rows).
Rainbow noise → row-to-row stddev >> 30. Real image → row stddev < 30.
"""
from __future__ import annotations
import json, time, urllib.request, urllib.parse, sys, os, subprocess
from pathlib import Path
import numpy as np
from PIL import Image

COMFY = "http://192.168.1.22:8188"
CANON = Path(__file__).parent.parent.parent
V8_ORCH = CANON / "lg/lg_mangaka/v8_color_orchestrator.py"
KAIZEN = CANON / "lg/lg_mangaka/kaizen_loop.py"
BUILD_MANIFEST = CANON / "lg/scripts/build-manifest.py"


def submit_test_render() -> Path | None:
    """Tiny SDXL render to check health. Returns path or None on failure."""
    wf = {
        "ckpt": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
        "pos":  {"class_type": "CLIPTextEncode",
                  "inputs": {"text": "1boy, simple background, anime",
                              "clip": ["ckpt", 1]}},
        "neg":  {"class_type": "CLIPTextEncode",
                  "inputs": {"text": "lowres, bad anatomy", "clip": ["ckpt", 1]}},
        "lat":  {"class_type": "EmptyLatentImage",
                  "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "ks":   {"class_type": "KSampler",
                  "inputs": {"seed": int(time.time()) % 100000,
                              "steps": 12, "cfg": 5.0,
                              "sampler_name": "dpmpp_2m_sde", "scheduler": "karras",
                              "denoise": 1.0,
                              "model": ["ckpt", 0], "positive": ["pos", 0],
                              "negative": ["neg", 0], "latent_image": ["lat", 0]}},
        "dec":  {"class_type": "VAEDecode",
                  "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        "save": {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "v8-watchdog-test",
                              "images": ["dec", 0]}},
    }
    try:
        req = urllib.request.Request(f"{COMFY}/prompt",
                                       data=json.dumps({"prompt": wf}).encode(),
                                       headers={"content-type": "application/json"},
                                       method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            pid = json.loads(r.read())["prompt_id"]
    except Exception as e:
        print(f"  ComfyUI unreachable: {e}", flush=True)
        return None

    # Poll for output
    end = time.monotonic() + 90
    while time.monotonic() < end:
        try:
            req = urllib.request.Request(f"{COMFY}/history/{pid}")
            with urllib.request.urlopen(req, timeout=10) as r:
                h = json.loads(r.read())
            if pid in h and h[pid].get("outputs"):
                for nid, no in h[pid]["outputs"].items():
                    for img in no.get("images", []):
                        fname = img["filename"]
                        q = urllib.parse.urlencode({"filename": fname,
                                                      "subfolder": "", "type": "output"})
                        req2 = urllib.request.Request(f"{COMFY}/view?{q}")
                        with urllib.request.urlopen(req2, timeout=30) as r2:
                            data = r2.read()
                        out = Path(f"/tmp/v8-watchdog-{int(time.time())}.png")
                        out.write_bytes(data)
                        return out
                return None
        except Exception:
            pass
        time.sleep(2)
    return None


def is_rainbow_noise(image_path: Path) -> tuple[bool, float, float]:
    """Detect rainbow-noise SDXL outputs via edge-direction ratio.

    Empirical (2026-05-25): rainbow has v/h edge ratio ~8.8, real
    images (color or B&W) have v/h ~1-3. Threshold 5.0 cleanly
    separates them on this ComfyUI host.

    Returns: (is_rainbow, saturation, v_over_h_edge_ratio)
    """
    im = Image.open(image_path).convert("RGB")
    arr = np.asarray(im).astype(float) / 255.0
    mx = arr.max(axis=2); mn = arr.min(axis=2)
    sat = float(((mx - mn) / (mx + 1e-9)).mean())
    gy = np.abs(arr[1:, :, :] - arr[:-1, :, :]).mean()
    gx = np.abs(arr[:, 1:, :] - arr[:, :-1, :]).mean()
    v_over_h = float(gy / (gx + 1e-9))
    is_rainbow = v_over_h > 5.0
    return is_rainbow, sat, v_over_h


def main():
    print(f"=== ComfyUI Recovery Watchdog ===", flush=True)
    print(f"Polling {COMFY} every 60s for clean SDXL output...", flush=True)
    print(f"Will auto-launch v8 on p0 when healthy.\n", flush=True)

    poll = 0
    while True:
        poll += 1
        print(f"[poll {poll}] {time.strftime('%H:%M:%S')} — submitting test render...", flush=True)
        out = submit_test_render()
        if out is None:
            print(f"  no output / ComfyUI down — retrying in 60s", flush=True)
            time.sleep(60)
            continue

        is_rb, sat, vh = is_rainbow_noise(out)
        status = "RAINBOW" if is_rb else "HEALTHY"
        print(f"  {out.name} → saturation={sat:.3f} v/h_edge={vh:.2f} → {status}",
              flush=True)

        if not is_rb:
            print(f"\n*** ComfyUI RECOVERED — running KAIZEN on p0 ***\n", flush=True)
            # Run kaizen loop with the new visual_hint + character_presence
            # fix prompts. 6 iters with different seeds finds stochastic best.
            log = Path("/tmp/v6-recovered-kaizen.log")
            with open(log, "w") as f:
                # Process mining found pre-v7 v6 path hit 69.9. Use --base v6
                # with new visual_hint + character_presence prompts.
                proc = subprocess.Popen(
                    ["/tmp/usd-venv/bin/python", "-u", str(KAIZEN),
                      "--preset", "ghosthacker", "--base", "v6",
                      "--iters", "6", "--seed-start", "40000", "0"],
                    stdout=f, stderr=subprocess.STDOUT)
            print(f"kaizen launched PID={proc.pid}, log={log}", flush=True)
            proc.wait()
            print(f"\nkaizen exited with code {proc.returncode}", flush=True)
            with open(log) as f:
                tail = f.readlines()[-50:]
                for line in tail:
                    if any(x in line for x in ["iter", "best", "total=", "→ "]):
                        print(f"  {line.rstrip()}")
            # Sync gallery
            for f in Path("/tmp").glob("kaizen-p00-iter*-scored.png"):
                subprocess.run(["cp", str(f), "/tmp/mangaka-gallery/img/"], check=False)
            for f in Path("/tmp").glob("kaizen-p00-iter*-score.json"):
                subprocess.run(["cp", str(f), "/tmp/mangaka-gallery/img/"], check=False)
            subprocess.run(["cp", "/tmp/kaizen-p00-best-scored.png",
                             "/tmp/mangaka-gallery/img/"], check=False)
            subprocess.run(["cp", "/tmp/gh-arc0-1-v5plus-p00-scored.png",
                             "/tmp/mangaka-gallery/img/"], check=False)
            subprocess.run(["cp", "/tmp/gh-arc0-1-v5plus-p00-score.json",
                             "/tmp/mangaka-gallery/img/"], check=False)
            subprocess.run(["/tmp/usd-venv/bin/python", str(BUILD_MANIFEST)],
                            check=False)
            print(f"Gallery updated: http://localhost:8765/", flush=True)
            return

        time.sleep(60)


if __name__ == "__main__":
    main()

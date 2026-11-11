"""3D Asset Generation Pipeline — text → image → 3D mesh → USD asset.

User: 3D object 生成 pipeline を作って. https://huggingface.co/TencentARC/Pixal3D
など で animagine xl で生成 → qa → qa clear → 3d object として利用で.

Stack chosen (ComfyUI nodes verified 2026-05-24):
  - Animagine XL 4.0 (image gen)        — already wired
  - Gemma 3:4b QA (Jump benchmark)      — already wired
  - Tencent Hunyuan3D-2 (image → mesh)  — 71 nodes available
    (note: TencentARC/Pixal3D doesn't exist on HF; Hunyuan3D-2 is
     Tencent's current SOTA image-to-3D model)
  - Hy3DPaintModel + DelightModel       — PBR texture
  - Hy3DExportMesh → GLB / OBJ / PLY
  - Convert to USD via usd-core import   — Blender stage usable

For emotion / motion / SFX:
  - MangakaCharacterEmotion (custom)    — already in pipeline
  - WanAnimateToVideo                    — WAN-based motion video
  - KlingMotionControl                   — Kling motion paths
  - SDPoseKeypointExtractor              — pose control points
  - MangakaPoseFromLibrary               — preset pose library
  - Geometry Nodes overlay (V6_GEONODES) — speed lines, motion blur

Pipeline flow:

  text prompt (CharacterNode.text_desc)
    ↓
  ComfyUI Animagine XL portrait pass
    ├─ multi-angle: front, 3/4, side, back
    ↓
  Gemma QA jump_benchmark
    ├─ score >= 65 → pass
    └─ < 65 → retry up to 3 times
    ↓
  Hunyuan3D-2 image → mesh
    ├─ Hy3DGenerateMeshMultiView (multi-view → consistent 3D)
    ├─ Hy3DMeshUVWrap (UV unwrapping)
    ├─ Hy3DPaintModel (PBR texture from multi-view images)
    ├─ Hy3DDelightImage (remove baked lighting)
    └─ Hy3DPostprocessMesh + FastSimplifyMesh
    ↓
  Hy3DExportMesh → /tmp/3d-assets/{character}.glb
    ↓
  trimesh → usd-core conversion → {character}.usda
    ↓
  Asset registry update (CharacterNode.lora_path → mesh_path)
    ↓
  scene_graph_designer uses real 3D mesh in Blender
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
import base64
from pathlib import Path

COMFY = "http://192.168.1.22:8188"
OUT_DIR = Path("/tmp/3d-assets")
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ─── Stage 1: Generate character portrait (multi-angle) ─────────────────

def gen_portrait_multi_view(char_name: str, prompt: str, page_seed: int = 42) -> list[Path]:
    """Generate 4 angles (front / 3-4 / side / back) for character via SDXL.
    Used as input for Hunyuan3D multi-view → 3D mesh.
    """
    angles = [
        ("front",   "front view facing camera"),
        ("3quarter","3/4 view turned slightly"),
        ("side",    "side profile view"),
        ("back",    "back view facing away"),
    ]
    outputs = []
    for angle_id, angle_prompt in angles:
        full_prompt = (
            f"{prompt}, {angle_prompt}, full body character design sheet, "
            f"plain white background, neutral lighting, T-pose, clear silhouette, "
            f"high quality, professional character sheet"
        )
        out_path = OUT_DIR / f"{char_name.lower()}-{angle_id}.png"
        # Build minimal txt2img workflow (Animagine XL)
        wf = {
            "ckpt":   {"class_type": "CheckpointLoaderSimple",
                       "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
            "pos":    {"class_type": "CLIPTextEncode",
                       "inputs": {"text": full_prompt, "clip": ["ckpt", 1]}},
            "neg":    {"class_type": "CLIPTextEncode",
                       "inputs": {"text": "low quality, deformed, multiple people, "
                                            "background scene, props, no white bg",
                                   "clip": ["ckpt", 1]}},
            "lat":    {"class_type": "EmptyLatentImage",
                       "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
            "ks":     {"class_type": "KSampler",
                       "inputs": {"seed": page_seed + hash(angle_id) % 1000,
                                   "steps": 28, "cfg": 6.0,
                                   "sampler_name": "dpmpp_2m_sde",
                                   "scheduler": "karras", "denoise": 1.0,
                                   "model": ["ckpt", 0], "positive": ["pos", 0],
                                   "negative": ["neg", 0], "latent_image": ["lat", 0]}},
            "dec":    {"class_type": "VAEDecode",
                       "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
            "save":   {"class_type": "SaveImage",
                       "inputs": {"filename_prefix": f"3d-portrait-{char_name.lower()}-{angle_id}",
                                   "images": ["dec", 0]}},
        }
        out = _submit_and_fetch(wf, out_path)
        if out: outputs.append(out)
    return outputs


# ─── Stage 2: QA via Gemma Jump benchmark ───────────────────────────────

def qa_check(image_path: Path, threshold: float = 65.0) -> tuple[bool, dict]:
    """Pass/fail decision via Gemma Jump benchmark."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("jbq", "/tmp/jump_benchmark_qa.py")
    jbq = importlib.util.module_from_spec(spec); spec.loader.exec_module(jbq)
    r = jbq.score_page(image_path)
    return r.get("total", 0) >= threshold, r


# ─── Stage 3: Hunyuan3D-2 image → 3D mesh ────────────────────────────────

def image_to_3d_hy3d(image_path: Path, char_name: str) -> Path | None:
    """Run Hunyuan3D-2 ComfyUI workflow: single image → 3D mesh (GLB).

    Multi-view variant (Hy3DGenerateMeshMultiView) would use the 4
    angle images for higher quality, but adds complexity. Start with
    single-image first.
    """
    img_name = _upload_image(image_path)
    out_glb = OUT_DIR / f"{char_name.lower()}.glb"

    wf = {
        "img":     {"class_type": "LoadImage",
                    "inputs": {"image": img_name}},
        "loader":  {"class_type": "Hy3DModelLoader",
                    "inputs": {"model": "hunyuan3d-dit-v2-mini",
                                "attention_mode": "sdpa",
                                "compile_args": None}},
        "delight": {"class_type": "Hy3DDelightImage",
                    "inputs": {"image": ["img", 0]}},
        "mesh":    {"class_type": "Hy3DGenerateMesh",
                    "inputs": {"pipeline": ["loader", 0],
                                "image": ["delight", 0],
                                "guidance_scale": 5.5,
                                "steps": 30, "seed": 42,
                                "octree_resolution": 384}},
        "post":    {"class_type": "Hy3DPostprocessMesh",
                    "inputs": {"trimesh": ["mesh", 0],
                                "remove_floaters": True,
                                "remove_degenerate": True,
                                "smooth_iterations": 2}},
        "export":  {"class_type": "Hy3DExportMesh",
                    "inputs": {"trimesh": ["post", 0],
                                "filename_prefix": f"3d-{char_name.lower()}",
                                "file_format": "glb"}},
    }
    return _submit_and_fetch(wf, out_glb, format="model")


# ─── Stage 4: GLB → USD conversion ───────────────────────────────────────

def glb_to_usd(glb_path: Path, out_usd: Path) -> Path | None:
    """Convert GLB to USD via trimesh + usd-core."""
    try:
        import trimesh
        from pxr import Usd, UsdGeom, Gf
        scene = trimesh.load(glb_path, force="scene")
        stage = Usd.Stage.CreateNew(str(out_usd))
        stage.SetMetadata("upAxis", "Y")
        root = UsdGeom.Xform.Define(stage, "/Character")
        stage.SetDefaultPrim(root.GetPrim())
        for name, geo in scene.geometry.items():
            mesh_path = f"/Character/{name.replace(' ', '_')}"
            prim = UsdGeom.Mesh.Define(stage, mesh_path)
            prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in geo.vertices])
            prim.GetFaceVertexCountsAttr().Set([3] * len(geo.faces))
            prim.GetFaceVertexIndicesAttr().Set(geo.faces.flatten().tolist())
        stage.GetRootLayer().Save()
        return out_usd
    except Exception as e:
        print(f"  GLB→USD fail: {e}")
        return None


# ─── Helpers ────────────────────────────────────────────────────────────

def _upload_image(local_path: Path) -> str:
    import uuid
    boundary = "----formboundary" + uuid.uuid4().hex
    fname = f"3d-input-{local_path.stem}-{uuid.uuid4().hex[:8]}.png"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{fname}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + local_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{COMFY}/upload/image", data=body,
                                  headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                  method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return (json.loads(r.read()).get("name")) or fname


def _submit_and_fetch(wf: dict, out_path: Path, format: str = "image") -> Path | None:
    req = urllib.request.Request(f"{COMFY}/prompt",
        data=json.dumps({"prompt": wf}).encode(),
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        pid = json.loads(r.read()).get("prompt_id")
    if not pid: return None
    # Wait for completion
    end = time.monotonic() + 600
    while time.monotonic() < end:
        with urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=10) as r:
            e = (json.loads(r.read()) or {}).get(pid)
        if e and e.get("outputs"):
            for nid, no in e["outputs"].items():
                items = no.get("images" if format == "image" else "result", [])
                for item in items:
                    fname = item.get("filename") if isinstance(item, dict) else None
                    if fname:
                        q = urllib.parse.urlencode({"filename": fname,
                                                     "subfolder": item.get("subfolder", ""),
                                                     "type": "output"})
                        with urllib.request.urlopen(f"{COMFY}/view?{q}", timeout=60) as r:
                            out_path.write_bytes(r.read())
                        return out_path
            return None
        time.sleep(5)
    return None


# ─── Top-level orchestrator ─────────────────────────────────────────────

def generate_character_asset(char_name: str, prompt: str,
                              qa_threshold: float = 65.0,
                              max_retries: int = 3) -> dict:
    """Full pipeline: text → image → QA → 3D mesh → USD."""
    result = {"char_name": char_name, "stages": [], "success": False}
    # Stage 1: portrait (front view only for now; multi-view in v2)
    for attempt in range(max_retries):
        portraits = gen_portrait_multi_view(f"{char_name}_a{attempt}", prompt)
        if not portraits:
            result["stages"].append({"stage": "portrait", "attempt": attempt, "status": "fail"})
            continue
        front = portraits[0]
        result["stages"].append({"stage": "portrait", "attempt": attempt,
                                   "files": [str(p) for p in portraits]})

        # Stage 2: QA
        passed, qa_r = qa_check(front, qa_threshold)
        result["stages"].append({"stage": "qa", "score": qa_r.get("total"),
                                   "passed": passed})
        if not passed:
            print(f"  QA fail attempt {attempt}: score {qa_r.get('total','?')}/100")
            continue

        # Stage 3: image → 3D
        glb = image_to_3d_hy3d(front, char_name)
        if not glb:
            result["stages"].append({"stage": "hy3d", "status": "fail"})
            continue
        result["stages"].append({"stage": "hy3d", "file": str(glb)})

        # Stage 4: GLB → USD
        usd = OUT_DIR / f"{char_name.lower()}.usda"
        usd_out = glb_to_usd(glb, usd)
        if usd_out:
            result["stages"].append({"stage": "usd", "file": str(usd_out)})
            result["success"] = True
            result["usd_path"] = str(usd_out)
            return result
    return result


if __name__ == "__main__":
    import sys
    import urllib.parse
    char = sys.argv[1] if len(sys.argv) > 1 else "Yuto"
    prompts = {
        "Yuto": "1boy, 17 year old Japanese teen male, dark messy black hair, "
                 "anxious expression, slim build, white short-sleeve shirt, navy slacks",
        "Nei":  "1girl, 16 year old Japanese teen girl, long platinum blonde hair, "
                 "calm expression, navy sailor uniform with red ribbon",
    }
    prompt = prompts.get(char, prompts["Yuto"])
    r = generate_character_asset(char, prompt)
    print(json.dumps(r, indent=2, ensure_ascii=False))

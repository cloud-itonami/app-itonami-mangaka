"""v7 Stage C — Character standalone render with transparent background.

Generates SDXL character image with explicit pose+emotion prompt,
then extracts alpha via background removal (rembg or white-key).
Output: character on transparent panel-sized PNG.

V5_USE_IPADAPTER=1 enables FaceID PlusV2 SDXL with per-character face
ref images from data/ghosthacker/resources/character-faces/. Resolver
sets this automatically when ghosthacker preset is loaded (character
axis ≥0.8 → IPAdapter on).
"""
from __future__ import annotations
import json, sys, time, os, urllib.request, urllib.parse, base64, uuid
from pathlib import Path
from PIL import Image
import numpy as np

COMFY = "http://192.168.1.22:8188"
FACE_REFS_DIR = Path(__file__).parent.parent.parent / "data/ghosthacker/resources/character-faces"

# Character description prompts (text identity, no LoRA)
CHAR_DESCS = {
    "Yuto":  "1boy, 17 year old Japanese teen, dark messy black hair, "
              "white short-sleeve school shirt, navy slacks, slim build",
    "Ren":   "1boy, 17 year old Japanese teen, dark hair half-covered with hoodie, "
              "sleepy droopy eyes, oversized hoodie",
    "Nei":   "1girl, 16 year old Japanese teen, long platinum blonde hair, "
              "navy sailor uniform with red ribbon tie, pleated navy skirt",
    "Akira": "1boy, 17 year old Japanese teen, short brown hair, "
              "energetic mischievous expression, fashionable streetwear",
    "Saki":  "1girl, 16 year old Japanese teen, shoulder-length brown hair, "
              "skeptical deadpan expression, navy sailor uniform with red ribbon",
}

# Pose → SDXL prompt mapping
POSE_PROMPTS = {
    "sitting_at_desk":      "sitting at school desk, hands on desk surface",
    "sitting_back_to_camera": "sitting facing away from camera, back visible",
    "sitting_legs_crossed": "sitting cross-legged",
    "sitting_slumped":       "sitting slumped over desk, head down, exhausted",
    "sitting_on_bed":        "sitting on bed edge, leaning forward",
    "sitting_phone":         "sitting with smartphone in hand, gazing at phone screen",
    "standing_facing":       "standing facing camera frontal pose",
    "standing_profile":      "standing in side profile view",
    "standing_back":         "standing facing away from camera",
    "standing_leaning_wall": "leaning against wall casually",
    "standing_arms_crossed": "standing arms crossed defiant",
    "standing_arms_akimbo":  "standing hands on hips",
    "standing_pointing":     "standing pointing finger forward",
    "walking_toward":        "walking toward camera",
    "walking_away":          "walking away from camera",
    "walking_side":          "walking in side profile",
    "running":               "running urgently forward",
    "leaning_over_desk":     "leaning forward over desk, intrigued",
    "leaning_door":          "leaning in doorway",
    "leaning_railing":       "leaning on railing looking out",
    "gesturing_hands_open":  "gesturing with open hands explaining",
    "gesturing_finger_point": "pointing finger emphatically",
    "gesturing_holding_object": "holding out object to show",
    "gesturing_brushing_hair": "brushing hair aside casually",
    "shocked_arms_up":       "shocked arms raised in surprise",
    "anxious_clutching":     "anxious clutching chest worried",
    "calm_observing":        "calm observing the scene",
    "smug_smile":            "smug confident smile",
}


def _http(method: str, path: str, body=None):
    headers = {"content-type": "application/json"} if body else {}
    req = urllib.request.Request(f"{COMFY}{path}", data=body, method=method,
                                  headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read()


def _upload_face_ref(local_path: Path) -> str | None:
    """Upload face PNG to ComfyUI input dir; returns the name reference."""
    if not local_path.exists():
        return None
    boundary = "----formboundary" + uuid.uuid4().hex
    fname = f"v7-face-{local_path.stem}-{uuid.uuid4().hex[:8]}.png"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{fname}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + local_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{COMFY}/upload/image", data=body,
                                  headers={"Content-Type":
                                            f"multipart/form-data; boundary={boundary}"},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read())
        return result.get("name") or fname
    except Exception:
        return None


def render_character_panel(char: str, pose: str, emotion: str,
                            shot: str, panel_w: int, panel_h: int,
                            page_seed: int, panel_idx: int = 0,
                            visual_hint: str = "") -> Path | None:
    """Render character standalone on white background; output panel-sized PNG.

    visual_hint: panel-specific scene description from manifest['visual']
                  — used to lift manifest_qa axes (window/scene/action/spatial).
    """
    char_desc = CHAR_DESCS.get(char, "1person")
    pose_desc = POSE_PROMPTS.get(pose, "standing")
    shot_desc = {"ECU": "extreme close up face",
                  "CU":  "close up portrait",
                  "MS":  "medium shot waist up",
                  "LS":  "long shot full body",
                  "Wide":"full body figure"}.get(shot, "medium shot")
    # Extract action/lighting/props from visual_hint (Gemma manifest_qa cues)
    visual_brief = visual_hint[:200] if visual_hint else ""

    # Process mining (2026-05-25): manifest_character_presence=2.8/10 is
    # the #1 bottleneck. SDXL spawns extra characters from training prior.
    # Solution: stronger "solo, alone, one person" positive + aggressive
    # multi-person NEG.
    # Panel-specific visual scene cue prepended (manifest 'visual' field).
    # This lifts manifest_window_check + scene_match + action_match by
    # giving SDXL the exact narrative context Gemma checks against.
    scene_cue = f"scene context: {visual_brief}. " if visual_brief else ""
    prompt = (
        f"{scene_cue}"
        f"high-quality manga panel character art, solo, alone, one person, "
        f"Death Note style, Obata Takeshi art style, "
        f"hyper-detailed eyes, sharp facial features, "
        f"{char_desc}, {pose_desc}, {emotion} expression, {shot_desc}, "
        f"full body shot, character centered, only one person in frame, "
        f"pure white background, no scenery, no props except those held by character, "
        f"sharp black ink lines, monochrome manga, professional"
    )
    neg = ("low quality, blurry, deformed, "
            "2girls, 2boys, 2 people, two people, three people, multiple people, "
            "twin, twins, multiple faces, multiple persons, group, crowd, "
            "duplicate, mirror image, reflection, side characters, "
            "background scene, room interior, "
            "school classroom, desks, walls, windows, props, "
            "color, watercolor, 3d render, photograph")

    # Generate at panel aspect ratio
    if panel_w >= panel_h:
        w, h = 1216, max(832, int(1216 * panel_h / panel_w))
    else:
        h, w = 1216, max(832, int(1216 * panel_w / panel_h))
    w = (w // 64) * 64; h = (h // 64) * 64

    wf = {
        "ckpt":   {"class_type": "CheckpointLoaderSimple",
                   "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
        "pos":    {"class_type": "CLIPTextEncode",
                   "inputs": {"text": prompt, "clip": ["ckpt", 1]}},
        "neg":    {"class_type": "CLIPTextEncode",
                   "inputs": {"text": neg, "clip": ["ckpt", 1]}},
        "lat":    {"class_type": "EmptyLatentImage",
                   "inputs": {"width": w, "height": h, "batch_size": 1}},
        # V7_CHAR_STEPS env (set by orchestrator from FA.pipeline_priority):
        #   character-dominant → 28 steps full quality
        #   mood/shot-dominant → 24 steps
        #   space-dominant     → 16 steps (bg matters more)
        #   default            → 20 steps
        "ks":     {"class_type": "KSampler",
                   "inputs": {"seed": (page_seed or 42) + panel_idx,
                               "steps": int(os.environ.get("V7_CHAR_STEPS", "20")),
                               "cfg":   5.5,
                               "sampler_name": "dpmpp_2m_sde",
                               "scheduler": "karras", "denoise": 1.0,
                               "model": ["ckpt", 0], "positive": ["pos", 0],
                               "negative": ["neg", 0], "latent_image": ["lat", 0]}},
        "dec":    {"class_type": "VAEDecode",
                   "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        "save":   {"class_type": "SaveImage",
                   "inputs": {"filename_prefix": f"v7-char-{char.lower()}-p{panel_idx:02d}",
                               "images": ["dec", 0]}},
    }

    # IPAdapter FaceID PlusV2 — gated on V5_USE_IPADAPTER env (set by FA
    # resolver when character≥0.8). Direct loaders since PLUS preset is
    # unavailable on the ComfyUI host (img2img-stylize.py:332 reference).
    if os.environ.get("V5_USE_IPADAPTER", "0") == "1":
        face_ref = FACE_REFS_DIR / f"{char.lower()}-face.png"
        face_name = _upload_face_ref(face_ref)
        if face_name:
            wf["ipa_model_load"] = {
                "class_type": "IPAdapterModelLoader",
                "inputs": {"ipadapter_file": "ip-adapter-faceid-plusv2_sdxl.bin"}}
            wf["clip_vision"] = {
                "class_type": "CLIPVisionLoader",
                "inputs": {"clip_name": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"}}
            wf["insight"] = {
                "class_type": "IPAdapterInsightFaceLoader",
                "inputs": {"provider": "CPU", "model_name": "buffalo_l"}}
            wf["ipa_img"] = {"class_type": "LoadImage",
                              "inputs": {"image": face_name}}
            wf["ipa_face"] = {"class_type": "IPAdapterFaceID",
                               "inputs": {
                                   "model":           ["ckpt", 0],
                                   "ipadapter":       ["ipa_model_load", 0],
                                   "image":           ["ipa_img", 0],
                                   "weight":          0.75,
                                   "weight_faceidv2": 1.0,
                                   "weight_type":     "linear",
                                   "combine_embeds":  "concat",
                                   "start_at":        0.0,
                                   "end_at":          1.0,
                                   "embeds_scaling":  "V only",
                                   "insightface":     ["insight", 0],
                                   "clip_vision":     ["clip_vision", 0],
                               }}
            wf["ks"]["inputs"]["model"] = ["ipa_face", 0]

    _, body = _http("POST", "/prompt", json.dumps({"prompt": wf}).encode())
    pid = json.loads(body).get("prompt_id")
    if not pid: return None

    # Poll history (300s — IPAdapter adds ~30s per panel; school-hierarchy
    # bg + char overlap can push to ~150s. Old 180s caused p2.8 timeout.)
    end = time.monotonic() + 300
    while time.monotonic() < end:
        _, b = _http("GET", f"/history/{pid}")
        e = (json.loads(b) or {}).get(pid)
        if e and e.get("outputs"):
            for nid, no in e["outputs"].items():
                for img in no.get("images", []):
                    fname = img.get("filename"); sub = img.get("subfolder", "")
                    if fname:
                        q = urllib.parse.urlencode({"filename": fname,
                                                     "subfolder": sub, "type": "output"})
                        _, data = _http("GET", f"/view?{q}")
                        out_path = Path(f"/tmp/v7-char-pg-p{panel_idx:02d}.png")
                        out_path.write_bytes(data)
                        return out_path
            return None
        time.sleep(3)
    return None


def extract_character_alpha(image_path: Path, out_path: Path = None,
                             white_threshold: int = 240) -> Path:
    """Make OUTER white background transparent via flood-fill from corners.

    Critical fix (2026-05-24): the prior pixel-wise white→transparent broke
    interior white regions (e.g. Yuto's white school shirt) by making them
    transparent too — when composited over mood-hatching bg, the hatching
    bled through the shirt. Flood-fill from corners only removes the
    OUTSIDE white silhouette, preserving interior whites as opaque.
    """
    from PIL import ImageDraw
    im = Image.open(image_path).convert("RGBA")
    w, h = im.size
    arr = np.asarray(im).copy()
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    white_mask = (r >= white_threshold) & (g >= white_threshold) & (b >= white_threshold)

    # Flood-fill from 4 corners to find ONLY exterior background
    # (interior whites — shirts, paper, eyes — stay opaque)
    visited = np.zeros_like(white_mask, dtype=bool)
    from collections import deque
    queue = deque()
    for cy, cx in ((0, 0), (0, w-1), (h-1, 0), (h-1, w-1)):
        if white_mask[cy, cx] and not visited[cy, cx]:
            queue.append((cy, cx))
            visited[cy, cx] = True
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < h and 0 <= nx < w and white_mask[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                queue.append((ny, nx))
    arr[visited, 3] = 0   # exterior bg → fully transparent

    # Edge softening: near-white pixels adjacent to exterior get partial alpha
    edge_threshold = 200
    edge_mask = ((r >= edge_threshold) & (g >= edge_threshold) & (b >= edge_threshold)
                  & ~visited)
    # 1-pixel dilation of `visited` boundary (no scipy needed):
    boundary = np.zeros_like(visited)
    boundary[1:, :]  |= visited[:-1, :]
    boundary[:-1, :] |= visited[1:, :]
    boundary[:, 1:]  |= visited[:, :-1]
    boundary[:, :-1] |= visited[:, 1:]
    boundary &= ~visited
    arr[boundary & edge_mask, 3] = 128
    Image.fromarray(arr).save(out_path or image_path)
    return out_path or image_path


if __name__ == "__main__":
    # Test: render Yuto standing_facing in panel 1 of page 1
    out = render_character_panel("Yuto", "standing_facing", "anxious",
                                   "MS", 600, 400, page_seed=12345, panel_idx=1)
    if out:
        alpha_out = out.with_name(out.stem + "_alpha.png")
        extract_character_alpha(out, alpha_out)
        print(f"OK: {out}  +  {alpha_out}")

"""v8 Color manga character + bg renderer using Pony Diffusion V6 XL.

User: 90+ を狙うために v8 color pipeline を build

v7 (Animagine XL + monochrome+Obata) maxed at ~63 because it was
optimizing B&W ink against a color-action benchmark. v8 switches to
Pony Diffusion V6 XL for color-native generation, drops the monochrome
filter, and renders SFX as colored gradient kana.

Pony Diffusion uses Danbooru-style tags + "score_9, score_8_up"
quality prefix. Prompts are reformatted accordingly.

Output: full color RGB PNG (not posterized B&W).
"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.parse, uuid
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

COMFY = "http://192.168.1.22:8188"
# Switched from Pony Diffusion V6 XL (produced rainbow noise on scene
# prompts — heavily fine-tuned on character-only with Danbooru tags).
# Animagine XL 4.0 is anime-color-native and handles scenes well.
CKPT = "animagine-xl-4.0.safetensors"

# Color character descriptions (Danbooru-tagged for Pony)
CHAR_DESCS_COLOR = {
    "Yuto":  "1boy, solo, 17 year old male, japanese teen, "
              "messy black hair, dark eyes, slim build, "
              "white short sleeve school shirt, navy slacks, sneakers",
    "Ren":   "1boy, solo, 17 year old male, japanese teen, "
              "dark hair, hood up, droopy eyes, oversized hoodie, "
              "dark grey clothing, sleepy expression",
    "Nei":   "1girl, solo, 16 year old female, japanese teen, "
              "long platinum blonde hair, blue eyes, "
              "navy sailor school uniform, red ribbon tie, pleated skirt, "
              "knee high socks",
    "Akira": "1boy, solo, 17 year old male, japanese teen, "
              "short brown hair, brown eyes, mischievous smile, "
              "fashionable streetwear, hoodie, jeans",
    "Saki":  "1girl, solo, 16 year old female, japanese teen, "
              "shoulder length brown hair, deadpan expression, "
              "navy sailor school uniform, red ribbon, skeptical look",
}

POSE_PROMPTS_COLOR = {
    "sitting_at_desk":       "sitting at desk, hands on desk surface",
    "sitting_back_to_camera": "sitting facing away, back to viewer",
    "sitting_legs_crossed":  "sitting cross-legged on floor",
    "sitting_slumped":        "sitting slumped forward, head down, exhausted",
    "sitting_on_bed":         "sitting on bed edge, leaning forward",
    "sitting_phone":          "sitting, holding smartphone, looking at phone screen",
    "standing_facing":        "standing, looking at viewer, frontal pose",
    "standing_profile":       "standing, profile view, from side",
    "standing_back":          "standing, back view, facing away",
    "standing_leaning_wall":  "leaning against wall casually, hands in pockets",
    "standing_arms_crossed":  "standing, arms crossed, defiant",
    "standing_arms_akimbo":   "standing, hands on hips, confident",
    "standing_pointing":      "standing, pointing finger forward, dramatic",
    "walking_toward":         "walking toward viewer",
    "walking_away":           "walking away, back view",
    "walking_side":           "walking, profile view, motion blur",
    "running":                "running forward, urgent motion, dynamic pose",
    "leaning_over_desk":      "leaning over desk, intrigued, hands on desk",
    "leaning_door":           "leaning in doorway, casual",
    "leaning_railing":        "leaning on railing, looking outward, contemplative",
    "gesturing_hands_open":   "gesturing with open hands, explaining, expressive",
    "gesturing_finger_point": "pointing finger emphatically, dramatic",
    "gesturing_holding_object": "holding object out, showing it",
    "gesturing_brushing_hair": "brushing hair aside, casual gesture",
    "shocked_arms_up":        "shocked, arms raised in surprise, wide eyes",
    "anxious_clutching":      "anxious, hands clutching chest, worried expression",
    "calm_observing":         "calm expression, observing scene",
    "smug_smile":             "smug confident smile, looking down",
}

# Animagine XL quality prompt — anime-color-native
PONY_QUALITY_PREFIX = "masterpiece, best quality, very aesthetic, absurdres, "
PONY_NEG = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, worst quality, low quality, "
    "monochrome, greyscale, sketch, lineart, "
    "multiple people, twins, multiple faces, deformed, ugly, blurry, "
    "watermark, signature, "
)

FACE_REFS_DIR = Path(__file__).parent.parent.parent / "data/ghosthacker/resources/character-faces"


def _http(method: str, path: str, body=None):
    headers = {"content-type": "application/json"} if body else {}
    req = urllib.request.Request(f"{COMFY}{path}", data=body, method=method,
                                  headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read()


def render_character_color(char: str, pose: str, emotion: str,
                            shot: str, panel_w: int, panel_h: int,
                            page_seed: int, panel_idx: int = 0) -> Path | None:
    """Color character render on solid panel-aspect bg (NOT white-keyed)."""
    char_desc = CHAR_DESCS_COLOR.get(char, "1person")
    pose_desc = POSE_PROMPTS_COLOR.get(pose, "standing")
    shot_desc = {"ECU": "extreme close-up face shot, eyes detail",
                  "CU":  "close-up portrait shot, head and shoulders",
                  "MS":  "medium shot, waist up",
                  "LS":  "long shot, full body",
                  "Wide":"full body, wide shot"}.get(shot, "medium shot")

    prompt = (
        PONY_QUALITY_PREFIX +
        f"{char_desc}, {pose_desc}, {emotion}, "
        f"{shot_desc}, full color illustration, "
        f"vibrant colors, manga style, action manga, "
        f"professional shading, detailed face, expressive eyes, "
        f"dynamic composition"
    )

    # SQUARE generation 1024x1024 — SDXL's native training aspect.
    # Non-square panel aspects (832x1216 etc.) caused tiled rainbow noise
    # in both Pony and Animagine. Crop to panel aspect post-render.
    w, h = 1024, 1024

    wf = {
        "ckpt":   {"class_type": "CheckpointLoaderSimple",
                   "inputs": {"ckpt_name": CKPT}},
        "pos":    {"class_type": "CLIPTextEncode",
                   "inputs": {"text": prompt, "clip": ["ckpt", 1]}},
        "neg":    {"class_type": "CLIPTextEncode",
                   "inputs": {"text": PONY_NEG, "clip": ["ckpt", 1]}},
        "lat":    {"class_type": "EmptyLatentImage",
                   "inputs": {"width": w, "height": h, "batch_size": 1}},
        "ks":     {"class_type": "KSampler",
                   "inputs": {"seed": (page_seed or 42) + panel_idx,
                               "steps": int(os.environ.get("V8_CHAR_STEPS", "24")),
                               "cfg": 7.0,
                               "sampler_name": "dpmpp_2m_sde",
                               "scheduler": "karras", "denoise": 1.0,
                               "model": ["ckpt", 0], "positive": ["pos", 0],
                               "negative": ["neg", 0], "latent_image": ["lat", 0]}},
        "dec":    {"class_type": "VAEDecode",
                   "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        "save":   {"class_type": "SaveImage",
                   "inputs": {"filename_prefix": f"v8-char-{char.lower()}-p{panel_idx:02d}",
                               "images": ["dec", 0]}},
    }
    _, body = _http("POST", "/prompt", json.dumps({"prompt": wf}).encode())
    pid = json.loads(body).get("prompt_id")
    if not pid: return None

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
                        out_path = Path(f"/tmp/v8-char-pg-p{panel_idx:02d}.png")
                        out_path.write_bytes(data)
                        # Crop 1024×1024 square to target panel aspect.
                        # Preserves SDXL's native quality.
                        _crop_to_panel_aspect(out_path, panel_w, panel_h)
                        return out_path
            return None
        time.sleep(3)
    return None


def _crop_to_panel_aspect(image_path: Path, panel_w: int, panel_h: int) -> None:
    """Crop center of SDXL square output to match panel aspect.

    SDXL native 1024×1024 → crop to e.g. 600×400 panel aspect by taking
    the center-aligned slice (preserves face/composition focus).
    """
    im = Image.open(image_path).convert("RGB")
    sw, sh = im.size
    target_ratio = panel_w / panel_h
    src_ratio = sw / sh
    if abs(target_ratio - src_ratio) < 0.01:
        return  # already matches
    if src_ratio > target_ratio:
        # Source is wider; crop horizontally
        new_w = int(sh * target_ratio)
        x0 = (sw - new_w) // 2
        im_crop = im.crop((x0, 0, x0 + new_w, sh))
    else:
        # Source is taller; crop vertically (keep top 2/3 for character heads)
        new_h = int(sw / target_ratio)
        y0 = max(0, (sh - new_h) // 3)   # bias toward top
        im_crop = im.crop((0, y0, sw, y0 + new_h))
    im_crop.save(image_path)


# Color scene prompts — full environment with vehicles/atmosphere/lighting
SCENE_COLOR_PROMPTS = {
    "yuto-bedroom":     "japanese teenage boy bedroom interior, single bed with blanket, "
                         "wooden study desk with smartphone and books, "
                         "wall posters and framed photos, window with curtain, evening orange light, "
                         "wooden floor, bookshelf, study lamp warm glow, "
                         "vibrant colors, anime background",
    "classroom":        "japanese high school classroom interior, "
                         "rows of wooden student desks with chairs, "
                         "blackboard with chalk writing, west window with afternoon sunlight, "
                         "school bag on desk, posters on wall, "
                         "warm color palette, anime background, detailed environment",
    "school-hierarchy": "japanese high school classroom, wooden desks, blackboard, "
                         "west window sunlight, hallway visible through door, "
                         "warm afternoon lighting, anime style, vibrant",
    "rens-room":        "dark hacker room interior, multi-monitor wall glowing blue, "
                         "research pinboard, gaming chair, dim purple lighting, "
                         "cables, server rack, cyber atmosphere, "
                         "neon highlights, anime background",
    "neis-room":        "teenage girl bedroom interior, vanity mirror, wardrobe, "
                         "single bed with pink sheets, fashion posters, "
                         "large window with daylight, makeup table, clothes rack, "
                         "warm pastel colors, anime background",
    "city-street":      "japanese residential street, paved sidewalk, "
                         "low concrete wall, residential houses, telephone poles, "
                         "vending machine, bicycle parked, afternoon golden hour light, "
                         "vibrant colors, anime background, detailed",
}


def render_bg_color(scene_slug: str, panel_w: int, panel_h: int,
                     out_path: Path, page_seed: int = 42) -> Path | None:
    """Color SDXL bg render via Pony Diffusion V6 XL — no monochrome."""
    prompt = SCENE_COLOR_PROMPTS.get(scene_slug,
        "anime background, detailed environment, vibrant colors")
    full_prompt = PONY_QUALITY_PREFIX + prompt

    # SQUARE generation — see render_character_color for rationale.
    w, h = 1024, 1024

    wf = {
        "ckpt":  {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": CKPT}},
        "pos":   {"class_type": "CLIPTextEncode",
                  "inputs": {"text": full_prompt, "clip": ["ckpt", 1]}},
        "neg":   {"class_type": "CLIPTextEncode",
                  "inputs": {"text": PONY_NEG + ", 1girl, 1boy, person, character",
                              "clip": ["ckpt", 1]}},
        "lat":   {"class_type": "EmptyLatentImage",
                  "inputs": {"width": w, "height": h, "batch_size": 1}},
        "ks":    {"class_type": "KSampler",
                  "inputs": {"seed": (page_seed or 42),
                              "steps": 20, "cfg": 7.0,
                              "sampler_name": "dpmpp_2m_sde",
                              "scheduler": "karras", "denoise": 1.0,
                              "model": ["ckpt", 0], "positive": ["pos", 0],
                              "negative": ["neg", 0], "latent_image": ["lat", 0]}},
        "dec":   {"class_type": "VAEDecode",
                  "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        "save":  {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": f"v8-bg-{scene_slug}",
                              "images": ["dec", 0]}},
    }
    _, body = _http("POST", "/prompt", json.dumps({"prompt": wf}).encode())
    pid = json.loads(body).get("prompt_id")
    if not pid: return None

    # pre-write white fallback so SDXL failure doesn't leave stale
    Image.new("RGB", (panel_w, panel_h), "white").save(out_path)

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
                        out_path.write_bytes(data)
                        # Crop square bg to panel aspect
                        _crop_to_panel_aspect(out_path, panel_w, panel_h)
                        return out_path
            return None
        time.sleep(3)
    return None


def extract_character_alpha_color(image_path: Path, out_path: Path = None,
                                    bg_threshold: int = 240) -> Path:
    """Color version of alpha extraction — flood-fill from corners.

    For color images, identify exterior bg (not necessarily white — could
    be any uniform region) via corner flood-fill on similarity to corner
    pixel color.
    """
    im = Image.open(image_path).convert("RGBA")
    w, h = im.size
    arr = np.asarray(im).copy()
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # Sample 4 corner colors
    corners = [(0, 0), (0, w-1), (h-1, 0), (h-1, w-1)]
    # Pick the most common corner color (likely bg)
    cc = arr[corners[0][0], corners[0][1], :3]
    # Tolerance-based mask: pixels within tolerance of corner color
    tol = 30
    bg_mask = ((np.abs(r.astype(int) - int(cc[0])) < tol) &
                (np.abs(g.astype(int) - int(cc[1])) < tol) &
                (np.abs(b.astype(int) - int(cc[2])) < tol))

    visited = np.zeros_like(bg_mask, dtype=bool)
    from collections import deque
    queue = deque()
    for cy, cx in corners:
        if bg_mask[cy, cx] and not visited[cy, cx]:
            queue.append((cy, cx))
            visited[cy, cx] = True
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < h and 0 <= nx < w and bg_mask[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                queue.append((ny, nx))
    arr[visited, 3] = 0
    Image.fromarray(arr).save(out_path or image_path)
    return out_path or image_path


if __name__ == "__main__":
    # Test: render Yuto in color, sitting on bed in bedroom
    out = render_character_color("Yuto", "sitting_on_bed", "anxious",
                                   "MS", 600, 400, page_seed=12345, panel_idx=1)
    print(f"char: {out}")
    bg = render_bg_color("yuto-bedroom", 1200, 800, Path("/tmp/v8-test-bg.png"), 42)
    print(f"bg:   {bg}")

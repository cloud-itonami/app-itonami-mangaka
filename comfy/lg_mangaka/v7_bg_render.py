"""v7 Stage D — Background standalone render (3 modes).

After characters are placed (Stage C), generate the background as a
separate layer. Three rendering modes per panel:

  realistic: SDXL empty scene (room only, no characters)
  symbolic:  集中線 / screentone fill (PIL generated, action panels)
  mood:      Heavy hatching atmosphere (emotion overlay)

Per-panel mode chosen by tone:
  tense/shock/intense/dramatic → symbolic (集中線, motion lines)
  contemplative/quiet/emotional → realistic (room detail)
  comedic/triumph → light (white bg + light screentone)
"""
from __future__ import annotations
import json, time, urllib.request, urllib.parse, base64
from pathlib import Path
from PIL import Image, ImageDraw
import math
import random

COMFY = "http://192.168.1.22:8188"

SCENE_BG_PROMPTS = {
    # Death Note signature: photo-realistic dense environment objects.
    # Process mining (2026-05-25): jump_background_detail mean 6.0/10
    # because previous prompts were too generic. Each scene now lists
    # 8-12 specific photo-real objects + texture details.
    "yuto-bedroom":     "Japanese teen bedroom interior, "
                         "rumpled single bed with crumpled blanket and wrinkled sheets, "
                         "wooden study desk with stacked textbooks scattered papers and pencils, "
                         "smartphone with cracked screen on desk, "
                         "wall covered in punk band posters and movie photos and concert tickets, "
                         "window with half-drawn curtain showing nighttime cityscape, "
                         "polished wood plank floor with visible grain, "
                         "overflowing bookshelf with disorganized books, "
                         "task lamp casting hard shadows, "
                         "wired alarm clock on nightstand, gaming controller on floor, "
                         "Death Note photo-realistic detail, manga ink style",
    "classroom":        "Japanese high school classroom 3-B interior, "
                         "rows of wooden student desks with metal frames and individual chairs, "
                         "chipped green blackboard with chalk equations and dust eraser, "
                         "tall west window with mullion grid showing tree-lined courtyard, "
                         "school bag hanging from desk hook, lunch box on top, "
                         "bulletin board with class schedule and yearbook photos, "
                         "fluorescent ceiling lights, polished linoleum floor, "
                         "wall clock showing afternoon, world map poster, "
                         "Death Note photo-realistic detail, manga ink style",
    "school-hierarchy": "Japanese high school 3-storey building interior corridor view, "
                         "wooden lockers lining hallway, classroom door open, "
                         "students passing through corridor in background blur, "
                         "polished wood floor, glass case with trophies, "
                         "afternoon sunlight through tall windows, "
                         "bulletin board, fire extinguisher mounted on wall, "
                         "Death Note photo-realistic detail, manga ink style",
    "rens-room":        "hacker basement room interior, "
                         "wall of 6 monitors showing code and surveillance feeds, "
                         "cables running across ceiling, "
                         "vintage research corkboard with red string connecting photos, "
                         "ergonomic gaming chair with worn leather, "
                         "server rack with blinking LEDs, "
                         "dim purple LED strip lighting, energy drink cans on desk, "
                         "papers and printouts scattered, mechanical keyboard, "
                         "noise-canceling headphones on desk, "
                         "Death Note photo-realistic detail, manga ink style, cyber atmosphere",
    "neis-room":        "teenage girl bedroom interior, "
                         "tall mirror with sticker frame, makeup table covered in cosmetics bottles, "
                         "wardrobe with clothes hanging out, "
                         "single bed with floral comforter and stuffed animals, "
                         "K-pop poster wall, large window with morning sunlight, "
                         "vanity table with hair accessories scattered, "
                         "round rug, jewelry hung on wall hooks, "
                         "books stacked on floor, study desk with laptop, "
                         "Death Note photo-realistic detail, manga ink style",
    "city-street":      "Japanese residential neighborhood street at golden hour, "
                         "narrow paved sidewalk with manhole covers and curb markings, "
                         "low concrete block wall with metal fence on top, "
                         "two-storey wooden houses with sliding doors and tiled roofs, "
                         "concrete telephone pole with tangled wires, "
                         "Coca-Cola vending machine glowing with internal light, "
                         "old bicycle leaning against wall, "
                         "potted plant on doorstep, mailbox with kanji, "
                         "Death Note photo-realistic detail, manga ink style, "
                         "intricate environmental texture",
}


def _http(method, path, body=None):
    headers = {"content-type": "application/json"} if body else {}
    req = urllib.request.Request(f"{COMFY}{path}", data=body, method=method,
                                  headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read()


def pick_bg_mode(tone: str) -> str:
    """Per-panel mode based on tone."""
    tone = (tone or "").lower()
    if any(t in tone for t in ["shock", "shout", "intense", "dramatic", "tense"]):
        return "symbolic"
    if any(t in tone for t in ["ominous", "mood", "anxious"]):
        return "mood"
    return "realistic"


def render_realistic_bg(scene_slug: str, panel_w: int, panel_h: int,
                         out_path: Path, page_seed: int = 42,
                         visual_hint: str = "") -> Path:
    """SDXL empty-scene render (no characters).

    visual_hint: panel-specific scene description from manifest['visual'].
    Adds lighting/time-of-day/prop context Gemma checks against.
    """
    prompt = SCENE_BG_PROMPTS.get(scene_slug,
        "empty room interior, manga ink style, NO people")
    # Extract first 200 chars of visual hint to lift manifest_window_check
    visual_cue = f", {visual_hint[:200]}" if visual_hint else ""
    if panel_w >= panel_h:
        w, h = 1216, max(832, (1216 * panel_h // panel_w // 64) * 64)
    else:
        h, w = 1216, max(832, (1216 * panel_w // panel_h // 64) * 64)
    w = max(64, (w // 64) * 64); h = max(64, (h // 64) * 64)

    wf = {
        "ckpt":  {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
        "pos":   {"class_type": "CLIPTextEncode",
                  "inputs": {"text": f"high-quality manga panel background, {prompt}{visual_cue}, "
                                       f"sharp black ink lines, monochrome, "
                                       f"detailed environment, panel borders", "clip": ["ckpt", 1]}},
        # NEG: suppress people but keep objects/furniture. Compared to the
        # prior over-broad NEG (which killed bedroom detail), this only
        # tokens-out humans, leaving "desk/chair/lamp/window/poster" intact.
        "neg":   {"class_type": "CLIPTextEncode",
                  "inputs": {"text": "1girl, 1boy, person, people, character, "
                                       "human figure, silhouette of person, face, "
                                       "child, woman, man, student standing, "
                                       "color, watercolor, photograph, 3d render, blurry",
                              "clip": ["ckpt", 1]}},
        "lat":   {"class_type": "EmptyLatentImage",
                  "inputs": {"width": w, "height": h, "batch_size": 1}},
        "ks":    {"class_type": "KSampler",
                  "inputs": {"seed": (page_seed or 42),
                              "steps": 22, "cfg": 5.5,
                              "sampler_name": "dpmpp_2m_sde",
                              "scheduler": "karras", "denoise": 1.0,
                              "model": ["ckpt", 0], "positive": ["pos", 0],
                              "negative": ["neg", 0], "latent_image": ["lat", 0]}},
        "dec":   {"class_type": "VAEDecode",
                  "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        "save":  {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": f"v7-bg-{scene_slug}",
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
                        out_path.write_bytes(data)
                        return out_path
            return None
        time.sleep(3)
    return None


def render_symbolic_bg(panel_w: int, panel_h: int, out_path: Path,
                        center_x: float = 0.5, center_y: float = 0.5,
                        ray_count: int = 36, gap_pct: float = 0.10) -> Path:
    """集中線 (speed lines / impact rays) — pure PIL drawing.

    center_x/y: 0-1 panel-relative center of radial burst
    ray_count: number of rays
    gap_pct: white area in center (no rays inside this radius)
    """
    im = Image.new("RGB", (panel_w, panel_h), "white")
    draw = ImageDraw.Draw(im)
    cx = panel_w * center_x
    cy = panel_h * center_y
    inner_r = min(panel_w, panel_h) * gap_pct
    outer_r = max(panel_w, panel_h) * 1.5
    # Draw rays as thin black triangles
    random.seed(int(cx * 1000 + cy))
    for i in range(ray_count):
        base_angle = (2 * math.pi * i) / ray_count
        spread = random.uniform(0.5, 1.5)
        # Triangle apex at inner_r, base at outer_r
        t1 = base_angle - 0.012 * spread
        t2 = base_angle + 0.012 * spread
        x_in = cx + inner_r * math.cos(base_angle)
        y_in = cy + inner_r * math.sin(base_angle)
        x_out1 = cx + outer_r * math.cos(t1)
        y_out1 = cy + outer_r * math.sin(t1)
        x_out2 = cx + outer_r * math.cos(t2)
        y_out2 = cy + outer_r * math.sin(t2)
        draw.polygon([(x_in, y_in), (x_out1, y_out1), (x_out2, y_out2)],
                      fill="black")
    im.save(out_path)
    return out_path


def render_mood_bg(panel_w: int, panel_h: int, out_path: Path,
                    hatch_angle: float = 45.0, hatch_density: float = 0.5) -> Path:
    """Atmospheric heavy hatching background."""
    im = Image.new("RGB", (panel_w, panel_h), "white")
    draw = ImageDraw.Draw(im)
    rad = math.radians(hatch_angle)
    dx = math.cos(rad); dy = math.sin(rad)
    spacing = max(2, int(10 / max(0.1, hatch_density)))
    # Draw parallel hatching lines
    for offset in range(-panel_h, panel_w + panel_h, spacing):
        x0 = offset
        y0 = 0
        x1 = offset + panel_h * dx / dy if abs(dy) > 0.01 else offset
        y1 = panel_h
        draw.line([(x0, y0), (x1, y1)], fill="black", width=1)
    im.save(out_path)
    return out_path


def render_bg(scene_slug: str, panel_w: int, panel_h: int,
               tone: str, out_path: Path, page_seed: int = 42,
               visual_hint: str = "") -> tuple[Path, str]:
    """Dispatch to mode-specific renderer.

    visual_hint: panel-specific scene description from manifest['visual'].
    Routes to render_realistic_bg for SDXL panel-specific lighting/props.
    """
    Image.new("RGB", (panel_w, panel_h), "white").save(out_path)

    mode = pick_bg_mode(tone)
    if mode == "symbolic":
        render_symbolic_bg(panel_w, panel_h, out_path)
    elif mode == "mood":
        render_mood_bg(panel_w, panel_h, out_path,
                        hatch_angle=45.0, hatch_density=0.6)
    else:  # realistic
        if "V7_REALISTIC_BG" in __import__("os").environ:
            result = render_realistic_bg(scene_slug, panel_w, panel_h, out_path,
                                          page_seed, visual_hint=visual_hint)
            if result is None:
                print(f"    [bg] SDXL realistic timeout — white fallback for {scene_slug}")
    return out_path, mode


if __name__ == "__main__":
    # Test each mode
    out_dir = Path("/tmp/v7-bg-test")
    out_dir.mkdir(exist_ok=True)
    render_symbolic_bg(600, 400, out_dir / "symbolic.png")
    render_mood_bg(600, 400, out_dir / "mood.png")
    print("OK: symbolic + mood backgrounds generated")
    print(f"  {out_dir}")

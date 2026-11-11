"""arc 0-1 page renderer v3.1 — 1-panel-per-submit + composite step.

The single-workflow v3 approach hit a workload ceiling on the host
(7 panels × 21-node sub-graph = 136-node workflow ran > 30 min before
needing kill). Split into:

  Step 1: per-panel workflow (~20 nodes each)
          → KSampler → VAEDecode → SaveImage("panel-pNN.png")

  Step 2: composite workflow
          PageCanvas → LoadImage × N → PanelPaste × N → SFX → Bubbles → SaveImage

Each step is small and resettable; ComfyUI frees memory between panels.

Cinematic / manifest mapping unchanged from v3.0:
  scene = SCENE_MAPPING[pageNum]
  shot  = SHOT_MAPPING[panel.shot]
  angle = ANGLE_MAPPING by tone keyword
  pose  = POSE_FROM_CONTEXT by visual + sceneSubject keyword
  emot  = EMOTION_MAPPING by tone keyword
  rule  = alternates for visual rhythm
"""
from __future__ import annotations
import hashlib, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

COMFY = "http://192.168.1.22:8188"
# Note: mangaka project was migrated to etzhayyim-root on 2026-05-22; data
# files (manifest + character profiles) are now under _archive/. Custom
# nodes + USD scenes are still in 60-apps/ at the time of this commit
# (inconsistent migration state — to be cleaned in a follow-up).
_BASE = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp")
for cand in [
    _BASE / "60-apps/ai-gftd-project-mangaka/data/ghosthacker",
    _BASE / "60-apps/ai-gftd-project-mangaka/data/ghosthacker",
]:
    if (cand / "resources/episodes/arc0-1-origin/image-gen-manifest.json").exists():
        ROOT = cand
        break
else:
    raise FileNotFoundError("ghosthacker data not found in any known location")
EPISODE = ROOT / "resources/episodes/arc0-1-origin"
CHARS = ROOT / "resources/characters"

PAGE_W, PAGE_H = 1280, 1817
MARGIN, GUTTER = 40, 16
SIZE_UNIT = {"small": 1, "medium": 2, "large": 3, "spread": 6}

SCENE_MAPPING = {
    **{n: "yuto-bedroom" for n in [0, 4, 5, 8, 11, 17, 18, 25, 28, 38]},
    **{n: "classroom" for n in [1, 2, 10, 14, 15, 16, 22, 23, 26, 30, 34, 36, 39, 40, 41, 42, 43, 44, 45]},
    **{n: "rens-room" for n in [6, 7, 20, 24, 35]},
    **{n: "city-street" for n in [3, 9, 31]},
    **{n: "akabane-shrine" for n in [32, 33]},
    **{n: "cyberspace" for n in [21, 27, 37]},
    **{n: "yuto-bedroom" for n in [12, 13, 29]},
    **{n: "classroom" for n in [19]},
}

SCENE_PELVIS = {
    "yuto-bedroom":     (3.0, 0.50, 2.0),
    "classroom":        (4.0, 0.50, 3.5),
    "rens-room":        (2.8, 0.50, 2.5),
    "city-street":      (5.0, 0.90, 12.0),
    "akabane-shrine":   (7.5, 0.90, 3.5),
    "cyberspace":       (5.0, 1.50, 4.0),
}

SHOT_MAPPING = {
    "extreme close up":"ECU", "close up":"CU", "medium close up":"MS",
    "medium":"MS", "medium long shot":"MLS", "long shot":"LS",
    "wide":"LS", "wide shot":"LS", "extreme long shot":"ELS",
    "establishing":"ELS", "pov":"POV", "ots":"OTS",
    "over the shoulder":"OTS", "two shot":"TWO", "insert":"INSERT",
}

ANGLE_MAPPING = {
    "intense":"low", "dramatic":"low", "triumph":"low",
    "ominous":"high", "melancholic":"high",
    "contemplative":"eye_level", "emotional":"eye_level", "tender":"eye_level",
    "shock":"dutch_R",
}

EMOTION_MAPPING = {
    "anxious":"anxious", "tense":"anxious", "nervous":"anxious",
    "fear":"fearful", "ominous":"fearful",
    "shock":"shocked", "surprise":"shocked",
    "sad":"sad", "melancholic":"sad", "emotional":"sad",
    "angry":"angry",
    "intense":"determined", "determined":"determined",
    "dramatic":"shocked",
    "joyful":"joyful", "triumph":"joyful", "happy":"joyful",
    "contemplative":"contemplative", "quiet":"contemplative",
    "tender":"embarrassed",
}

POSE_FROM_CONTEXT = {
    "sleeping_at_desk":      ["sleep", "dozing", "head down"],
    "looking_at_phone":      ["smartphone", "phone screen", "looking at phone", "scrolling"],
    "anxious_at_desk":       ["desk", "sitting", "seated", "anxious"],
    "talking_animated":      ["talking", "speaking", "shouting", "gesture", "calling out"],
    "walking_running":       ["walking", "running", "rushing", "approaching"],
    "standing_facing_camera":[],
}

CHAR_LORA = {"Yuto":"yuto_persona.safetensors","Ren":"ren_persona.safetensors","Nei":"nei_persona.safetensors"}
_KATAKANA = {"Akira":"アキラ","Yuto":"ユウト","Ren":"レン","Nei":"ネイ","Mei":"メイ","Saki":"サキ","nue":"ヌエ","Chise":"チセ"}
def latinize(s):
    for en,kat in _KATAKANA.items(): s = s.replace(en, kat)
    return s


def pick_shot(panel):
    s = (panel.get("shot") or "").lower().strip()
    return SHOT_MAPPING.get(s, "MS")

def pick_angle(panel):
    tone = (panel.get("tone") or "").lower()
    for k, v in ANGLE_MAPPING.items():
        if k in tone: return v
    return "eye_level"

def pick_emotion(panel):
    text = (panel.get("tone") or "").lower() + " " + (panel.get("sceneSubject") or "").lower()
    for k, v in EMOTION_MAPPING.items():
        if k in text: return v
    return "neutral"

def pick_pose(panel):
    text = (panel.get("visual") or "").lower() + " " + (panel.get("sceneSubject") or "").lower()
    for pose, keys in POSE_FROM_CONTEXT.items():
        for k in keys:
            if k in text: return pose
    return "standing_facing_camera"

def pick_rule(idx):
    if idx == 1: return "center"
    if idx % 3 == 0: return "thirds_R"
    if idx % 3 == 1: return "thirds_L"
    return "center"


def _http(method, path, body=None, headers=None):
    req = urllib.request.Request(f"{COMFY}{path}", data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read()

def submit(wf):
    s, b = _http("POST", "/prompt", json.dumps({"prompt": wf}).encode(), {"content-type": "application/json"})
    j = json.loads(b)
    if j.get("node_errors"):
        print(f"  node_errors: {json.dumps(j['node_errors'], indent=2)[:1500]}")
    return j.get("prompt_id")

def wait_for(pid, timeout=1200):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s, b = _http("GET", f"/history/{pid}")
        e = (json.loads(b) or {}).get(pid)
        if e and (e.get("outputs") or e.get("status", {}).get("status_str") in ("error", "success")):
            return e
        time.sleep(5)
    return {}

def fetch_view(filename, subfolder=""):
    q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
    s, b = _http("GET", f"/view?{q}")
    return b


def char_tag_prompt(name):
    pfile = CHARS / name / "profile.jsonld"
    if not pfile.exists(): return ""
    p = json.loads(pfile.read_text())
    a = p.get("gh:appearance", {})
    gender = "1girl" if "female" in (a.get("gh:face", "").lower()) else "1boy"
    return ", ".join([
        "anime illustration", f"{name.lower()}_persona", gender,
        f"{p.get('schema:age', 17)} year old",
        a.get("gh:face", ""), a.get("gh:hair", ""), a.get("gh:eyes", ""),
    ]).replace(", , ", ", ")


STYLE = ("(monochrome inked manga panel:1.25), (sharp black ink lines:1.2), screentone, "
         "(high contrast B&W:1.2), cinematic chiaroscuro, shonen-jump style, "
         "detailed background, environment visible, professional manga page")

NEG = ("low quality, worst quality, blurry, deformed, color illustration, watercolor, "
       "sepia, cyan tint, multiple people, repeated faces, photograph, 3d render")


def compute_layout(panels):
    rows = {}
    for p in panels:
        r = p.get("panelLayout", {}).get("gh:row") or 1
        rows.setdefault(int(r), []).append(p)
    sorted_rows = sorted(rows.keys())
    avail_h = PAGE_H - 2 * MARGIN - (len(sorted_rows) - 1) * GUTTER
    row_h = avail_h // len(sorted_rows)
    layout = []
    cur_y = MARGIN
    for r in sorted_rows:
        row_panels = sorted(rows[r], key=lambda p: p.get("panelLayout", {}).get("gh:readingOrder", p["panelIndex"]))
        units = [SIZE_UNIT.get(p.get("panelLayout", {}).get("gh:size", "medium"), 2) for p in row_panels]
        total_units = sum(units)
        avail_w = PAGE_W - 2 * MARGIN - (len(row_panels) - 1) * GUTTER
        unit_w = avail_w / total_units
        cur_x = PAGE_W - MARGIN
        for i, p in enumerate(row_panels):
            w = int(round(units[i] * unit_w))
            cur_x -= w
            layout.append({"idx": p["panelIndex"], "x": cur_x, "y": cur_y, "w": w, "h": row_h, "panel": p})
            if i < len(row_panels) - 1: cur_x -= GUTTER
        cur_y += row_h + GUTTER
    layout.sort(key=lambda s: s["idx"])
    return layout


def build_panel_workflow(page_num, panel, scene_slug, pelvis):
    """Single-panel workflow — ~22 nodes. Returns wf + output filename prefix."""
    idx = panel["panelIndex"]
    focused_chars = [c for c in (panel.get("focusedCharacters") or []) if c in CHAR_LORA]
    focal = focused_chars[0] if focused_chars else None
    shot = pick_shot(panel)
    angle = pick_angle(panel)
    rule = pick_rule(idx)
    emotion = pick_emotion(panel)
    pose_name = pick_pose(panel)
    char_tags = char_tag_prompt(focal) if focal else ""
    visual = panel.get("visual", "")[:180]
    base = f"{char_tags}, {shot.lower()} shot, {visual}, {STYLE}".replace(", , ", ", ")
    filename_prefix = f"v3p{page_num:02d}p{idx:02d}"
    wf = {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"}},
        "cnet": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "controlnet-union-sdxl-promax.safetensors"}},
        "scene": {"class_type": "MangakaUSDLoader", "inputs": {"scene_name": scene_slug}},
        "light": {"class_type": "MangakaUSDLight", "inputs": {"scene": ["scene", 0]}},
        "mat":   {"class_type": "MangakaUSDMaterial", "inputs": {"scene": ["scene", 0]}},
        "pose":  {"class_type": "MangakaPoseFromLibrary", "inputs": {
                     "pose_name": pose_name, "pelvis_x": pelvis[0], "pelvis_y": pelvis[1], "pelvis_z": pelvis[2], "scale": 1.0}},
        "shot":  {"class_type": "MangakaShotComposition", "inputs": {
                     "subject_pose": ["pose", 0], "shot_type": shot, "angle": angle, "rule": rule,
                     "subject_yaw_deg": -90.0, "width": 1216, "height": 832}},
        "cam":   {"class_type": "MangakaCameraViewFromParams", "inputs": {
                     "scene": ["scene", 0], "camera_params": ["shot", 0], "render_resolution": 608}},
        "proj":  {"class_type": "MangakaProjectPose", "inputs": {"pose": ["pose", 0], "camera": ["cam", 2]}},
        "em":    {"class_type": "MangakaCharacterEmotion", "inputs": {"emotion": emotion, "intensity": 1.0}},
        "concat1": {"class_type": "MangakaPromptConcat", "inputs": {
                       "base": base, "face_emotion": ["em", 0], "body_modifier": ["em", 1], "extra_suffix": ""}},
        "concat2": {"class_type": "MangakaPromptConcat", "inputs": {
                       "base": ["concat1", 0], "face_emotion": ["light", 0], "body_modifier": ["mat", 0], "extra_suffix": ""}},
    }
    # LoRA chain for focal character only
    model_ref = ["ckpt", 0]
    if focal:
        wf["lora"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                         "model": ["ckpt", 0], "lora_name": CHAR_LORA[focal], "strength_model": 0.55}}
        model_ref = ["lora", 0]
    wf["pos"] = {"class_type": "CLIPTextEncode", "inputs": {"text": ["concat2", 0], "clip": ["ckpt", 1]}}
    wf["neg"] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["ckpt", 1]}}
    wf["cn1"] = {"class_type": "ControlNetApply", "inputs": {"conditioning": ["pos", 0], "control_net": ["cnet", 0], "image": ["cam", 1], "strength": 0.35}}
    wf["cn2"] = {"class_type": "ControlNetApply", "inputs": {"conditioning": ["cn1", 0], "control_net": ["cnet", 0], "image": ["cam", 0], "strength": 0.25}}
    wf["cn3"] = {"class_type": "ControlNetApply", "inputs": {"conditioning": ["cn2", 0], "control_net": ["cnet", 0], "image": ["proj", 0], "strength": 0.65}}
    wf["lat"] = {"class_type": "EmptyLatentImage", "inputs": {"width": 1216, "height": 832, "batch_size": 1}}
    wf["ks"]  = {"class_type": "KSampler", "inputs": {
                     "seed": page_num * 100000 + idx * 1009, "steps": 32, "cfg": 6.5,
                     "sampler_name": "dpmpp_2m_sde", "scheduler": "karras", "denoise": 1.0,
                     "model": model_ref, "positive": ["cn3", 0], "negative": ["neg", 0], "latent_image": ["lat", 0]}}
    wf["dec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}}
    wf["save"]= {"class_type": "SaveImage", "inputs": {"filename_prefix": filename_prefix, "images": ["dec", 0]}}
    return wf, filename_prefix


def build_composite_workflow(page_num, layout, panel_filenames):
    """Final composite workflow — loads each saved panel, pastes into page canvas + bubbles."""
    wf = {
        "canvas": {"class_type": "MangakaPageCanvas", "inputs": {"width": PAGE_W, "height": PAGE_H}},
    }
    page_ref = ["canvas", 0]
    for slot in layout:
        idx = slot["idx"]
        fname = panel_filenames[idx]
        load_id = f"load_p{idx}"
        wf[load_id] = {"class_type": "LoadImage", "inputs": {"image": fname}}
        paste_id = f"paste_p{idx}"
        wf[paste_id] = {"class_type": "MangakaPanelPaste", "inputs": {
                            "page": page_ref, "panel": [load_id, 0],
                            "x": slot["x"], "y": slot["y"], "w": slot["w"], "h": slot["h"], "border_width": 3}}
        page_ref = [paste_id, 0]

    # Bubbles
    for slot in layout:
        p = slot["panel"]
        dlgs = [d for d in (p.get("dialogues") or []) if (d.get("text") or "")]
        cx = slot["x"] + slot["w"] // 2
        cy = slot["y"] + slot["h"] // 2
        is_right = cx >= PAGE_W // 2
        is_top = cy <= PAGE_H // 2
        anchor = ("top" if is_top else "bottom") + "-" + ("right" if is_right else "left")
        tail = ("down" if is_top else "up") + "-" + ("left" if is_right else "right")
        for di, d in enumerate(dlgs):
            text = latinize((d.get("text") or "")[:24])
            cur_anchor = anchor
            if di > 0 and "top" in anchor: cur_anchor = anchor.replace("top", "bottom")
            bub_id = f"bub_p{slot['idx']}_{di}"
            wf[bub_id] = {"class_type": "MangakaMangaBubble", "inputs": {
                              "image": page_ref, "text": text,
                              "panel_x": slot["x"], "panel_y": slot["y"], "panel_w": slot["w"], "panel_h": slot["h"],
                              "anchor": cur_anchor, "tail_dir": tail, "tail_length": 16,
                              "width": 64, "min_height": 250, "font_size": 28, "padding": 14,
                              "vertical": True, "style": "normal", "outline_width": 4, "overflow": 6}}
            page_ref = [bub_id, 0]

    wf["save"] = {"class_type": "SaveImage", "inputs": {
                      "filename_prefix": f"mangaka-page-arc01-v3-p{page_num:02d}", "images": page_ref}}
    return wf


def render_page(page_num):
    print(f"\n=== Page {page_num} (v3.1) ===")
    manifest = json.loads((EPISODE / "image-gen-manifest.json").read_text())
    panels = sorted([p for p in manifest["panels"] if p["pageNum"] == page_num], key=lambda p: p["panelIndex"])
    if not panels:
        raise ValueError(f"no panels for page {page_num}")
    layout = compute_layout(panels)
    scene_slug = SCENE_MAPPING.get(page_num, "yuto-bedroom")
    pelvis = SCENE_PELVIS[scene_slug]
    print(f"  scene={scene_slug}, {len(panels)} panels")
    # ───────────────────── Step 1: per-panel render ─────────────────────
    panel_filenames = {}
    for slot in layout:
        idx = slot["idx"]; p = slot["panel"]
        wf, prefix = build_panel_workflow(page_num, p, scene_slug, pelvis)
        print(f"  panel {idx}: shot={pick_shot(p)} angle={pick_angle(p)} pose={pick_pose(p)} emotion={pick_emotion(p)} chars={p.get('focusedCharacters') or []}")
        pid = submit(wf)
        if not pid:
            print(f"    SUBMIT FAIL")
            return None
        t0 = time.monotonic()
        e = wait_for(pid, timeout=600)
        el = time.monotonic() - t0
        s = (e.get("status") or {}).get("status_str")
        outs = e.get("outputs") or {}
        if s == "error":
            print(f"    FAIL ({el:.0f}s)")
            for m in (e.get("status", {}).get("messages") or [])[-3:]:
                print(f"      {m}")
            return None
        # Save panel image — outs may be empty when ComfyUI cached the
        # whole prompt; fall back to the inferred filename pattern.
        got = False
        for nid, out in outs.items():
            for im in out.get("images", []):
                fname = im["filename"]
                panel_filenames[idx] = fname
                data = fetch_view(fname, im.get("subfolder", ""))
                Path(f"/tmp/v3-panel-p{page_num:02d}-p{idx:02d}.png").write_bytes(data)
                print(f"    panel {idx} done ({el:.0f}s) -> {fname}")
                got = True
                break
            if got: break
        if not got:
            # Cached-output fallback: predict filename
            fname = f"{prefix}_00001_.png"
            try:
                data = fetch_view(fname, "")
                if data:
                    panel_filenames[idx] = fname
                    Path(f"/tmp/v3-panel-p{page_num:02d}-p{idx:02d}.png").write_bytes(data)
                    print(f"    panel {idx} cached ({el:.0f}s) -> {fname}")
                    got = True
            except Exception as ex:
                print(f"    panel {idx} cached but file fetch failed: {ex}")
        if not got:
            print(f"    FAIL panel {idx}: no output")
            return None

    # ───────────────────── Step 2: composite ─────────────────────
    print(f"  compositing {len(panel_filenames)} panels...")
    comp_wf = build_composite_workflow(page_num, layout, panel_filenames)
    pid = submit(comp_wf)
    if not pid:
        print(f"  COMPOSITE SUBMIT FAIL")
        return None
    t0 = time.monotonic()
    e = wait_for(pid, timeout=300)
    el = time.monotonic() - t0
    outs = e.get("outputs") or {}
    s = (e.get("status") or {}).get("status_str")
    if s == "error" or not outs:
        print(f"  COMPOSITE FAIL ({el:.0f}s)")
        return None
    # Save final page
    for nid, out in outs.items():
        for im in out.get("images", []):
            fname = im["filename"]
            data = fetch_view(fname, im.get("subfolder", ""))
            local = Path(f"/tmp/gh-arc0-1-v3-p{page_num:02d}.png")
            local.write_bytes(data)
            print(f"  composite done ({el:.0f}s) -> {local}")
            return local
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: render-arc01-page-v3.py <page_num>")
        return 1
    pn = int(sys.argv[1])
    render_page(pn)


if __name__ == "__main__":
    sys.exit(main() or 0)

"""v10 panel renderer — single-pass ComfyUI with full panel context.

User: ComfyUI を中心とした生成プロセス. openusd は最後に必要であれば合成.

This module renders ONE panel via ONE SDXL workflow that contains:
  - All characters in panel (focused + ambient)
  - Scene location (manifest visual + scene description)
  - Tone / mood
  - Specific props (smartphone, etc.)
  - Shot type (camera framing)
  - Dialogue context (panel narrative beat)

Output: PNG at panel aspect, single-shot. No separate bg/char compositing.

5 panel pipelines:
  cu_color   - color anime (Animagine XL color, full scene)
  cu_ink     - B&W manga (Animagine XL monochrome, Death Note style)
  cu_color_usd - color + USD bg composite (rare)
  cu_ink_usd   - B&W + USD bg composite (rare)
  cu_action  - emphasized action (motion lines, SFX integrated)

Each pipeline returns a ready-to-composite PNG (panel-aspect).
"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.parse, uuid
from pathlib import Path
from typing import Optional
from PIL import Image
import numpy as np

# 2026-05-26: env-overridable so we can switch hosts without code edit.
# New gad = Ubuntu 192.168.1.23 (replaced Windows 192.168.1.22 after AMD ROCm crash).
COMFY = os.environ.get("COMFY_HOST", "http://192.168.1.23:8188")
COMFY_SSH_HOST = os.environ.get("COMFY_SSH_HOST", "gad@192.168.1.23")
COMFY_SSH_PASS = os.environ.get("COMFY_SSH_PASS", "230803")
CKPT = "animagine-xl-4.0.safetensors"

# Character descriptions per pipeline
CHAR_COLOR = {
    "Yuto":  "1boy, 17 year old japanese teen male, messy black hair, dark eyes, white school shirt, navy slacks, slim build",
    "Ren":   "1boy, 17 year old japanese teen male, dark hair under hoodie, sleepy droopy eyes, oversized grey hoodie",
    "Nei":   "1girl, 16 year old japanese teen female, long platinum blonde hair, blue eyes, navy sailor uniform with red ribbon",
    "Akira": "1boy, 17 year old japanese teen male, short brown hair, mischievous expression, fashionable streetwear",
    "Saki":  "1girl, 16 year old japanese teen female, shoulder-length brown hair, skeptical expression, navy sailor uniform",
}

CHAR_INK = {
    "Yuto":  "1boy, 17yo japanese teen, dark messy black hair, white school shirt, navy slacks, sharp features, manga ink",
    "Ren":   "1boy, 17yo japanese teen, dark hair hood up, droopy eyes, oversized hoodie, slumped posture, manga ink",
    "Nei":   "1girl, 16yo japanese teen, long blonde hair, navy sailor uniform red ribbon, manga ink",
    "Akira": "1boy, 17yo japanese teen, short brown hair, mischievous grin, hoodie, manga ink",
    "Saki":  "1girl, 16yo japanese teen, brown bob hair, deadpan expression, sailor uniform, manga ink",
}

SCENE_COLOR = {
    # Posters/items GENERIC (no branded IP). User 2026-05-25 directive.
    "yuto-bedroom":     "japanese teenage bedroom, single bed, study desk with smartphone, punk band posters, concert ticket pinboard, curtain, wooden floor, evening warm light",
    "classroom":        "japanese high school classroom interior, wooden desks, blackboard, west window, afternoon sunlight",
    "school-hierarchy": "japanese high school classroom interior, desks, blackboard, large window, afternoon light",
    "rens-room":        "dark hacker bedroom, multi-monitor wall, gaming chair, cables, dim purple LED light, server rack",
    "neis-room":        "teenage girl bedroom, vanity mirror, wardrobe, fashion posters, large bright window",
    "city-street":      "japanese residential street, sidewalk, low wall, houses, telephone poles, golden hour",
}

SCENE_INK = {
    # Posters/objects are GENERIC (no Death Note/branded references — user
    # 2026-05-25: "poster とかは death note に寄せないで").
    # Style is "manga ink" / "shonen jump ink" but content avoids IP.
    "yuto-bedroom":     "Japanese teen bedroom interior, single bed with crumpled sheets, wooden study desk with smartphone, wall covered in punk band posters and concert tickets, half-drawn curtain, wood plank floor, warm evening lighting from desk lamp, manga ink style",
    "classroom":        "Japanese high school classroom 3-B interior, rows of wooden student desks with chairs, chipped chalkboard with equations, west window with afternoon daylight, school bag hanging on chair, manga ink style",
    "school-hierarchy": "Japanese high school classroom interior, wooden desks in rows, chalkboard, west window with afternoon sunlight, fluorescent ceiling lights, polished linoleum floor, manga ink style",
    "rens-room":        "dark hacker basement room, multi-monitor wall with code, vintage research corkboard with red string and photos, gaming chair, dim purple LED light, cables across ceiling, manga ink style",
    "neis-room":        "teen girl bedroom interior, vanity mirror with sticker frame, wardrobe with clothes, single bed with floral comforter, K-pop concert posters on wall, large window with morning sunlight, manga ink style",
    "city-street":      "Japanese residential neighborhood street at golden hour, narrow paved sidewalk, low concrete wall with metal fence, two-storey wooden houses, telephone poles with wires, vending machine glowing, bicycle leaning against wall, manga ink style",
}

# Pony-style quality prefix (for color)
QUALITY_COLOR = "masterpiece, best quality, very aesthetic, absurdres, "
# Ink-style quality. Concrete technique tags (screentone / cross-hatching /
# balanced line density) added per the co-scientist quality loop meta-review
# (coscientist_quality.py, best-of-run 88/100): specifying technical artistic
# techniques beats broad style tags ("bold lines", "high impact") for fidelity.
QUALITY_INK = ("high-quality manga panel, sharp black ink lines, monochrome, "
               "screentone shading, cross-hatching, balanced line density, "
               "high-frequency texture, dramatic chiaroscuro, "
               "anatomically correct, clear readable composition, ")  # 94 + iter1/2 meta (anatomy/clarity counters shading clutter)
# Negatives carry style-neutral anatomy/quality guards. Mangled hands + extra
# fingers are the single most common visible SDXL manga defect, so both ink and
# color share the full hand/anatomy set (previously only NEG_COLOR had it).
# `text`/`speech bubble` are intentionally NOT negated — SFX kana is a wanted
# graphic element (jump_benchmark_qa `sfx_text` axis) and bubbles are PIL-composited.
NEG_COLOR = ("lowres, low quality, worst quality, jpeg artifacts, blurry, "
             "bad anatomy, bad hands, extra fingers, fused fingers, missing fingers, "
             "malformed limbs, extra limbs, deformed, mutated, watermark, signature, "
             "2girls, 2boys, twin, group")
NEG_INK = ("low quality, worst quality, jpeg artifacts, blurry, "
           "bad anatomy, bad hands, extra fingers, fused fingers, missing fingers, "
           "malformed limbs, extra limbs, deformed, mutated, watermark, signature, "
           "multiple people, twin, multiple faces, color, watercolor, photograph, "
           "low contrast, flat shading, washed out")  # co-scientist deep run 94/100

# ── theme-driven style switching (data/style-registry.edn) ──────────────────
# When MANGAKA_WORK or MANGAKA_GENRE is set, _build_prompt switches the quality
# prefix / negative / mode to the profile resolved from the style registry
# (作品テーマ -> 作画スタイル). Unset = the hardcoded defaults above (backward
# compatible). resolve() returns {mode, positive, negative, cfg, steps, sampler}.
try:
    from lg_mangaka import style_registry as _styreg
except Exception:  # pragma: no cover
    _styreg = None
_STYLE_WORK = os.environ.get("MANGAKA_WORK", "")
_STYLE_GENRE = os.environ.get("MANGAKA_GENRE", "")


def _style_profile():
    if _styreg is None or not (_STYLE_WORK or _STYLE_GENRE):
        return None
    try:
        return _styreg.resolve(_STYLE_WORK, _STYLE_GENRE)
    except Exception:  # pragma: no cover
        return None

# v11 (2026-05-27/28): style swap at import — witchwatch or shokugeki.
_V11_STYLE = os.environ.get("V11_STYLE", "")
if _V11_STYLE in ("witchwatch", "shokugeki", "ishida", "amano", "togashi"):
    try:
        import sys, importlib.util
        _here = os.path.dirname(__file__)
        _style_file = f"v11_{_V11_STYLE}.py"
        _spec = importlib.util.spec_from_file_location(
            f"v11_{_V11_STYLE}", os.path.join(_here, _style_file))
        _sm = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_sm)
        _sm.patch_module(sys.modules[__name__])
        print(f"[v11] {_V11_STYLE} style profile active")
    except Exception as e:
        print(f"[v11] {_V11_STYLE} patch skipped: {e}")
elif _V11_STYLE == "hybrid":
    # 2026-05-29 STEP A — hybrid: base = Witch Watch (clean line, safer),
    # per-panel Shokugeki battle descriptors injected at prompt build time.
    try:
        import sys, importlib.util
        _here = os.path.dirname(__file__)
        _spec = importlib.util.spec_from_file_location(
            "v11_witchwatch", os.path.join(_here, "v11_witchwatch.py"))
        _sm = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_sm)
        _sm.patch_module(sys.modules[__name__])
        print("[v11] hybrid style profile active (base=witchwatch, +shokugeki for battle panels)")
    except Exception as e:
        print(f"[v11] hybrid patch skipped: {e}")


def _http(method, path, body=None):
    headers = {"content-type": "application/json"} if body else {}
    req = urllib.request.Request(f"{COMFY}{path}", data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read()


def _restart_comfyui_remote() -> bool:
    """SSH into ComfyUI host, restart ComfyUI systemd service.

    Auto-resilience for the recurring ComfyUI freeze pattern.
    Returns True when HTTP responds again, False on failure.
    2026-05-26: switched from Windows scheduled task to Linux systemctl.
    """
    import subprocess
    try:
        subprocess.run([
            "sshpass", "-p", COMFY_SSH_PASS,
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            COMFY_SSH_HOST,
            f"echo {COMFY_SSH_PASS} | sudo -S systemctl restart comfyui"
        ], timeout=30, check=False, capture_output=True)
    except Exception as e:
        print(f"  [comfy-restart] SSH failed: {e}", flush=True)
        return False
    # Wait for HTTP up (max 180s)
    end = time.monotonic() + 180
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(f"{COMFY}/system_stats", timeout=5) as r:
                if b"comfyui_version" in r.read():
                    return True
        except Exception:
            pass
        time.sleep(10)
    return False


def _shot_desc(shot: str, mode: str = "color") -> str:
    s = (shot or "").lower()
    if "extreme close" in s: return "extreme close-up shot, intense detail"
    if "close" in s:          return "close-up shot, head and shoulders"
    if "insert" in s:          return "insert shot, object detail focus"
    if "wide" in s:            return "wide shot, full scene"
    if "long" in s:            return "long shot, full body"
    if "medium" in s:          return "medium shot, waist up"
    return "medium shot"


def _build_prompt(panel: dict, scene_slug: str, pipeline: str) -> tuple[str, str, int, int]:
    """Build prompt + neg + dimensions for given pipeline."""
    focal = panel.get("focusedCharacters") or []
    shot = panel.get("shot", "Medium")
    tone = panel.get("tone", "")
    visual = (panel.get("visual") or "")[:200]

    is_color = pipeline in ("cu_color", "cu_color_usd")
    is_action = pipeline == "cu_action"

    # Theme-driven style override (style-registry.edn); falls back to defaults.
    _prof = _style_profile()
    if _prof and _prof.get("mode"):
        is_color = (_prof["mode"] == "color")

    chars_lib = CHAR_COLOR if is_color else CHAR_INK
    scene_lib = SCENE_COLOR if is_color else SCENE_INK
    quality = QUALITY_COLOR if is_color else QUALITY_INK
    if _prof and _prof.get("positive"):
        quality = _prof["positive"] + ", "

    # Character description
    char_part = ""
    if focal:
        if len(focal) == 1:
            char_part = chars_lib.get(focal[0], "1person") + ", solo, alone, one person"
        else:
            cd = [chars_lib.get(c, "1person") for c in focal[:2]]
            char_part = " AND ".join(cd) + f", {len(focal)} characters"

    scene_part = scene_lib.get(scene_slug, "interior scene")
    shot_part = _shot_desc(shot, "color" if is_color else "ink")
    # 2026-05-30 — STEP F: prefer story-canonical visualNote over generic manifest visual
    canonical_note = (panel.get("_story_visual_note") or "").strip()
    canonical_setting = (panel.get("_story_setting") or "").strip()
    if canonical_note:
        visual_part = f"scene direction: {canonical_note}"
        if canonical_setting:
            visual_part = f"setting: {canonical_setting} | " + visual_part
    elif visual:
        visual_part = f"scene: {visual}"
    else:
        visual_part = ""

    # 2026-05-29 — STEP D: narrative continuity injection
    # precedingBeat / followingBeat from manifest give cross-page emotional bridge.
    # pageTitle gives the scene's overall arc summary.
    # 2026-05-30 — STEP E: story comprehension intent (from Gemma page reading)
    narrative_parts = []
    pre_beat = (panel.get("precedingBeat") or "")[:140]
    fol_beat = (panel.get("followingBeat") or "")[:140]
    page_title = (panel.get("pageTitle") or "")[:80]
    story_summary = (panel.get("_story_summary") or "")[:200]
    panel_intent = (panel.get("_panel_intent") or "")[:120]
    if story_summary:
        narrative_parts.append(f"story beat: {story_summary}")
    if panel_intent:
        narrative_parts.append(f"this panel: {panel_intent}")
    if page_title and not story_summary:
        narrative_parts.append(f"page arc: {page_title}")
    if pre_beat:
        narrative_parts.append(f"continuing from: {pre_beat}")
    if fol_beat:
        narrative_parts.append(f"leading toward: {fol_beat}")

    # Action emphasis
    if is_action:
        quality += "dynamic action, motion lines, speed lines, "

    # v12 (2026-05-30): V11_TAG_ONLY=1 strips descriptive English/Japanese
    # injections so pure Danbooru-tag styles (e.g. togashi) are not diluted.
    # Drops: visual_part (canonical_note/manifest visual prose),
    # narrative_parts (story beat/page arc/continuing-from prose),
    # shot_part (descriptive shot), tone "{tone} mood" (uses bare tone tag).
    _tag_only = os.environ.get("V11_TAG_ONLY") == "1"

    prompt_parts = [quality]
    if not _tag_only and visual_part: prompt_parts.append(visual_part)
    if char_part:   prompt_parts.append(char_part)
    if _tag_only:
        prompt_parts.append(scene_part)
        # v12 (2026-05-30): shot composition tag — drives panel variety
        # (was missing in initial TAG_ONLY → all frontal portraits)
        _shot_tags = globals().get("SHOT_TAGS") or {}
        _shot_part = _shot_tags.get(shot) or _shot_tags.get((shot or "").upper()) or ""
        if _shot_part: prompt_parts.append(_shot_part)
        if tone: prompt_parts.append(tone)
    else:
        prompt_parts.extend([scene_part, shot_part])
        if tone: prompt_parts.append(f"{tone} mood")
        # Inject narrative continuity AFTER scene description so it nudges the
        # emotional tone without dominating the visual prompt.
        prompt_parts.extend(narrative_parts)
    if is_color:
        prompt_parts.append("full color anime illustration, vibrant detail")
    else:
        # 2026-05-27/28/29: V11_STYLE switches between witchwatch / shokugeki / hybrid / default
        # STEP A (2026-05-29): hybrid mode = tone-aware per-panel routing
        _vs = os.environ.get("V11_STYLE", "")
        if _vs == "hybrid":
            # Route style based on this panel's tone/emphasis (NOT page-uniform)
            emph = (panel.get("panelLayout", {}).get("gh:emphasis") or "").lower()
            tone_l = tone.lower()
            # Shokugeki for true battle moments
            if emph in ("impact", "climax") and tone_l in ("action", "tense", "ominous"):
                try:
                    from lg_mangaka import v11_shokugeki as _sm
                    prompt_parts.append(_sm.get_ink_footer())
                except Exception:
                    prompt_parts.append("Death Note ink style, professional manga")
            # Witch Watch for calm / dialogue / contemplative
            elif tone_l in ("quiet", "contemplative", "emotional", "triumph", "curious"):
                try:
                    from lg_mangaka import v11_witchwatch as _sm
                    prompt_parts.append(_sm.get_ink_footer())
                except Exception:
                    prompt_parts.append("Death Note ink style, professional manga")
            # Default to Witch Watch for everything else (safer than Shokugeki)
            else:
                try:
                    from lg_mangaka import v11_witchwatch as _sm
                    prompt_parts.append(_sm.get_ink_footer())
                except Exception:
                    prompt_parts.append("Death Note ink style, professional manga")
        elif _vs in ("witchwatch", "shokugeki", "ishida", "amano"):
            try:
                if _vs == "witchwatch":
                    from lg_mangaka import v11_witchwatch as _sm
                elif _vs == "shokugeki":
                    from lg_mangaka import v11_shokugeki as _sm
                elif _vs == "ishida":
                    from lg_mangaka import v11_ishida as _sm
                else:
                    from lg_mangaka import v11_amano as _sm
                prompt_parts.append(_sm.get_ink_footer())
            except Exception:
                prompt_parts.append("Death Note ink style, professional manga")
        elif _vs == "togashi":
            # Pure-tag style — footer is already in QUALITY_INK; no descriptive footer
            pass
        else:
            prompt_parts.append("Death Note ink style, professional manga")

    # v11 (2026-05-28) Battle style switch: action/impact panels need INTENSITY.
    # Witch Watch soft style + action = doesn't feel like a fight. Inject
    # battle-specific descriptors when emphasis=impact and tone=action/tense.
    # (Skipped in V11_TAG_ONLY mode — pure-tag styles use only tags.)
    emph = (panel.get("panelLayout", {}).get("gh:emphasis") or "").lower()
    if not _tag_only and emph in ("impact", "climax") and tone in ("action", "tense", "ominous"):
        prompt_parts.append(
            "intense shonen battle scene, dynamic radial speed lines, "
            "strong action perspective, dramatic motion blur, dramatic ink "
            "weight, heavy black contrast at action peaks, manga action pose"
        )

    prompt = ", ".join(prompt_parts)
    neg = NEG_COLOR if is_color else NEG_INK
    if _prof and _prof.get("negative"):
        neg = _prof["negative"]

    # 1024×1024 native SDXL aspect
    w, h = 1024, 1024
    return prompt, neg, w, h


def _crop_to_panel(image_path: Path, panel_w: int, panel_h: int) -> None:
    """Crop 1024 square to panel aspect, top-bias for character faces."""
    im = Image.open(image_path).convert("RGB")
    sw, sh = im.size
    target_ratio = panel_w / panel_h
    src_ratio = sw / sh
    if abs(target_ratio - src_ratio) < 0.01:
        return
    if src_ratio > target_ratio:
        new_w = int(sh * target_ratio)
        x0 = (sw - new_w) // 2
        im_crop = im.crop((x0, 0, x0 + new_w, sh))
    else:
        new_h = int(sw / target_ratio)
        y0 = max(0, (sh - new_h) // 3)
        im_crop = im.crop((0, y0, sw, y0 + new_h))
    im_crop.save(image_path)


def render_v10_panel(panel: dict, scene_slug: str, panel_w: int, panel_h: int,
                      pipeline: str, page_seed: int) -> Optional[Path]:
    """v10 single-pass SDXL render for one panel.

    Returns: Path to PNG at panel aspect, or None on failure.
    """
    idx = panel.get("panelIndex", 0)
    prompt, neg, w, h = _build_prompt(panel, scene_slug, pipeline)
    steps = int(os.environ.get("V10_STEPS", "24"))

    # v13 (2026-05-30 evening): MANGAKA_BACKEND=comfyui routes to Modal H100
    # ComfyUI deployment (mangaka-comfyui). Uses panel_hq_workflow which has
    # IPAdapter FaceID + ControlNet Union pre-wired. Character ref image is
    # loaded from data/ghosthacker/resources/character-faces/<name>-face.png
    # and base64-encoded into the refs param.
    if os.environ.get("MANGAKA_BACKEND") == "comfyui":
        try:
            import base64 as _b64, modal as _modal
            from lg_mangaka import comfy_workflows as _cw

            # v13.5 Page-first + per-panel selective edit (2026-05-30 evening):
            # V13_PAGE_FIRST=1 → default clean Danbooru-tag SDXL for all panels
            # V13_FIX_PANELS=2,4,7 → these panel indices get IPA Plus + CN edit
            # (others use clean). Goal: unified page style + targeted fixes.
            if os.environ.get("V13_PAGE_FIRST") == "1":
                fix_panels = set()
                fix_env = os.environ.get("V13_FIX_PANELS", "")
                if fix_env:
                    fix_panels = {int(x.strip()) for x in fix_env.split(",") if x.strip()}
                if idx not in fix_panels:
                    # Clean path (page-first default)
                    wf = _cw.panel_clean_workflow(
                        panel_rkey=f"p{idx:02d}-base",
                        positive=prompt, negative=neg,
                        seed=(page_seed or 42) + idx * 17,
                        width=panel_w, height=panel_h,
                        steps=int(os.environ.get("V10_STEPS","28")),
                        cfg=7.0, ckpt="animagine-xl-4.0.safetensors",
                    )
                    run = _modal.Function.from_name("mangaka-comfyui","run_workflow")
                    png = run.remote(wf, refs=None)
                    out_path = Path(f"/tmp/v10-panel-p{idx:02d}.png")
                    out_path.write_bytes(png)
                    return out_path
                # else: fall through to IPA Plus path for fix panels

            # v13 isolation: V13_IPA_PLUS_ONLY=1 → IPAdapter Plus alone (no FaceID/LoRA)
            if os.environ.get("V13_IPA_PLUS_ONLY") == "1" or os.environ.get("V13_PAGE_FIRST") == "1":
                CHARS = {"yuto":"yuto-face.png","ren":"ren-face.png","nei":"nei-face.png",
                          "akira":"akira-face.png","saki":"saki-face.png"}
                focal_chars = panel.get("focusedCharacters") or []
                primary = next((c.lower() for c in focal_chars if c.lower() in CHARS), None)
                ref_filename = CHARS.get(primary, "yuto-face.png")
                ref_path = ("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/"
                             "60-apps/ai-gftd-project-mangaka/data/ghosthacker/"
                             f"resources/character-faces/{ref_filename}")
                if not os.path.exists(ref_path):
                    ref_filename = "yuto-face.png"
                    ref_path = ref_path.rsplit("/",1)[0] + f"/{ref_filename}"
                with open(ref_path, "rb") as f:
                    ref_b64 = _b64.b64encode(f.read()).decode()
                wf = _cw.panel_ipa_plus_workflow(
                    panel_rkey=f"p{idx:02d}",
                    positive=prompt,
                    negative=neg,
                    reference_image_filename=ref_filename,
                    seed=(page_seed or 42) + idx * 17,
                    width=panel_w, height=panel_h,
                    steps=int(os.environ.get("V10_STEPS","28")),
                    cfg=7.0,
                    ckpt="animagine-xl-4.0.safetensors",
                    ipa_weight=float(os.environ.get("V13_IPA_WEIGHT","0.5")),
                )
                run = _modal.Function.from_name("mangaka-comfyui","run_workflow")
                png = run.remote(wf, refs={ref_filename: ref_b64})
                out_path = Path(f"/tmp/v10-panel-p{idx:02d}.png")
                out_path.write_bytes(png)
                return out_path

            # v13 isolation: V13_NO_IPA=1 → use panel_clean_workflow
            # (no IPAdapter, no FaceID, no LoRA — pure SDXL txt2img on Animagine)
            if os.environ.get("V13_NO_IPA") == "1":
                wf = _cw.panel_clean_workflow(
                    panel_rkey=f"p{idx:02d}",
                    positive=prompt,
                    negative=neg,
                    seed=(page_seed or 42) + idx * 17,
                    width=panel_w, height=panel_h,
                    steps=int(os.environ.get("V10_STEPS","28")),
                    cfg=7.0,
                    ckpt="animagine-xl-4.0.safetensors",
                )
                run = _modal.Function.from_name("mangaka-comfyui","run_workflow")
                png = run.remote(wf, refs=None)
                out_path = Path(f"/tmp/v10-panel-p{idx:02d}.png")
                out_path.write_bytes(png)
                return out_path

            CHARS = {"yuto":"yuto-face.png","ren":"ren-face.png","nei":"nei-face.png",
                      "akira":"akira-face.png","saki":"saki-face.png"}
            focal_chars = panel.get("focusedCharacters") or []
            primary = next((c.lower() for c in focal_chars if c.lower() in CHARS), None)
            ref_filename = CHARS.get(primary, "yuto-face.png")
            ref_path = ("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/"
                         "60-apps/ai-gftd-project-mangaka/data/ghosthacker/"
                         f"resources/character-faces/{ref_filename}")
            if not os.path.exists(ref_path):
                ref_path = ("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/"
                             "60-apps/ai-gftd-project-mangaka/data/ghosthacker/"
                             "resources/character-faces/yuto-face.png")
                ref_filename = "yuto-face.png"
            with open(ref_path, "rb") as f:
                ref_b64 = _b64.b64encode(f.read()).decode()
            shot_to_framing = {"Extreme Close Up":"close","ECU":"close",
                                "Close Up":"close","CU":"close",
                                "Medium":"medium","MS":"medium",
                                "Medium Long":"medium","MLS":"medium",
                                "Long":"wide","LS":"wide","Wide":"wide","WS":"wide",
                                "Over the Shoulder":"medium","OTS":"medium",
                                "Insert":"close","POV":"medium"}
            framing = shot_to_framing.get(panel.get("shot",""),"medium")
            wf = _cw.panel_hq_workflow(
                panel_rkey=f"p{idx:02d}",
                reference_image_filename=ref_filename,
                framing=framing,
                characters=focal_chars,
                environment=scene_slug.replace("-"," "),
                mood=panel.get("tone","") or "neutral",
                action=(panel.get("visual") or "")[:120],
                seed=(page_seed or 42) + idx * 17,
                width=panel_w, height=panel_h,
                steps=int(os.environ.get("V10_STEPS","28")),
                cfg=7.0,
                ckpt="animagine-xl-4.0.safetensors",  # override (only model in volume)
                ipadapter_weight=0.75, ipadapter_face_weight=0.85,
                controlnet_strength=0.55,
                negative=neg,
            )
            run = _modal.Function.from_name("mangaka-comfyui","run_workflow")
            png = run.remote(wf, refs={ref_filename: ref_b64})
            out_path = Path(f"/tmp/v10-panel-p{idx:02d}.png")
            out_path.write_bytes(png)
            return out_path
        except Exception as e:
            print(f"  [v13-comfyui] panel {idx} failed: {e}", flush=True)
            return None

    # v12 (ADR-2605300001, 2026-05-30): MANGAKA_BACKEND=modal routes to Modal
    # H100 (mangaka-kaizen / render_panel_h100). Bypasses ComfyUI/IPAdapter
    # — diffusers-native HF pipeline; no IPA character ref. Style comes from
    # the V11_STYLE-driven prompt only.
    if os.environ.get("MANGAKA_BACKEND") == "modal":
        try:
            import modal as _modal
            _fn_name = os.environ.get("MANGAKA_MODAL_FN", "render_panel_h100")
            _render = _modal.Function.from_name("mangaka-kaizen", _fn_name)
            _seed = (page_seed or 42) + idx * 17
            _png = _render.remote(prompt, neg, width=w, height=h,
                                  steps=steps, cfg=5.5, seed=_seed)
            out_path = Path(f"/tmp/v10-panel-p{idx:02d}.png")
            out_path.write_bytes(_png)
            _crop_to_panel(out_path, panel_w, panel_h)
            return out_path
        except Exception as e:
            print(f"  [v12-modal] panel {idx} failed: {e}", flush=True)
            return None

    # v11 B (2026-05-27): IPAdapter character reference for identity lock.
    # Only applies when focal character matches a known reference file.
    use_ipa = os.environ.get("V11_IPADAPTER", "0") == "1"
    focal = panel.get("focusedCharacters") or []
    # Known character refs uploaded to gad ~/ComfyUI/input/
    # 2026-05-27 B3: expanded with sub-characters (mei, yuko, ken, black0awd-operator)
    KNOWN_CHARS = {"yuto", "ren", "nei", "akira", "saki",
                    "mei", "yuko", "ken", "black0awd-operator"}
    # Manifest aliases — some panels use casing/space variants
    CHAR_ALIASES = {
        "blackOawdOperator": "black0awd-operator",
        "black0awdoperator": "black0awd-operator",
        "blackoawd-operator": "black0awd-operator",
    }
    primary_char = None
    if focal:
        cand = focal[0].lower().strip()
        cand = CHAR_ALIASES.get(cand, cand)
        if cand in KNOWN_CHARS:
            primary_char = cand
    ipa_ref = f"{primary_char}-face.png" if (use_ipa and primary_char) else None

    wf = {
        "ckpt": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": CKPT}},
        "pos":  {"class_type": "CLIPTextEncode",
                  "inputs": {"text": prompt, "clip": ["ckpt", 1]}},
        "neg":  {"class_type": "CLIPTextEncode",
                  "inputs": {"text": neg, "clip": ["ckpt", 1]}},
        "lat":  {"class_type": "EmptyLatentImage",
                  "inputs": {"width": w, "height": h, "batch_size": 1}},
    }

    # If IPAdapter enabled + we have a character ref: inject IPAdapter chain
    model_ref = ["ckpt", 0]
    if ipa_ref:
        wf["ipa_load"] = {"class_type": "IPAdapterUnifiedLoader",
                           "inputs": {"model": ["ckpt", 0],
                                       "preset": "PLUS (high strength)"}}
        wf["ipa_img"] = {"class_type": "LoadImage",
                          "inputs": {"image": ipa_ref}}
        wf["ipa"] = {"class_type": "IPAdapter",
                      "inputs": {"model": ["ipa_load", 0],
                                  "ipadapter": ["ipa_load", 1],
                                  "image": ["ipa_img", 0],
                                  "weight": 0.65,
                                  "start_at": 0.0,
                                  "end_at": 0.6,
                                  "weight_type": "style transfer"}}
        model_ref = ["ipa", 0]

    # v11 B4 (2026-05-27): per-panel seed offset includes hashed shot+tone
    # so panels with similar seeds don't render near-identical compositions.
    # Also adds a per-attempt salt: caller can pass V11_SEED_SALT env to
    # bump variance when a re-render is needed.
    _shot_t = (panel.get("shot") or "") + (panel.get("tone") or "")
    _shot_hash = sum(ord(c) for c in _shot_t) * 31
    _salt = int(os.environ.get("V11_SEED_SALT", "0"))
    panel_seed = (page_seed or 42) + idx * 17 + _shot_hash + _salt
    wf["ks"] = {"class_type": "KSampler",
                "inputs": {"seed": panel_seed,
                            "steps": steps, "cfg": 5.5,
                            "sampler_name": "dpmpp_2m_sde",
                            "scheduler": "karras", "denoise": 1.0,
                            "model": model_ref, "positive": ["pos", 0],
                            "negative": ["neg", 0], "latent_image": ["lat", 0]}}
    wf["dec"] = {"class_type": "VAEDecode",
                  "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}}
    wf["save"] = {"class_type": "SaveImage",
                   "inputs": {"filename_prefix": f"v10-{pipeline}-p{idx:02d}",
                               "images": ["dec", 0]}}

    # Submit with retry — restart ComfyUI on timeout (recurring freeze pattern)
    for attempt in range(3):
        try:
            _, body = _http("POST", "/prompt", json.dumps({"prompt": wf}).encode())
            pid = json.loads(body).get("prompt_id")
            if pid:
                break
        except Exception as e:
            print(f"  [v10] submit attempt {attempt+1} failed: {e}", flush=True)
            if attempt < 2:
                print(f"  [v10] restarting ComfyUI...", flush=True)
                if _restart_comfyui_remote():
                    print(f"  [v10] ComfyUI back up, retrying", flush=True)
                    continue
        time.sleep(2)
    else:
        return None
    if not pid: return None

    end = time.monotonic() + 300
    fail_streak = 0
    while time.monotonic() < end:
        try:
            _, b = _http("GET", f"/history/{pid}")
            fail_streak = 0
            e = (json.loads(b) or {}).get(pid)
            if e and e.get("outputs"):
                for nid, no in e["outputs"].items():
                    for img in no.get("images", []):
                        fname = img.get("filename"); sub = img.get("subfolder", "")
                        if fname:
                            q = urllib.parse.urlencode({"filename": fname,
                                                         "subfolder": sub, "type": "output"})
                            _, data = _http("GET", f"/view?{q}")
                            out_path = Path(f"/tmp/v10-panel-p{idx:02d}.png")
                            out_path.write_bytes(data)
                            _crop_to_panel(out_path, panel_w, panel_h)
                            return out_path
                return None
        except Exception:
            fail_streak += 1
            # If we've had repeated HTTP failures, ComfyUI likely froze.
            # Restart and re-submit this panel.
            if fail_streak >= 3:
                print(f"  [v10] {fail_streak} HTTP failures — restarting ComfyUI", flush=True)
                if _restart_comfyui_remote():
                    print(f"  [v10] ComfyUI restored, re-submitting panel", flush=True)
                    # Re-submit prompt
                    try:
                        _, body = _http("POST", "/prompt",
                                         json.dumps({"prompt": wf}).encode())
                        pid = json.loads(body).get("prompt_id")
                        end = time.monotonic() + 300
                        fail_streak = 0
                        continue
                    except Exception:
                        return None
                else:
                    return None
        time.sleep(3)
    return None


if __name__ == "__main__":
    # Test render p0.1 (Yuto ECU ominous) in 4 pipelines
    test_panel = {
        "panelIndex": 1,
        "shot": "Extreme Close Up",
        "tone": "ominous",
        "focusedCharacters": ["Yuto"],
        "visual": "A close-up of Yuto's face half-covered by a blanket, eyes wide and shadowed with dark circles. The blue light from a smartphone illuminates his face.",
        "sceneSubject": "Notification Sound",
    }
    import sys
    for pip in ["cu_color", "cu_ink", "cu_action"]:
        if len(sys.argv) > 1 and sys.argv[1] != pip and sys.argv[1] != "all":
            continue
        print(f"\n=== Pipeline {pip} ===")
        t0 = time.monotonic()
        out = render_v10_panel(test_panel, "yuto-bedroom", 600, 400, pip, 12345)
        elapsed = time.monotonic() - t0
        print(f"  output: {out}  ({elapsed:.1f}s)")

"""SFX kana overlay — adds dramatic SFX text to panels.

User: Death Note class への path. Death Note の特徴的な SFX kana
(ドーン, ガチャ, チャッ, ジャッ) を panels に overlap として追加。

Mapping (manifest.panel.tone or shot → SFX):
  shock / shout            ドーン / ドオォン
  insert close action       チャッ / ガチャ
  walking / footsteps       タッタッ / ザッザッ
  silence / suspense        ・・・
  hit / impact              ドゴ / バンッ
  door / mechanical         ガチャ / ガキ
  motion / fast             ザッ / シュッ

Uses Hiragino W8 for Japanese font, large bold style with white outline
+ black fill (Death Note characteristic).
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import os, random

# 2026-05-28: expanded SFX library — Witch Watch / Jump-tier expressiveness.
# Each entry = list of (kana, scale_mult, rotation_jitter, style) tuples
# style: "heavy" (W8 outline), "brush" (italic-tilt), "fine" (W3 thin),
#        "stretch" (wide kerning), "pop" (small radial)
SFX_LIBRARY = {
    # Tone-based — many alternatives per tone for variety
    "tense":         [("ドッ", 1.0, 5, "heavy"), ("ザッ", 1.0, -3, "heavy"),
                       ("ザザッ", 1.2, 8, "heavy"), ("ヒュッ", 0.85, 12, "brush"),
                       ("ピシッ", 0.9, -8, "heavy"), ("ガッ", 1.1, 4, "heavy")],
    "ominous":       [("ジワ・・", 0.9, 0, "fine"), ("ドクン", 1.1, -5, "heavy"),
                       ("ゴゴゴ", 1.0, 0, "stretch"), ("ザワ", 0.85, 3, "fine"),
                       ("ザワザワ", 1.0, 0, "fine"), ("シーン", 1.2, 0, "stretch")],
    "shocked":       [("ハッ", 1.0, 8, "heavy"), ("ドキッ", 1.15, -6, "heavy"),
                       ("ビクッ", 1.1, 10, "heavy"), ("ギクッ", 1.0, -8, "heavy"),
                       ("ガーン", 1.4, 0, "stretch")],
    "shout":         [("ドーン", 1.5, -8, "heavy"), ("ドオォン", 1.6, 5, "heavy"),
                       ("バンッ", 1.3, 12, "heavy"), ("バッ", 1.2, -10, "heavy"),
                       ("ドガーン", 1.7, 4, "stretch"), ("ズバッ", 1.4, -6, "brush")],
    "intense":       [("ドッ", 1.0, 0, "heavy"), ("バッ", 1.0, 5, "heavy"),
                       ("ガッ", 1.1, -4, "heavy"), ("ザッ", 1.0, 3, "heavy"),
                       ("ドカン", 1.4, 0, "stretch"), ("ドゴッ", 1.3, -8, "heavy")],
    "action":        [("ザザザ", 1.2, 0, "heavy"), ("ダダッ", 1.15, 8, "heavy"),
                       ("ガガガ", 1.3, 0, "stretch"), ("ヒュン", 1.0, 15, "brush"),
                       ("シュッ", 0.9, -12, "brush"), ("ビュン", 1.1, 15, "brush"),
                       ("ドドド", 1.2, 0, "stretch")],
    "quiet":         [("・・・", 0.7, 0, "fine"), ("シーン", 1.0, 0, "stretch"),
                       ("スッ", 0.8, 5, "fine")],
    "contemplative": [("・・・", 0.7, 0, "fine"), ("ジワ", 0.85, 0, "fine"),
                       ("フゥ", 0.85, 5, "fine"), ("ホッ", 0.85, -3, "fine")],
    "emotional":     [("ドキ", 1.0, -5, "heavy"), ("ハァ", 0.9, 0, "fine"),
                       ("ジーン", 1.0, 0, "stretch"), ("グッ", 1.1, 5, "heavy"),
                       ("ウルッ", 0.95, 0, "fine"), ("ぐすん", 0.85, -5, "fine")],
    "triumph":       [("ニヤッ", 1.0, 8, "brush"), ("フッ", 0.9, 0, "fine"),
                       ("ピッ", 0.85, 10, "heavy"), ("バッ", 1.1, -5, "heavy")],
    "comedic":       [("シュッ", 0.9, 10, "brush"), ("ピョン", 1.0, -8, "pop"),
                       ("ポカン", 1.0, 0, "stretch"), ("ガビーン", 1.2, 5, "stretch"),
                       ("チーン", 1.0, 0, "fine"), ("ガクッ", 1.0, -10, "heavy")],
    "ecstatic":      [("バーン", 1.4, 0, "stretch"), ("ドーン", 1.5, -5, "heavy"),
                       ("カッ", 1.1, 8, "heavy"), ("キラッ", 1.0, 10, "brush")],
    "curious":       [("チラッ", 0.85, 5, "fine"), ("ジー", 0.9, 0, "stretch"),
                       ("ハテ", 0.9, -3, "fine")],
    # Shot-based
    "insert":        [("カチッ", 0.9, 0, "heavy"), ("チャッ", 0.9, 5, "heavy"),
                       ("カチャ", 0.95, -5, "fine"), ("カシャ", 1.0, 0, "fine"),
                       ("ピッ", 0.85, 10, "heavy")],
    "close":         [("ハッ", 1.0, 8, "heavy"), ("ジッ", 0.9, 0, "fine")],
    # Action verbs from visual text
    "walking":       [("タッ", 0.95, -3, "heavy"), ("ザッザッ", 1.1, 0, "heavy"),
                       ("カツカツ", 1.0, 0, "fine")],
    "running":       [("ダッ", 1.15, 10, "heavy"), ("ザッ", 1.0, 5, "heavy"),
                       ("タタタッ", 1.2, 0, "stretch")],
    "phone":         [("プルル", 1.0, 0, "stretch"), ("ピロン", 0.95, 5, "fine")],
    "knock":         [("コンコン", 1.0, 0, "heavy"), ("トントン", 0.95, 0, "fine")],
    "door":          [("ガチャ", 1.05, 0, "heavy"), ("ガキッ", 1.1, -5, "heavy"),
                       ("バタン", 1.2, 0, "heavy"), ("ガラガラ", 1.0, 0, "stretch")],
    "footstep":      [("ザッ", 1.0, 0, "heavy"), ("タッ", 0.9, -3, "fine")],
    # Impact effects
    "crash":         [("ガシャン", 1.4, -5, "heavy"), ("ガッシャーン", 1.6, 0, "stretch"),
                       ("バキッ", 1.3, 10, "heavy"), ("バリッ", 1.2, -8, "heavy"),
                       ("パリン", 1.1, 5, "heavy")],
    "punch":         [("ドゴッ", 1.3, -5, "heavy"), ("バゴッ", 1.4, 8, "heavy"),
                       ("ドゴォ", 1.5, 0, "stretch"), ("ボコッ", 1.2, -10, "heavy")],
    "explosion":     [("ドカーン", 1.8, 0, "stretch"), ("バーン", 1.5, 5, "heavy"),
                       ("ドゴーン", 1.7, -3, "stretch"), ("ズドン", 1.5, 0, "heavy")],
}

# Font setup — Hiragino W8 (system Japanese)
HIRAGINO_BLACK = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
HIRAGINO_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
HIRAGINO_FINE = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
HIRAGINO_BRUSH = "/System/Library/Fonts/ヒラギノ明朝 W6.ttc"

FONT_BY_STYLE = {
    "heavy":   HIRAGINO_BLACK,
    "brush":   HIRAGINO_BRUSH,
    "fine":    HIRAGINO_FINE,
    "stretch": HIRAGINO_BLACK,    # same font, drawn with wide kerning
    "pop":     HIRAGINO_BLACK,    # small radial style
}


def pick_sfx_for_panel(panel: dict) -> str | None:
    """Pick SFX for a panel.
    2026-05-30 — STEP F: story-canonical SFX takes precedence.
    If panel has _story_sfx_texts (from gh:script type=sfx), use one of those
    directly. Otherwise fall back to tone/visual heuristic SFX library.
    """
    # Story-canonical SFX override
    canon_sfx = panel.get("_story_sfx_texts") or []
    if canon_sfx:
        # Pick first non-empty canonical SFX text
        for txt in canon_sfx:
            if txt and txt.strip():
                # Return as tuple — pick a style heuristically
                # Long SFX (like "ブーン。ブーン。ブーン。") → stretch/heavy
                t = txt.strip().rstrip("。")
                # Take first segment if comma-separated repetition
                first_seg = t.split("。")[0].split("、")[0]
                return (first_seg, 1.1, 0, "heavy")

    tone = (panel.get("tone") or "").lower()
    shot = (panel.get("shot") or "").lower()
    visual = (panel.get("visual") or "").lower()

    # 2026-05-29 STEP C — context-aware SFX selection.
    # Old logic: trigger on tone keywords broadly → BATTLE SFX on calm scenes.
    # New: require BOTH a physical action AND impact-class emphasis to add SFX.
    # Calm tones (quiet, contemplative) get NO SFX even if "tense" is present.
    emph = (panel.get("panelLayout", {}).get("gh:emphasis") or "").lower()
    import re

    # Hard exclusion — never add SFX in clearly calm scenes
    CALM_TONES = ["quiet", "contemplative", "emotional", "curious"]
    if any(t in tone for t in CALM_TONES):
        # only allow if emphasis is impact AND visual has a clear action verb
        ACTION_VERBS_HARD = ["punch", "kick", "crash", "slam", "burst",
                              "explosion", "shoot", "scream", "shatter",
                              "fall", "tumble"]
        has_hard_action = any(re.search(rf"\b{kw}\b", visual)
                              for kw in ACTION_VERBS_HARD)
        if not (emph == "impact" and has_hard_action):
            return None

    # Physical-action visual keywords
    DRAMATIC_VISUAL = ["bang", "fire", "explosion", "punch", "kick",
                       "crash", "slam", "burst", "knock", "shoot",
                       "scream", "shatter", "shooting", "running", "footstep",
                       "phone", "click", "alarm"]
    has_dramatic_visual = any(re.search(rf"\b{re.escape(kw)}\b", visual)
                              for kw in DRAMATIC_VISUAL)

    # Tone trigger: ONLY when paired with impact emphasis (else skip)
    DRAMATIC_TONES = ["shocked", "shout", "intense", "tense", "ominous",
                       "action", "triumph"]
    has_dramatic_tone = any(t in tone for t in DRAMATIC_TONES)
    impact_emphasis = emph in ("impact", "climax", "punchline")

    is_insert = "insert" in shot

    # Gate: only add SFX when at least ONE strong signal present
    if not (has_dramatic_visual or (has_dramatic_tone and impact_emphasis)
            or (is_insert and has_dramatic_visual)):
        return None

    candidates = []
    if has_dramatic_visual:
        for kw in DRAMATIC_VISUAL:
            if re.search(rf"\b{re.escape(kw)}\b", visual):
                if "knock" in kw: candidates.extend(SFX_LIBRARY["knock"])
                elif "phone" in kw: candidates.extend(SFX_LIBRARY["phone"])
                elif "scream" in kw or "shout" in kw: candidates.extend(SFX_LIBRARY["shout"])
                elif "crash" in kw or "shatter" in kw: candidates.extend(SFX_LIBRARY["crash"])
                elif "explosion" in kw: candidates.extend(SFX_LIBRARY["explosion"])
                elif "punch" in kw or "kick" in kw: candidates.extend(SFX_LIBRARY["punch"])
                elif "running" in kw or "footstep" in kw:
                    candidates.extend(SFX_LIBRARY["running"])
                else: candidates.extend(SFX_LIBRARY["intense"])
    if has_dramatic_tone and impact_emphasis:
        for k, sfx_list in SFX_LIBRARY.items():
            if k in tone:
                candidates.extend(sfx_list)
    if is_insert and has_dramatic_visual and not candidates:
        candidates.extend(SFX_LIBRARY["insert"])

    if not candidates:
        return None
    # 2026-05-28: stronger hash — index alone collapses to same SFX repeatedly.
    # Now include shot + tone + visual + page so each panel gets distinct
    # variety from the 102-entry library.
    import hashlib
    seed = (str(panel.get("panelIndex", 0)) + (panel.get("shot") or "") +
            (panel.get("tone") or "") + (panel.get("visual") or "")[:50] +
            str(panel.get("pageNum", 0)))
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return candidates[h % len(candidates)]


def overlay_sfx(im: Image.Image, sfx_entry,
                 panel_x: int, panel_y: int, panel_w: int, panel_h: int,
                 size_pct: float = 0.35,
                 panel: dict = None,
                 next_panel: dict = None) -> Image.Image:
    """Overlay SFX kana text on a panel — gaze-flow aware.

    sfx_entry: either str (legacy) or (text, scale, rot_deg, style) tuple.
    size_pct: target text height as percent of panel height
    panel: manifest panel dict for gaze_node + flow_direction
    next_panel: next panel for cross-panel flow direction
    """
    # 2026-05-28: tuple format support — (text, scale_mult, rot_deg, style)
    if isinstance(sfx_entry, tuple):
        sfx_text, entry_scale, entry_rot, style = sfx_entry
    else:
        sfx_text, entry_scale, entry_rot, style = sfx_entry, 1.0, 0, "heavy"

    draw = ImageDraw.Draw(im)
    shot = (panel.get("shot") or "").lower() if panel else ""
    shot_scale = 1.0
    if "extreme close" in shot:
        shot_scale = 0.45
    elif "close up" in shot:
        shot_scale = 0.6
    elif "insert" in shot:
        shot_scale = 0.7
    # ReAct loop override (V11_SFX_SIZE_OVERRIDE, default 1.0)
    react_scale = float(os.environ.get("V11_SFX_SIZE_OVERRIDE", "1.0"))
    # Combine: panel-aspect base scale × shot scale × entry style scale × react
    target_h = int(panel_h * size_pct * shot_scale * entry_scale * react_scale)
    target_h = max(20, target_h)
    font_path = FONT_BY_STYLE.get(style, HIRAGINO_BLACK)
    try:
        font = ImageFont.truetype(font_path, target_h)
    except Exception:
        try:
            font = ImageFont.truetype(HIRAGINO_BLACK, target_h)
        except Exception:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), sfx_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Gaze-flow position (user 2026-05-25: SFX biased toward gaze_node,
    # flow direction points to next panel)
    if panel is not None:
        try:
            import importlib.util
            from pathlib import Path as _P
            _gf_path = _P(__file__).parent.parent / "lg_mangaka/v10_gaze_flow.py"
            if _gf_path.exists():
                spec = importlib.util.spec_from_file_location("gaze_flow", str(_gf_path))
                gf = importlib.util.module_from_spec(spec); spec.loader.exec_module(gf)
                # 2026-05-27 revised: place SFX in OPPOSITE quadrant from
                # subject so kana never occludes face/body. User feedback:
                # "sfx の位置が適切じゃない、effect text が character の上に乗っている"
                gx, gy = gf.gaze_node(panel)
                # Subject quadrant (right? bottom?)
                subj_right = gx > 0.5
                subj_bottom = gy > 0.5
                # SFX anchor in opposite quadrant — 78% inset from corner
                sfx_xf = 0.18 if subj_right else 0.82
                sfx_yf = 0.18 if subj_bottom else 0.82
                tx = panel_x + int(panel_w * sfx_xf) - text_w // 2
                ty = panel_y + int(panel_h * sfx_yf) - text_h // 2
                # Rotation: entry-defined jitter + flow direction bias
                rot = gf.flow_direction(panel, next_panel)
                angle = ((rot - 135) / 180.0) * 15 + entry_rot
            else:
                raise FileNotFoundError("gaze_flow.py missing")
        except Exception:
            # Fall back to original hash placement
            tx = panel_x + (panel_w // 4 if hash(sfx_text) % 2 == 0
                             else panel_w * 3 // 5)
            ty = panel_y + panel_h // 3 - text_h // 2
            angle = ((hash(sfx_text) % 14) - 7) * 1.5
    else:
        tx = panel_x + (panel_w // 4 if hash(sfx_text) % 2 == 0
                         else panel_w * 3 // 5)
        ty = panel_y + panel_h // 3 - text_h // 2
        angle = ((hash(sfx_text) % 14) - 7) * 1.5

    # Clamp to panel bounds
    tx = max(panel_x, min(panel_x + panel_w - text_w, tx))
    ty = max(panel_y, min(panel_y + panel_h - text_h, ty))

    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer)
    outline_w = max(4, target_h // 16)
    # 2026-05-28: style-specific rendering — stretch uses per-char spacing,
    # pop draws a radial highlight, others use std outlined text.
    if style == "stretch":
        # Wide-kerning: draw each char with extra horizontal space
        char_x = tx
        kern = int(target_h * 0.15)
        for ch in sfx_text:
            cb = ldraw.textbbox((0, 0), ch, font=font)
            cw = cb[2] - cb[0]
            for ox in range(-outline_w, outline_w + 1, 2):
                for oy in range(-outline_w, outline_w + 1, 2):
                    ldraw.text((char_x + ox, ty + oy), ch,
                                fill=(255, 255, 255, 255), font=font)
            ldraw.text((char_x, ty), ch, fill=(0, 0, 0, 255), font=font)
            char_x += cw + kern
    else:
        for ox in range(-outline_w, outline_w + 1, 2):
            for oy in range(-outline_w, outline_w + 1, 2):
                ldraw.text((tx + ox, ty + oy), sfx_text,
                            fill=(255, 255, 255, 255), font=font)
        ldraw.text((tx, ty), sfx_text, fill=(0, 0, 0, 255), font=font)
    layer = layer.rotate(angle, resample=Image.BICUBIC, expand=False)
    im.paste(layer, (0, 0), layer)
    return im


def overlay_sfx_on_composite(composite_path: Path, layout: list,
                              panels: list, out_path: Path = None,
                              size_pct: float = 0.35) -> Path:
    """Apply SFX overlay to a composited manga page based on manifest panels.

    size_pct: target text height as percent of panel height
              (ADR-2605241500 composite_emphasis.sfx-driven)
    """
    im = Image.open(composite_path).convert("RGB")
    panels_by_idx = {p["panelIndex"]: p for p in panels}
    sorted_idxs = sorted(panels_by_idx.keys())
    added = []
    for slot in layout:
        idx = slot["idx"]
        if idx not in panels_by_idx: continue
        panel = panels_by_idx[idx]
        # Find next panel for gaze-flow direction
        next_panel = None
        try:
            ci = sorted_idxs.index(idx)
            if ci + 1 < len(sorted_idxs):
                next_panel = panels_by_idx[sorted_idxs[ci + 1]]
        except: pass
        sfx = pick_sfx_for_panel(panel)
        if not sfx: continue
        overlay_sfx(im, sfx, slot["x"], slot["y"], slot["w"], slot["h"],
                     size_pct=size_pct, panel=panel, next_panel=next_panel)
        # Track text only for summary
        sfx_text = sfx[0] if isinstance(sfx, tuple) else sfx
        added.append((idx, sfx_text))
    if out_path is None:
        out_path = composite_path
    im.save(out_path)
    return out_path, added


if __name__ == "__main__":
    import sys, json
    page_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
    manifest = json.loads(MANIFEST.read_text())
    panels = sorted([p for p in manifest["panels"] if p["pageNum"] == page_num],
                     key=lambda p: p["panelIndex"])
    print(f"Page {page_num} panels — SFX picks:")
    for p in panels:
        sfx = pick_sfx_for_panel(p)
        print(f"  panel {p['panelIndex']:>2}: tone={p.get('tone'):<14} shot={p.get('shot'):<25} sfx={sfx}")

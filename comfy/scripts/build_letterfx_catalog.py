#!/usr/bin/env python3
"""Build the lettering / SFX / 効果線 / トーン pattern catalog (10 each).

Emits a page-record-shaped JSON with 4 catalog pages — bubbles, sfx, effect
lines, tones — each a 2×5 grid of 10 panels, one pattern per panel. Render with
komawari_blueprint_pdf.py. Catalog pages set _showGaze/_showPath/_showShotBox
false so the letter/fx/tone layers are the focus.
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "sample-letterfx-patterns.page.json"
GEOM = {"trimSize": "b5", "bleedPermille": 17, "safeTop": 40, "safeRight": 40,
        "safeBottom": 40, "safeLeft": 40, "gutterPermille": 13}


def grid10():
    rects = []
    for t in (17, 213, 409, 605, 801):
        rects.append({"x": 508, "y": t, "w": 475, "h": 184})   # right (RTL first)
        rects.append({"x": 17, "y": t, "w": 477, "h": 184})    # left
    return rects


def page(title, panels):
    return {"pageNum": 0, "pageTitle": title, "printGeometry": GEOM,
            "_showGaze": False, "_showPath": False, "_showShotBox": False,
            "panels": panels}


def cells(layer_key, specs):
    out = []
    for i, (rect, spec) in enumerate(zip(grid10(), specs)):
        out.append({"order": i + 1, **rect, layer_key: spec})
    return out


# ── セリフ 10 形 ──────────────────────────────────────────────────────────
# (shape, 明示の列 右→左) — lines[] が改行位置をデータで持つので変な所で折れない
BUB = [("round", ["やあ"]),
       ("oval", ["おはよう、", "調子は？"]),
       ("spiky", ["うわあッ！"]),
       ("burst", ["ドケェ！！"]),
       ("cloud", ["…どうしよう"]),
       ("rect", ["——3日前の", "放課後。"]),
       ("whisper", ["…ねえ、", "聞いてる？"]),
       ("jagged", ["ザ…ザ…", "応答セヨ"]),
       ("thought", ["(まずい、", "バレる)"]),
       ("wavy", ["な、なんで", "君が…"])]
bub_panels = cells("bubbles", [[{
    "text": "".join(lines), "lines": lines, "shape": shp,
    "posX": 500, "posY": 430, "sizeW": 660, "sizeH": 560,
    "tailX": 500, "tailY": 910, "writingMode": "vertical-rtl", "order": 1
}] for shp, lines in BUB])

# ── SFX 10 ─────────────────────────────────────────────────────────────────
# (text, style, scale, rot, weight, bleed, posX, posY) — scale lowered since the
# per-glyph 小→大 ramp now multiplies on top.
SFX = [("ドン", "impact", 110, -8, "heavy", False, 500, 500),
       ("ぽつ", "soft", 85, 0, "light", False, 520, 470),
       ("ピピッ", "electronic", 95, 0, "medium", False, 500, 470),
       ("ザワザワ", "organic", 90, -6, "medium", False, 500, 520),
       ("ガキィン", "metallic", 100, 16, "heavy", False, 480, 470),
       ("シーン", "silence", 100, 0, "light", False, 500, 470),
       ("ゴゴゴ", "rough", 100, 0, "heavy", False, 500, 520),
       ("ドオォン", "impact", 120, -6, "heavy", True, 500, 500),
       ("バキ", "impact", 105, 26, "heavy", False, 480, 470),
       ("スゥ", "soft", 90, -20, "light", False, 520, 450)]
# 小→大 ramp + 広がり + burst + easing + 回転ゆらぎ + rays/bezier/行ごと demo
SFX_RAMP = [
    {"scaleStart": 55, "scaleEnd": 185, "spread": 30, "burst": "converge",
     "easing": "bezier", "bezier": [150, 850, 850, 150]},                       # ドン カスタムベジェ(S字)
    None,                                                                       # ぽつ
    None,                                                                       # ピピッ
    {"scaleStart": 90, "scaleEnd": 150, "spread": 16},                          # ザワザワ
    {"text": "ドドド", "scaleStart": 80, "scaleEnd": 150, "spread": 14,
     "lines": ["ドドド", "ドドド", "ドドド"], "burst": "alternate"},               # 行ごと収束/拡散 切替
    None,                                                                       # シーン
    {"scaleStart": 80, "scaleEnd": 150, "spread": 18, "easing": "ease-in-out", "rotJitter": 7},  # ゴゴゴ
    {"text": "ドン", "scaleStart": 55, "scaleEnd": 130, "spread": 14, "rays": 8,
     "rotJitter": 6},                                                           # ドオォン→ドン×8 放射状爆発
    {"scaleStart": 60, "scaleEnd": 175, "spread": 12, "easing": "exp-in"},      # バキ 流線で一気に伸長
    {"scaleStart": 120, "scaleEnd": 60, "spread": 8}]                           # スゥ 大→小(遠ざかる音)
# parallel 効果線 so the SFX warp/scale visibly aligns to it (auto-derived)
SFX_FX = [[{"kind": "focus", "centerX": 500, "centerY": 470, "density": 70}],  # ドン→集中
          None, None, None,
          [{"kind": "flash", "centerX": 480, "centerY": 470, "density": 55}],   # ガキィン
          None,
          [{"kind": "vertical", "density": 45}],                                # ゴゴゴ
          [{"kind": "explosion", "centerX": 500, "centerY": 500, "density": 72}],  # ドオォン
          [{"kind": "speed", "direction": 28, "density": 65}],                  # バキ→流線
          [{"kind": "speed", "direction": 250, "density": 50}]]                 # スゥ→上抜け
sfx_panels = []
_sfx_rects = grid10()
for i, (t, st, sc, rot, wt, bl, px, py) in enumerate(SFX):
    sfx = {"text": t, "style": st, "scale": sc, "rotation": rot,
           "weight": wt, "bleed": bl, "posX": px, "posY": py}
    if SFX_RAMP[i]:
        sfx.update(SFX_RAMP[i])
    cell = {"order": i + 1, **_sfx_rects[i], "sfx": [sfx]}
    if SFX_FX[i]:
        cell["effectLines"] = SFX_FX[i]
    sfx_panels.append(cell)

# ── 効果線 10 ───────────────────────────────────────────────────────────────
FX = [("focus", {"centerX": 500, "centerY": 400, "density": 72, "coverage": "radial"}),
      ("speed", {"direction": 0, "density": 70, "coverage": "band"}),
      ("vertical", {"density": 55}),
      ("flash", {"centerX": 500, "centerY": 460, "density": 60, "coverage": "radial"}),
      ("shock", {"centerX": 500, "centerY": 500, "density": 66}),
      ("aura", {"density": 50, "coverage": "edge"}),
      ("motion-blur", {"direction": 28, "density": 55}),
      ("explosion", {"centerX": 520, "centerY": 500, "density": 72}),
      ("sparkle", {"density": 40}),
      ("speed", {"direction": 90, "density": 66, "coverage": "band"})]
fx_panels = cells("effectLines", [[{"kind": k, **extra}] for k, extra in FX])

# ── トーン 10 ───────────────────────────────────────────────────────────────
TONE = [("dot-flat", {"density": 50, "mood": "mood"}),
        ("dot-gradient", {"density": 60, "mood": "depth"}),
        ("hatch", {"density": 55, "angle": 45, "mood": "shadow"}),
        ("cross-hatch", {"density": 62, "mood": "menace"}),
        ("gradient-linear", {"density": 50, "angle": 90, "mood": "depth"}),
        ("solid-black", {"density": 100, "regionX": 150, "regionY": 250, "regionW": 700,
                         "regionH": 640, "mood": "shadow"}),
        ("flash-white", {"density": 40, "mood": "focus"}),
        ("flashback", {"density": 45, "mood": "flashback"}),
        ("sparkle", {"density": 35, "mood": "shoujo"}),
        ("noise", {"density": 60, "mood": "menace"})]
tone_panels = cells("tones", [[{"kind": k, **extra}] for k, extra in TONE])

# ── フォント 10 (シーン別 lettering font roles) ──────────────────────────────
FONTS = [("antigochi", ["標準セリフ", "アンチゴチ"]),
         ("gothic", ["強調・ナレ", "ゴシック体"]),
         ("mincho", ["独白・地の文", "明朝体"]),
         ("bold-mincho", ["回想・荘厳", "太明朝"]),
         ("maru", ["優しい・日常", "丸ゴシック"]),
         ("kyokasho", ["手紙・学校", "教科書体"]),
         ("brush", ["和風・力強", "筆/楷書"]),
         ("handwritten", ["小声・心の声", "手書き風"]),
         ("digital", ["電子・SMS", "デジタル角"]),
         ("horror", ["恐怖・不穏", "ホラー震え"])]
font_panels = cells("bubbles", [[{
    "lines": lines, "text": "".join(lines), "shape": "round", "font": role,
    "posX": 500, "posY": 430, "sizeW": 740, "sizeH": 560,
    "tailX": 500, "tailY": 910, "writingMode": "vertical-rtl", "order": 1
}] for role, lines in FONTS])

doc = {"episode": "letterfx-pattern-catalog",
       "schema": "ai.gftd.mangaka.page (bubble/sfx/effectLine/tone/fontRole)",
       "pages": [
           page("セリフ 10形 / speech-balloon shapes (bubbles)", bub_panels),
           page("効果音 10 / SFX onomatopoeia (sfx)", sfx_panels),
           page("効果線 10 / effect lines (effectLines)", fx_panels),
           page("トーン 10 / screentone (tones)", tone_panels),
           page("フォント 10 / lettering font roles (font)", font_panels),
       ]}
OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
print(f"wrote {OUT}  ({len(doc["pages"])} pages, 10 each)")

#!/usr/bin/env python3
"""層設計器 — 1パネルを『1枚絵』ではなく層スタックとして定義する。Cut の演出データ
(gaze.impression / vfx / intent)から、得意な手続き型ジェネレータが描く層を導出する:

  base art   ← AI (gemini/Animagine)            … 人物/背景(別工程)
  tones      ← 手続き型ハーフトーン draw_tone    … 均一トーン(impression mood 発)
  effectLines← 手続き型ベクター draw_fx          … 集中線/流線(impression 発、focus=gaze)
  sfx        ← ベクター・タイポ draw_sfx          … 描き文字(vfx + manifest sfx 発)
  bubbles    ← レタラー draw_bubble              … 写植(別工程)

正準 z-order: panel art → tones → effectLines → SFX → bubbles (lexicon #panel)。
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_canonical_storyboard as B  # noqa: E402

# impression → 効果線(集中線/流線): (kind, density)
IMPRESSION_FX = {
    "speed": ("speed", 82), "impact": ("explosion", 88), "tension": ("focus", 50),
    "dread": ("focus", 44), "ominous": ("focus", 40), "awe": ("flash", 62),
}
# impression → スクリーントーン: (kind, mood, density)
IMPRESSION_TONE = {
    "dread": ("cross-hatch", "menace", 46), "ominous": ("cross-hatch", "menace", 42),
    "tension": ("hatch", "tension", 34), "melancholy": ("dot-gradient", "melancholy", 40),
    "awe": ("flash-white", "awe", 28),
}
# vfx キーワード → 描き文字
VFX_KANA = {"slash": "ザンッ", "energy": "シャッ", "impact": "ドンッ", "glitch": "バチッ",
            "explosion": "ドォン", "spark": "パチッ", "shadow": "ゾワ", "particle": "キラ",
            "shock": "ビシッ", "smoke": "ゴウ"}


def layers_for_cut(cut, mp, climax=False):
    """Cut + manifest panel → (tones, effectLines, sfx)。各層は手続き型コンポジタが描く。"""
    gz = cut.get("gaze", {})
    imp = gz.get("impression", "")
    fx, tones, sfx = [], [], []
    # 効果線(集中線=focus / 流線=speed)。focus は gaze 焦点中心、speed は entry→exit 方向
    k, d = IMPRESSION_FX.get(imp, (None, 0))
    if k:
        e = {"kind": k, "centerX": gz.get("focusX", 500), "centerY": gz.get("focusY", 460),
             "density": d, "coverage": 85}
        if k in ("speed", "motion-blur"):
            ix, iy = gz.get("entryX", 800), gz.get("entryY", 150)
            ex, ey = gz.get("exitX", 150), gz.get("exitY", 850)
            e["direction"] = round(math.degrees(math.atan2(ey - iy, ex - ix)))
        fx.append(e)
    # スクリーントーン(mood)。範囲は gaze.region(無ければ全面)
    tk = IMPRESSION_TONE.get(imp)
    if tk:
        kind, mood, dens = tk
        tones.append({"kind": kind, "mood": mood, "density": dens,
                      "regionX": gz.get("regionX", 0), "regionY": gz.get("regionY", 0),
                      "regionW": gz.get("regionW", 1000), "regionH": gz.get("regionH", 1000)})
    # 描き文字 SFX: manifest の speaker=='sfx' + cut.vfx 由来
    kanas = [d.get("text") for d in (mp.get("dialogues") or [])
             if (d.get("speaker") or "").lower() == "sfx" and d.get("text")]
    for v in (cut.get("vfx") or []):
        for key, kana in VFX_KANA.items():
            if key in v.lower():
                kanas.append(kana)
                break
    kanas = list(dict.fromkeys(kanas))
    if kanas:
        sfx += B._sfx_from_kana(kanas, climax)
    elif imp in ("impact", "speed", "ominous", "dread", "tension", "awe"):
        sfx += B.build_sfx(mp.get("tone"), imp, climax)   # impression 発の描き文字
    return tones, fx, sfx[:2]

#!/usr/bin/env python3
"""Koma-wari (panel-layout) blueprint → PDF.

Renders the *new* ai.gftd.mangaka.page data model — printGeometry (内枠/仕上がり/
断ち切り), per-panel bleed (断ち切り), shot (引き/寄り + camera + move) and gaze
(視線範囲/遷移/印象) — as a vector schematic, one page per board, into a single
multi-page PDF. This is a LAYOUT blueprint, not the illustrated render (which needs
the ComfyUI/compose backend). It makes the koma-wari + direction data reviewable.

All panel x/y/w/h are integer permille (‰, 0-1000) of the FULL board (外枠, bleed
included). gaze.* coords are panel-local permille. Mirrors the lexicon exactly, so
the input JSON also serves as a schema fixture.

Usage:
  python3 -m scripts.komawari_blueprint_pdf \
      --in scripts/sample-komawari-arc0-1.page.json --out /tmp/komawari-arc0-1.pdf
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# B5 default; board aspect == trim aspect (symmetric permille bleed).
TRIM_MM = {"b5": (182, 257), "a4": (210, 297), "b4": (257, 364),
           "webtoon": (800, 1280), "tankobon": (127, 182)}
BOARD_H = 1500          # board (外枠) height in px; width derived from trim aspect
CAP = 104               # caption band height above the board

# framing → accent color (引き=cool/wide, 寄り=warm/close)
FRAMING_COLOR = {"hiki": (40, 110, 200), "yori": (200, 70, 70), "neutral": (90, 90, 90)}
INK = (20, 20, 24)
TRIM_COL = (214, 84, 84)        # 仕上がり線
SAFE_COL = (62, 110, 206)       # 基準線 / 内枠
PANEL_FILL = (246, 246, 248)
BLEED_FILL = (252, 243, 243)
MIN_FACE_FRAC = 0.04            # パネル面積比 これ未満の顔は背景/遠景/誤検出 → 吹き出し回避・監査の対象外
GAZE_FOCUS = (210, 40, 40)
GAZE_REGION = (40, 160, 90)
GAZE_ENTRY = (40, 160, 90)
GAZE_EXIT = (235, 140, 30)
PATH_COL = (150, 60, 200)


def _font(size: int, weight: str = "W6"):
    for p in (f"/System/Library/Fonts/ヒラギノ角ゴシック {weight}.ttc",
              "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _dashed(d, p0, p1, color, width=2, dash=14, gap=9):
    x0, y0 = p0
    x1, y1 = p1
    dist = math.hypot(x1 - x0, y1 - y0)
    if dist < 1:
        return
    ux, uy = (x1 - x0) / dist, (y1 - y0) / dist
    n = int(dist // (dash + gap)) + 1
    for i in range(n):
        s = i * (dash + gap)
        e = min(s + dash, dist)
        d.line([(x0 + ux * s, y0 + uy * s), (x0 + ux * e, y0 + uy * e)],
               fill=color, width=width)


def _dashed_rect(d, box, color, width=2):
    x0, y0, x1, y1 = box
    _dashed(d, (x0, y0), (x1, y0), color, width)
    _dashed(d, (x1, y0), (x1, y1), color, width)
    _dashed(d, (x1, y1), (x0, y1), color, width)
    _dashed(d, (x0, y1), (x0, y0), color, width)


def _arrow(d, p0, p1, color, width=5, head=20):
    d.line([p0, p1], fill=color, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    for s in (math.radians(150), math.radians(-150)):
        d.line([p1, (p1[0] + head * math.cos(ang + s),
                     p1[1] + head * math.sin(ang + s))], fill=color, width=width)


# ── lettering / fx / tone layers ────────────────────────────────────────────
TONE_COL = (118, 118, 128)
FX_COL = (66, 104, 158)
BUB_INK = (20, 20, 24)
SFX_STYLE = {"impact": (15, 15, 18), "soft": (90, 90, 96), "electronic": (40, 90, 170),
             "organic": (60, 50, 40), "metallic": (70, 80, 95), "silence": (120, 120, 128),
             "rough": (40, 40, 40)}
SHAPE_JP = {"round": "丸", "oval": "楕", "spiky": "叫", "burst": "爆", "cloud": "雲",
            "rect": "角", "whisper": "囁", "jagged": "電", "thought": "心", "wavy": "揺"}

import random as _random

# ── manga lettering font roles (10) ─────────────────────────────────────────
# role → (preview font path on macOS, sim, 日本語ラベル/用途). The role is the
# scene-matched DATA; the preview font is a best-effort local approximation of
# the real commercial manga family (true アンチック/丸ゴ/教科書体 are licensed).
_FONT_FB = ["/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"]
_HG = "/System/Library/Fonts/Hiragino Sans GB.ttc"
_MIN = "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"
FONT_ROLES = {
    "antigochi":   (_HG,  None,    "アンチゴチ・標準セリフ"),
    "gothic":      (_HG,  "bold",  "ゴシック・強調/ナレ/看板"),
    "mincho":      (_MIN, None,    "明朝・独白/シリアス/地の文"),
    "bold-mincho": (_MIN, "bold",  "太明朝・回想/荘厳"),
    "maru":        (_HG,  None,    "丸ゴ・優しい/コミカル/子供"),
    "kyokasho":    ("/System/Library/Fonts/Supplemental/Songti.ttc", None, "教科書体・手紙/学校"),
    "brush":       ("/System/Library/Fonts/Supplemental/AppleMyungjo.ttf", "bold", "筆/楷書・和風/力強"),
    "handwritten": (_HG,  "jitter", "手書き・小声/ツッコミ/心の声"),
    "digital":     (_HG,  "digital", "デジタル角・電子音/SMS/機械/放送"),
    "horror":      (_MIN, "horror", "ホラー震え・恐怖/不穏/狂気"),
}
# scene defaults when a bubble/sfx omits an explicit font role
SHAPE_FONT = {"spiky": "gothic", "burst": "gothic", "rect": "gothic",
              "whisper": "handwritten", "jagged": "digital", "thought": "mincho",
              "cloud": "mincho", "wavy": "handwritten"}
SFX_FONT = {"electronic": "digital", "metallic": "gothic", "silence": "mincho",
            "soft": "maru", "organic": "handwritten", "rough": "horror", "impact": "gothic"}


def _role_font(role, size):
    path, sim, _ = FONT_ROLES.get(role, FONT_ROLES["antigochi"])
    for p in [path] + _FONT_FB:
        try:
            return ImageFont.truetype(p, size), sim
        except Exception:
            continue
    return _font(size), sim


def _region_px(box, spec):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    rx, ry = spec.get("regionX", 0), spec.get("regionY", 0)
    rw, rh = spec.get("regionW", 1000), spec.get("regionH", 1000)
    return (x0 + rx / 1000 * w, y0 + ry / 1000 * h,
            x0 + (rx + rw) / 1000 * w, y0 + (ry + rh) / 1000 * h)


def _ppx(box, vx, vy):
    x0, y0, x1, y1 = box
    return (x0 + vx / 1000 * (x1 - x0), y0 + vy / 1000 * (y1 - y0))


def draw_tone(img, box, t, font):
    """Screentone swatch over a panel-local region (clipped via a tile)."""
    rx0, ry0, rx1, ry1 = (int(v) for v in _region_px(box, t))
    w, h = max(1, rx1 - rx0), max(1, ry1 - ry0)
    if w < 4 or h < 4:
        return
    kind, dens = t.get("kind", "dot-flat"), t.get("density", 50)
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    if kind in ("dot-flat", "dot-gradient", "flashback"):
        step = max(9, 26 - dens // 6)
        for yy in range(0, h, step):
            for xx in range(0, w, step):
                r = 1.7 if kind != "dot-gradient" else 0.8 + 2.8 * (yy / h)
                td.ellipse([xx - r, yy - r, xx + r, yy + r], fill=TONE_COL)
    elif kind in ("hatch", "cross-hatch", "noise"):
        sp = max(6, 20 - dens // 6)
        for off in range(-h, w, sp):
            td.line([(off, h), (off + h, 0)], fill=TONE_COL, width=1)
        if kind == "cross-hatch":
            for off in range(0, w + h, sp):
                td.line([(off, 0), (off - h, h)], fill=TONE_COL, width=1)
    elif kind == "gradient-linear":
        n = 30
        for i in range(n):
            if (i * i) % 5 < 2:
                continue
            yy = h * i / n
            td.line([(0, yy), (w, yy)], fill=TONE_COL, width=1)
    elif kind == "solid-black":
        td.rectangle([0, 0, w, h], fill=(58, 58, 64, 255))
    elif kind == "flash-white":
        cx, cy = w / 2, h / 2
        for a in range(0, 360, 11):
            rr = math.radians(a)
            td.line([(cx, cy), (cx + w * math.cos(rr), cy + h * math.sin(rr))],
                    fill=(196, 202, 214), width=1)
    elif kind == "sparkle":
        step = max(36, 96 - dens)
        for yy in range(step // 2, h, step):
            for xx in range(step // 2, w, step):
                s = 6
                td.line([(xx - s, yy), (xx + s, yy)], fill=TONE_COL, width=1)
                td.line([(xx, yy - s), (xx, yy + s)], fill=TONE_COL, width=1)
    img.paste(tile, (rx0, ry0), tile)
    if os.environ.get("KOMA_CLEAN") != "1":
        ImageDraw.Draw(img).text((rx0 + 4, ry0 + 2), f"tone:{kind}", font=font, fill=(150, 120, 170))


def draw_fx(img, box, e, font):
    """効果線 overlay, clipped to the panel via a tile."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    kind, dens = e.get("kind", "speed"), e.get("density", 60)
    cx, cy = _ppx((0, 0, w, h), e.get("centerX", 500), e.get("centerY", 500))
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    step = max(2, 10 - dens // 12)
    if kind in ("focus", "flash", "explosion", "shock"):
        clear = min(w, h) * (0.16 if kind == "focus" else 0.05)
        R = (w + h)
        col = (200, 205, 215) if kind == "flash" else FX_COL
        for a in range(0, 360, step):
            rr = math.radians(a)
            jit = 1.0 if kind != "explosion" else (0.6 + 0.4 * ((a // step) % 3))
            td.line([(cx + clear * math.cos(rr), cy + clear * math.sin(rr)),
                     (cx + R * jit * math.cos(rr), cy + R * jit * math.sin(rr))],
                    fill=col, width=1)
    elif kind in ("speed", "motion-blur"):
        ang = math.radians(e.get("direction", 0))
        nx, ny = math.cos(ang + math.pi / 2), math.sin(ang + math.pi / 2)
        dx, dy = math.cos(ang), math.sin(ang)
        L = w + h
        sp = max(6, 22 - dens // 6)
        for off in range(-int(L), int(L), sp):
            mx, my = w / 2 + nx * off, h / 2 + ny * off
            td.line([(mx - dx * L, my - dy * L), (mx + dx * L, my + dy * L)],
                    fill=FX_COL, width=2 if kind == "motion-blur" else 1)
    elif kind == "vertical":
        sp = max(8, 26 - dens // 5)
        for xx in range(0, w, sp):
            td.line([(xx, 0), (xx, h)], fill=FX_COL, width=1)
    elif kind == "aura":
        for k in range(1, 4):
            td.rectangle([k * 5, k * 5, w - k * 5, h - k * 5], outline=FX_COL, width=1)
    elif kind == "sparkle":
        for yy in range(40, h, 80):
            for xx in range(40, w, 80):
                for a in range(0, 360, 45):
                    rr = math.radians(a)
                    td.line([(xx, yy), (xx + 12 * math.cos(rr), yy + 12 * math.sin(rr))],
                            fill=FX_COL, width=1)
    img.paste(tile, (x0, y0), tile)
    ImageDraw.Draw(img).text((x0 + 4, y1 - 24), f"効果線:{kind}", font=font, fill=FX_COL)


# Japanese line-break (禁則) sets for vertical lettering.
_BREAK_AFTER = "、。！？"                      # prefer a column break right after these
# a column must not START with these (closing punct + small kana + long vowel = 禁則)
_NO_START = "、。，．！？）」』〕｝〉》ー～〜…‥ァィゥェォッャュョヮぁぃぅぇぉっゃゅょゎ々"


def _wrap_seg(seg: str, maxc: int) -> list:
    """1セグメント(、で区切った後)を均等割り+禁則で縦列へ。"""
    n = len(seg)
    if n == 0:
        return []
    ncol = max(1, round(n / maxc))
    cap = max(3, -(-n // ncol))
    cols, cur = [], ""
    for ch in seg:
        cur += ch
        if len(cur) >= cap:
            cols.append(cur); cur = ""
    if cur:
        cols.append(cur)
    fixed = []
    for c in cols:
        while c and c[0] in _NO_START and fixed:
            fixed[-1] += c[0]; c = c[1:]
        if c:
            fixed.append(c)
    if len(fixed) >= 2 and len(fixed[-1]) == 1:
        fixed[-2] += fixed[-1]; fixed.pop()
    return fixed


def wrap_jp(text: str, maxc: int = 6) -> list:
    """セリフ組版: 、=改行(列区切り・文字は出さない) / 。=除去(別吹き出し境界) /
    ？！は残す。各セグメントを均等割り+禁則で縦列にする。"""
    if not text:
        return []
    text = text.replace("。", "").replace("．", "")
    out = []
    for seg in text.split("、"):
        seg = seg.strip("　 ")
        if seg:
            out.extend(_wrap_seg(seg, maxc))
    return out[:7]


# 縦書き用 字形/回転テーブル
_VPUNC = {"（": "︵", "）": "︶", "「": "﹁", "」": "﹂", "『": "﹃", "』": "﹄",
          "【": "︻", "】": "︼", "〔": "︹", "〕": "︺", "｛": "︷", "｝": "︸",
          "…": "︙", "‥": "︰"}
_VROT = set("ー〜～—–-")                  # 長音/ダッシュは元グリフを90°回転して縦線に


def _is_ascii(c):
    return " " <= c <= "~"                               # 半角英数記号 (parens含む→縦中横でまとまる)


def _tok_vert(col):
    """列を CJK 1字トークンと ASCII 連続ラン(縦中横)に分割。"""
    out, cur, asc = [], "", None
    for c in col:
        a = _is_ascii(c)
        if cur and a != asc:
            out.append((asc, cur)); cur = ""
        cur += c; asc = a
    if cur:
        out.append((asc, cur))
    return out


def _paste_hrun(img, xc, ytop, s, font, fill, cw, ch):
    """ASCII ラン(Mei / (^ ^) 等)を横書きのまま 縦中横 で1セルに収める。"""
    tmp = Image.new("RGBA", (len(s) * (font.size + 2) + 12, int(font.size * 1.6) + 8), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((4, 4), s, font=font, fill=fill)
    bb = tmp.getbbox()
    if not bb:
        return
    tmp = tmp.crop(bb)
    maxw = cw * 1.45
    if tmp.width > maxw:
        sc = maxw / tmp.width
        tmp = tmp.resize((int(tmp.width * sc), max(1, int(tmp.height * sc))), Image.BICUBIC)
    img.paste(tmp, (int(xc - tmp.width / 2), int(ytop + ch / 2 - tmp.height / 2)), tmp)


def _vtext_lines(d, cx, cy, lines, font, fill, sim=None, img=None):
    lines = [ln for ln in lines if ln][:7]
    if not lines:
        return
    gap = 7 if sim == "digital" else 3
    ch, cw = font.size + gap, font.size + 5
    rnd = _random.Random(20260606)
    x = cx + (len(lines) * cw) / 2 - cw / 2          # rightmost column first (RTL)
    for col in lines:
        toks = _tok_vert(col)
        # cells: 顔文字/記号ラン=1セル(縦中横), 英字(人名)とCJK=1字1セル
        cells = sum(1 if (asc and not s.isalpha()) else len(s) for asc, s in toks)
        y = cy - cells * ch / 2
        for asc, s in toks:
            if asc and not s.isalpha():              # 顔文字/記号/数字 → 縦中横
                if img is not None:
                    _paste_hrun(img, x, y, s, font, fill, cw, ch)
                else:
                    d.text((x - font.size / 2, y), s, font=font, fill=fill)
                y += ch
                continue
            seq = s.upper() if asc else s            # 英字(人名/英単語)は大文字で1字ずつ縦に
            for c in seq:
                g = _VPUNC.get(c, c)
                ox = oy = rot = 0
                if sim == "jitter":
                    ox = rnd.randint(-2, 2)
                if sim == "horror":
                    ox, oy, rot = rnd.randint(-3, 3), rnd.randint(-4, 4), rnd.randint(-13, 13)
                if c in _VROT:
                    rot = 90                         # 長音記号などを縦向きに
                if rot and img is not None:
                    sq = int(font.size * 1.7)
                    tmp = Image.new("RGBA", (sq, sq), (0, 0, 0, 0))
                    ImageDraw.Draw(tmp).text((sq / 2 - font.size / 2, sq / 2 - font.size / 2),
                                             g, font=font, fill=fill)
                    tmp = tmp.rotate(rot, resample=Image.BICUBIC)
                    img.paste(tmp, (int(x - sq / 2 + ox), int(y + font.size / 2 - sq / 2 + oy)), tmp)
                elif asc:                            # 英字1字 — 中央寄せ(幅が狭いため)
                    d.text((x + ox, y + oy), c, font=font, fill=fill, anchor="ma")
                else:
                    d.text((x - font.size / 2 + ox, y + oy), g, font=font, fill=fill)
                y += ch
        x -= cw


def _angdiff(a, b):
    return ((a - b + math.pi) % (2 * math.pi)) - math.pi


def _bubble_outline(d, cx, cy, bw, bh, rfn, tail, N=128, width=3):
    """Build a smooth bubble outline polygon, splicing a triangular tail (くちばし)
    into the perimeter so the tail is one continuous shape — not a separate line."""
    poly, apex_done = [], False
    half = tail[3] if tail else 0
    for k in range(N):
        a = 2 * math.pi * k / N
        if tail and abs(_angdiff(a, tail[2])) < half:
            if not apex_done:
                poly.append((tail[0], tail[1])); apex_done = True
            continue
        rr = rfn(a)
        poly.append((cx + bw * rr * math.cos(a), cy + bh * rr * math.sin(a)))
    d.polygon(poly, outline=BUB_INK, width=width, fill=(255, 255, 255))


def _curved_tail(d, cx, cy, bw, bh, ta, width, length, curve):
    """Curved, tapering 'ちょろっと' speech tail. Drawn over the (already-drawn)
    bubble body: a quadratic-bezier spine from inside the bubble out to a flicked
    tip, with width tapering to a point. White fill hides the body's edge arc;
    only the portion OUTSIDE the body is stroked so it reads as one shape."""
    bx = cx + bw * 0.84 * math.cos(ta)              # spine start (inside the body)
    by = cy + bh * 0.84 * math.sin(ta)
    ex = cx + bw * math.cos(ta) + math.cos(ta) * length   # tip (flicked by curve)
    ey = cy + bh * math.sin(ta) + math.sin(ta) * length
    perx, pery = -math.sin(ta), math.cos(ta)
    ctrlx = (bx + ex) / 2 + perx * curve
    ctrly = (by + ey) / 2 + pery * curve
    ex += perx * curve * 0.9                         # tip flicks toward the curve
    ey += pery * curve * 0.9
    N = 18
    left, right = [], []
    for i in range(N + 1):
        t = i / N
        sx = (1 - t) ** 2 * bx + 2 * (1 - t) * t * ctrlx + t * t * ex
        sy = (1 - t) ** 2 * by + 2 * (1 - t) * t * ctrly + t * t * ey
        tgx = 2 * (1 - t) * (ctrlx - bx) + 2 * t * (ex - ctrlx)
        tgy = 2 * (1 - t) * (ctrly - by) + 2 * t * (ey - ctrly)
        tl = math.hypot(tgx, tgy) or 1
        nx, ny = -tgy / tl, tgx / tl
        w = width * 0.5 * (1 - t) ** 1.15           # taper to a point
        left.append((sx + nx * w, sy + ny * w))
        right.append((sx - nx * w, sy - ny * w))
    d.polygon(left + right[::-1], fill=(255, 255, 255))

    def outside(p):
        return ((p[0] - cx) / bw) ** 2 + ((p[1] - cy) / bh) ** 2 > 1.0
    for edge in (left, right):
        seg = []
        for p in edge:
            if outside(p):
                seg.append(p)
            elif len(seg) >= 2:
                d.line(seg, fill=BUB_INK, width=3, joint="curve"); seg = []
            else:
                seg = []
        if len(seg) >= 2:
            d.line(seg, fill=BUB_INK, width=3, joint="curve")


def _place_bubble(img, box, b, font, placed=None, faces_px=None, others=None):
    """吹き出しの最終ジオメトリを計算(描画しない): 自動サイズ + 四隅/連結配置 +
    顔/他バブル回避 + 重なれば縮小。戻り値 geom dict(cx,cy,bw,bh,…)。描画は
    _render_bubble、グローバルな重なり解消は render_page の relaxation が行う。"""
    shape = b.get("shape", "round")
    x0, y0, x1, y1 = box
    pw, ph = x1 - x0, y1 - y0
    bw = (b.get("sizeW", 360) / 1000) * pw / 2
    bh = (b.get("sizeH", 300) / 1000) * ph / 2
    # ── FIT CONSTRAINT (はみ出し再発防止) ─────────────────────────────────
    # テキスト量から必要サイズを算出 → 吹き出しをコマ内上限まで自動拡大 →
    # 上限でも入らなければフォントを縮小。これで文字は常に吹き出し内に収まる。
    role = b.get("font") or SHAPE_FONT.get(shape, "antigochi")
    _bf, sim = _role_font(role, font.size)
    cols = b.get("lines") or wrap_jp(b.get("text", ""), b.get("maxCharsPerCol", 6))
    ncols = max(1, len(cols))
    nrows = max((len(c) for c in cols), default=1)
    fs = font.size
    blk_w, blk_h = ncols * (fs + 5), nrows * (fs + 3)
    usable = 0.86 if shape in ("rect", "whisper") else 0.72   # 余白を確保(文字が縁に触れない)
    pad = fs * 0.85
    autofit = b.get("autofit", "fit") != "off"
    if autofit:
        # 吹き出しサイズ=文字ブロック+余白(文字量に比例)。固定最小を撤廃して短文が巨大化
        # しないようにする。HxH 風に内側余白(usable)を確保。上限でデカすぎを抑制。
        capw, caph = (0.42, 0.40) if shape in ("rect", "whisper") else (0.34, 0.34)
        # 小さすぎ floor(1〜2字でも潰れない最小)。
        fl_w, fl_h = pw * 0.05 + pad, ph * 0.045 + pad
        bw = min(max(fl_w, (blk_w / 2 + pad) / usable), pw * capw)
        bh = min(max(fl_h, (blk_h / 2 + pad) / usable), ph * caph)
    # ── 配置 + 衝突回避: 連結→直前バブルの左へ / 他は四隅アンカー。顔 + 既出の
    # 他吹き出し(ページ全体)から押し出し、それでも重なるなら吹き出しを縮小して
    # 重なりを解消する(データ構造=配置の衝突解消)。連結は鎖を保つため対象外。 ──
    link = b.get("linkTo")
    linked = link is not None and placed is not None and link in placed
    anchor = "free" if linked else b.get("anchor", "free")
    _OH = {"top-right": 24, "top-left": 18, "bottom-right": 18, "bottom-left": 18,
           "top": 12, "bottom": 12, "center": 0}
    obstacles = list(faces_px or [])                     # 全ての顔を回避(誰の顔も覆わない)
    if others and not linked:
        obstacles += [(ocx - obw, ocy - obh, 2 * obw, 2 * obh)   # (cx,cy,bw,bh)→(x,y,w,h)
                      for (ocx, ocy, obw, obh) in others]
    W, H = img.size

    def _place(bw, bh):
        if linked:
            pcx, pcy, pbw, pbh = placed[link]
            ov = min(bw, pbw) * 0.12                       # 連結のため少し重ねる
            cx = pcx - pbw - bw + ov                       # RTL: 直前の左へ
            cy = min(y1 - bh, max(y0 + bh, pcy + pbh * 0.16))
        elif anchor != "free":
            oh = b.get("overhang", _OH.get(anchor, 0)) / 100.0
            cx = (x1 - bw * (1 - oh) if "right" in anchor else
                  x0 + bw * (1 - oh) if "left" in anchor else (x0 + x1) / 2)
            cy = (y0 + bh * (1 - oh) if "top" in anchor else
                  y1 - bh * (1 - oh) if "bottom" in anchor else (y0 + y1) / 2)
        else:
            cx, cy = _ppx(box, b.get("posX", 500), b.get("posY", 200))
        if obstacles and not linked:                       # 顔/他バブルから押し出す
            for _ in range(24):
                worst, wov = None, 0.0
                for f in obstacles:
                    ix = max(0, min(cx + bw, f[0] + f[2]) - max(cx - bw, f[0]))
                    iy = max(0, min(cy + bh, f[1] + f[3]) - max(cy - bh, f[1]))
                    if ix * iy > wov:
                        wov, worst = ix * iy, f
                if not worst or wov < bw * bh * 0.02:
                    break
                vx, vy = cx - (worst[0] + worst[2] / 2), cy - (worst[1] + worst[3] / 2)
                vl = math.hypot(vx, vy) or 1
                if vl < 1:
                    vx, vy, vl = 0, 1, 1
                cx += vx / vl * min(bw, bh) * 0.55
                cy += vy / vl * min(bw, bh) * 0.55
            cx = max(x0 - bw * 0.9, min(x1 + bw * 0.9, cx))
            cy = max(y0 - bh * 0.9, min(y1 + bh * 0.9, cy))
        cx = max(bw + 6, min(W - bw - 6, cx))              # ページ端(文字切れ防止)
        cy = max(bh + 6, min(H - bh - 6, cy))
        resid = 0.0                                        # 残存重なり率(最大)
        for f in obstacles:
            ix = max(0, min(cx + bw, f[0] + f[2]) - max(cx - bw, f[0]))
            iy = max(0, min(cy + bh, f[1] + f[3]) - max(cy - bh, f[1]))
            resid = max(resid, ix * iy / (4 * bw * bh))
        return cx, cy, resid

    scale, cx, cy = 1.0, (x0 + x1) / 2, (y0 + y1) / 2
    for _ in range(6):                                     # 重なれば縮小して再配置
        cx, cy, resid = _place(bw * scale, bh * scale)
        if linked or resid < 0.16 or bw * scale < pw * 0.12:
            break
        scale *= 0.85
    bw, bh = bw * scale, bh * scale
    avail_w = bw * 2 * usable - pad * 2                    # 最終サイズで文字を再フィット
    avail_h = bh * 2 * usable - pad * 2
    # 文字下限はパネル相対(読める最小 ≒ コマ短辺の2.6%)。小さすぎ防止。
    floor_fs = max(13, int(min(pw, ph) * 0.026))
    fit_fs = max(floor_fs, int(fs * min(1.0, avail_w / max(1, blk_w), avail_h / max(1, blk_h))))
    return {"cx": cx, "cy": cy, "bw": bw, "bh": bh, "shape": shape, "cols": cols,
            "role": role, "sim": sim, "fit_fs": fit_fs, "anchor": anchor, "linked": linked}


def draw_bubble(img, box, b, font, label_font, placed=None, faces_px=None, others=None):
    """互換ラッパ: 配置→描画を一括(単体プレビュー用)。ページ全体の重なり解消が
    必要な本番経路は render_page が _place_bubble → relaxation → _render_bubble を使う。"""
    g = _place_bubble(img, box, b, font, placed, faces_px, others)
    _render_bubble(img, box, b, g, label_font)
    return (g["cx"], g["cy"], g["bw"], g["bh"])


def _render_bubble(img, box, b, g, label_font):
    """確定 geom(g)で吹き出しを描画。relaxation 後の cx/cy を反映するため bb と尻尾
    角度 ta はここで再計算する。"""
    d = ImageDraw.Draw(img)
    cx, cy, bw, bh = g["cx"], g["cy"], g["bw"], g["bh"]
    shape, cols, role, sim, fit_fs = g["shape"], g["cols"], g["role"], g["sim"], g["fit_fs"]
    anchor, linked = g["anchor"], g["linked"]
    x0, y0, x1, y1 = box
    bb = [cx - bw, cy - bh, cx + bw, cy + bh]
    ta = 0.0
    # 連結バブルは尻尾なし(先頭だけ話者へ)。叫びはトゲが向きなので尻尾なし。
    has_tail = shape not in ("thought", "rect", "whisper", "spiky", "burst") and not linked \
        and (b.get("tailX") is not None or anchor not in ("free", "center"))
    if has_tail:
        if b.get("tailX") is not None:               # 顔の口元など明示ターゲット優先
            tx, ty = _ppx(box, b["tailX"], b.get("tailY", 900))
            ta = math.atan2(ty - cy, tx - cx)
        elif anchor not in ("free", "center"):
            ta = math.atan2((y0 + y1) / 2 - cy, (x0 + x1) / 2 - cx)
    if shape in ("round", "oval"):                      # 少し有機的な楕円 (風船回避)
        _bubble_outline(d, cx, cy, bw, bh,
                        lambda a: 1 + 0.024 * math.sin(5 * a + 0.6) + 0.014 * math.cos(8 * a + 1.1),
                        None)
    elif shape == "wavy":
        _bubble_outline(d, cx, cy, bw, bh, lambda a: 1 + 0.05 * math.sin(11 * a), None)
    elif shape in ("spiky", "burst"):                   # トゲを不揃いに → 自然な叫び
        spikes = 15 if shape == "spiky" else 13
        inner = 0.56 if shape == "spiky" else 0.62
        srnd = _random.Random(int(cx * 7 + cy * 13) or 1)
        pts = []
        for k in range(spikes * 2):
            a = math.pi * k / spikes - math.pi / 2 + srnd.uniform(-0.06, 0.06)
            rr = srnd.uniform(0.9, 1.15) if k % 2 == 0 else inner * srnd.uniform(0.88, 1.08)
            pts.append((cx + bw * rr * math.cos(a), cy + bh * rr * math.sin(a)))
        d.polygon(pts, outline=BUB_INK, width=3, fill=(255, 255, 255))
    elif shape in ("cloud", "thought"):
        N = 9                                            # puffy lobes (smooth)
        pts = []
        for k in range(N * 14):
            a = 2 * math.pi * k / (N * 14)
            rr = 1 + 0.17 * (math.cos(N * a) * 0.5 + 0.5) ** 1.4 - 0.04
            pts.append((cx + bw * rr * math.cos(a), cy + bh * rr * math.sin(a)))
        d.polygon(pts, outline=BUB_INK, width=3, fill=(255, 255, 255))
        if shape == "thought":
            tx, ty = _ppx(box, b.get("tailX", 400), b.get("tailY", 900))
            for k, s in enumerate((12, 8, 5)):
                ex, ey = cx + (tx - cx) * (0.5 + 0.25 * k), cy + (ty - cy) * (0.5 + 0.25 * k)
                d.ellipse([ex - s, ey - s, ex + s, ey + s], outline=BUB_INK, width=2,
                          fill=(255, 255, 255))
    elif shape == "rect":
        d.rectangle(bb, outline=BUB_INK, width=3, fill=(255, 255, 255))
    elif shape == "whisper":
        r = int(min(bb[2] - bb[0], bb[3] - bb[1]) * 0.18)
        d.rounded_rectangle(bb, radius=max(2, r), fill=(255, 255, 255))   # 白塗り=可読(暗い絵でも読める)
        _dashed_rect(d, bb, BUB_INK, 2)                                    # 点線枠=小声/独白
    elif shape == "jagged":
        pts = []
        for k in range(24):
            a = math.radians(k * 15)
            rr = 1.0 if k % 2 == 0 else 0.8
            pts.append((cx + bw * rr * math.cos(a), cy + bh * rr * math.sin(a)))
        d.polygon(pts, outline=BUB_INK, width=2, fill=(255, 255, 255))
    # curved, tapering tail (ちょろん) — bezier curve is the default; short flick
    if has_tail:
        u = min(bw, bh)
        tw = b.get("tailWidth", 340) / 1000.0 * u
        tl = b.get("tailLen", 333) / 1000.0 * u        # 短いちょろん (旧の約1/3)
        tc = b.get("tailCurve", 260) / 1000.0 * tl     # ベジェ既定カーブ
        _curved_tail(d, cx, cy, bw, bh, ta, tw, tl, tc)
    # text rendered at fit_fs (computed above) so it never overflows the bubble
    bfont, _ = _role_font(role, fit_fs)
    _vtext_lines(d, cx, cy, cols, bfont, BUB_INK, sim, img)
    if os.environ.get("KOMA_CLEAN") != "1" and os.environ.get("KOMA_READ") != "1":
        d.text((bb[0] + 3, bb[1] - 18), f"{SHAPE_JP.get(shape, shape)}·{role}",  # 校正ラベル
               font=label_font, fill=(150, 60, 160))
    return (cx, cy, bw, bh)


def _taper(im, near=1.0, far=0.6):
    """Vertically taper a glyph strip along +x (near→far) — perspective ゆがみ."""
    w, h = im.size
    if abs(near - far) < 0.02 or w < 4:
        return im
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    strips = max(10, w // 6)
    for i in range(strips):
        xa, xb = int(w * i / strips), int(w * (i + 1) / strips)
        if xb <= xa:
            continue
        f = near + (far - near) * (i / strips)
        nh = max(1, int(h * f))
        st = im.crop((xa, 0, xb, h)).resize((xb - xa, nh), Image.BICUBIC)
        out.paste(st, (xa, (h - nh) // 2), st)
    return out


def _sfx_flow(box, s, panel):
    """(angle_rad|None, intensity 0..1, vanish_px|None) — the motion/time axis the
    SFX warps + scales along. Priority: explicit flowDir → speed/motion 効果線 →
    focus/explosion vanishing point → gaze entry→exit (時間軸) → sfx.rotation."""
    if s.get("flowDir") is not None:
        return math.radians(s["flowDir"]), 0.7, None
    els = (panel or {}).get("effectLines") or []
    for e in els:
        if e.get("kind") in ("speed", "motion-blur") and e.get("direction") is not None:
            return math.radians(e["direction"]), 0.95, None
    for e in els:
        if e.get("kind") == "vertical":                # 縦線 → 下方向に積む (ゴゴゴ)
            return math.radians(90), 0.5, None
    for e in els:
        if e.get("kind") in ("focus", "explosion", "flash", "shock"):
            return None, 0.9, _ppx(box, e.get("centerX", 500), e.get("centerY", 500))
    g = (panel or {}).get("gaze") or {}
    if "exitX" in g and "entryX" in g:
        return math.atan2(g["exitY"] - g["entryY"], g["exitX"] - g["entryX"]), 0.55, None
    if s.get("rotation"):
        return math.radians(-s["rotation"]), 0.3, None
    return None, 0.0, None


def _ease(t, kind, bez=None):
    t = max(0.0, min(1.0, t))
    if kind == "bezier" and bez and len(bez) >= 4:            # カスタム cubic-bezier
        x1, y1, x2, y2 = [v / 1000.0 for v in bez[:4]]
        lo, hi = 0.0, 1.0
        for _ in range(22):                                   # solve bx(u)=t (bisection)
            u = (lo + hi) / 2
            bx = 3 * (1 - u) ** 2 * u * x1 + 3 * (1 - u) * u * u * x2 + u ** 3
            lo, hi = (u, hi) if bx < t else (lo, u)
        u = (lo + hi) / 2
        return 3 * (1 - u) ** 2 * u * y1 + 3 * (1 - u) * u * u * y2 + u ** 3
    if kind == "ease-in":     return t * t
    if kind == "ease-out":    return 1 - (1 - t) * (1 - t)
    if kind == "ease-in-out": return t * t * (3 - 2 * t)
    if kind == "exp-in":      return (math.exp(3 * t) - 1) / (math.exp(3) - 1)
    if kind == "exp-out":     return (1 - math.exp(-3 * t)) / (1 - math.exp(-3))
    return t                                                   # linear


def draw_sfx(img, box, s, font_path, panel=None):
    pw, ph = box[2] - box[0], box[3] - box[1]
    cx, cy = _ppx(box, s.get("posX", 500), s.get("posY", 500))
    base = max(13, min(pw, ph) * 0.15 * s.get("scale", 100) / 100.0)
    style = s.get("style", "impact")
    lines = s.get("lines") or ([s.get("text", "")] if s.get("text") else [])   # 行ごと
    if not any(lines):
        return
    role = s.get("font") or SFX_FONT.get(style, "gothic")
    fill = SFX_STYLE.get(style, (15, 15, 18))
    halo = (255, 255, 255) if style != "silence" else fill

    ang0, inten, vanish = _sfx_flow(box, s, panel)
    s0 = s.get("scaleStart", round(100 - 45 * inten)) / 100.0
    s1 = s.get("scaleEnd", round(100 + 60 * inten)) / 100.0
    easing = s.get("easing", "ease-in" if vanish is not None else "linear")
    bez = s.get("bezier")
    spread = s.get("spread", round((70 if vanish is not None else 25) * inten)) / 100.0
    skew = s.get("skew", int(20 * inten)) / 100.0
    rotj = s.get("rotJitter", 13 if role == "horror" else 0)
    rays = max(1, min(24, s.get("rays", 1)))                   # 多方向放射の本数
    ray_arc = math.radians(s.get("rayArc", 360))
    rnd = _random.Random(99)

    burst0 = s.get("burst")
    if vanish is not None and burst0 is None:
        kinds = {e.get("kind") for e in (panel or {}).get("effectLines") or []}
        burst0 = "diverge" if kinds & {"explosion", "flash", "shock"} else "converge"

    def base_angle(burst):
        if vanish is not None:
            vx, vy = vanish
            d0 = (cx - vx, cy - vy) if burst != "converge" else (vx - cx, vy - cy)
            return math.radians(-25) if math.hypot(*d0) < 2 else math.atan2(d0[1], d0[0])
        return ang0 if ang0 is not None else math.radians(-s.get("rotation", 0))

    L = len(lines)
    for li, line in enumerate(lines):
        if not line:
            continue
        lb = (("converge", "diverge")[li % 2]) if burst0 == "alternate" else burst0   # 行ごと収束/拡散
        n = len(line)
        sizes = [base * (s0 + (s1 - s0) * _ease(0 if n == 1 else i / (n - 1), easing, bez))
                 for i in range(n)]
        cum, acc = [], 0.0
        for gs in sizes:
            cum.append(acc + gs / 2); acc += gs
        run = acc * 1.04
        ba = base_angle(lb)
        if vanish is not None:
            ax, ay = vanish
            anchor_c = cum[0] if lb == "diverge" else cum[-1]
        else:
            ax, ay, anchor_c = cx, cy, run / 2
        line_off = (li - (L - 1) / 2) * base * ((s0 + s1) / 2) * 1.25   # 行の直交スタック
        for r in range(rays):
            rang = ba + (0 if rays == 1 else (r / rays) * ray_arc)      # 放射状に回転複製
            dx, dy = math.cos(rang), math.sin(rang)
            nx, ny = -dy, dx
            bx0 = ax - dx * anchor_c + nx * line_off
            by0 = ay - dy * anchor_c + ny * line_off
            for i, ch in enumerate(line):
                gs = sizes[i]
                gcx, gcy = bx0 + dx * cum[i], by0 + dy * cum[i]
                frac = 0.0 if n == 1 else (i / (n - 1) - 0.5)
                gx, gy = gcx + nx * spread * run * frac, gcy + ny * spread * run * frac
                gf, _ = _role_font(role, max(8, int(gs)))
                s2 = int(gs * 2.4) + 10
                tmp = Image.new("RGBA", (s2, s2), (0, 0, 0, 0))
                ImageDraw.Draw(tmp).text((s2 / 2 - gs / 2, s2 / 2 - gs * 0.62), ch, font=gf,
                                         fill=fill, stroke_width=max(2, int(gs * 0.085)),
                                         stroke_fill=halo)
                if abs(skew) > 0.02:
                    try:
                        w, h = tmp.size
                        c = 0.0 if skew > 0 else abs(skew) * h
                        tmp = tmp.transform((w + int(abs(skew) * h), h), Image.AFFINE,
                                            (1, -skew, c, 0, 1, 0), resample=Image.BICUBIC)
                    except Exception:
                        pass
                # 文字は基本『正立』(縦に積むゴゴゴ等が横倒しにならない)。放射
                # (rays>1) か glyphTilt='axis' のときだけ軸方向へ回す。
                axis_tilt = rays > 1 or s.get("glyphTilt") == "axis"
                deg = (-math.degrees(rang) if axis_tilt else 0) + \
                      (rnd.randint(-rotj, rotj) if rotj else 0)
                if abs(deg) > 0.5:
                    tmp = tmp.rotate(deg, expand=True, resample=Image.BICUBIC)
                img.paste(tmp, (int(gx - tmp.width / 2), int(gy - tmp.height / 2)), tmp)


def draw_title(img, box, title, font_path):
    """扉タイトルを写植(ベクター文字)として negative-space に組む。gemini に焼かせず、
    work/chapter のタイトル文字列(データ)から renderer が描く。縦書き主タイトル + 小さな
    シリーズ柱 + 任意のサブ(tagline)。暗い絵の上でも読めるよう太い白抜き(黒縁)。"""
    if not title or not title.get("text"):
        return
    x0, y0, x1, y1 = box
    pw, ph = x1 - x0, y1 - y0
    text = title["text"]
    series = title.get("series", "")
    tagline = title.get("tagline", "")
    place = title.get("placement", "right")            # negative-space 側
    scale = title.get("scale", 78) / 100.0             # 主タイトル高 = パネル高の割合
    dark = title.get("color", "white") != "black"
    ink = (250, 250, 250) if dark else (16, 16, 18)
    edge = (12, 12, 14) if dark else (250, 250, 250)
    role = title.get("font", "bold-mincho")            # 扉=太明朝が既定(荘厳)
    # 縦書き主タイトル: 横長コマでは細くならないよう複数列に折る。列数を増やして
    # 1文字を大きく保つ(col高=ph*scale に収まる最小列数)。
    avail_h = ph * scale
    n = max(1, len(text))
    # 列数を 1..3 で試し、negative-space 幅(pw*0.5)に収まる範囲で 1 文字が最大になる
    # レイアウトを採る。横長コマ→2-3列で大きく、縦長コマ→1列。
    best = (20, 1, n)
    for nc in range(1, 4):
        per = math.ceil(n / nc)
        fs = int(min(avail_h / per, pw * 0.20))
        if (nc * fs * 1.18 <= pw * 0.5 or nc == 1) and fs > best[0]:
            best = (fs, nc, per)
    fs, ncol, per = best
    tf, _ = _role_font(role, fs)
    gap = int(fs * 0.06)
    ch_h = fs + gap
    margin = int(min(pw, ph) * 0.05)
    d = ImageDraw.Draw(img)
    sw = max(3, int(fs * 0.10))                         # 黒縁の太さ
    # RTL: 1列目を最も右(or 左placement なら最も左)に、以降内側へ。
    col_w = fs * 1.18
    for ci in range(ncol):
        seg = text[ci * per:(ci + 1) * per]
        if place == "right":
            cx = x1 - margin - fs / 2 - ci * col_w
        else:
            cx = x0 + margin + fs / 2 + ci * col_w
        cy0 = y0 + (ph - len(seg) * ch_h) / 2 + (ph * 0.04)
        for i, c in enumerate(seg):
            d.text((cx, cy0 + i * ch_h), c, font=tf, fill=ink, anchor="ma",
                   stroke_width=sw, stroke_fill=edge)
    # series/tagline 位置の基準に最終列の cx を使う
    cx = (x1 - margin - fs / 2 - (ncol - 1) * col_w) if place == "right" \
        else (x0 + margin + fs / 2 + (ncol - 1) * col_w)
    cy0 = y0 + (ph - per * ch_h) / 2 + (ph * 0.04)
    # シリーズ柱(小・横): 主タイトル列の外側上方
    if series:
        sf, _ = _role_font("gothic", max(12, int(fs * 0.26)))
        sx = (cx - fs * 0.8) if place == "right" else (cx + fs * 0.8)
        d.text((sx, cy0 - sf.size * 1.4), series, font=sf, fill=ink, anchor="ma",
               stroke_width=max(2, sw // 2), stroke_fill=edge)
    # tagline(小・縦): 主タイトルの内側にもう一列
    if tagline:
        gf, _ = _role_font("mincho", max(13, int(fs * 0.30)))
        gx = (cx - fs * 1.15) if place == "right" else (cx + fs * 1.15)
        gh = gf.size + int(gf.size * 0.08)
        gy0 = y0 + (ph - len(tagline) * gh) / 2 + (ph * 0.04)
        for i, ch in enumerate(tagline):
            d.text((gx, gy0 + i * gh), ch, font=gf, fill=ink, anchor="ma",
                   stroke_width=max(2, sw // 2), stroke_fill=edge)


def _relax_bubbles(items, size, passes=150):
    """ページ全体の吹き出しを力学的に分離(重なりをデータ的に解消)。非連結バブルは
    互いの重なり + 顔から反発して移動し、各自パネル±0.9・ページ内にクランプ。連結
    バブルは毎パス head の現在位置にスナップ(鎖を保持)。同一鎖どうしは反発しない。"""
    W, H = size

    def _cxb(cx, bw):                                        # 外枠(board)横内にクランプ→見切れ防止
        return max(bw + 6, min(W - bw - 6, cx))

    def _cyb(cy, bh):                                        # 外枠縦内(caption band CAP の下〜board底)
        return max(CAP + bh + 6, min(H - bh - 6, cy))
    heads = [it for it in items if not it["g"]["linked"]]
    for _ in range(passes):
        for it in heads:
            g = it["g"]
            cx, cy, bw, bh = g["cx"], g["cy"], g["bw"], g["bh"]
            fx = fy = 0.0
            for jt in items:
                if jt is it or jt["root"] is it["root"]:    # 自分/同一鎖は除外
                    continue
                h = jt["g"]
                ix = min(cx + bw, h["cx"] + h["bw"]) - max(cx - bw, h["cx"] - h["bw"])
                iy = min(cy + bh, h["cy"] + h["bh"]) - max(cy - bh, h["cy"] - h["bh"])
                if ix > 0 and iy > 0:                       # 重なり→小さい侵入軸で押し離す
                    if ix <= iy:
                        fx += ix if cx >= h["cx"] else -ix
                    else:
                        fy += iy if cy >= h["cy"] else -iy
            for f in it["faces"]:                           # 顔は強く避ける(覆わない=最優先)
                ix = min(cx + bw, f[0] + f[2]) - max(cx - bw, f[0])
                iy = min(cy + bh, f[1] + f[3]) - max(cy - bh, f[1])
                if ix > 0 and iy > 0:
                    fcx, fcy = f[0] + f[2] / 2, f[1] + f[3] / 2
                    if ix <= iy:
                        fx += (ix if cx >= fcx else -ix) * 1.4
                    else:
                        fy += (iy if cy >= fcy else -iy) * 1.4
            if fx == 0 and fy == 0:
                continue
            cx, cy = cx + fx * 0.5, cy + fy * 0.5
            x0, y0, x1, y1 = it["box"]
            # 所属パネル拘束: 吹き出し中心は所属コマ内に留める(隣コマへ流出=セリフが
            # 別パネルに乗る問題を防ぐ)。少しだけ margin を許容。
            mx, my = bw * 0.25, bh * 0.25
            cx = max(x0 - mx, min(x1 + mx, cx))
            cy = max(y0 - my, min(y1 + my, cy))
            g["cx"] = _cxb(cx, bw)
            g["cy"] = _cyb(cy, bh)
        for it in items:                                    # 連結バブルを head にスナップ
            if not it["g"]["linked"] or not it["head"]:
                continue
            hg, g = it["head"]["g"], it["g"]
            g["cx"] = _cxb(hg["cx"] - hg["bw"] - g["bw"] + min(g["bw"], hg["bw"]) * 0.12, g["bw"])
            x0, y0, x1, y1 = it["box"]
            g["cy"] = _cyb(min(y1 - g["bh"], max(y0 + g["bh"], hg["cy"] + hg["bh"] * 0.16)), g["bh"])
    # 最終: 顔から強制退避 — どのバブルも顔を覆わない(bubble_integration / 可読性)。
    # 候補出口は「全顔に対する合計被り」を最小化する位置を選ぶ(別の顔へ飛び移る振動を防ぐ)。
    def _face_cov(cx, cy, bw, bh, faces):
        tot = 0.0
        for f in faces:
            ix = min(cx + bw, f[0] + f[2]) - max(cx - bw, f[0])
            iy = min(cy + bh, f[1] + f[3]) - max(cy - bh, f[1])
            if ix > 0 and iy > 0:
                tot += ix * iy
        return tot

    def _bub_ov(cx, cy, bw, bh, it):                         # 他バブル(別鎖)との合計重なり
        tot = 0.0
        for jt in items:
            if jt is it or jt["root"] is it["root"]:
                continue
            h = jt["g"]
            ix = min(cx + bw, h["cx"] + h["bw"]) - max(cx - bw, h["cx"] - h["bw"])
            iy = min(cy + bh, h["cy"] + h["bh"]) - max(cy - bh, h["cy"] - h["bh"])
            if ix > 0 and iy > 0:
                tot += ix * iy
        return tot

    for it in heads:
        g, bw, bh = it["g"], it["g"]["bw"], it["g"]["bh"]
        x0, y0, x1, y1 = it["box"]
        for _ in range(40):
            cur = _face_cov(g["cx"], g["cy"], bw, bh, it["faces"]) + _bub_ov(g["cx"], g["cy"], bw, bh, it)
            worst, wov = None, 0.0
            for f in it["faces"]:
                ix = min(g["cx"] + bw, f[0] + f[2]) - max(g["cx"] - bw, f[0])
                iy = min(g["cy"] + bh, f[1] + f[3]) - max(g["cy"] - bh, f[1])
                if ix > 0 and iy > 0 and ix * iy > wov:
                    wov, worst = ix * iy, f
            fa = (worst[2] * worst[3]) if worst else 1.0
            if not worst or (wov < 0.05 * 4 * bw * bh and wov < 0.15 * fa):
                break                                        # bubble側/顔側どちらも軽微なら終了
            fx0, fy0, fw, fh = worst
            cand = [(g["cx"], fy0 - bh - 5), (g["cx"], fy0 + fh + bh + 5),
                    (fx0 - bw - 5, g["cy"]), (fx0 + fw + bw + 5, g["cy"])]
            cand = [(_cxb(ex, bw), _cyb(ey, bh)) for ex, ey in cand]
            # 顔被り + 他バブル重なり の合計を最小化する出口を選ぶ(顔回避が新たな重なりを生むのを防ぐ)
            def _cost(e):
                return (_face_cov(e[0], e[1], bw, bh, it["faces"]) + _bub_ov(e[0], e[1], bw, bh, it),
                        (e[0] - g["cx"]) ** 2 + (e[1] - g["cy"]) ** 2)
            ex, ey = min(cand, key=_cost)
            if _cost((ex, ey))[0] >= cur - 1.0:
                break                                        # どこへ動いても改善しない→諦める
            g["cx"], g["cy"] = ex, ey
    for it in items:                                        # 退避後も連結を再スナップ
        if not it["g"]["linked"] or not it["head"]:
            continue
        hg, g = it["head"]["g"], it["g"]
        g["cx"] = _cxb(hg["cx"] - hg["bw"] - g["bw"] + min(g["bw"], hg["bw"]) * 0.12, g["bw"])
        x0, y0, x1, y1 = it["box"]
        g["cy"] = _cyb(min(y1 - g["bh"], max(y0 + g["bh"], hg["cy"] + hg["bh"] * 0.16)), g["bh"])
        # 連結バブルも顔を覆ったら顔の下(無理なら上)へ縦にずらす(可読性最優先)
        for f in it["faces"]:
            ix = min(g["cx"] + g["bw"], f[0] + f[2]) - max(g["cx"] - g["bw"], f[0])
            iy = min(g["cy"] + g["bh"], f[1] + f[3]) - max(g["cy"] - g["bh"], f[1])
            if ix > 0 and iy > 0 and ix * iy > 0.15 * (f[2] * f[3]):
                below = f[1] + f[3] + g["bh"] + 5
                above = f[1] - g["bh"] - 5
                g["cy"] = _cyb(below if below <= y1 - g["bh"] else max(y0 + g["bh"], above), g["bh"])
                break
    # 設計原則: 吹き出しは所属コマに完全格納(隣コマへ drift しない)。最終ハード格納パス。
    for it in items:
        g = it["g"]
        bw, bh = g["bw"], g["bh"]
        x0, y0, x1, y1 = it["box"]
        m = 3
        g["cx"] = (x0 + x1) / 2 if (x1 - x0) <= 2 * bw + 2 * m else max(x0 + bw + m, min(x1 - bw - m, g["cx"]))
        g["cy"] = (y0 + y1) / 2 if (y1 - y0) <= 2 * bh + 2 * m else max(y0 + bh + m, min(y1 - bh - m, g["cy"]))


def render_page(page: dict) -> Image.Image:
    geom = page.get("printGeometry") or {}
    tw, th = TRIM_MM.get(geom.get("trimSize", "b5"), TRIM_MM["b5"])
    W = int(BOARD_H * tw / th)
    H = BOARD_H
    img = Image.new("RGB", (W, H + CAP), "white")
    d = ImageDraw.Draw(img)

    # KOMA_READ=1 = 通し読み用クリーン出力(視線矢印・shot ラベル・読み順番号・キャプション帯・
    # trim/safe 補助線・断ち切りラベルを全て隠し、コマ絵+SFX+吹き出し+扉タイトルだけ残す)。
    # KOMA_CLEAN=1(既定の cut-design レビュー出力)は注釈を残し顔ボックスのみ隠す。
    read_mode = os.environ.get("KOMA_READ") == "1"
    _dflt = not read_mode
    show_gaze = page.get("_showGaze", _dflt)
    show_path = page.get("_showPath", _dflt)
    show_shot = page.get("_showShotBox", _dflt)
    f_layer = _font(16, "W3")
    sfx_font_path = next((p for p in ("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
                                      "/System/Library/Fonts/Hiragino Sans GB.ttc")
                          if Path(p).exists()), "/System/Library/Fonts/Helvetica.ttc")

    def bx(p): return p / 1000.0 * W            # board-permille x → px
    def by(p): return CAP + p / 1000.0 * H       # board-permille y → px (offset by caption)

    # ── caption band ──────────────────────────────────────────────────────
    rh = page.get("rhythm") or {}
    f_title = _font(34, "W6")
    f_meta = _font(24, "W3")
    bleed = geom.get("bleedPermille", 0)
    f_lab = _font(20, "W6")
    f_small = _font(18, "W3")
    if not read_mode:
        d.rectangle([0, 0, W, CAP], fill=(248, 248, 250), outline=(210, 210, 214))
        d.text((20, 12), f"p{page.get('pageNum','?')}  {page.get('pageTitle','')}",
               font=f_title, fill=INK)
        meta = (f"tempo={rh.get('tempo','-')}   opensOn={rh.get('opensOn','-')}   "
                f"climax=p{rh.get('climaxPanelOrder','-')}   "
                f"readingPath={'→'.join(map(str, rh.get('readingPath', [])))}   "
                f"trim={geom.get('trimSize','b5')}  bleed={geom.get('bleedPermille',0)}‰")
        d.text((20, 60), meta, font=f_meta, fill=(70, 70, 80))

        # ── board / trim / safe frames(レビュー時のみ)─────────────────────
        d.rectangle([0, CAP, W - 1, CAP + H - 1], outline=(180, 180, 184), width=2)  # 外枠
        trim_box = [bx(bleed), by(bleed), bx(1000 - bleed), by(1000 - bleed)]
        d.rectangle(trim_box, outline=TRIM_COL, width=2)                              # 仕上がり線
        st = geom.get("safeTop", 0); sr = geom.get("safeRight", 0)
        sb = geom.get("safeBottom", 0); sl = geom.get("safeLeft", 0)
        safe_box = [bx(bleed + sl), by(bleed + st), bx(1000 - bleed - sr), by(1000 - bleed - sb)]
        _dashed_rect(d, safe_box, SAFE_COL, 2)                                        # 基準線/内枠
        d.text((trim_box[0] + 6, trim_box[1] + 4), "仕上がり線 trim", font=f_small, fill=TRIM_COL)
        d.text((safe_box[0] + 6, safe_box[1] + 4), "基準線/内枠 safe", font=f_small, fill=SAFE_COL)

    panels = sorted(page.get("panels", []), key=lambda p: p.get("order", 0))
    centers, placed, face_px = {}, [], []

    # ── panels ────────────────────────────────────────────────────────────
    for p in panels:
        x, y, w, h = p["x"], p["y"], p["w"], p["h"]
        bl = set(p.get("bleed", []))
        x0 = 0 if "left" in bl else bx(x)
        y0 = CAP if "top" in bl else by(y)
        x1 = W if "right" in bl else bx(x + w)
        y1 = (CAP + H) if "bottom" in bl else by(y + h)
        fill = BLEED_FILL if bl else PANEL_FILL
        # 正規版パネル画像があれば COVER 合成、無ければ点描背景
        has_img = False
        imgp = p.get("_imagePath")
        if imgp and os.path.exists(imgp):
            try:
                pim = Image.open(imgp).convert("RGB")
                iw, ih = pim.size
                pw_, ph_ = int(x1 - x0), int(y1 - y0)
                sc = max(pw_ / iw, ph_ / ih)
                pim = pim.resize((max(1, int(iw * sc)), max(1, int(ih * sc))), Image.LANCZOS)
                cx0 = int(p.get("_cropX", 0.5) * (pim.width - pw_))    # 顔寄せクロップ
                cy0 = int(p.get("_cropY", 0.5) * (pim.height - ph_))
                img.paste(pim.crop((cx0, cy0, cx0 + pw_, cy0 + ph_)), (int(x0), int(y0)))
                has_img = True
            except Exception:
                has_img = False
        if not has_img:
            d.rectangle([x0, y0, x1, y1], fill=fill)
        # border on every edge EXCEPT bleed edges (断ち切り → no border, art reaches board)
        bw = 4
        if "top" not in bl:    d.line([(x0, y0), (x1, y0)], fill=INK, width=bw)
        if "right" not in bl:  d.line([(x1, y0), (x1, y1)], fill=INK, width=bw)
        if "bottom" not in bl: d.line([(x1, y1), (x0, y1)], fill=INK, width=bw)
        if "left" not in bl:   d.line([(x0, y1), (x0, y0)], fill=INK, width=bw)

        pw, ph = x1 - x0, y1 - y0
        cx, cy = x0 + pw / 2, y0 + ph / 2
        centers[p["order"]] = (cx, cy)
        pbox = (x0, y0, x1, y1)

        # 検出した顔(データ正規化済) — 配置設計の基準。px 矩形は監査にも使う。
        # ただし極小顔(パネル面積の <MIN_FACE_FRAC)は背景/遠景/誤検出なので吹き出し
        # 配置・監査の対象外(覆っても可読性に影響しない & 避けると配置が過剰拘束される)。
        for f in p.get("faces", []):
            if f[2] * f[3] < MIN_FACE_FRAC * 1_000_000:
                continue
            fx0, fy0 = x0 + f[0] / 1000 * (x1 - x0), y0 + f[1] / 1000 * (y1 - y0)
            fx1, fy1 = x0 + (f[0] + f[2]) / 1000 * (x1 - x0), y0 + (f[1] + f[3]) / 1000 * (y1 - y0)
            face_px.append((fx0, fy0, fx1, fy1))
            if page.get("_showFaces", True) and os.environ.get("KOMA_CLEAN") != "1":
                d.rectangle([fx0, fy0, fx1, fy1], outline=(0, 210, 210), width=2)
                d.text((fx0 + 2, fy0 + 1), "顔", font=f_layer, fill=(0, 170, 170))

        # トーン/効果線 は画像が無いコマのみ(実画像は自前の陰影/効果線を持つ)
        if not has_img:
            for t in p.get("tones", []):
                draw_tone(img, pbox, t, f_layer)
            for e in p.get("effectLines", []):
                draw_fx(img, pbox, e, f_layer)

        # gaze region / focus / entry → exit (視線)
        g = p.get("gaze") or {}
        def gx(v): return x0 + v / 1000.0 * pw
        def gy(v): return y0 + v / 1000.0 * ph
        if show_gaze:
            if {"regionX", "regionY", "regionW", "regionH"} <= g.keys():
                _dashed_rect(d, [gx(g["regionX"]), gy(g["regionY"]),
                                 gx(g["regionX"] + g["regionW"]), gy(g["regionY"] + g["regionH"])],
                             GAZE_REGION, 2)
            if "focusX" in g:
                fx, fy = gx(g["focusX"]), gy(g["focusY"])
                d.ellipse([fx - 9, fy - 9, fx + 9, fy + 9], fill=GAZE_FOCUS)
            if "entryX" in g:
                ex, ey = gx(g["entryX"]), gy(g["entryY"])
                d.ellipse([ex - 11, ey - 11, ex + 11, ey + 11], outline=GAZE_ENTRY, width=4)
            if "exitX" in g and "entryX" in g:
                _arrow(d, (gx(g["entryX"]), gy(g["entryY"])),
                       (gx(g["exitX"]), gy(g["exitY"])), GAZE_EXIT, width=4, head=16)

        # shot label (引き/寄り + scale + move + emphasis)
        sh = p.get("shot") or {}
        fr = sh.get("framing", "neutral")
        acc = FRAMING_COLOR.get(fr, (90, 90, 90))
        fr_jp = {"hiki": "引き", "yori": "寄り", "neutral": "—"}.get(fr, fr)
        if show_shot:
            lab1 = f"#{p['order']} {sh.get('scale','?')} · {fr_jp}"
            lab2 = f"{sh.get('move','static')}  ∠{sh.get('angle','eye')}  e{sh.get('emphasis','-')}"
            imp = g.get("impression")
            d.rectangle([x0 + 6, y0 + 6, x0 + 6 + 250, y0 + 6 + 58], fill=(255, 255, 255), outline=acc, width=2)
            d.text((x0 + 14, y0 + 10), lab1, font=f_lab, fill=acc)
            d.text((x0 + 14, y0 + 34), lab2, font=f_small, fill=(60, 60, 66))
            if imp:
                d.text((x0 + 14, y0 + ph - 28), f"印象:{imp}", font=f_small, fill=GAZE_FOCUS)
        elif not read_mode:                 # コマ番号の丸(レビュー用)。読み用は番号なし
            d.ellipse([x0 + 8, y0 + 8, x0 + 38, y0 + 38], fill=acc)
            d.text((x0 + 16, y0 + 12), str(p["order"]), font=f_lab, fill="white")
        if bl and not read_mode:             # 断ち切りラベルもレビュー用のみ
            tag = f"断ち切り {'/'.join(sorted(bl))}"
            tw_px = d.textbbox((0, 0), tag, font=f_small)[2]
            d.text((min(x1 - 12 - tw_px, W - 16 - tw_px), y1 - 28), tag,
                   font=f_small, fill=(190, 60, 60))

        # セリフ/効果音 はパネル本体描画後に全パネルまとめて上層へ (z順正規化)
        placed.append((p, pbox))

    # ── page reading path (視線遷移 across panels) ─────────────────────────
    if show_path:
        path = rh.get("readingPath") or [p["order"] for p in panels]
        f_num = _font(26, "W6")
        for i, order in enumerate(path):
            if order not in centers:
                continue
            c = centers[order]
            if i + 1 < len(path) and path[i + 1] in centers:
                _arrow(d, c, centers[path[i + 1]], PATH_COL, width=4, head=18)
        for i, order in enumerate(path):
            if order not in centers:
                continue
            cx, cy = centers[order]
            d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=PATH_COL)
            d.text((cx - 7, cy - 14), str(i + 1), font=f_num, fill="white")

    # ── z順 正規化: 効果音(SFX)layer → セリフ(吹き出し)layer を最前面に ──────
    # 背景/トーン < 効果線 < (視線/演出注釈) < SFX < 吹き出し の順で合成。
    for p, pbox in placed:                                   # SFX layer
        for s in p.get("sfx", []):
            draw_sfx(img, pbox, s, sfx_font_path, p)
    for p, pbox in placed:                                   # 扉タイトル写植 layer
        if p.get("title"):
            draw_title(img, pbox, p["title"], sfx_font_path)
    # 吹き出し: ①全配置(_place_bubble) ②グローバル relaxation で重なり解消 ③描画
    items = []
    for p, pbox in placed:
        bpw, bph = pbox[2] - pbox[0], pbox[3] - pbox[1]
        bub_font = _font(max(14, int(min(bpw, bph) * 0.045)), "W6")
        fpx = [(pbox[0] + f[0] / 1000 * bpw, pbox[1] + f[1] / 1000 * bph,
                f[2] / 1000 * bpw, f[3] / 1000 * bph) for f in p.get("faces", [])
               if f[2] * f[3] >= MIN_FACE_FRAC * 1_000_000]   # 極小顔は避けない
        for s in p.get("sfx", []):                            # SFX も障害物に(描き文字と被らない)
            gh = max(0.06, s.get("scale", 100) / 1000.0) * bph
            n = max(1, len(s.get("text", "")))
            sx = pbox[0] + s.get("posX", 300) / 1000 * bpw
            sy = pbox[1] + s.get("posY", 500) / 1000 * bph
            fpx.append((sx - gh * 0.45, sy - gh * n * 0.5, gh * 0.9, gh * n))  # 縦書き縦長box
        pbubs, order_item = {}, {}
        others = [(it["g"]["cx"], it["g"]["cy"], it["g"]["bw"], it["g"]["bh"]) for it in items]
        for b in sorted(p.get("bubbles", []), key=lambda z: z.get("order", 0)):
            g = _place_bubble(img, pbox, b, bub_font, pbubs, fpx, others)
            o = b.get("order", len(pbubs) + 1)
            pbubs[o] = (g["cx"], g["cy"], g["bw"], g["bh"])
            others.append(pbubs[o])
            link = b.get("linkTo")
            head = order_item.get(link) if (link is not None and g["linked"]) else None
            it = {"box": pbox, "b": b, "g": g, "head": head, "faces": fpx}
            it["root"] = head["root"] if head else it
            order_item[o] = it
            items.append(it)
    _relax_bubbles(items, img.size)                          # ページ全体で重なり解消
    for it in items:
        _render_bubble(img, it["box"], it["b"], it["g"], f_layer)

    ov, boxes = 0, [(it["g"]["cx"], it["g"]["cy"], it["g"]["bw"], it["g"]["bh"])
                    for it in items if not it["g"]["linked"]]   # 監査(連結の意図的重なりは除外)
    for i in range(len(boxes)):
        ax, ay, aw, ah = boxes[i]
        for j in range(i + 1, len(boxes)):
            bx, by, bw_, bh_ = boxes[j]
            ix = max(0, min(ax + aw, bx + bw_) - max(ax - aw, bx - bw_))
            iy = max(0, min(ay + ah, by + bh_) - max(ay - ah, by - bh_))
            if ix * iy > 0.25 * min(4 * aw * ah, 4 * bw_ * bh_):
                ov += 1
    # 顔被り監査: 最終配置のセリフ吹き出しが顔矩形を >18% 覆ったら読みづらい
    covered = 0
    for it in items:
        g = it["g"]
        if it["b"].get("shape") in ("rect",):           # ナレ矩形は対象外
            continue
        bx0, by0, bx1, by1 = g["cx"] - g["bw"], g["cy"] - g["bh"], g["cx"] + g["bw"], g["cy"] + g["bh"]
        for fx0, fy0, fx1, fy1 in face_px:
            ix = max(0, min(bx1, fx1) - max(bx0, fx0))
            iy = max(0, min(by1, fy1) - max(by0, fy0))
            farea = max(1.0, (fx1 - fx0) * (fy1 - fy0))
            if ix * iy > 0.18 * farea:
                covered += 1
                break
    # 見切れ監査: 吹き出しが外枠(board)端を >6px はみ出す = 文字が切れる(ユーザ指摘)
    clipped = 0
    for it in items:
        g = it["g"]
        if (g["cx"] - g["bw"] < -6 or g["cx"] + g["bw"] > W + 6
                or g["cy"] - g["bh"] < CAP - 6 or g["cy"] + g["bh"] > CAP + H + 6):
            clipped += 1
    if ov or covered or clipped or os.environ.get("KOMA_METRICS"):
        import sys
        print(f"[metrics] page={page.get('pageNum')} overlap={ov} face_covered={covered} "
              f"clipped={clipped} bubbles={len(items)} faces={len(face_px)}", file=sys.stderr)
    if read_mode:                       # 通し読み: 上部キャプション帯を切り落としコマ面だけに
        img = img.crop((0, CAP, W, CAP + H))
    return img


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(Path(__file__).parent / "sample-komawari-arc0-1.page.json"))
    ap.add_argument("--out", default="/tmp/komawari-blueprint.pdf")
    args = ap.parse_args(argv)

    doc = json.loads(Path(args.inp).read_text())
    pages = doc["pages"] if isinstance(doc, dict) and "pages" in doc else doc
    imgs = [render_page(p) for p in pages]
    if not imgs:
        raise SystemExit("no pages")
    out = Path(args.out)
    imgs[0].save(out, "PDF", save_all=True, append_images=imgs[1:], resolution=150.0)
    print(f"wrote {out}  ({len(imgs)} pages, {imgs[0].size[0]}x{imgs[0].size[1]} px/board)")
    # also drop a PNG of page 1 for a quick eyeball
    png = out.with_suffix(".p1.png")
    imgs[0].save(png)
    print(f"wrote {png}  (page-1 preview)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

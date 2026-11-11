"""bubble_v2 — proper vertical Japanese text + shape variety.

Issues fixed (2026-05-29 user feedback):
  - 縦書きが正しくない: text was split by char count, not by 句読点/breaks
  - 改行が不適切: same — now break at 、。「」/ leading punctuation
  - 吹き出しが単調: all rounded rect. Now 5 shapes by dialogue type:
      normal  → rounded rect
      shout   → spiky burst (! / 力強い)
      thought → cloud (・・・ や 思考)
      narration → rectangle box (「」 or no quote)
      whisper → dashed outline (小声、ヒソヒソ)

Detects type from text content / punctuation. Falls back to normal.
"""
from __future__ import annotations
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Type detection ──────────────────────────────────────────────────────────

def detect_bubble_type(text: str) -> str:
    """Classify dialogue → bubble shape."""
    if not text:
        return "normal"
    t = text.strip()
    # Shout indicators
    if t.endswith(("!", "！", "!!", "！！", "ッ!", "ッ！")):
        return "shout"
    if any(ch in t for ch in ("ッ!", "ガッ", "ドカ", "バーン")):
        return "shout"
    # Narration: starts with 「 or contains 〜だった / 〜である
    if t.startswith(("「", "『")) or "だった" in t or "である" in t:
        return "normal"  # actually still bubble — keep round
    # Thought
    if t.startswith(("・・・", "…", "（", "(")) and not t.endswith(("?", "？")):
        return "thought"
    if "・・・" in t and len(t) <= 5:
        return "thought"
    # Whisper
    if "ヒソヒソ" in t or "ボソッ" in t or t.startswith("(小声"):
        return "whisper"
    return "normal"


# ── Vertical Japanese text layout ───────────────────────────────────────────

_KATAKANA = {"Akira":"アキラ","Yuto":"ユウト","Ren":"レン","Nei":"ネイ",
              "Mei":"メイ","Saki":"サキ","nue":"ヌエ","Chise":"チセ",
              "Yuko":"ユウコ","Ken":"ケン"}


def latinize(s: str) -> str:
    for en, k in _KATAKANA.items():
        s = s.replace(en, k)
    return s


# Punctuation marks for break preference. 「、」は dialog で使うと縦書きで読みづらいので
# auto-break から外し、ハード文末のみ break candidate にする (per p13 eval feedback)
_BREAK_HARD = "。！？"
_BREAK_QUOTE = "」』）)"
_BREAK_CHARS = _BREAK_HARD


def _normalize_text(text: str) -> str:
    """Pre-process dialogue text for vertical rendering.
    - 「…」 (1 char ellipsis) → 「・・・」 (3 chars vertical, per p13 eval)
    - 「‥」 (2 char ellipsis) → 「・・」
    """
    if not text:
        return text
    text = text.replace("…", "・・・").replace("‥", "・・")
    return text


def column_split(text: str, max_chars_per_col: int = 7) -> list[list[str]]:
    """Split text into vertical columns (top-to-bottom chars, R-to-L cols).

    Break priority:
      1. Manual `\\n` markers — always respect (user-controlled in EDN)
      2. Hard sentence-end punctuation (。！？)
      3. Cap at max_chars_per_col
    「、」は auto-break しない (dialog readability)。
    「…」は 「・・・」 に normalize (vertical 3-char)。
    """
    if not text:
        return []
    text = _normalize_text(text)

    # Manual line breaks ("\n" in EDN) = explicit column boundary
    if "\n" in text:
        return [list(seg) for seg in text.split("\n") if seg]

    chars = list(text)
    if len(chars) <= max_chars_per_col:
        return [chars]

    cols = []
    cur = []
    last_break_idx = -1
    for ch in chars:
        cur.append(ch)
        if ch in _BREAK_CHARS:
            last_break_idx = len(cur) - 1
        if len(cur) >= max_chars_per_col:
            if last_break_idx >= 2 and last_break_idx < len(cur) - 1:
                cols.append(cur[: last_break_idx + 1])
                cur = cur[last_break_idx + 1 :]
            else:
                cols.append(cur[:])
                cur = []
            last_break_idx = -1
    if cur:
        cols.append(cur)
    return cols


# ── Bubble shape rendering ──────────────────────────────────────────────────

def draw_rounded_bubble(draw, bx, by, bw, bh, outline_w=3):
    draw.rounded_rectangle([bx, by, bx + bw, by + bh],
                            radius=18, fill=(255, 255, 255),
                            outline=(0, 0, 0), width=outline_w)


def draw_spike_bubble(draw, bx, by, bw, bh, outline_w=4, n_spikes=18):
    """Spiky shout bubble (irregular star-like outline)."""
    cx, cy = bx + bw // 2, by + bh // 2
    rx, ry = bw // 2, bh // 2
    points = []
    for i in range(n_spikes * 2):
        ang = 2 * math.pi * i / (n_spikes * 2)
        r_factor = 1.0 if (i % 2 == 0) else 0.72
        # Add slight jitter
        jit = 1.0 + (((i * 31) % 7) - 3) * 0.02
        px = cx + rx * r_factor * jit * math.cos(ang)
        py = cy + ry * r_factor * jit * math.sin(ang)
        points.append((px, py))
    draw.polygon(points, fill=(255, 255, 255),
                  outline=(0, 0, 0))
    # Outline thickness via overdraw
    for w in range(1, outline_w):
        draw.line(points + [points[0]], fill=(0, 0, 0), width=1)


def draw_cloud_bubble(draw, bx, by, bw, bh, outline_w=3, n_bumps=14):
    """Thought-cloud bubble — overlapping circles protruding OUTSIDE bubble.

    2026-05-29 revised: bumps are at radius (rx+bump_r/2) so they protrude
    half their radius beyond the bubble core ellipse. Much more visible.
    Bumps are larger (radius = max(14, min/8)).
    """
    cx, cy = bx + bw // 2, by + bh // 2
    # Core ellipse smaller so bumps make total reach ~= bw,bh
    bump_r = max(14, min(bw, bh) // 9)
    rx_core = bw // 2 - bump_r
    ry_core = bh // 2 - bump_r
    # Fill interior ellipse first
    draw.ellipse([cx - rx_core, cy - ry_core, cx + rx_core, cy + ry_core],
                  fill=(255, 255, 255))
    # Border bumps — place at perimeter, larger + outside
    for i in range(n_bumps):
        ang = 2 * math.pi * i / n_bumps
        # Push bumps slightly outward (90% rx_core + bump_r * 0.4 protrusion)
        rx_eff = rx_core + bump_r // 3
        ry_eff = ry_core + bump_r // 3
        px = cx + rx_eff * math.cos(ang)
        py = cy + ry_eff * math.sin(ang)
        draw.ellipse([px - bump_r, py - bump_r, px + bump_r, py + bump_r],
                      fill=(255, 255, 255), outline=(0, 0, 0), width=outline_w)
    # Small trailing thought bubbles (signature thought-cloud look)
    trail_r = bump_r // 2
    # Direction depends on bubble position — point AWAY from center of page
    trail_dx = -1 if bx > 600 else 1   # tail points outward
    trail_dy = 1                       # tail goes down
    for i in range(3):
        offset = bump_r * 1.3 * (i + 1)
        tr = max(4, trail_r - i * 3)
        tx = cx + trail_dx * (rx_core + offset)
        ty = cy + ry_core + offset
        draw.ellipse([tx - tr, ty - tr, tx + tr, ty + tr],
                      fill=(255, 255, 255), outline=(0, 0, 0), width=outline_w)


def draw_box_bubble(draw, bx, by, bw, bh, outline_w=3):
    """Narration box — sharp rectangle."""
    draw.rectangle([bx, by, bx + bw, by + bh],
                    fill=(255, 255, 255), outline=(0, 0, 0), width=outline_w)


def draw_whisper_bubble(draw, bx, by, bw, bh, outline_w=2, dash=10):
    """Dashed outline whisper bubble."""
    draw.rounded_rectangle([bx, by, bx + bw, by + bh],
                            radius=18, fill=(255, 255, 255), outline=None)
    # Manual dashed outline
    perim_pts = []
    # Top edge L→R
    for x in range(bx, bx + bw, dash * 2):
        draw.line([(x, by), (min(x + dash, bx + bw), by)],
                  fill=(0, 0, 0), width=outline_w)
    # Right edge T→B
    for y in range(by, by + bh, dash * 2):
        draw.line([(bx + bw, y), (bx + bw, min(y + dash, by + bh))],
                  fill=(0, 0, 0), width=outline_w)
    # Bottom edge R→L
    for x in range(bx + bw, bx, -dash * 2):
        draw.line([(x, by + bh), (max(x - dash, bx), by + bh)],
                  fill=(0, 0, 0), width=outline_w)
    # Left edge B→T
    for y in range(by + bh, by, -dash * 2):
        draw.line([(bx, y), (bx, max(y - dash, by))],
                  fill=(0, 0, 0), width=outline_w)


SHAPE_DRAWERS = {
    "normal":    draw_rounded_bubble,
    "shout":     draw_spike_bubble,
    "thought":   draw_cloud_bubble,
    "narration": draw_box_bubble,
    "whisper":   draw_whisper_bubble,
}


def draw_bubble_tail(draw, bx, by, bw, bh, target_px, target_py,
                       outline_w=3, btype="normal"):
    """Draw a small triangular tail from the bubble edge pointing toward
    (target_px, target_py) — normally the speaker's face position.

    Skipped for box/narration (no tail needed)."""
    if btype in ("narration",):
        return
    # Compute closest edge midpoint
    cx, cy = bx + bw / 2, by + bh / 2
    dx, dy = target_px - cx, target_py - cy
    if dx == 0 and dy == 0:
        return
    # Find which edge the target is past (relative to center)
    side = None
    # Use normalized direction to pick edge
    import math as _m
    if abs(dx) * bh > abs(dy) * bw:
        side = "right" if dx > 0 else "left"
    else:
        side = "bottom" if dy > 0 else "top"

    # Tail base points (along the chosen edge, larger for visibility per eval)
    tail_w = max(32, min(bw, bh) // 4)
    if side == "right":
        ex = bx + bw
        ey = max(by + bh // 4, min(by + bh - bh // 4, cy + dy * 0.4))
        base_a = (ex, ey - tail_w / 2)
        base_b = (ex, ey + tail_w / 2)
    elif side == "left":
        ex = bx
        ey = max(by + bh // 4, min(by + bh - bh // 4, cy + dy * 0.4))
        base_a = (ex, ey - tail_w / 2)
        base_b = (ex, ey + tail_w / 2)
    elif side == "bottom":
        ey = by + bh
        ex = max(bx + bw // 4, min(bx + bw - bw // 4, cx + dx * 0.4))
        base_a = (ex - tail_w / 2, ey)
        base_b = (ex + tail_w / 2, ey)
    else:  # top
        ey = by
        ex = max(bx + bw // 4, min(bx + bw - bw // 4, cx + dx * 0.4))
        base_a = (ex - tail_w / 2, ey)
        base_b = (ex + tail_w / 2, ey)

    # Tip — extend toward target but cap so tail isn't huge
    dist = (dx * dx + dy * dy) ** 0.5
    tip_dist = min(dist, max(tail_w * 1.4, 30))
    tip_x = (base_a[0] + base_b[0]) / 2 + (dx / dist) * tip_dist
    tip_y = (base_a[1] + base_b[1]) / 2 + (dy / dist) * tip_dist
    tip = (tip_x, tip_y)

    # Fill white triangle (covers bubble outline at base)
    draw.polygon([base_a, base_b, tip], fill=(255, 255, 255))
    # Outline both tail sides (not the base — keeps bubble outline continuous)
    draw.line([base_a, tip], fill=(0, 0, 0), width=outline_w)
    draw.line([base_b, tip], fill=(0, 0, 0), width=outline_w)


# ── Main bubble renderer ───────────────────────────────────────────────────

def _is_latin_text(text: str) -> bool:
    """Returns True if text is predominantly ASCII / Latin chars
    (i.e. should be rendered horizontally, not vertically)."""
    if not text:
        return False
    ascii_count = sum(1 for ch in text if ch.isascii() and (ch.isalnum() or ch in " -_."))
    return ascii_count >= len(text) * 0.7


def draw_bubble_v2(draw, font, text: str,
                    panel_x: int, panel_y: int, panel_w: int, panel_h: int,
                    anchor: str = "top-right",
                    shape: str = None,
                    tail_target: tuple = None,
                    font_size: int = None,
                    max_chars_per_col: int = None,
                    pos: tuple = None,
                    size: tuple = None,
                    outline_width: int = 3,
                    padding: int = 22,
                    line_height: int = None,
                    col_width: int = None,
                    writing_mode: str = None):
    """Replace draw_vertical_bubble with shape-aware vertical Japanese.

    Rich EDN-driven parameters:
      shape: explicit shape override ("normal"/"shout"/"thought"/"narration"/"whisper")
             — falls back to detect_bubble_type(text) if None
      tail_target: (x_norm, y_norm) ∈ [0,1]² — point in PANEL coords toward
             which the bubble tail should point (speaker's face). None = no tail.
      font_size: override default 36 truetype size (caller must reload font
             unless using the passed-in `font`)
      max_chars_per_col: per-bubble column wrap cap (default 7)
      pos: (x_norm, y_norm) — explicit normalized position in PANEL, overrides anchor
      size: (w_norm, h_norm) — explicit normalized size, overrides auto-fit cap
      outline_width: bubble border thickness (3 default, 4 for shout)
      padding: inner padding from bubble edge to text
      line_height / col_width: explicit char metrics
    """
    text = latinize((text or "")[:64])
    if not text:
        return

    btype = shape or detect_bubble_type(text)

    # Horizontal mode: explicit override OR auto-detect Latin text.
    # For Latin in narration/box bubbles, render as horizontal rows.
    horizontal = (writing_mode == "horizontal") or (
        writing_mode != "vertical" and _is_latin_text(text)
    )

    if horizontal:
        # Word-wrap by spaces (or chunk by max-chars if no spaces)
        max_chars_per_line = max_chars_per_col or 12
        words = text.split(" ") if " " in text else [text]
        lines = []
        cur = ""
        for w in words:
            tentative = (cur + " " + w).strip() if cur else w
            if len(tentative) > max_chars_per_line and cur:
                lines.append(cur)
                cur = w
            else:
                cur = tentative
        if cur:
            lines.append(cur)
        cols = None  # signal horizontal mode below
    else:
        cols = column_split(text, max_chars_per_col=max_chars_per_col or 9)
        if not cols:
            return
        lines = None

    line_h = line_height or 38
    col_w = col_width or 42
    inner_pad = padding
    outer_pad = 12
    if horizontal:
        max_col_len = max(len(ln) for ln in lines) if lines else 0
        n_cols = len(lines) if lines else 1
    else:
        max_col_len = max(len(c) for c in cols)
        n_cols = len(cols)

    # Cap to panel proportions
    import os
    bub_shrink = float(os.environ.get("V11_BUBBLE_SHRINK", "1.0"))
    if size is not None:
        bw = int(panel_w * size[0])
        bh = int(panel_h * size[1])
    else:
        max_bw = int(panel_w * 0.38 * bub_shrink)
        max_bh = int(panel_h * 0.55 * bub_shrink)
        needed_bw = n_cols * col_w + inner_pad * 2
        needed_bh = max_col_len * line_h + inner_pad * 2
        if needed_bw > max_bw:
            col_w = max(28, (max_bw - inner_pad * 2) // n_cols)
        if needed_bh > max_bh:
            line_h = max(22, (max_bh - inner_pad * 2) // max_col_len)
        bw = min(max_bw, max(80, n_cols * col_w + inner_pad * 2))
        bh = min(max_bh, max(120, max_col_len * line_h + inner_pad * 2))
        if btype == "thought":
            bw = int(bw * 1.15)
            bh = int(bh * 1.15)

    # Position (explicit pos overrides anchor)
    if pos is not None:
        # pos is the CENTER of the bubble in normalized panel coords
        bx = panel_x + int(panel_w * pos[0]) - bw // 2
        by = panel_y + int(panel_h * pos[1]) - bh // 2
    elif anchor == "top-right":
        bx, by = panel_x + panel_w - bw - outer_pad, panel_y + outer_pad
    elif anchor == "top-left":
        bx, by = panel_x + outer_pad, panel_y + outer_pad
    elif anchor == "middle-right":
        bx, by = panel_x + panel_w - bw - outer_pad, panel_y + (panel_h - bh) // 2
    elif anchor == "middle-left":
        bx, by = panel_x + outer_pad, panel_y + (panel_h - bh) // 2
    elif anchor == "bottom-right":
        bx, by = panel_x + panel_w - bw - outer_pad, panel_y + panel_h - bh - outer_pad
    else:
        bx, by = panel_x + outer_pad, panel_y + panel_h - bh - outer_pad

    # Draw bubble shape
    drawer = SHAPE_DRAWERS.get(btype, draw_rounded_bubble)
    if btype == "shout":
        drawer(draw, bx - 8, by - 8, bw + 16, bh + 16, outline_w=outline_width)
    elif btype == "whisper":
        # Boost whisper visibility — solid outline option via outline_width
        drawer(draw, bx, by, bw, bh, outline_w=max(outline_width, 3))
    else:
        try:
            drawer(draw, bx, by, bw, bh, outline_w=outline_width)
        except TypeError:
            drawer(draw, bx, by, bw, bh)

    # Tail toward speaker face (skip narration)
    if tail_target is not None and btype != "narration":
        tx = panel_x + panel_w * tail_target[0]
        ty = panel_y + panel_h * tail_target[1]
        draw_bubble_tail(draw, bx, by, bw, bh, tx, ty,
                          outline_w=outline_width, btype=btype)

    # Text rendering
    if horizontal and lines:
        # Horizontal rows, left-to-right, top-to-bottom
        for ri, line in enumerate(lines):
            ly = by + inner_pad + ri * line_h + line_h // 2
            lx = bx + inner_pad
            draw.text((lx, ly), line, font=font, fill=(0, 0, 0), anchor="lm")
    else:
        # Vertical RIGHT-to-LEFT column order (first col rightmost)
        for ci, col in enumerate(cols):
            cx = bx + bw - inner_pad - col_w // 2 - ci * col_w
            for ri, ch in enumerate(col):
                cy = by + inner_pad + ri * line_h + line_h // 2
                draw.text((cx, cy), ch, font=font, fill=(0, 0, 0), anchor="mm")

"""Face/detail-aware automatic speech-bubble placement (pure PIL, zero deps).

Why edge-density and not a face detector
----------------------------------------
The render env ships PIL only — no cv2 / mediapipe / numpy — and anime/manga
faces evade OpenCV Haar cascades. But we don't actually need a face detector:
in a black-ink manga panel the characters (eyes + hair + line detail) are the
*busiest* region (high local edge density), while sky / walls / gutters / empty
space are smooth (low edge density). Professional letterers place balloons over
the emptiest region that still reads in panel order. We reproduce exactly that
with an edge-density heuristic. The densest cell doubles as a "where is the
speaker's face" proxy for tail-pointing.

Pipeline (per panel)
--------------------
  1. Grayscale -> downscale -> FIND_EDGES -> aggregate into a GX*GY detail grid.
  2. Summed-area table (integral image) over the grid for O(1) rect-sum queries.
  3. For each bubble of known normalized footprint, score a set of candidate
     centers by:
         detail under the footprint            (avoid faces / line art)
       + overlap penalty vs placed bubbles     (no bubble-on-bubble)
       + reading-order bias                     (RTL manga: early -> top/right)
       + edge-hug penalty                       (keep clear of panel frame)
     and pick the minimum-cost center that stays inside the panel.

All math is plain Python lists; a panel costs ~7k pixel reads + a tiny grid
scan, negligible next to image generation.
"""

from __future__ import annotations

import math
from PIL import Image, ImageFilter

# Coarse detail grid resolution. Manga panels are usually portrait, so give the
# vertical axis more cells. Each grid cell is sampled from an S*S pixel block.
GRID_X = 12
GRID_Y = 16
# Downscaled px per grid cell. 16 -> a 192x256 working image: coarse enough to
# be cheap, fine enough that face/hair/eye line art survives the downscale and
# stays distinguishable from smooth sky/wall/gutter regions.
_BLOCK = 16

# Cost weights (detail term is normalized to [0,1]; the rest are tuned around it)
_W_OVERLAP = 6.0     # bubble must not cover another bubble — dominant
_W_ORDER = 0.35      # reading-order pull (top for early bubbles, RTL)
_W_RIGHT = 0.10      # mild right-side preference (Japanese RTL)
_W_FRAME = 0.25      # stay off the panel frame / extreme edges

# Candidate-center sampling density
_NC = 13
_NR = 17


def build_detail_sat(panel_img: Image.Image, gx: int = GRID_X, gy: int = GRID_Y):
    """Return (sat, gx, gy) where sat is a summed-area table over a gx*gy edge-
    density grid. sat has (gy+1) rows and (gx+1) cols (zero-padded top/left)."""
    sw, sh = gx * _BLOCK, gy * _BLOCK
    im = panel_img.convert("L").resize((sw, sh), Image.BILINEAR)
    edges = im.filter(ImageFilter.FIND_EDGES)
    # get_flattened_data() on Pillow >=11; getdata() elsewhere. Row-major, len sw*sh.
    px = list(getattr(edges, "get_flattened_data", edges.getdata)())

    # FIND_EDGES fabricates a bright edge along the image border (kernel reads off
    # the canvas). Zero a thin ring so edge-touching anchors aren't mistaken for
    # busy regions.
    ring = 2
    for yy in list(range(ring)) + list(range(sh - ring, sh)):
        base = yy * sw
        for xx in range(sw):
            px[base + xx] = 0
    for yy in range(sh):
        base = yy * sw
        for xx in list(range(ring)) + list(range(sw - ring, sw)):
            px[base + xx] = 0

    # Aggregate S*S blocks into grid cells.
    grid = [[0.0] * gx for _ in range(gy)]
    for cy in range(gy):
        for cx in range(gx):
            acc = 0
            base = cy * _BLOCK * sw + cx * _BLOCK
            for by in range(_BLOCK):
                row = base + by * sw
                acc += sum(px[row:row + _BLOCK])
            grid[cy][cx] = acc

    # Normalize so detail terms sit in a stable [0,1]-ish range across panels.
    mx = max((max(r) for r in grid), default=0.0) or 1.0
    for cy in range(gy):
        for cx in range(gx):
            grid[cy][cx] /= mx

    # Summed-area table (integral image) over the grid.
    sat = [[0.0] * (gx + 1) for _ in range(gy + 1)]
    for cy in range(gy):
        rowsum = 0.0
        for cx in range(gx):
            rowsum += grid[cy][cx]
            sat[cy + 1][cx + 1] = sat[cy][cx + 1] + rowsum
    return sat, gx, gy


def _rect_mean(sat, gx, gy, x0n, y0n, x1n, y1n) -> float:
    """Mean grid value over a normalized rectangle [x0n,x1n]x[y0n,y1n]."""
    cx0 = max(0, min(gx, int(x0n * gx)))
    cy0 = max(0, min(gy, int(y0n * gy)))
    cx1 = max(cx0 + 1, min(gx, int(math.ceil(x1n * gx))))
    cy1 = max(cy0 + 1, min(gy, int(math.ceil(y1n * gy))))
    total = sat[cy1][cx1] - sat[cy0][cx1] - sat[cy1][cx0] + sat[cy0][cx0]
    cells = (cx1 - cx0) * (cy1 - cy0)
    return total / cells if cells else 1.0


def estimate_bubble_size_norm(
    text: str,
    panel_w: int,
    panel_h: int,
    max_chars_per_col: int | None = None,
    font_size: int | None = None,
    size=None,
    writing_mode: str | None = None,
) -> tuple[float, float]:
    """Approximate the normalized (w, h) footprint draw_bubble_v2 will produce.

    Mirrors the size caps/columns in bubble_v2.draw_bubble_v2 closely enough for
    placement scoring; exact pixel parity is unnecessary."""
    if size is not None and len(size) >= 2:
        return float(size[0]), float(size[1])

    t = (text or "")[:64]
    if not t:
        return 0.18, 0.18
    n = len(t)
    is_latin = writing_mode == "horizontal" or (
        writing_mode != "vertical" and all(ord(c) < 0x3000 for c in t)
    )

    scale = (font_size or 36) / 36.0
    col_w = 42 * scale
    line_h = 38 * scale
    pad = 44  # inner_pad*2

    if is_latin:
        per = max_chars_per_col or 12
        n_lines = max(1, math.ceil(n / per))
        max_len = min(n, per)
        bw = max_len * (col_w * 0.55) + pad   # latin glyphs are narrower
        bh = n_lines * line_h + pad
    else:
        mcpc = max_chars_per_col or 9
        n_cols = max(1, math.ceil(n / mcpc))
        max_len = min(n, mcpc)
        bw = n_cols * col_w + pad
        bh = max_len * line_h + pad

    # Caps from draw_bubble_v2 (0.38w x 0.55h).
    bw = min(bw, panel_w * 0.38)
    bh = min(bh, panel_h * 0.55)
    bw = max(bw, 80)
    bh = max(bh, 110)
    return min(0.92, bw / panel_w), min(0.92, bh / panel_h)


def face_hint(sat, gx, gy) -> tuple[float, float]:
    """Normalized center of the densest grid cell — a proxy for the main face,
    used to point speech-bubble tails at the speaker."""
    best, bx, by = -1.0, gx // 2, gy // 2
    for cy in range(gy):
        for cx in range(gx):
            v = sat[cy + 1][cx + 1] - sat[cy][cx + 1] - sat[cy + 1][cx] + sat[cy][cx]
            if v > best:
                best, bx, by = v, cx, cy
    return (bx + 0.5) / gx, (by + 0.5) / gy


def _overlap_frac(a, b) -> float:
    """Overlap area as a fraction of the smaller box. a,b = (cx,cy,w,h) norm."""
    ax0, ay0 = a[0] - a[2] / 2, a[1] - a[3] / 2
    ax1, ay1 = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx0, by0 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx1, by1 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    smaller = min(a[2] * a[3], b[2] * b[3]) or 1e-6
    return inter / smaller


def place_bubble(
    sat,
    gx: int,
    gy: int,
    size_n: tuple[float, float],
    placed: list,
    order_index: int = 0,
    n_bubbles: int = 1,
    anchor_hint: str | None = None,
    reading: str = "rtl",
) -> tuple[float, float]:
    """Pick the normalized CENTER for a bubble of footprint size_n that minimizes
    detail coverage + overlap + reading-order cost. `placed` is the list of
    already-placed (cx,cy,w,h) norm rects (mutate it after calling)."""
    bw, bh = size_n
    bw = min(bw, 0.96)
    bh = min(bh, 0.96)
    half_w, half_h = bw / 2, bh / 2

    lo_x, hi_x = half_w + 0.01, 1 - half_w - 0.01
    lo_y, hi_y = half_h + 0.01, 1 - half_h - 0.01
    if hi_x < lo_x:
        lo_x = hi_x = 0.5
    if hi_y < lo_y:
        lo_y = hi_y = 0.5

    # Reading-order target: RTL manga reads top->bottom, right->left. Early
    # bubbles want the top; the right-side bias is applied separately.
    frac = (order_index + 0.5) / max(1, n_bubbles)
    target_y = lo_y + (hi_y - lo_y) * frac
    if reading == "ltr":
        right_pref = lambda cx: (cx - lo_x) / max(1e-6, hi_x - lo_x)  # prefer left
    else:
        right_pref = lambda cx: (hi_x - cx) / max(1e-6, hi_x - lo_x)  # prefer right

    # Honor an explicit anchor hint as a soft nudge, not a hard constraint.
    hint_xy = _anchor_center(anchor_hint, half_w, half_h)

    best_cost, best = float("inf"), (0.5, target_y)
    for ri in range(_NR):
        cy = lo_y + (hi_y - lo_y) * (ri / max(1, _NR - 1))
        for ci in range(_NC):
            cx = lo_x + (hi_x - lo_x) * (ci / max(1, _NC - 1))

            detail = _rect_mean(sat, gx, gy, cx - half_w, cy - half_h,
                                cx + half_w, cy + half_h)
            overlap = sum(_overlap_frac((cx, cy, bw, bh), p) for p in placed)
            order = abs(cy - target_y) + 0.6 * right_pref(cx)
            # Penalize touching the panel frame (extreme edges).
            frame = max(0.0, 0.06 - min(cx - half_w, 1 - cx - half_w,
                                        cy - half_h, 1 - cy - half_h)) * 16
            hint = 0.0
            if hint_xy is not None:
                hint = 0.5 * (abs(cx - hint_xy[0]) + abs(cy - hint_xy[1]))

            cost = (detail
                    + _W_OVERLAP * overlap
                    + _W_ORDER * order
                    + _W_RIGHT * right_pref(cx)
                    + _W_FRAME * frame
                    + 0.20 * hint)
            if cost < best_cost:
                best_cost, best = cost, (cx, cy)
    return best


def refine_anchor(
    sat,
    gx: int,
    gy: int,
    size_n: tuple[float, float],
    anchor: str | None,
    placed: list,
    order_index: int = 0,
    n_bubbles: int = 1,
    reading: str = "rtl",
    keep_margin: float = 0.08,
    overlap_tol: float = 0.10,
):
    """Anchor-respecting placement: keep the authored `anchor` position unless it
    actually sits on a face / busy art or collides with an already-placed bubble,
    in which case relocate to the nearest emptier readable spot.

    Returns (pos, rect):
      pos  = None    -> keep the static anchor (let draw_bubble_v2 use `anchor`)
             (cx,cy) -> explicit normalized center to use instead
      rect = (cx,cy,w,h) normalized box to append to `placed` either way, so the
             next bubble avoids this one.
    """
    bw, bh = min(size_n[0], 0.96), min(size_n[1], 0.96)
    half_w, half_h = bw / 2, bh / 2
    a = _anchor_center(anchor, half_w, half_h) or (0.5, 0.5)
    ax = min(max(a[0], half_w + 0.01), 1 - half_w - 0.01)
    ay = min(max(a[1], half_h + 0.01), 1 - half_h - 0.01)

    anchor_detail = _rect_mean(sat, gx, gy, ax - half_w, ay - half_h,
                               ax + half_w, ay + half_h)
    anchor_overlap = sum(_overlap_frac((ax, ay, bw, bh), p) for p in placed)

    best = place_bubble(sat, gx, gy, (bw, bh), placed, order_index,
                        n_bubbles, anchor_hint=anchor, reading=reading)
    best_detail = _rect_mean(sat, gx, gy, best[0] - half_w, best[1] - half_h,
                             best[0] + half_w, best[1] + half_h)

    # Authored anchor wins unless it clearly covers more art than the best spot
    # or overlaps a sibling bubble.
    if anchor_overlap <= overlap_tol and anchor_detail <= best_detail + keep_margin:
        return None, (ax, ay, bw, bh)
    return best, (best[0], best[1], bw, bh)


def _anchor_center(anchor, half_w, half_h):
    if not anchor:
        return None
    ax = 1 - half_w - 0.02 if "right" in anchor else (
        half_w + 0.02 if "left" in anchor else 0.5)
    ay = half_h + 0.02 if "top" in anchor else (
        1 - half_h - 0.02 if "bottom" in anchor else 0.5)
    return ax, ay

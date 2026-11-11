#!/usr/bin/env python3
"""漫画ページのコマ割りを画像から抽出してデータ化する(recursive XY-cut)。

スキャンページ(黒インクのコマ + 白ガター)を、全幅/全高に渡る白い溝(ガター)で
再帰的に縦横分割し、各リーフをインク外接矩形にトリムしてコマ矩形を得る。座標は
ページ content-bbox 基準の permille(‰, 0-1000)に正規化する。ARIA(天野こずえ)の
段(tier)主体・全幅ブリージングコマ・可変段高 を実データとして取り出す目的。

RUN: python3 scripts/extract_komawari.py --glob '/tmp/aria-ref/p*.png' \
        --out scripts/aria-komawari-patterns.json --overlay /tmp/aria-overlay
"""
import argparse
import glob
import json
import os

import numpy as np
from PIL import Image, ImageDraw

INK_T = 200          # gray < INK_T を「インク(非紙)」とみなす(content-bbox / trim 用)
WHITE_T = 235        # gray > WHITE_T = 紙(白)。スクリーントーン(灰~200)と区別
GUT_WHITE = 0.82     # 行/列のうち紙ピクセル率がこれ以上なら白いガター(溝)
MIN_GUT_FR = 0.011   # ガター最小幅(領域寸法比)これ未満の溝では分割しない
MIN_PANEL_FR = 0.055 # コマ最小辺(ページ寸法比)
PAD_FR = 0.004       # トリム時の余白(ページ寸法比)


def _content_bbox(ink, fr=0.004):
    ys = np.where(ink.mean(axis=1) > fr)[0]
    xs = np.where(ink.mean(axis=0) > fr)[0]
    if len(ys) == 0 or len(xs) == 0:
        return 0, 0, ink.shape[1], ink.shape[0]
    return xs[0], ys[0], xs[-1] + 1, ys[-1] + 1


BORDER_INK = 0.30    # 白帯の外縁に枠線(高インク行)があれば真のガター。内部の白(空)は枠線なし


def _has_border(ink_prof, s, e, lo, hi):
    """白帯[s,e]の直外に枠線(高インク)があるか。コマ内部の白い余白(空/床)を除外する。"""
    k = 4
    pre = ink_prof[max(lo, s - k):s]
    post = ink_prof[e:min(hi, e + k)]
    mpre = pre.max() if len(pre) else 0.0
    mpost = post.max() if len(post) else 0.0
    return mpre >= BORDER_INK and mpost >= BORDER_INK


def _best_gutter(white_prof, ink_prof, lo, hi, min_gut):
    """white_prof(紙率)が GUT_WHITE 以上で連続し、かつ両外縁に枠線がある最長帯の中心と幅。"""
    best = (0, None)
    run_s = None
    for i in range(lo, hi + 1):
        on = i < hi and white_prof[i] >= GUT_WHITE
        if on:
            if run_s is None:
                run_s = i
        else:
            if run_s is not None:
                w = i - run_s
                if w > best[0] and _has_border(ink_prof, run_s, i, lo, hi):
                    best = (w, (run_s + i) // 2)
                run_s = None
    return best if best[0] >= min_gut else (0, None)


def _xycut(white, ink, x0, y0, x1, y1, W, H, depth=0):
    """領域[x0,y0,x1,y1]を再帰分割してコマ矩形リスト(px)を返す。white=紙, ink=非紙。"""
    w, h = x1 - x0, y1 - y0
    if w < MIN_PANEL_FR * W or h < MIN_PANEL_FR * H or depth > 7:
        return [(x0, y0, x1, y1)]
    ws = white[y0:y1, x0:x1]
    ins = ink[y0:y1, x0:x1]
    row, col = ws.mean(axis=1), ws.mean(axis=0)           # 紙率(ガター)
    irow, icol = ins.mean(axis=1), ins.mean(axis=0)       # 非紙率(枠線検出)
    # 端の余白は無視して内部のガターのみ探す
    m_h = max(2, int(0.04 * h))
    m_w = max(2, int(0.04 * w))
    gh_w, gh_c = _best_gutter(row, irow, m_h, h - m_h, max(3, int(MIN_GUT_FR * H)))
    gv_w, gv_c = _best_gutter(col, icol, m_w, w - m_w, max(3, int(MIN_GUT_FR * W)))
    # 横/縦どちらの溝がより明瞭(広い)かで分割方向を決める(ARIA は段優先になりやすい)
    use_h = gh_c is not None and (gv_c is None or gh_w >= gv_w)
    use_v = gv_c is not None and (gh_c is None or gv_w > gh_w)
    if use_h:
        cy = y0 + gh_c
        return (_xycut(white, ink, x0, y0, x1, cy, W, H, depth + 1)
                + _xycut(white, ink, x0, cy, x1, y1, W, H, depth + 1))
    if use_v:
        cx = x0 + gv_c
        return (_xycut(white, ink, x0, y0, cx, y1, W, H, depth + 1)
                + _xycut(white, ink, cx, y0, x1, y1, W, H, depth + 1))
    return [(x0, y0, x1, y1)]


def _trim(ink, box, W, H):
    x0, y0, x1, y1 = box
    sub = ink[y0:y1, x0:x1]
    ys = np.where(sub.mean(axis=1) > 0.012)[0]
    xs = np.where(sub.mean(axis=0) > 0.012)[0]
    if len(ys) == 0 or len(xs) == 0:
        return None
    pad_w, pad_h = int(PAD_FR * W), int(PAD_FR * H)
    nx0 = x0 + max(0, xs[0] - pad_w)
    ny0 = y0 + max(0, ys[0] - pad_h)
    nx1 = x0 + min(x1 - x0, xs[-1] + 1 + pad_w)
    ny1 = y0 + min(y1 - y0, ys[-1] + 1 + pad_h)
    return (nx0, ny0, nx1, ny1)


def extract(path):
    im = Image.open(path).convert("L")
    g = np.asarray(im, dtype=np.float32)
    ink = (g < INK_T).astype(np.float32)
    white = (g > WHITE_T).astype(np.float32)
    H, W = ink.shape
    cx0, cy0, cx1, cy1 = _content_bbox(ink)
    cw, ch = max(1, cx1 - cx0), max(1, cy1 - cy0)
    leaves = _xycut(white, ink, cx0, cy0, cx1, cy1, W, H)
    panels = []
    for b in leaves:
        t = _trim(ink, b, W, H)
        if not t:
            continue
        bx0, by0, bx1, by1 = t
        if (bx1 - bx0) < MIN_PANEL_FR * W or (by1 - by0) < MIN_PANEL_FR * H:
            continue
        panels.append(t)
    # 読み順 RTL: 段(y)優先で上→下、同段は右→左
    panels.sort(key=lambda p: (round((p[1] - cy0) / ch * 12), -(p[0])))
    out = []
    for p in panels:
        out.append({
            "x": round((p[0] - cx0) / cw * 1000),
            "y": round((p[1] - cy0) / ch * 1000),
            "w": round((p[2] - p[0]) / cw * 1000),
            "h": round((p[3] - p[1]) / ch * 1000),
        })
    return out, (cx0, cy0, cx1, cy1, W, H)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--overlay", default="")
    args = ap.parse_args(argv)
    files = sorted(glob.glob(args.glob))
    patterns = []
    if args.overlay:
        os.makedirs(args.overlay, exist_ok=True)
    for f in files:
        try:
            panels, geo = extract(f)
        except Exception as e:
            print(f"{os.path.basename(f)}: ERR {e}")
            continue
        patterns.append({"src": os.path.basename(f), "n": len(panels), "panels": panels})
        print(f"{os.path.basename(f)}: {len(panels)} panels")
        if args.overlay:
            cx0, cy0, cx1, cy1, W, H = geo
            im = Image.open(f).convert("RGB")
            d = ImageDraw.Draw(im)
            cw, ch = cx1 - cx0, cy1 - cy0
            for i, p in enumerate(panels):
                X0 = cx0 + p["x"] / 1000 * cw
                Y0 = cy0 + p["y"] / 1000 * ch
                X1 = X0 + p["w"] / 1000 * cw
                Y1 = Y0 + p["h"] / 1000 * ch
                d.rectangle([X0, Y0, X1, Y1], outline=(255, 0, 0), width=5)
                d.text((X0 + 8, Y0 + 6), str(i + 1), fill=(255, 0, 0))
            im.save(os.path.join(args.overlay, os.path.basename(f)))
    json.dump({"source": "ARIA完全版 5巻 (天野こずえ)", "patterns": patterns},
              open(args.out, "w"), ensure_ascii=False, indent=2)
    ns = [p["n"] for p in patterns]
    print(f"\n{len(patterns)} pages, panels/page: min {min(ns)} max {max(ns)} "
          f"avg {sum(ns) / len(ns):.1f} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

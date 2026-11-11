#!/usr/bin/env python3
"""Adopt the new koma-wari + direction model into the CANONICAL ghosthacker
storyboard.

Reads the canonical episode manifest (image-gen-manifest.json — 46 pages /
279 panels, the real arc0-1 storyboard) and emits the same episode in the new
`ai.gftd.mangaka.page` record shape: per-page printGeometry (内枠/仕上がり/
断ち切り) + rhythm (テンポ/視線遷移), and per-panel rect (permille of the board)
+ bleed (断ち切り) + shot (引き/寄り + camera + move) + gaze (視線範囲/遷移/印象).

Each page is assigned a koma-wari layout drawn from the 10 reviewed patterns,
selected by panel count + scene role (splash / establishing / action /
dialogue / grid). The manifest's shot string + tone + focusCharacter drive the
shot/gaze fields, so the adoption is faithful to the existing storyboard.

Output: storyboard.komawari.page.json (next to the manifest) — render with
komawari_blueprint_pdf.py to a full 46-page blueprint PDF.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
from pathlib import Path

EP = (Path(__file__).resolve().parents[1].parent
      / "data/ghosthacker/resources/episodes/arc0-1-origin")

# ── shot string → canonical scale enum ──────────────────────────────────────
def to_scale(shot: str) -> str:
    s = (shot or "").lower()
    if "extreme close" in s:               return "ECU"
    if "over the shoulder" in s or s == "ots": return "OTS"
    if "close" in s:                       return "CU"
    if "insert" in s:                      return "insert"
    if "pov" in s:                         return "POV"
    if "establish" in s:                   return "WS"
    if "wide" in s:                        return "WS"
    if "medium" in s:                      return "MS"
    return "MS"

YORI = {"ECU", "CU", "MCU", "insert", "POV", "OTS"}
HIKI = {"MLS", "LS", "WS"}
SCALE_EMPH = {"ECU": 72, "CU": 58, "MCU": 52, "MS": 48, "MLS": 50,
              "LS": 60, "WS": 80, "OTS": 48, "insert": 44, "POV": 55}


def framing(scale: str) -> str:
    if scale in YORI: return "yori"
    if scale in HIKI: return "hiki"
    return "neutral"


def impression(tone: str, scale: str) -> str:
    t = (tone or "").lower()
    for key, imp in (("shock", "impact"), ("impact", "impact"), ("tense", "tension"),
                     ("fear", "dread"), ("dread", "dread"), ("anx", "dread"),
                     ("sad", "melancholy"), ("melan", "melancholy"),
                     ("calm", "calm"), ("quiet", "calm"), ("warm", "calm"),
                     ("comed", "comedic"), ("funny", "comedic"),
                     ("omin", "ominous"), ("dark", "ominous"),
                     ("fast", "speed"), ("action", "speed"), ("speed", "speed"),
                     ("awe", "awe"), ("wonder", "awe")):
        if key in t:
            return imp
    return {"ECU": "tension", "CU": "tension", "WS": "awe", "insert": "tension"}.get(scale, "calm")


# ── page role detection ─────────────────────────────────────────────────────
ACTION_TONES = ("tense", "shock", "fast", "action", "impact", "fear", "panic", "attack")


def page_mode(panels: list[dict], scales: list[str]) -> str:
    n = len(panels)
    if n == 1:
        return "splash"
    tones = " ".join((p.get("tone") or "") for p in panels).lower()
    title = (panels[0].get("pageTitle") or "").lower()
    tense = sum(1 for p in panels if any(k in (p.get("tone") or "").lower() for k in ACTION_TONES))
    if scales[0] in HIKI and tense < 2:                # 1コマ目が引き=状況説明 → 大ゴマ開き
        return "establishing"
    if tense >= 2 or any(k in tones for k in ("shock", "attack", "panic")):
        return "action"
    yoriish = sum(1 for s in scales if s in ("CU", "MCU", "MS", "ECU"))
    if yoriish >= max(2, n - 1):
        return "dialogue"
    return "grid"


# ── layout: 動的コマ割り (行サイズ・列幅・段高を seed 可変、単調を解消) ──────────
def _split_rows(cnt: int, rng) -> list:
    """cnt 個のコマを 1〜3 個/行に可変分割(2-3 を主、たまに 1 で大ゴマ)。"""
    rows, rem = [], cnt
    while rem > 0:
        k = min(rng.choice([2, 3, 2, 3, 2, 1, 3]), rem)
        rows.append(k); rem -= k
    return rows


def row_plan(n: int, mode: str, seed: int = 0):
    """戻り値 (plan, hweights): plan=各行の『コマ別 幅ウェイト』のリスト(不等幅)、
    hweights=各行の段高ウェイト。同一行内は不等幅、段高も可変、随所に大ゴマを混ぜて
    ページごとに違うリズムを作る。reading order は 行=上→下 / 行内=右→左 のまま。"""
    if n <= 1 or mode == "splash":
        return [[1.0]], [1.0]
    rng = random.Random(seed * 97 + n * 31 + 7)
    if mode == "establishing":
        rows = [1] + _split_rows(n - 1, rng)            # 上に大ゴマ(状況説明)
    elif mode == "action":
        rows = _split_rows(n - 1, rng) + [1]            # 下に見せゴマ
    else:
        rows = _split_rows(n, rng)
    plan = [[1.0] if k == 1 else [round(rng.uniform(0.74, 1.45), 2) for _ in range(k)]
            for k in rows]
    hw = [round(rng.uniform(0.80, 1.06), 2) for _ in rows]
    if mode == "establishing":
        hw[0] = round(rng.uniform(1.5, 1.9), 2)
    elif mode == "action":
        hw[-1] = round(rng.uniform(1.55, 2.0), 2)
    elif len(rows) >= 2 and rng.random() < 0.7:         # それ以外も1行を大ゴマ化
        hw[rng.randrange(len(rows))] = round(rng.uniform(1.3, 1.65), 2)
    return plan, hw


B, G, INNER = 17, 14, 966                       # trim inset, gutter, usable span (permille)


def build_rects(plan, weights):
    """Return rects [[x,y,w,h]...] in reading order (rows top→bottom, RTL within row).
    plan[r] = その行のコマ別 幅ウェイト(不等幅), weights[r] = 段高ウェイト。"""
    rects, tot_h = [], sum(weights)
    avail_h = INNER - (len(plan) - 1) * G
    y = B
    for row, hw in zip(plan, weights):
        ncols = len(row)
        rh = avail_h * hw / tot_h
        avail_w = INNER - (ncols - 1) * G
        sw = sum(row)
        x = B + INNER                            # 右端から左へ(RTL, c=0=右端)
        for c in range(ncols):
            cw = avail_w * row[c] / sw
            x -= cw
            rects.append([round(x), round(y), round(cw), round(rh)])
            x -= G
        y += rh + G
    return rects


_ARIA_PATTERNS = None


def _load_aria_patterns():
    """ARIA(天野こずえ)実ページから抽出したコマ割りパターン(permille 矩形)。"""
    global _ARIA_PATTERNS
    if _ARIA_PATTERNS is None:
        import os
        fp = os.path.join(os.path.dirname(__file__), "aria-komawari-patterns.json")
        try:
            pats = json.load(open(fp))["patterns"]
            _ARIA_PATTERNS = [p for p in pats if 2 <= p["n"] <= 9]
        except Exception:
            _ARIA_PATTERNS = []
    return _ARIA_PATTERNS


def _aria_adapt(panels, target):
    """パターンのコマ数を target に合わせる。多ければ最小コマを隣へ統合、少なければ
    最大コマを長辺で分割。ARIA の段構造(全幅/可変段高)はできるだけ保つ。"""
    panels = [dict(p) for p in panels]
    while len(panels) > target:                          # 最小コマを同段の隣へ横統合
        i = min(range(len(panels)), key=lambda k: panels[k]["w"] * panels[k]["h"])
        s = panels[i]
        nb = [(j, q) for j, q in enumerate(panels) if j != i
              and abs((q["y"] + q["h"] / 2) - (s["y"] + s["h"] / 2)) < max(q["h"], s["h"]) * 0.5]
        if not nb:
            panels.pop(i); continue
        j, q = min(nb, key=lambda jq: abs(jq[1]["x"] - s["x"]))
        x0 = min(s["x"], q["x"]); y0 = min(s["y"], q["y"])
        q2 = {"x": x0, "y": y0,
              "w": max(s["x"] + s["w"], q["x"] + q["w"]) - x0,
              "h": max(s["y"] + s["h"], q["y"] + q["h"]) - y0}
        panels = [q2 if k == min(i, j) else p for k, p in enumerate(panels) if k != max(i, j)]
    while len(panels) < target:                          # 最大コマを長辺で2分割
        i = max(range(len(panels)), key=lambda k: panels[k]["w"] * panels[k]["h"])
        s = panels.pop(i)
        if s["w"] >= s["h"]:                              # 横長→左右割り
            half = (s["w"] - G) // 2
            a = {"x": s["x"], "y": s["y"], "w": half, "h": s["h"]}
            b = {"x": s["x"] + half + G, "y": s["y"], "w": s["w"] - half - G, "h": s["h"]}
        else:                                            # 縦長→上下割り
            half = (s["h"] - G) // 2
            a = {"x": s["x"], "y": s["y"], "w": s["w"], "h": half}
            b = {"x": s["x"], "y": s["y"] + half + G, "w": s["w"], "h": s["h"] - half - G}
        panels[i:i] = [a, b]
    return panels


def aria_layout(n, seed=0):
    """ARIA 実パターンを n コマに合わせて返す。戻り: (rects[[x,y,w,h]‰板], 大ゴマidx)。
    パターンが無ければ None。座標は build_rects と同じ board permille(B..B+INNER)。"""
    pats = _load_aria_patterns()
    if not pats:
        return None
    cands = [p for p in pats if p["n"] == n] or [p for p in pats if abs(p["n"] - n) <= 1] \
        or [p for p in pats if abs(p["n"] - n) <= 2]
    if not cands:
        return None
    rng = random.Random(seed * 131 + n * 17 + 3)
    pat = cands[rng.randrange(len(cands))]
    panels = _aria_adapt(pat["panels"], n)
    # RTL 読み順: 段(y)優先 上→下、同段は右→左
    panels.sort(key=lambda p: (round(p["y"] / 90), -p["x"]))
    rects = [[round(B + p["x"] / 1000 * INNER), round(B + p["y"] / 1000 * INNER),
              round(p["w"] / 1000 * INNER), round(p["h"] / 1000 * INNER)] for p in panels]
    climax = max(range(len(rects)), key=lambda k: rects[k][2] * rects[k][3])
    return rects, climax


def apply_bleed(rects, mode):
    bleed = [[] for _ in rects]
    if mode == "splash":
        rects[0] = [0, 0, 1000, 1000]
        bleed[0] = ["top", "right", "bottom", "left"]
    elif mode == "establishing":
        bleed[0] = ["top", "left", "right"]     # hero row spans
    elif mode == "action":
        bleed[-1] = ["bottom", "left", "right"] # bottom hero
        # top-row outer panels bleed to the top edge
        for i, r in enumerate(rects):
            if r[1] <= B + 2 and i != len(rects) - 1:
                bleed[i] = sorted(set(bleed[i] + ["top"]))
    return bleed


def climax_index(rects, mode):
    if mode in ("splash", "establishing"):
        return 0
    if mode == "action":
        return len(rects) - 1
    return max(range(len(rects)), key=lambda i: rects[i][2] * rects[i][3])


def angle_for(scale, mode, climax, title):
    t = (title or "").lower()
    if scale in HIKI and climax:
        if mode == "action": return "worms-eye"
        if any(k in t for k in ("wall", "全体", "捜査", "overview", "俯瞰")): return "birds-eye"
        return "low"
    if scale == "insert":  return "high"
    if scale == "OTS":     return "OTS"
    if scale == "POV":     return "POV"
    return "eye"


def move_for(scale, mode, climax, idx):
    if mode == "action":
        return ["push-in", "pull-back", "pan-left", "pan-right"][idx % 4]
    if climax and scale in YORI: return "push-in"
    if scale in HIKI:            return "pull-back"
    return "static"


def _local(rect, board_pt):
    x, y, w, h = rect
    lx = (board_pt[0] - x) / max(w, 1) * 1000
    ly = (board_pt[1] - y) / max(h, 1) * 1000
    return [max(80, min(920, round(lx))), max(80, min(920, round(ly)))]


def gaze_for(rect, scale, prev_c, next_c, tone, idx, n):
    x, y, w, h = rect
    fy = 380 if scale in HIKI else (430 if scale in YORI else 460)
    inset = 0.16
    g = {"focusX": 500, "focusY": fy,
         "regionX": round(inset * 1000), "regionY": round(inset * 1000),
         "regionW": round((1 - 2 * inset) * 1000), "regionH": round((1 - 2 * inset) * 1000)}
    cx, cy = x + w / 2, y + h / 2
    g["entryX"], g["entryY"] = (_local(rect, prev_c) if prev_c else [900, 140])
    g["exitX"], g["exitY"] = (_local(rect, next_c) if next_c else [500, 910])
    g["impression"] = impression(tone, scale)
    return g


TEMPO = {"splash": "hold", "establishing": "release", "action": "accel",
         "dialogue": "sustain", "grid": "sustain"}
OPENS = {"splash": "hiki", "establishing": "hiki", "action": "yori",
         "dialogue": "yori", "grid": "yori"}


# ── lettering / fx / tone heuristics ────────────────────────────────────────
_BREAK_AFTER = "、。！？"
_NO_START = "、。，．！？）」』〕｝〉》ー～〜…‥ァィゥェォッャュョヮぁぃぅぇぉっゃゅょゎ々"


def _wrap_seg(seg: str, maxc: int) -> list:
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
    """セリフ組版: 、=改行(列区切り・除去) / 。=除去 / ？！は残す。
    bubble.lines として改行位置をデータに焼き込む。"""
    if not text:
        return []
    text = text.replace("。", "").replace("．", "")
    out = []
    for seg in text.split("、"):
        seg = seg.strip("　 ")
        if seg:
            out.extend(_wrap_seg(seg, maxc))
    return out[:7]


def split_dialogue(text: str, budget: int = 20) -> list:
    """可読性優先パッキング: 文(。)・節(、)に分けたあと、budget 字以内なら隣接片を
    1つの吹き出しに詰める(、は改行として表示)。断片モノローグ(『7年。集めた。繋いだ。
    辿った』)を細切れ4吹き出しにせず、流れる1〜2吹き出しにして読者の混乱を減らす。
    『。』『、』は表示しない / ？！は残す。"""
    import re
    if not text:
        return []
    vis = lambda x: len(x.replace("、", ""))
    units = [u.replace("。", "").replace("、", "").strip("　 ")
             for u in re.split(r"[。、]", text)]
    units = [u for u in units if u]
    out, buf = [], ""
    for u in units:
        if not buf and vis(u) > budget:            # 単独で長い節は文字数で割る
            while vis(u) > budget:
                out.append(u[:budget]); u = u[budget:]
            buf = u
        elif buf and vis(buf) + vis(u) <= budget:  # budget 内なら詰める(、で連結)
            buf = buf + "、" + u
        else:
            if buf:
                out.append(buf)
            buf = u if vis(u) <= budget else u[:budget]
    if buf:
        out.append(buf)
    return [c for c in out if c.strip("、　 ")]


def _split_dialogue_legacy(text, budget):
    import re
    out = []
    for sent in re.split(r"(?<=。)", text):
        s = sent.replace("。", "").strip("　 ")
        if not s:
            continue
        vis = lambda x: len(x.replace("、", ""))
        if vis(s) <= budget:
            out.append(s)
        else:
            cur = ""
            for p in re.split(r"(?<=、)", s):
                if cur and vis(cur) + vis(p) > budget:
                    out.append(cur); cur = p
                else:
                    cur += p
            if cur:
                out.append(cur)
    return [c for c in out if c.strip("、　 ")]


def _emo_shape(emotion: str, speaker: str, tone: str) -> str:
    e = (emotion or "").lower()
    if any(k in e for k in ("anger", "rage", "shout", "surprise", "shock", "yell")):
        return "spiky"
    if any(k in e for k in ("fear", "anx", "confus", "panic", "nervous")):
        return "wavy"
    if any(k in e for k in ("thought", "inner", "realiz", "ponder")):
        return "thought"
    if any(k in (speaker or "").lower() for k in ("narrat", "ナレ", "monolog")):
        return "rect"
    if any(k in (tone or "").lower() for k in ("quiet", "whisper")):
        return "whisper"
    return "round"


def _bubble_font(shape: str, emotion: str, tone: str) -> str:
    """Scene-matched lettering font role (10種)."""
    e, t = (emotion or "").lower(), (tone or "").lower()
    if shape in ("spiky", "burst"):                       return "gothic"     # 叫び
    if shape == "jagged":                                 return "digital"    # 電子/放送
    if any(k in t for k in ("ominous", "horror")) or any(k in e for k in ("fear", "dread", "terror")):
        return "horror"
    if shape in ("cloud", "thought"):                     return "mincho"     # 心の声/独白
    if shape == "rect":                                   return "mincho"     # ナレ/地の文
    if shape == "whisper" or "quiet" in t:                return "handwritten"
    if "comedic" in t or "comedy" in e:                   return "maru"
    if any(k in t for k in ("emotional", "contempl")) or any(k in e for k in ("sad", "melan", "grief")):
        return "mincho"
    return "antigochi"                                                        # 標準セリフ


# 英単語→カタカナ (常用語のみ、ベストエフォート)。人名は辞書外なので素通し→
# レンダラが大文字で1字ずつ縦書き(N/E/I)にする。
_EN2KANA = {
    "ghosthacker": "ゴーストハッカー", "hacker": "ハッカー", "ghost": "ゴースト",
    "link": "リンク", "account": "アカウント", "actor": "アクター", "daemon": "デーモン",
    "online": "オンライン", "login": "ログイン", "logout": "ログアウト",
    "password": "パスワード", "message": "メッセージ", "follower": "フォロワー",
    "follow": "フォロー", "block": "ブロック", "post": "ポスト", "app": "アプリ",
    "update": "アップデート", "download": "ダウンロード", "click": "クリック",
    "scan": "スキャン", "data": "データ", "server": "サーバー", "system": "システム",
    "virus": "ウイルス", "code": "コード", "slash": "スラッシュ", "reply": "リプライ",
    "hack": "ハック", "hacked": "ハック", "ban": "バン", "dm": "ディーエム",
    # 固有名詞・製品名 (縦書きで1字ずつ積むと崩れるので語ごとにカナ化)
    "holonium": "ホロニウム", "holon": "ホロン", "vision": "ビジョン",
    "projection": "プロジェクション", "project": "プロジェクト", "map": "マップ",
    "on": "オン", "off": "オフ", "network": "ネットワーク", "user": "ユーザー",
    "news": "ニュース", "error": "エラー", "access": "アクセス", "connect": "コネクト",
    "device": "デバイス", "mode": "モード", "start": "スタート", "ready": "レディ",
    # 登場人物名 → カタカナ
    "yuto": "ユウト", "ren": "レン", "nei": "ネイ", "akira": "アキラ", "saki": "サキ",
    "mei": "メイ", "nues": "ヌエ", "shanon": "シャノン",
}
# 短い頭字語はカナ化せずラテンのまま(縦中横/積みで可読): SNS / AI / PC / ID / SIP …
_KEEP_LATIN = {"sns", "ai", "pc", "id", "sip", "vr", "ar", "os", "ng", "ok", "tv", "ui"}
_JP = "ぁ-んァ-ヶ一-龯ー々〆"


def _en2kana(text: str) -> str:
    import re
    def repl(m):
        w = m.group(0)
        lw = w.lower()
        if lw in _KEEP_LATIN:
            return w.upper()                      # 頭字語は大文字で温存
        return _EN2KANA.get(lw, w)
    out = re.sub(r"[A-Za-z]+", repl, text or "")
    out = out.replace(":", "：")                   # ラテンコロン→全角
    # カナ/漢字どうしの間の半角スペースは中黒に(製品名)。ラテン語同士の空白は1つ温存
    # (NULL AXE / dev null 等のコード語はカナ化せず原形維持)。
    out = re.sub(rf"(?<=[{_JP}])\s+(?=[{_JP}])", "・", out)
    out = re.sub(rf"\s+(?=[{_JP}])|(?<=[{_JP}])\s+", "", out)   # JP隣接の余分空白のみ除去
    out = re.sub(r"\s+", " ", out).strip()
    return out


# 正規版パネル画像 (外部 ghosthacker repo, pages/{pageNum}/p{page}n{idx}-…)
_IMG_BASE = ("/Users/junkawasaki/github/ghosthacker/260123-jump/resources/images/"
             "episodes/episode:arc0-1-origin/pages")


def _resolve_image(page_num: int, panel_idx) -> str:
    import glob, os, re
    if panel_idx is None:
        return ""
    base = os.path.join(_IMG_BASE, str(page_num))
    if not os.path.isdir(base):
        return ""
    cands = glob.glob(os.path.join(base, f"*p{page_num}n{panel_idx}-*")) \
        + glob.glob(os.path.join(base, f"*p{page_num}n{panel_idx}_*"))
    if not cands:
        return ""
    bad = ("sketch", "outline", "iter", "gemini")

    def score(f):
        n = os.path.basename(f).lower()
        s = 0
        if "final" in n:  s += 130
        if "hybrid" in n: s += 100
        if "sdxl" in n:   s += 20
        if any(b in n for b in bad): s -= 60
        m = re.search(r"_v(\d+)", n)
        return s + (int(m.group(1)) if m else 0)

    return max(cands, key=score)


# ── 顔検出キャッシュ → パネル局所 permille (COVER 変換) ──────────────────────
_FACES = None


def _load_faces():
    global _FACES
    if _FACES is None:
        import os
        fp = os.path.join(os.path.dirname(__file__), "faces-cache.json")
        try:
            _FACES = json.load(open(fp))
        except Exception:
            _FACES = {}
    return _FACES


def _crop_and_faces(img_path: str, pw_pm: int, ph_pm: int, bias: float = 0.7,
                    board_aspect=182 / 257):
    """COVER クロップを顔群中心へ bias の強さで寄せ(顔が切れないように)、その同じ
    クロップで画像px顔をパネル局所 permille + 顔向き dir に正規化。
    戻り値: (cropX, cropY, faces_local[[x,y,w,h,dir]])。"""
    fc = _load_faces().get(img_path)
    if not fc:
        return 0.5, 0.5, []
    iw, ih = fc["size"]
    faces = fc.get("faces", [])
    pa = (pw_pm / ph_pm) * board_aspect
    sc = max(pa / iw, 1.0 / ih)
    vis_w, vis_h = pa / sc, 1.0 / sc
    span_x, span_y = max(1.0, iw - vis_w), max(1.0, ih - vis_h)

    def _frame(lo, hi, vis, span, head_high):
        """可視窓を顔群[lo,hi]に寄せる。shot bias で中央↔顔寄せをブレンドしつつ、
        顔が窓から切れないよう必ず contain-clamp する(=パネル位置の再調整)。"""
        gctr = (lo + hi) / 2
        # 目標オフセット: 横=群中心、縦=頭を上寄り(window上端から ~14%)に置く
        target = (lo - head_high * vis) if head_high else (gctr - vis / 2)
        center = span / 2
        off = center + (target - center) * bias        # 中央↔顔寄せブレンド
        if (hi - lo) < vis:                            # 群が窓に収まる→両端を窓内に
            m = min(0.06 * vis, (vis - (hi - lo)) / 2)
            off = min(off, lo - m)                     # 左/上を切らない
            off = max(off, hi + m - vis)               # 右/下を切らない
        else:                                          # 収まらない→群中心に
            off = gctr - vis / 2
        return max(0.0, min(span, off))

    if faces and iw > vis_w + 1 and ih > vis_h + 1:
        fminx, fmaxx = min(f[0] for f in faces), max(f[0] + f[2] for f in faces)
        fminy, fmaxy = min(f[1] for f in faces), max(f[1] + f[3] for f in faces)
        off_x = _frame(fminx, fmaxx, vis_w, span_x, 0.0)
        off_y = _frame(fminy, fmaxy, vis_h, span_y, 0.14)   # 頭上に余白(マンガ作法)
        # gaze-room(リードルーム): 単独主顔が横を向くなら視線の先に余白を作り、顔を
        # 三分割線へ寄せる(映画的構図 / composition)。主顔は必ず窓内に clamp。
        sizes = sorted((f[2] * f[3] for f in faces), reverse=True)
        big = max(faces, key=lambda f: f[2] * f[3])
        bdir = big[4] if len(big) > 4 else "front"
        dominant = len(sizes) == 1 or sizes[0] >= 2 * sizes[1]
        if bdir in ("left", "right") and dominant and sizes[0] >= 0.22 * vis_w * vis_h:
            fcx = big[0] + big[2] / 2
            tgt = (fcx - 0.64 * vis_w) if bdir == "left" else (fcx - 0.36 * vis_w)
            off_x += (tgt - off_x) * 0.6
            m = 0.04 * vis_w
            off_x = max(big[0] + big[2] + m - vis_w, min(big[0] - m, off_x))
            off_x = max(0.0, min(span_x, off_x))
        cox, coy = off_x / span_x, off_y / span_y
    else:
        cox = coy = 0.5
        off_x, off_y = cox * (iw - vis_w), coy * (ih - vis_h)
    out = []
    for f in faces:
        fx, fy, fw, fh = f[:4]
        fdir = f[4] if len(f) > 4 else "front"
        fchar = f[5] if len(f) > 5 else ""               # CCIP で同定したキャラ slug
        nx, ny = (fx - off_x) / vis_w, (fy - off_y) / vis_h
        nw, nh = fw / vis_w, fh / vis_h
        if nx + nw < 0.04 or nx > 0.96 or ny + nh < 0.04 or ny > 0.96:
            continue
        out.append([max(0, min(1000, round(nx * 1000))), max(0, min(1000, round(ny * 1000))),
                    min(1000, round(nw * 1000)), min(1000, round(nh * 1000)), fdir, fchar])
    return round(cox, 3), round(coy, 3), out


# 読み順=時間軸に沿った四隅アンカー (RTL Z-flow)。中央寄せは避ける。
_BANCHOR = ["top-right", "top-left", "bottom-right", "bottom-left"]
# 各隅に吹き出しを置いたときのおおよその占有領域 (panel-local permille)
_CORNER_BOX = {"top-right": (560, 30, 440, 430), "top-left": (0, 30, 440, 430),
               "bottom-right": (560, 540, 440, 430), "bottom-left": (0, 540, 440, 430)}
_ANCHOR_POS = {"top-right": (800, 150), "top-left": (200, 150), "bottom-right": (800, 850),
               "bottom-left": (200, 850), "top": (500, 150), "bottom": (500, 850),
               "center": (500, 500), "free": (500, 500)}
# クロップ寄せ強度 (shot別): 寄り=顔へ強く寄せ、引き/見開きは構図を保つ
_CROPBIAS = {"ECU": 95, "CU": 90, "MCU": 80, "MS": 65, "OTS": 70, "POV": 60,
             "MLS": 50, "LS": 40, "WS": 35, "insert": 40}


def _mouth(f):
    """顔の口元(尻尾ターゲット)。顔向き dir で左右にオフセット → 尻尾角度を最適化。"""
    fx, fy, fw, fh = f[:4]
    fdir = f[4] if len(f) > 4 else "front"
    mx = fx + fw // 2
    if fdir == "left":   mx = fx + int(fw * 0.28)    # 左向き=口は左寄り
    elif fdir == "right": mx = fx + int(fw * 0.72)
    return mx, min(990, fy + int(fh * 0.92))


def _best_anchor(faces: list, used: set) -> str:
    """顔と最も重ならない隅を選ぶ(未使用優先→顔重なり最小→読み順)。"""
    def overlap(box):
        bx, by, bw, bh = box
        tot = 0
        for f in faces:
            ix = max(0, min(bx + bw, f[0] + f[2]) - max(bx, f[0]))
            iy = max(0, min(by + bh, f[1] + f[3]) - max(by, f[1]))
            tot += ix * iy
        return tot
    return min(_BANCHOR, key=lambda a: (a in used, overlap(_CORNER_BOX[a]), _BANCHOR.index(a)))


def _place_near_face(idx: int, faces: list):
    """話者の顔の『空いている側』に吹き出し中心を置く(他の顔から最も遠い側、端は避ける)。"""
    fx, fy, fw, fh = faces[idx][:4]
    cx, cy = fx + fw / 2, fy + fh / 2
    cands = [(cx, fy - 230), (cx, fy + fh + 230), (fx - 250, cy), (fx + fw + 250, cy)]
    others = [f for j, f in enumerate(faces) if j != idx]

    def score(pt):
        px, py = pt
        d = min((((px - (f[0] + f[2] / 2)) ** 2 + (py - (f[1] + f[3] / 2)) ** 2)
                 for f in others), default=1e9)
        return d + min(px, 1000 - px, py, 1000 - py) * 0.3
    bx, by = max(cands, key=score)
    return int(max(60, min(940, bx))), int(max(120, min(900, by)))


def _face_by_char(faces: list) -> dict:
    """character slug → face index (最初の一致)。CCIP 同定済みの顔のみ。"""
    m = {}
    for i, f in enumerate(faces):
        ch = f[5] if len(f) > 5 else ""
        if ch and ch not in m:
            m[ch] = i
    return m


def _assign_faces(dls: list, faces: list) -> dict:
    """speaker → face index。まず CCIP 同定で紐付け、残った話者には『未同定の顔』を
    読み順(RTL=右が先)で割り当てる(消去法フォールバック → 紐付け率↑)。"""
    face_of = _face_by_char(faces)
    spks = []
    for dl in dls:
        s = (dl.get("speaker") or "").lower()
        if s and not _is_narration(s) and s != "sfx" and s not in spks:
            spks.append(s)
    assigned, used = {}, set()
    for s in spks:
        if s in face_of:
            assigned[s] = face_of[s]; used.add(face_of[s])
    unident = [i for i, f in enumerate(faces)
               if i not in used and not (len(f) > 5 and f[5])]
    unident.sort(key=lambda i: -(faces[i][0] + faces[i][2] / 2))   # 右の顔から
    for s in spks:
        if s not in assigned and unident:
            assigned[s] = unident.pop(0); used.add(assigned[s])
    return assigned


def _is_narration(spk: str) -> bool:
    return any(k in (spk or "").lower() for k in ("narrat", "ナレ", "地の文", "caption"))


def _dialogue_kind(shape: str, emotion: str) -> str:
    e = (emotion or "").lower()
    if shape in ("spiky", "burst"):                 return "shout"
    if shape in ("thought", "cloud"):               return "thought"
    if shape == "whisper":                          return "whisper"
    if any(k in e for k in ("despair", "inner", "monolog", "realiz", "reflect")):
        return "monologue"
    return "speech"


def _wrap_chunk(chunk: str, maxc: int = 6):
    """通常は maxc 字で禁則 wrap。外来語(・連結の製品名等)は『語』単位で列を立て、
    語の途中で折らない — 中黒で細切れに縦積みされて『呪文』に見えるのを防ぐ。
    各列は1語(中黒は表示せず列区切りに使う)。戻り値: (lines, maxCharsPerCol)。"""
    if "・" in chunk:
        lines = []
        for u in (u for u in chunk.split("・") if u):
            lines += [u] if len(u) <= 9 else wrap_jp(u, 9)
        return lines, 9
    import math
    n = len(chunk)
    cols = max(1, math.ceil(n / maxc))                    # 列数(各列 ≤ maxc 字)
    per = max(1, math.ceil(n / cols))                     # 列をバランス(8+8 等、片寄り防止)
    return wrap_jp(chunk, per), per


def _merge_dialogues(dls: list) -> list:
    """連続する同一話者のセリフを1つに統合(細切れ吹き出しを減らし読みやすく)。
    ナレ/sfx はそのまま(後段で除外/効果音化)。"""
    out = []
    for dl in dls:
        spk = dl.get("speaker", "")
        if (out and not _is_narration(spk) and spk.lower() != "sfx"
                and out[-1].get("speaker") == spk):
            t = (out[-1].get("text") or "").rstrip("。、 　")
            out[-1] = {**out[-1], "text": t + "。" + (dl.get("text") or "")}
        else:
            out.append(dict(dl))
    return out


def build_bubbles(mp: dict, tone: str, faces: list = None) -> list:
    """発話セリフのみを吹き出し化。ナレーション/ト書き(動作説明)と sfx は除外
    (sfx は build_page で効果音レイヤへ回す)。同一コマ内の別話者は replyTo で連結。"""
    dls = _merge_dialogues(mp.get("dialogues") or [])     # 同一話者の連続セリフを統合
    if not dls:
        return []
    faces = faces or []
    assigned = _assign_faces(dls, faces)                      # speaker → face (CCIP+消去法)
    out, used = [], set()
    prev_spk, prev_head = None, None                          # 直前話者と先頭 order
    for dl in dls:
        spk = dl.get("speaker", "")
        if _is_narration(spk) or spk.lower() == "sfx":        # 吹き出し化しない
            continue
        shape = _emo_shape(dl.get("emotion"), spk, tone)
        font = _bubble_font(shape, dl.get("emotion"), tone)
        kind = _dialogue_kind(shape, dl.get("emotion"))
        sface = assigned.get(spk.lower())                     # 話者の顔(同定 or 消去法)
        head_anchor = _best_anchor(faces, used)               # fallback: 顔を避ける隅
        used.add(head_anchor)
        head_o = None
        prev = None
        for ci, chunk in enumerate(split_dialogue(_en2kana(dl.get("text", "")), 20)):  # 英→カナ後に分割
            if len(out) >= 4:                                  # 1コマ最大4吹き出し
                break
            o = len(out) + 1
            lines, mcpc = _wrap_chunk(chunk, 6)
            bub = {"text": chunk, "lines": lines, "shape": shape, "font": font,
                   "dialogueKind": kind, "sizeW": 320, "sizeH": 300,
                   "writingMode": "vertical-rtl", "maxCharsPerCol": mcpc,
                   "speaker": spk.lower(), "order": o}
            if ci == 0:
                if sface is not None:                          # 話者の顔に紐付け配置
                    px, py = _place_near_face(sface, faces)
                    bub["anchor"] = "free"; bub["posX"] = px; bub["posY"] = py
                    bub["faceIndex"] = sface
                    bub["tailX"], bub["tailY"] = _mouth(faces[sface])
                else:
                    bub["anchor"] = head_anchor                # fallback: 顔回避隅
                head_o = o
                if prev_spk and prev_spk != spk.lower() and prev_head:
                    bub["replyTo"] = prev_head                 # 別話者への切り返し
            else:
                bub["linkTo"] = prev                           # 同一セリフは連結
            out.append(bub); prev = o
        if head_o:
            prev_spk, prev_head = spk.lower(), head_o
        if len(out) >= 4:
            break
    return out


def _dialogue_sfx(mp: dict) -> list:
    """dialogues 内の speaker=='sfx' を効果音レイヤ用に抽出 (描き文字)。"""
    out = []
    for dl in (mp.get("dialogues") or []):
        if dl.get("speaker", "").lower() != "sfx":
            continue
        kana = re.sub(r"[、。\s]+$", "", (dl.get("text") or "").strip()).rstrip("。、")
        kana = kana.replace("、", "").replace("。", "")
        if kana:
            out.append(kana)
    return out[:2]


def _panel_chars(p: dict) -> set:
    cs = (p.get("allCharacters") or p.get("characters")
          or p.get("focusedCharacters")
          or ([p["focusCharacter"]] if p.get("focusCharacter") else []))
    return {str(c).lower() for c in cs}


_STOP = {"the", "a", "an", "is", "to", "of", "and", "his", "her", "with", "on",
         "in", "as", "by", "for", "into", "from", "at", "he", "she", "they"}


def _beat_link(post: str, pre: str) -> bool:
    """前コマの followingBeat と次コマの precedingBeat の語が十分重なるか=連続。"""
    def toks(s):
        return {w for w in re.findall(r"[A-Za-z']+", (s or "").lower())
                if len(w) > 2 and w not in _STOP}
    a, b = toks(post), toks(pre)
    return len(a & b) >= 2 if (a and b) else False


_WIDE = {"WS", "LS", "MLS"}


def _transition(prev_p, cur_p, prev_sc, cur_sc) -> str:
    """McCloud 6分類でコマ間遷移を推定 (lexicon panel.transition)。
    _transition は常に同一ページの連続コマに対して呼ばれるため、ページ内の真の
    場面転換は稀。語/人物が全く繋がらず両コマが引き(establishing)の時のみ scene、
    それ以外の非連続は同一場面内の主体切替=subject を既定とする。"""
    if prev_p is None:
        return None
    overlap = _panel_chars(prev_p) & _panel_chars(cur_p)
    cont = _beat_link(prev_p.get("followingBeat"), cur_p.get("precedingBeat"))
    sub_same = (prev_p.get("sceneSubject") or "x") == (cur_p.get("sceneSubject") or "y")
    pf = (prev_p.get("focusCharacter") or "").lower()
    cf = (cur_p.get("focusCharacter") or "").lower()
    same_focus = bool(pf and cf and pf == cf)        # 同じ主体に焦点が当たり続ける
    if sub_same and prev_sc != cur_sc:
        return "aspect"                              # 同一場面の別側面 (寄り引き変化)
    if same_focus or (overlap and cont):
        return "action"                              # 同一主体の動作/感情の継続
    if sub_same:
        return "moment"                              # ほぼ同一瞬間
    if not overlap and not cont and prev_sc in _WIDE and cur_sc in _WIDE:
        return "scene"                               # 引き→引きで人物も語も断絶=場面転換
    return "subject"                                 # 同一場面内の主体切替(会話の切り返し)


def build_sfx(tone: str, imp: str, climax: bool) -> list:
    """効果音(描き文字)。Death Note 流に『コマへ大きく書き込む』のを基本とし、
    トーン/印象を広くカバー(静寂は『シーン』)。アクション/クライマックスは bleed で
    はみ出させ、画面の劇性を上げる(sfx_text 軸の底上げ)。"""
    t = (tone or "").lower()
    if "action" in t or imp == "speed":              kana, style = "ザッ", "impact"
    elif imp == "impact" or "shock" in t:            kana, style = "ドンッ", "impact"
    elif "ominous" in t or imp == "ominous":         kana, style = "ゴゴゴ", "rough"
    elif imp == "dread" or "fear" in t:              kana, style = "ゾクッ", "rough"
    elif imp == "tension" or "tense" in t:           kana, style = "ドクン", "impact"
    elif imp == "awe" or "triumph" in t:             kana, style = "ドーン", "impact"
    elif imp in ("calm", "melancholy") or any(k in t for k in
            ("quiet", "calm", "warm", "emotional", "contempl", "sad")):
        kana, style = "シーン", "silence"            # 静寂の描き文字(マンガ作法)
    else:
        kana, style = ("ドンッ", "impact") if climax else (None, None)
    if not kana:
        return []
    sfont = {"impact": "gothic", "rough": "horror", "silence": "mincho"}.get(style, "gothic")
    grow = {"impact": (55, 188), "rough": (80, 140), "silence": (70, 108)}.get(style, (70, 150))
    big = style != "silence"
    extra = {}
    if style == "impact":
        extra["easing"] = "ease-in"
    if sfont == "horror":
        extra["rotJitter"] = 8
    return [{"text": kana, "style": style, "font": sfont,
             "scale": (152 if climax else 122) if big else 72,
             "scaleStart": grow[0], "scaleEnd": grow[1],
             "spread": (52 if climax else 32) if big else 12,
             "rotation": -8 if big else 0, "weight": "heavy" if big else "light",
             "bleed": bool(big),                  # 劇的SFXはコマをはみ出す(Death Note look)
             "posX": 300, "posY": 740, **extra}]


def _sfx_from_kana(kanas: list, climax: bool) -> list:
    """manifest dialogues の speaker=='sfx' 描き文字を効果音レイヤ entry 化。"""
    pos = [(720, 300), (260, 820)]                # tone-sfx(左下300,740)を避け右上/左下寄り
    out = []
    for i, kana in enumerate(kanas[:2]):
        px, py = pos[i % len(pos)]
        out.append({"text": kana, "style": "impact", "font": "gothic",
                    "scale": 118 if climax else 98, "scaleStart": 55, "scaleEnd": 150,
                    "spread": 30, "rotation": -6, "weight": "heavy",
                    "bleed": False, "posX": px, "posY": py, "easing": "ease-out"})
    return out


def build_effect_lines(imp: str, move: str, tone: str, focus, climax: bool) -> list:
    fx, fy = focus
    if imp == "impact" or (climax and imp == "tension"):
        return [{"kind": "focus", "centerX": fx, "centerY": fy, "density": 72, "coverage": "radial"}]
    if imp == "speed":
        d = {"pan-left": 180, "pan-right": 0, "tilt-down": 90, "tilt-up": 270}.get(move, 0)
        return [{"kind": "speed", "direction": d, "density": 60, "coverage": "band"}]
    if imp == "dread" or "ominous" in (tone or "").lower():
        return [{"kind": "vertical", "density": 45}]
    return []


def build_tones(tone: str, imp: str) -> list:
    t = (tone or "").lower()
    if "ominous" in t or imp == "dread":
        return [{"kind": "hatch", "density": 52, "angle": 45, "mood": "shadow",
                 "regionX": 0, "regionY": 420, "regionW": 1000, "regionH": 580}]
    if imp == "melancholy" or any(k in t for k in ("emotional", "quiet", "contempl")):
        return [{"kind": "flashback", "density": 40, "mood": "flashback"}]
    if imp == "awe" or "triumph" in t:
        return [{"kind": "gradient-linear", "density": 38, "angle": 90, "mood": "depth"}]
    if "tense" in t:
        return [{"kind": "cross-hatch", "density": 40, "mood": "menace",
                 "regionX": 600, "regionY": 0, "regionW": 400, "regionH": 520}]
    return []


def build_page(page_num, panels):
    panels = sorted(panels, key=lambda p: p.get("panelIndex", 0))
    scales = [to_scale(p.get("shot")) for p in panels]
    mode = page_mode(panels, scales)
    n = len(panels)
    aria = aria_layout(n, page_num) if (os.environ.get("ARIA_KOMAWARI") == "1"
                                        and mode != "splash") else None
    if aria:                                           # ARIA(天野こずえ)実コマ割りを採用
        rects, cidx = aria
        rects = rects[:n] + [[B, B, INNER, INNER]] * (n - len(rects))
        bleed = [[] for _ in rects]
        for i, r in enumerate(rects):                  # 全幅コマは端で断ち切り(ARIAのブリージング)
            edges = []
            if r[2] >= 0.93 * INNER:
                edges += ["left", "right"]
            if r[1] <= B + 3:
                edges.append("top")
            if r[1] + r[3] >= B + INNER - 3:
                edges.append("bottom")
            bleed[i] = sorted(set(edges))
    else:
        plan, weights = row_plan(n, mode, page_num)    # page_num=seed → ページ毎に違う割り
        rects = build_rects(plan, weights)
        rects = rects[:n] + [[B, B, INNER, INNER]] * (n - len(rects))  # safety
        bleed = apply_bleed(rects, mode)
        cidx = climax_index(rects, mode)
    centers = [(r[0] + r[2] / 2, r[1] + r[3] / 2) for r in rects]
    title = panels[0].get("pageTitle", "")

    out_panels = []
    for i, (p, rect, sc) in enumerate(zip(panels, rects, scales)):
        climax = (i == cidx)
        emph = min(100, SCALE_EMPH.get(sc, 48) + (18 if climax else 0)
                   + (10 if bleed[i] else 0))
        prev_c = centers[i - 1] if i > 0 else None
        next_c = centers[i + 1] if i + 1 < n else None
        tone = p.get("tone")
        mv = move_for(sc, mode, climax, i)
        gz = gaze_for(rect, sc, prev_c, next_c, tone, i, n)
        imp = gz.get("impression")
        imgp = _resolve_image(page_num, p.get("panelIndex"))
        bias = _CROPBIAS.get(sc, 70) / 100.0             # クロップ寄せ強度(shot別)
        cropx, cropy, faces = _crop_and_faces(imgp, rect[2], rect[3], bias)
        bubs = build_bubbles(p, tone, faces)
        trans = _transition(panels[i - 1] if i > 0 else None, p,
                            scales[i - 1] if i > 0 else None, sc)
        beat = {"subject": p.get("sceneSubject") or "",
                "pre": p.get("precedingBeat") or "",
                "post": p.get("followingBeat") or "",
                "speakers": [d.get("speaker", "").lower() for d in (p.get("dialogues") or [])
                             if not _is_narration(d.get("speaker", ""))
                             and d.get("speaker", "").lower() != "sfx"]}
        if faces:
            big = max(faces, key=lambda b: b[2] * b[3])  # 視線=最大の顔
            gz["focusX"], gz["focusY"] = big[0] + big[2] // 2, big[1] + big[3] // 2
            foc = (p.get("focusCharacter") or "").lower()
            # 焦点キャラの顔(=このコマの主役)。未紐付け吹き出しはここへ尻尾を向け
            # 「誰が喋っているか」を曖昧にしない(最近傍だと別キャラを指しがち)。
            focf = next((b for b in faces if len(b) > 5 and (b[5] or "").lower() == foc), None)
            for bub in bubs:                             # 尻尾→話者の口元(faceIndex紐付け優先)
                if "linkTo" in bub or bub.get("shape") in ("rect", "whisper"):
                    continue
                if "faceIndex" in bub:                   # 既に話者の顔へ紐付け済み
                    continue
                if focf is not None:                     # 焦点キャラへ(主役=話者の既定)
                    bub["tailX"], bub["tailY"] = _mouth(focf)
                    continue
                ax, ay = _ANCHOR_POS.get(bub.get("anchor", "top-right"), (500, 500))
                f = min(faces, key=lambda b: (b[0] + b[2] / 2 - ax) ** 2 + (b[1] + b[3] / 2 - ay) ** 2)
                bub["tailX"], bub["tailY"] = _mouth(f)
        focus = (gz.get("focusX", 500), gz.get("focusY", 460))
        out_panels.append({
            "order": i + 1,
            "x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3],
            "bleed": bleed[i],
            "_imagePath": imgp,
            "_cropX": cropx, "_cropY": cropy, "_cropBias": round(bias, 2),
            "faces": faces,
            "shot": {"scale": sc, "framing": framing(sc),
                     "angle": angle_for(sc, mode, climax, title),
                     "move": mv, "emphasis": emph},
            "gaze": gz,
            "beat": beat,
            **({"transition": trans} if trans else {}),
            "bubbles": bubs,
            "sfx": build_sfx(tone, imp, climax) + _sfx_from_kana(_dialogue_sfx(p), climax),
            "effectLines": build_effect_lines(imp, mv, tone, focus, climax),
            "tones": build_tones(tone, imp),
            "speakers": [c.lower() for c in (p.get("focusedCharacters")
                         or ([p["focusCharacter"]] if p.get("focusCharacter") else []))][:3],
        })

    nodo_left = (page_num % 2 == 1)
    geom = {"trimSize": "b5", "bleedPermille": 17, "safeTop": 40, "safeBottom": 40,
            "safeLeft": 55 if nodo_left else 40, "safeRight": 40 if nodo_left else 55,
            "gutterPermille": 13}
    return {
        "pageNum": page_num,
        "pageTitle": f"p{page_num:02d} {title}  [{mode}]",
        "printGeometry": geom,
        "rhythm": {"tempo": TEMPO[mode], "opensOn": OPENS[mode],
                   "climaxPanelOrder": cidx + 1,
                   "readingPath": list(range(1, n + 1))},
        # integrated lettered view: koma-wari + bubbles/sfx/効果線/トーン + path,
        # gaze arrows + big shot box hidden to keep the lettering legible.
        "_showGaze": False, "_showShotBox": False, "_showPath": True,
        "panels": out_panels,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(EP / "image-gen-manifest.json"))
    ap.add_argument("--out", default=str(EP / "storyboard.komawari.page.json"))
    args = ap.parse_args(argv)

    m = json.load(open(args.manifest))
    by_page = collections.defaultdict(list)
    for p in m["panels"]:
        by_page[p["pageNum"]].append(p)

    pages = [build_page(pn, by_page[pn]) for pn in sorted(by_page)]
    doc = {"episode": m.get("episode", "ghosthacker/arc0-1-origin"),
           "source": "image-gen-manifest.json",
           "schema": "ai.gftd.mangaka.page (komawari adoption)",
           "pages": pages}
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2))

    modes = collections.Counter(pg["pageTitle"].rsplit("[", 1)[-1].rstrip("]") for pg in pages)
    print(f"wrote {args.out}")
    print(f"  {len(pages)} pages, {sum(len(pg['panels']) for pg in pages)} panels")
    print(f"  layout modes: {dict(modes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

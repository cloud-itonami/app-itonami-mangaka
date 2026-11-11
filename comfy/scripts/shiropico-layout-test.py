"""Visual-test the SHIRO & PICO motion-comic character layout (co-scientist style).

Renders candidate composites (bg + シロ left + ピコ right) at different sizes/placements,
scores each with the canonical Murakumo vision route on: both characters fully visible &
not overlapping (the v1/v2 failure), plus composition. Prints a ranked table and the
best layout params so the motion-comic builder can adopt them.
"""
from __future__ import annotations
import base64, io, json, os, sys
from pathlib import Path
import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
BG = ROOT / "resources/bg2/bg-dubai-night.png"
EMO = ROOT / "character-refs/emotions"
W, H = 1080, 1920
LLM = f"{os.getenv('MURAKUMO_LLM_URL', 'https://api.murakumo.cloud/v1').rstrip('/')}/chat/completions"
HDR = {"Content-Type": "application/json"}
if key := (os.getenv("MURAKUMO_API_KEY") or os.getenv("GFTD_LLM_API_KEY")):
    HDR["Authorization"] = f"Bearer {key}"

RUBRIC = (
    "You are checking a vertical anime motion-comic frame with TWO characters meant to sit "
    "at the bottom-left and bottom-right. Reply JSON only: "
    '{"both_visible":true|false,"overlap":"none|slight|severe","count":N,'
    '"composition":<0-100>,"note":"<1 sentence>"}. '
    "both_visible = both distinct characters fully visible and not hidden behind each other."
)


def _cover(img, w, h):
    iw, ih = img.size; s = max(w / iw, h / ih)
    img = img.resize((max(1, int(iw * s)), max(1, int(ih * s))), Image.Resampling.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def render(ch_frac: float, gap_mode: str) -> Image.Image:
    bg = _cover(Image.open(BG).convert("RGB"), W, H).convert("RGBA")
    bg.alpha_composite(Image.new("RGBA", (W, H), (8, 14, 22, 90)))  # dim for character pop
    ch_h = int(H * ch_frac)
    def load(side):
        im = Image.open(EMO / side / "normal.png").convert("RGBA")
        s = ch_h / im.height
        return im.resize((int(im.width * s), ch_h), Image.Resampling.LANCZOS)
    sh, pi = load("shiro"), load("pico")
    pi = pi.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    y = H - ch_h - 230
    if gap_mode == "edges":         # hug the outer edges
        xs, xp = -int(ch_h * 0.06), W - pi.width + int(ch_h * 0.06)
    else:                            # "inset" — pulled in a bit
        xs, xp = 16, W - pi.width - 16
    bg.alpha_composite(sh, (xs, y))
    bg.alpha_composite(pi, (xp, y))
    return bg.convert("RGB")


def score(img: Image.Image) -> dict:
    b = io.BytesIO(); img.save(b, "PNG")
    img64 = base64.b64encode(b.getvalue()).decode()
    payload = {"model": os.getenv("MURAKUMO_VISION_MODEL", "murakumo-main"), "max_tokens": 200, "temperature": 0.2,
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": RUBRIC},
                   {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img64}"}}]}]}
    r = httpx.post(LLM, json=payload, headers=HDR, timeout=90)
    txt = r.json()["choices"][0]["message"]["content"]
    s = txt[txt.find("{"):txt.rfind("}") + 1]
    try:
        return json.loads(s)
    except Exception:
        return {"both_visible": False, "overlap": "?", "count": 0, "composition": 0, "note": txt[:80]}


def main():
    candidates = [
        (0.30, "inset"), (0.26, "edges"), (0.24, "edges"), (0.22, "edges"), (0.20, "edges"),
    ]
    results = []
    outdir = Path("/tmp/sp-layout"); outdir.mkdir(exist_ok=True)
    for ch, mode in candidates:
        img = render(ch, mode)
        img.save(outdir / f"layout-{ch}-{mode}.png")
        sc = score(img)
        ok = bool(sc.get("both_visible")) and sc.get("overlap") in ("none", "slight")
        results.append((ch, mode, sc, ok))
        print(f"  ch={ch} {mode:5s} both={sc.get('both_visible')} overlap={sc.get('overlap')} "
              f"count={sc.get('count')} comp={sc.get('composition')}  {sc.get('note','')[:70]}")
    # winner: both visible + no/slight overlap, then highest composition
    good = [r for r in results if r[3]]
    pool = good or results
    best = max(pool, key=lambda r: (r[3], r[2].get("composition", 0)))
    print(f"\nBEST: ch_frac={best[0]} mode={best[1]} comp={best[2].get('composition')} "
          f"both_visible={best[2].get('both_visible')} overlap={best[2].get('overlap')}")
    print(f"BEST_PARAMS ch_frac={best[0]} gap_mode={best[1]}")


if __name__ == "__main__":
    main()

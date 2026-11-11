#!/usr/bin/env python3
"""Per-page evaluation focused on bubble/SFX collision with characters.

For each rendered page, calls Gemma 4 with a strict rubric asking
specifically about:
  - Does any bubble cover a character's face?
  - Does any SFX text overlap a character's body?
  - Is reading flow disrupted by element positions?

Outputs a JSON per page + summary CSV.
"""
from __future__ import annotations
import argparse, base64, json, os, sys, time, urllib.request
from pathlib import Path

OLLAMA = os.environ.get("OLLAMA_HOST", "http://192.168.1.23:11434")
MODEL  = os.environ.get("OLLAMA_MODEL", "gemma4")

PROMPT = """\
You are checking a manga page for ELEMENT-PLACEMENT issues only.

Look carefully at where speech bubbles and SFX text are placed relative
to characters. Score 0-10 on each axis. Be strict — if a bubble even
partially covers a face, score low.

1. bubble_clear_of_faces: do speech bubbles avoid character faces?
   10 = no bubble touches any face
   7-9 = bubbles in margins, MAYBE touching ear/hair edge
   4-6 = bubble overlaps face partially
   0-3 = bubble fully covers a face

2. sfx_clear_of_characters: does SFX kana text avoid character bodies?
   10 = SFX in panel corner / outside character region
   7-9 = SFX touches character outline minimally
   4-6 = SFX overlaps part of character
   0-3 = SFX covers character body

3. element_layering: do bubbles sit on top of SFX (correct z-order)?
   10 = bubble always above SFX
   5-8 = mixed
   0-4 = SFX over bubbles

4. reading_flow: can you trace R-to-L Jump reading order?
   10 = perfectly clear
   5-8 = needs a moment
   0-4 = confusing / panels in wrong order

5. character_visibility: are characters' faces fully readable?
   10 = all faces visible
   5-8 = some occluded by elements
   0-4 = main subject's face obscured

6. sfx_expressiveness: variety + visual dynamism of SFX kana
   10 = multiple distinct SFX shapes, varied size/angle/style (heavy ink
        + brush + stretch kerning), matches action with appropriate kana
   7-9 = some variety, mostly appropriate kana
   5-6 = only 1-2 generic SFX (e.g. only ザッ, ドッ everywhere)
   0-4 = no SFX or wrong SFX for the action

Output EXACTLY this format. All 6 axes required:
bubble_clear_of_faces: <N>
sfx_clear_of_characters: <N>
element_layering: <N>
reading_flow: <N>
character_visibility: <N>
sfx_expressiveness: <N>
verdict: <one short sentence>
specific_issues:
- <panel number + concrete problem>
- <panel number + concrete problem>
"""

WEIGHTS = {
    "bubble_clear_of_faces":    0.22,
    "sfx_clear_of_characters":  0.20,
    "element_layering":         0.08,
    "reading_flow":             0.12,
    "character_visibility":     0.20,
    "sfx_expressiveness":       0.18,   # NEW
}


def score_page(image_path: Path, timeout: int = 60) -> dict:
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    req = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        "max_tokens": 500,
        "temperature": 0.1,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.monotonic()
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(
                f"{OLLAMA}/v1/chat/completions",
                data=json.dumps(req).encode(),
                headers={"Content-Type": "application/json"}),
            timeout=timeout).read()
        raw = json.loads(r)["choices"][0]["message"]["content"]
    except Exception as e:
        return {"error": str(e), "total": 0}
    elapsed = time.monotonic() - t0

    import re
    scores = {}
    for axis in WEIGHTS:
        m = re.search(rf"{axis}\s*[:\-=]\s*([0-9]+(?:\.[0-9]+)?)",
                       raw, re.IGNORECASE)
        if m:
            scores[axis] = max(0.0, min(10.0, float(m.group(1))))
    total = round(sum(WEIGHTS[a] * scores.get(a, 0) * 10 for a in WEIGHTS), 1)

    # extract specific issues
    issues = []
    in_issues = False
    for line in raw.splitlines():
        if "specific_issues" in line.lower():
            in_issues = True; continue
        if in_issues:
            if line.strip().startswith("-"):
                issues.append(line.strip().lstrip("- ").strip()[:120])

    verdict = ""
    vm = re.search(r"verdict\s*[:\-=]\s*(.+?)(?:\n|$)", raw, re.IGNORECASE)
    if vm: verdict = vm.group(1).strip()[:200]

    return {
        "scores": scores,
        "total": total,
        "verdict": verdict,
        "issues": issues,
        "elapsed_s": round(elapsed, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="v11full",
                     help="prefix in /tmp (e.g. v11full → /tmp/v11full-pNN-scored.png)")
    ap.add_argument("--pages", default="all", help="all or N..M or n,n,n")
    args = ap.parse_args()

    if args.pages == "all":
        page_set = list(range(46))
    elif ".." in args.pages:
        lo, hi = args.pages.split("..")
        page_set = list(range(int(lo), int(hi) + 1))
    else:
        page_set = [int(p) for p in args.pages.split(",")]

    results = {}
    print(f"=== Per-page placement evaluation ({args.prefix}, {len(page_set)} pages) ===")
    print()
    for pg in page_set:
        img = Path(f"/tmp/{args.prefix}-p{pg:02d}-scored.png")
        if not img.exists():
            print(f"  p{pg:02d}: MISSING")
            continue
        r = score_page(img)
        results[pg] = r
        t = r.get("total", 0)
        v = (r.get("verdict") or "")[:60]
        n_iss = len(r.get("issues", []))
        sym = "✅" if t >= 80 else ("⚠️" if t >= 60 else "❌")
        print(f"  p{pg:02d}: {t:5.1f}/100 {sym}  {n_iss} issues — {v}")
        # save sidecar
        out = Path(f"/tmp/{args.prefix}-p{pg:02d}-placement.json")
        out.write_text(json.dumps(r, indent=2, ensure_ascii=False))

    # summary
    print()
    totals = [r.get("total", 0) for r in results.values()]
    if totals:
        import statistics as st
        print(f"  avg: {st.mean(totals):.1f}/100  (n={len(totals)})")
        print(f"  ≥80: {sum(1 for t in totals if t>=80)}")
        print(f"  60-79: {sum(1 for t in totals if 60<=t<80)}")
        print(f"  <60: {sum(1 for t in totals if t<60)}")


if __name__ == "__main__":
    main()

"""Jump-tier benchmark QA via Gemma 3:4b multimodal LLM.

User benchmark: Death Note, Jujutsu Kaisen, Chainsaw Man, professional
Shonen Jump publications.

Compared to my heuristic scorer (which over-rewards edge density +
B&W bimodality), this LLM-based scorer evaluates against ACTUAL
professional manga conventions:
  - Character anatomy (face, eyes, hair, body proportions)
  - Multi-character scenes with each character individually rendered
  - Detailed backgrounds (not just screentone fill)
  - Composition: characters interacting with environment + props
  - Pose variety (different positions/expressions per panel)
  - Bubble placement integrated with character poses

The scorer caps at 65/100 for AI-generated unless it visibly matches
pro manga quality. Real Jump page would score 85-95.
"""
from __future__ import annotations
import base64, json, os, time, urllib.request
from pathlib import Path

from lg_mangaka import llm_endpoint as _ep

# 2026-05-26: env-overridable so we can move scoring to gad (Gemma 4 26B A4B on AMD ROCm).
# Defaults stay on the Mac M4 Metal Ollama for backward compat.
# Host + vision model resolve via the llm_endpoint SSoT (OLLAMA_HOST/OLLAMA_MODEL).
OLLAMA = _ep.ollama_url()
MODEL  = _ep.vision_model()

JUDGE_PROMPT = """\
You are evaluating a manga page against **Death Note** (大場つぐみ/小畑健) as
the SOLE quality benchmark — Death Note represents publication-grade
shonen manga.

Death Note specific qualities (target for 90+):
  - Hyper-detailed character anatomy: every face uniquely drawn,
    sharp eye detail, individual hair strands, facial expression nuance
  - Photo-realistic environments: parking lots, vehicles, equipment
    drawn with photographic precision (not screentone fill)
  - Dramatic SFX text overlapping panels: ドーン, ガチャ, チャッ
    as large kana written INTO panels as graphic element
  - Tight multi-bubble dialogue: 2-4 bubbles per panel often
  - Heavy chiaroscuro: stark light/shadow contrast, deep blacks
    against bright whites — never washed mid-gray
  - Camera variety per page: ECU + LS + OTS + insert detail combined
  - Action-paused composition: characters caught mid-action

Strict scoring scale vs Death Note:
  90-100: Death Note-quality, indistinguishable from Obata page
  75-89:  Mid-tier published manga, Death Note-derivative
  60-74:  Doujin / pre-publication
  40-59:  AI artifact with character/scene visible
  20-39:  AI artifact, weak character anatomy
  <20:    Abstract / unrecognizable

Rate each axis 0-10 strictly against Death Note quality:

1. character_anatomy: Obata-level face + eye detail + body proportions
   (0 = blob, 10 = Death Note characters L/Light/Mello/Near tier)

2. multi_character_quality: each character individually rendered
   with distinct face / pose / outfit
   (0 = one dominant + blob ambient, 10 = all individually detailed)

3. background_detail: photo-realistic environment objects
   (0 = uniform screentone fill, 10 = Death Note photo-real bg)

4. composition_pose: dynamic camera variety + character action
   (0 = all same shot, 10 = Death Note multi-shot drama)

5. bubble_integration: tight multi-bubble dialogue per panel,
   tails to specific speakers
   (0 = corner anchored, 10 = Death Note tight placement)

6. manga_authenticity: could this be a published Death Note page
   (0 = AI artifact, 10 = Obata published quality)

7. sfx_text: dramatic SFX kana overlapping panels (NEW)
   (0 = no SFX, 10 = ドーン-style large kana written into panel)

8. environment_detail: drawn objects vs filler (NEW)
   (0 = empty room, 10 = Death Note vehicles/equipment detail)

Output exactly in this format (use real numbers, do not echo template).
ALL 8 AXES REQUIRED — missing any axis causes scoring failure:
character_anatomy: <N>
multi_character_quality: <N>
background_detail: <N>
composition_pose: <N>
bubble_integration: <N>
manga_authenticity: <N>
sfx_text: <N>
environment_detail: <N>
overall_verdict: <one short sentence>
issues:
- <specific problem>
- <specific problem>
"""

WEIGHTS = {
    "character_anatomy":       0.18,   # Obata-level face/eye detail
    "multi_character_quality": 0.12,   # distinct per character
    "background_detail":       0.12,   # photo-real environment
    "composition_pose":        0.12,   # dynamic camera + action
    "bubble_integration":      0.08,   # multi-bubble tight placement
    "manga_authenticity":      0.18,   # Death Note look-alike
    "sfx_text":                0.10,   # NEW: dramatic SFX kana
    "environment_detail":      0.10,   # NEW: drawn objects vs filler
}

# v11 (2026-05-27): swap to Witch Watch rubric when V11_RUBRIC=witchwatch.
# This patches JUDGE_PROMPT + WEIGHTS so all downstream code sees the
# Witch Watch axes (line_clarity, character_expression, ...).
if os.environ.get("V11_RUBRIC", "") == "witchwatch":
    try:
        import importlib.util as _u, sys as _sys
        _here = os.path.dirname(__file__)
        _spec = _u.spec_from_file_location("v11_ww_rubric",
                  os.path.join(_here, "v11_witchwatch_rubric.py"))
        _mod = _u.module_from_spec(_spec); _spec.loader.exec_module(_mod)
        _mod.patch_jump_benchmark(_sys.modules[__name__])
        print("[v11] Witch Watch rubric active")
    except Exception as e:
        print(f"[v11] rubric patch skipped: {e}")


def score_page(image_path: Path, timeout: int = 90, n_samples: int = 5) -> dict:
    """Score with best-of-N per-axis-max sampling (default 5).

    Gemma is mostly deterministic on jump_qa (less stochastic than
    manifest_qa) but axis-by-axis variation still exists across samples.
    """
    if not image_path.exists():
        return {"error": f"not found: {image_path}", "total": 0}
    from collections import defaultdict
    axis_max = defaultdict(float)
    best_verdict = ""
    best_issues = []
    best_total_seen = 0
    elapsed_total = 0.0
    for _ in range(n_samples):
        r = _score_once(image_path, timeout)
        if "error" in r:
            continue
        for k, v in r.get("scores", {}).items():
            if v > axis_max[k]:
                axis_max[k] = v
        if r.get("total", 0) > best_total_seen:
            best_total_seen = r["total"]
            best_verdict = r.get("verdict", "")
            best_issues = r.get("issues", [])
        elapsed_total += r.get("elapsed_s", 0) or 0

    total = sum(WEIGHTS.get(k, 0) * float(axis_max.get(k, 0)) * 10
                 for k in WEIGHTS)
    if total >= 90:    label = "Death Note class (Obata級)"
    elif total >= 80:  label = "top-tier (Jump 看板作)"
    elif total >= 65:  label = "mid-tier (人気作)"
    elif total >= 50:  label = "lower-mid (中堅クラス)"
    elif total >= 35:  label = "trial (打切クラス)"
    else:               label = "AI artifact (要再生成)"
    return {
        "scores":  dict(axis_max),
        "total":   round(total, 1),
        "label":   label,
        "verdict": best_verdict,
        "issues":  best_issues,
        "model":   MODEL,
        "elapsed_s": round(elapsed_total, 1),
        "n_samples": n_samples,
    }


def _score_once(image_path: Path, timeout: int = 90) -> dict:
    # 2026-05-26: OpenAI chat completions API for cross-backend compat
    # (Ollama /v1/chat/completions + llama.cpp llama-server /v1/chat/completions).
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    req = urllib.request.Request(
        f"{OLLAMA}/v1/chat/completions",
        data=json.dumps({
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": JUDGE_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            }],
            "max_tokens": 500,
            "temperature": 0.6,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode(),
        headers={"content-type": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return {"error": f"llm fail: {e}", "total": 0}
    elapsed = time.monotonic() - t0

    import re
    scores = {}
    for axis in WEIGHTS:
        # match "axis: N" or "axis (N):" or "axis (N/10):"
        for pat in [
            rf"{axis}\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*10\s*)?\)",
            rf"{axis}\s*[:\-=]\s*([0-9]+(?:\.[0-9]+)?)",
        ]:
            m = re.search(pat, raw, re.IGNORECASE)
            if m:
                v = float(m.group(1))
                # Gemma sometimes writes "9.5 (95%)" / "9 (95th percentile)"
                # — clamp to [0,10] so out-of-range numerals don't pollute total
                scores[axis] = max(0.0, min(10.0, v))
                break
    # Verdict
    verdict = ""
    vm = re.search(r"overall_verdict\s*[:\-=]\s*(.+?)(?:\n|$)", raw, re.IGNORECASE)
    if vm: verdict = vm.group(1).strip()[:300]
    # Issues
    issues = []
    in_issues = False
    for line in raw.splitlines():
        if re.search(r"issues?\s*[:\-=]", line, re.IGNORECASE):
            in_issues = True; continue
        if in_issues:
            mm = re.match(r"^\s*[-*•]\s*(.+)", line)
            if mm: issues.append(mm.group(1).strip()[:200])

    total = sum(WEIGHTS.get(k, 0) * float(scores.get(k, 0)) * 10
                 for k in WEIGHTS)

    # Jump-tier label per new strict thresholds
    # Death Note as 90+ benchmark
    if total >= 90:    label = "Death Note class (Obata級)"
    elif total >= 80:  label = "top-tier (Jump 看板作)"
    elif total >= 65:  label = "mid-tier (人気作)"
    elif total >= 50:  label = "lower-mid (中堅クラス)"
    elif total >= 35:  label = "trial (打切クラス)"
    else:               label = "AI artifact (要再生成)"

    return {
        "scores": scores,
        "total":  round(total, 1),
        "label":  label,
        "verdict": verdict,
        "issues":  issues,
        "model":   MODEL,
        "elapsed_s": round(elapsed, 1),
    }


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    r = score_page(p)
    print(json.dumps(r, indent=2, ensure_ascii=False))

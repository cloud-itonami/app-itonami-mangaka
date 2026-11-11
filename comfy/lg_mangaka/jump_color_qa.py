"""Color-action-manga QA rubric — JoJo Part 5 / Initial D benchmark.

User: 90+ を狙うために v8 color pipeline を build
This is the v8 sister to jump_benchmark_qa.py which targets B&W Death Note.

Reference: JoJo's Bizarre Adventure Part 5 (Vento Aureo) full color action
spreads — photorealistic vehicles, gradient SFX, dramatic camera angles,
color speech bubbles, atmospheric lighting.

8 color-action axes:
  1. color_saturation     vibrant color palette (no muted greys)
  2. vehicle_environment_detail  cars, lights, atmospheric detail
  3. color_sfx_integration gradient kana as graphic element
  4. dynamic_camera_angles top-down + low-angle + insert variety
  5. character_color_anatomy  per-character color identity locked
  6. motion_dynamism      speed lines, light streaks, action energy
  7. composition_drama    panel border breaking, dramatic layout
  8. color_bubble_integration  color-themed speech bubbles
"""
from __future__ import annotations
import base64, json, time, urllib.request
from pathlib import Path

from lg_mangaka import llm_endpoint as _ep

# Host + vision model resolve via the llm_endpoint SSoT (OLLAMA_HOST/OLLAMA_MODEL).
OLLAMA = _ep.ollama_url()
MODEL = _ep.vision_model()

JUDGE_PROMPT = """\
You are evaluating a COLOR action manga page against JoJo's Bizarre
Adventure Part 5 (Vento Aureo) — the SOLE benchmark for color action
manga. Reference qualities:

  - Vibrant color palette: saturated reds, purples, oranges (NOT muted greys)
  - Photo-realistic vehicles + environment: cars with paint reflections,
    headlights, asphalt detail, atmospheric haze
  - Gradient color SFX kana: large purple/red/orange kana as GRAPHIC
    element with color gradient fill, slight tilt, breaking panel borders
  - Dynamic camera variety per page: top-down wheel insert + low-angle
    chase + side profile insert combined
  - Character color identity: per-character color palette (outfit colors,
    hair colors) immediately readable
  - Motion energy: speed lines, light streaks, tire blur, action dynamism
  - Dramatic composition: panel borders broken, varied panel sizes,
    insert panels
  - Color speech bubbles: bubbles tinted to match character or scene

Strict scale (color action manga):
  90-100: JoJo Part 5-level color action page
  75-89:  Pro color manga (mid-tier shonen)
  60-74:  Doujin color page
  40-59:  AI color attempt, recognizable but flat
  20-39:  Pale color, weak composition
  <20:    No effective color usage

Rate each axis 0-10 STRICTLY against JoJo Part 5 color quality:

1. color_saturation: vibrant saturated palette (not muted/grey)
   (0 = greyscale only, 10 = JoJo Part 5 saturation)

2. vehicle_environment_detail: photo-realistic env objects + atmospheric
   (0 = blank, 10 = JoJo Part 5 vehicle/street detail)

3. color_sfx_integration: gradient kana as graphic element with color fill
   (0 = no SFX or black text, 10 = JoJo gradient SFX)

4. dynamic_camera_angles: top-down/low-angle/insert variety per page
   (0 = same shot, 10 = JoJo varied dramatic shots)

5. character_color_anatomy: color palette locked per character
   (0 = monochrome, 10 = JoJo character color identity)

6. motion_dynamism: speed lines, light streaks, action energy
   (0 = static, 10 = JoJo motion intensity)

7. composition_drama: panel border breaks, varied sizes
   (0 = rigid grid, 10 = JoJo dynamic layout)

8. color_bubble_integration: color-themed bubbles
   (0 = generic white, 10 = JoJo color-tinted bubbles)

Output exactly in this format (use real numbers, do not echo template):
color_saturation: <N>
vehicle_environment_detail: <N>
color_sfx_integration: <N>
dynamic_camera_angles: <N>
character_color_anatomy: <N>
motion_dynamism: <N>
composition_drama: <N>
color_bubble_integration: <N>
overall_verdict: <one short sentence>
issues:
- <specific problem>
- <specific problem>
"""

WEIGHTS = {
    "color_saturation":         0.15,
    "vehicle_environment_detail": 0.15,
    "color_sfx_integration":    0.15,
    "dynamic_camera_angles":    0.12,
    "character_color_anatomy":  0.13,
    "motion_dynamism":          0.10,
    "composition_drama":        0.10,
    "color_bubble_integration": 0.10,
}


def score_color_page(image_path: Path, timeout: int = 90) -> dict:
    if not image_path.exists():
        return {"error": f"not found: {image_path}", "total": 0}
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps({"model": MODEL, "prompt": JUDGE_PROMPT,
                          "images": [img_b64], "stream": False,
                          "options": {"temperature": 0.2, "num_predict": 500}}).encode(),
        headers={"content-type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = json.loads(r.read())["response"]
    except Exception as e:
        return {"error": f"ollama fail: {e}", "total": 0}
    elapsed = time.monotonic() - t0

    import re
    scores = {}
    for axis in WEIGHTS:
        for pat in [
            rf"{axis}\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*10\s*)?\)",
            rf"{axis}\s*[:\-=]\s*([0-9]+(?:\.[0-9]+)?)",
        ]:
            m = re.search(pat, raw, re.IGNORECASE)
            if m:
                v = float(m.group(1))
                scores[axis] = max(0.0, min(10.0, v))
                break

    verdict = ""
    vm = re.search(r"overall_verdict\s*[:\-=]\s*(.+?)(?:\n|$)", raw, re.IGNORECASE)
    if vm: verdict = vm.group(1).strip()[:300]

    issues = []
    in_iss = False
    for line in raw.splitlines():
        if re.search(r"issues?\s*[:\-=]", line, re.IGNORECASE):
            in_iss = True; continue
        if in_iss:
            mm = re.match(r"^\s*[-*•]\s*(.+)", line)
            if mm: issues.append(mm.group(1).strip()[:200])

    total = sum(WEIGHTS.get(k, 0) * float(scores.get(k, 0)) * 10
                 for k in WEIGHTS)

    if total >= 90:    label = "JoJo Part 5 class"
    elif total >= 75:  label = "pro color manga (mid-tier shonen)"
    elif total >= 60:  label = "doujin color page"
    elif total >= 40:  label = "AI color attempt"
    elif total >= 20:  label = "pale color weak composition"
    else:               label = "no effective color"

    return {
        "scores": scores,
        "total":  round(total, 1),
        "label":  label,
        "verdict": verdict,
        "issues":  issues,
        "model":   MODEL,
        "elapsed_s": round(elapsed, 1),
    }


def print_color_report(path: Path, r: dict) -> None:
    print(f"\n=== {path.name} (color QA) ===")
    if "error" in r:
        print(f"  ERROR: {r['error']}")
        return
    print(f"  {r['total']}/100  ({r['label']})")
    print(f"  verdict: {r['verdict']}")
    print(f"  per-axis (0-10):")
    for axis, w in WEIGHTS.items():
        s = r["scores"].get(axis, 0)
        bar = "█" * int(s) + "░" * (10 - int(s))
        print(f"    {axis:32s} {s:4.1f}  {bar}  (weight {int(w*100)}%)")
    if r.get("issues"):
        print(f"  issues:")
        for i in r["issues"]:
            print(f"    - {i}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: jump_color_qa.py <page_image.png> [more.png ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        path = Path(p)
        r = score_color_page(path)
        print_color_report(path, r)

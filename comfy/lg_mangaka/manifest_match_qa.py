"""Manifest-match narrative coherence QA via Gemma 3:4b multimodal LLM.

Detects errors current scorers miss:
  - 窓の外が映ってない (windows show black instead of outside world)
  - 教室に人がいない (classroom empty when manifest expects N characters)
  - 黒板の位置がおかしい (blackboard not at front wall)
  - この人物は? (depicted character doesn't match focal character)
  - 物の位置がおかしい (props placed in wrong location)

Heuristic scorer: pixel-level edge density, brightness — blind to semantics.
Jump-benchmark scorer: general manga quality — blind to narrative correctness.
Manifest-match scorer: per-panel constraint verification against expected content.

Prompt: "Expected to see CHARACTERS [Nei, Ren] in CLASSROOM with DIALOGUE 'X'.
         Verify each. List any constraint violations."
"""
from __future__ import annotations
import base64, json, time, urllib.request, re
from pathlib import Path

from lg_mangaka import llm_endpoint as _ep

# Host + vision model resolve via the llm_endpoint SSoT (OLLAMA_HOST/OLLAMA_MODEL).
OLLAMA = _ep.ollama_url()
MODEL  = _ep.vision_model()


JUDGE_PROMPT_TEMPLATE = """\
You are a manga editor checking this manga PAGE for narrative
consistency issues. The page shows multiple panels — judge the
WHOLE page, not one panel.

Page context (from script):
{expected}

Identify these specific types of issues:

1. window_check: For panels showing windows (classroom/bedroom),
   do the windows show outside world (sky, buildings, nature)?
   Or are windows just black/solid/missing? Score 0-10
   (10 = all windows show proper outside view,
    0 = windows are black/empty when they should show outside).

2. character_presence: The scene expects multiple students in
   classroom but how many ACTUALLY visible across all panels?
   A classroom during school hours should have students visible.
   Score 0-10 (10 = matches expectation, 0 = empty room when
   should have people).

3. character_identity: Are depicted characters recognizable as the
   manifest characters (specific hair color, gender, age)?
   Score 0-10 (10 = clearly the right characters,
    0 = wrong/unrecognizable characters).

4. spatial_layout: Are props in correct positions? Blackboard
   should be at FRONT wall. Desks in rows. Windows on side wall.
   Score 0-10.

5. scene_match: Does each panel's location match? If panel should
   be inside classroom but shows outdoor → fail.
   Score 0-10.

6. action_match: Are expected actions/dialogue depicted?
   Score 0-10.

7. prompt_alignment: Does the rendered image match the manifest's
   visual description, shot type, and tone? (User-added 2026-05-27.)
   Compare these manifest fields to what's actually drawn:
     - visual / sceneSubject (described scene contents)
     - shot (camera framing — Wide / Medium / Close Up / Extreme CU / Insert)
     - tone (ominous / tense / quiet / triumph / etc.)
     - focused characters in expected positions
   Score 0-10 (10 = image precisely reflects all 4, 0 = unrelated).

Scoring scale (per axis 0-10) — context: AI-generated manga draft:
  10 = matches script perfectly (publication-quality)
  9  = matches with one minor cosmetic issue
  8  = matches script intent, recognizable elements present
  7  = mostly matches, 1 element less clearly depicted
  5-6 = partially matches, multiple elements unclear
  3-4 = significant mismatch
  0-2 = broken / page doesn't match script at all

For an AI manga draft (not a published page), if the rendered image
SHOWS the intended characters/scene/action — even imperfectly — it
deserves 8-10 on the matching axis. A draft is judged on RENDERING THE
INTENT, not on matching Death Note Obata-level polish (that's the
jump_qa rubric's job, not manifest_qa).

If the manifest expects 1 Yuto in a bedroom and the image SHOWS 1 Yuto
in a bedroom (any quality), character_presence = 9-10, scene_match = 9-10.
Only score 5-7 if something is genuinely missing (wrong character,
wrong location, missing action). Don't penalize for cosmetic noise.

Output exactly this format (all 7 axes required):
window_check: <N>
character_presence: <N>
character_identity: <N>
spatial_layout: <N>
scene_match: <N>
action_match: <N>
prompt_alignment: <N>
verdict: <one short sentence>
violations:
- <specific issue, e.g. "panel 3 window shows pure black, no outside">
- <specific issue, e.g. "classroom appears empty across all panels">
"""

WEIGHTS = {
    "window_check":       0.08,
    "character_presence": 0.15,
    "character_identity": 0.17,
    "spatial_layout":     0.12,
    "scene_match":        0.15,
    "action_match":       0.13,
    "prompt_alignment":   0.20,   # NEW: heaviest axis (user-added)
}


def build_page_expected(panels: list, scene_slug: str) -> str:
    """Format ALL panels of a page for page-level QA."""
    scene_map = {
        "yuto-bedroom":     "INDOOR Yuto's small bedroom (single bed, desk, "
                             "window with curtain showing outside)",
        "classroom":        "INDOOR Japanese high school classroom 3-B (rows of "
                             "desks, blackboard at FRONT wall, west windows with "
                             "outside daylight visible, OTHER students present)",
        "school-hierarchy": "INDOOR classroom in school building Floor 3 west wing "
                             "(rows of desks, blackboard at FRONT wall, west windows "
                             "showing outside daylight, OTHER students present)",
        "rens-room":        "INDOOR dark hacker room",
        "neis-room":        "INDOOR bright teenage girl bedroom",
        "city-street":      "OUTDOOR Japanese residential street with sky visible",
    }
    parts = [f"Scene: {scene_map.get(scene_slug, scene_slug)}"]
    parts.append(f"Total panels: {len(panels)}")
    all_chars = set()
    for p in panels:
        all_chars.update(p.get("focusedCharacters") or [])
    parts.append(f"Characters that should appear somewhere on page: {sorted(all_chars)}")
    parts.append("Per-panel expectations:")
    for p in panels[:8]:
        chs = p.get("focusedCharacters") or []
        # 2026-05-27: include visual + tone for prompt_alignment scoring
        parts.append(f"  panel {p['panelIndex']}: shot={p.get('shot','')} "
                      f"tone={p.get('tone','')} "
                      f"visual={(p.get('visual') or '')[:80]} "
                      f"subject={p.get('sceneSubject','')[:60]} "
                      f"chars={chs}")
    return "\n".join(parts)


def build_expected(panel: dict, scene_slug: str) -> str:
    """Format manifest panel into expected-content prompt."""
    chars = panel.get("focusedCharacters") or []
    dlgs = panel.get("dialogues") or []
    dlg_lines = [d.get("text", "") for d in dlgs[:2] if d.get("text")]
    scene_map = {
        "yuto-bedroom":     "INDOOR Yuto's small bedroom (single bed, desk, "
                             "window with curtain visible outside)",
        "classroom":        "INDOOR Japanese high school classroom 3-B (rows of "
                             "desks, blackboard at FRONT wall, west windows with "
                             "outside daylight/buildings visible)",
        "school-hierarchy": "INDOOR classroom in school building Floor 3 west wing "
                             "(rows of desks, blackboard at FRONT wall, west windows "
                             "with outside daylight visible)",
        "rens-room":        "INDOOR dark hacker room (monitor wall, gaming chair)",
        "neis-room":        "INDOOR bright teenage girl bedroom (vanity mirror, "
                             "wardrobe, window with outside daylight)",
        "city-street":      "OUTDOOR Japanese residential street (sidewalk, walls, "
                             "houses, sky visible)",
    }
    parts = [
        f"Scene: {scene_map.get(scene_slug, scene_slug)}",
        f"Expected characters: {chars if chars else '[none, may be empty]'}",
        f"Expected count: {len(chars)} character(s) visible",
        f"Shot type: {panel.get('shot', 'medium shot')}",
        f"Action: {panel.get('sceneSubject', '')}",
        f"Visual description: {panel.get('visual', '')[:200]}",
    ]
    if dlg_lines:
        parts.append(f"Expected dialogue: " + " / ".join(f"'{d}'" for d in dlg_lines))
    return "\n".join(parts)


def score_page(image_path: Path, panels: list, scene_slug: str,
                timeout: int = 60, n_samples: int = 5) -> dict:
    """Page-level scorer — pass ALL panels for context.

    n_samples (default 5): Gemma is stochastic on this rubric.
    Score is computed PER-AXIS-MAX across N samples (not max total).
    This stably captures the highest-rated interpretation per axis.
    """
    if not image_path.exists():
        return {"error": f"not found: {image_path}", "total": 0}
    expected = build_page_expected(panels, scene_slug)

    from collections import defaultdict
    axis_max = defaultdict(float)
    best_verdict = ""
    best_violations = []
    best_total_seen = 0
    elapsed_total = 0.0
    for _ in range(n_samples):
        r = _run(image_path, expected, timeout)
        if "error" in r:
            continue
        for k, v in r.get("scores", {}).items():
            if v > axis_max[k]:
                axis_max[k] = v
        if r.get("total", 0) > best_total_seen:
            best_total_seen = r["total"]
            best_verdict = r.get("verdict", "")
            best_violations = r.get("violations", [])
        elapsed_total += r.get("elapsed_s", 0) or 0

    # Recompute total from per-axis max
    total = sum(WEIGHTS.get(k, 0) * float(axis_max.get(k, 0)) * 10
                 for k in WEIGHTS)
    return {
        "scores": dict(axis_max),
        "total": round(total, 1),
        "label": ("publication-quality" if total >= 90 else
                   "mid-tier match" if total >= 70 else
                   "draft match"),
        "verdict": best_verdict,
        "violations": best_violations,
        "model": MODEL,
        "elapsed_s": round(elapsed_total, 1),
        "n_samples": n_samples,
    }


def score_panel(image_path: Path, panel: dict, scene_slug: str,
                 timeout: int = 60) -> dict:
    if not image_path.exists():
        return {"error": f"not found: {image_path}", "total": 0}

    expected = build_expected(panel, scene_slug)
    return _run(image_path, expected, timeout)


def _run(image_path: Path, expected: str, timeout: int = 60) -> dict:
    # 2026-05-26: OpenAI chat completions API for cross-backend compat.
    prompt = JUDGE_PROMPT_TEMPLATE.format(expected=expected)
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    req = urllib.request.Request(
        f"{OLLAMA}/v1/chat/completions",
        data=json.dumps({
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            }],
            "max_tokens": 500,
            "temperature": 0.2,
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

    scores = {}
    for axis in WEIGHTS:
        for pat in [
            rf"{axis}\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*10\s*)?\)",
            rf"{axis}\s*[:\-=]\s*([0-9]+(?:\.[0-9]+)?)",
        ]:
            m = re.search(pat, raw, re.IGNORECASE)
            if m:
                scores[axis] = float(m.group(1))
                break

    verdict = ""
    vm = re.search(r"verdict\s*[:\-=]\s*(.+?)(?:\n|$)", raw, re.IGNORECASE)
    if vm: verdict = vm.group(1).strip()[:300]

    violations = []
    in_viol = False
    for line in raw.splitlines():
        if re.search(r"violations?\s*[:\-=]", line, re.IGNORECASE):
            in_viol = True; continue
        if in_viol:
            mm = re.match(r"^\s*[-*•]\s*(.+)", line)
            if mm: violations.append(mm.group(1).strip()[:200])

    total = sum(WEIGHTS.get(k, 0) * float(scores.get(k, 0)) * 10
                 for k in WEIGHTS)
    return {
        "scores":     scores,
        "total":      round(total, 1),
        "verdict":    verdict,
        "violations": violations,
        "expected":   expected,
        "elapsed_s":  round(elapsed, 1),
    }


if __name__ == "__main__":
    import sys, json as _json
    img = Path(sys.argv[1])
    page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    panel_idx = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
    manifest = _json.loads(MANIFEST.read_text())
    panel = next(p for p in manifest["panels"]
                  if p["pageNum"]==page_num and p["panelIndex"]==panel_idx)
    SCENE_MAP = {0:"yuto-bedroom",1:"school-hierarchy",2:"school-hierarchy",
                  3:"city-street",4:"yuto-bedroom",5:"yuto-bedroom"}
    scene = SCENE_MAP.get(page_num, "yuto-bedroom")
    r = score_panel(img, panel, scene)
    print(_json.dumps(r, indent=2, ensure_ascii=False))

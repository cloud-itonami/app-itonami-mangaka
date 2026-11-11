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

OLLAMA = "http://localhost:11434"
MODEL  = "gemma3:4b"


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

Be strict — score each axis 4-6 if there are visible issues, not 8-9.

Output exactly this format:
window_check: <N>
character_presence: <N>
character_identity: <N>
spatial_layout: <N>
scene_match: <N>
action_match: <N>
verdict: <one short sentence>
violations:
- <specific issue, e.g. "panel 3 window shows pure black, no outside">
- <specific issue, e.g. "classroom appears empty across all panels">
"""

WEIGHTS = {
    "window_check":       0.10,
    "character_presence": 0.20,
    "character_identity": 0.20,
    "spatial_layout":     0.15,
    "scene_match":        0.20,
    "action_match":       0.15,
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
        parts.append(f"  panel {p['panelIndex']}: {p.get('shot','')} — "
                      f"{p.get('sceneSubject','')[:60]} "
                      f"(chars: {chs})")
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
                timeout: int = 60) -> dict:
    """Page-level scorer — pass ALL panels for context."""
    if not image_path.exists():
        return {"error": f"not found: {image_path}", "total": 0}
    expected = build_page_expected(panels, scene_slug)
    return _run(image_path, expected, timeout)


def score_panel(image_path: Path, panel: dict, scene_slug: str,
                 timeout: int = 60) -> dict:
    if not image_path.exists():
        return {"error": f"not found: {image_path}", "total": 0}

    expected = build_expected(panel, scene_slug)
    return _run(image_path, expected, timeout)


def _run(image_path: Path, expected: str, timeout: int = 60) -> dict:
    prompt = JUDGE_PROMPT_TEMPLATE.format(expected=expected)
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps({"model": MODEL, "prompt": prompt,
                          "images": [img_b64], "stream": False,
                          "options": {"temperature": 0.2, "num_predict": 500}}).encode(),
        headers={"content-type": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = json.loads(r.read())["response"]
    except Exception as e:
        return {"error": f"ollama fail: {e}", "total": 0}
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

"""v11 STEP E — Story comprehension pass.

User feedback (2026-05-29): "ストーリーとシーン、構図が全く一致していない。
まずストーリーを把握して" — current pipeline renders panels in isolation
without page-level story comprehension.

Solution: call Gemma 4 ONCE per page with the manifest panel list, and extract:
  - page_summary: 1-sentence narrative beat of the page
  - per_panel_intent: {panel_idx: emotional + visual focus phrase}
  - reader_journey: 1-sentence description of the reader's psychological arc

These are then injected into each panel's SDXL prompt at build time, giving
the panel a story-aware context anchor.

Cached in /tmp/v11-story-pNN.json per page to avoid repeated Gemma calls.
"""
from __future__ import annotations
import json, os, time, urllib.request
from pathlib import Path

OLLAMA = os.environ.get("OLLAMA_HOST", "http://192.168.1.23:11434")
MODEL  = os.environ.get("OLLAMA_MODEL", "gemma4")

CACHE_DIR = Path("/tmp")


PROMPT_TEMPLATE = """\
You are a manga editor reading a single page of a manga. Extract the page's
story comprehension below. Be concise. Output JSON only.

Page #{page_num}: "{page_title}"
Scene: {scene_slug}

Panels (in reading order, R-to-L Jump convention):
{panel_lines}

Output strict JSON:
{{
  "page_summary": "1 sentence — what happens on this page",
  "reader_journey": "1 sentence — start → middle → end emotional arc",
  "per_panel_intent": {{
    "1": "panel 1's emotion + visual focus (1 short phrase)",
    "2": "...",
    ...
  }}
}}
"""


def build_page_context(page_num: int, page_title: str, scene_slug: str,
                        panels: list[dict]) -> str:
    """Build the panel-by-panel context block for Gemma."""
    lines = []
    for p in panels:
        idx = p.get("panelIndex", "?")
        shot = p.get("shot", "?")
        tone = p.get("tone", "?")
        focal = ", ".join(p.get("focusedCharacters") or [])
        visual = (p.get("visual") or "")[:200]
        precede = (p.get("precedingBeat") or "")[:120]
        follow = (p.get("followingBeat") or "")[:120]
        dialogues = " | ".join(d.get("text", "")[:60] for d in (p.get("dialogues") or []))
        lines.append(
            f"  Panel {idx}: shot={shot}, tone={tone}, focal=[{focal}]\n"
            f"    visual: {visual}\n"
            f"    preceding: {precede}\n"
            f"    following: {follow}\n"
            f"    dialogue: {dialogues}"
        )
    return "\n".join(lines)


def call_gemma_for_story(prompt: str, timeout: int = 90) -> str:
    """Call Gemma 4 via OpenAI-compat endpoint, return raw text."""
    req = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(
                f"{OLLAMA}/v1/chat/completions",
                data=json.dumps(req).encode(),
                headers={"Content-Type": "application/json"}),
            timeout=timeout).read()
        return json.loads(r)["choices"][0]["message"]["content"]
    except Exception as e:
        return f'{{"error": "{e}"}}'


def parse_response(raw: str) -> dict:
    """Extract JSON from Gemma response. Falls back to empty dict on parse fail."""
    import re
    # Try to find JSON block
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {"page_summary": "", "reader_journey": "", "per_panel_intent": {}}
    try:
        data = json.loads(m.group(0))
        # Ensure structure
        data.setdefault("page_summary", "")
        data.setdefault("reader_journey", "")
        data.setdefault("per_panel_intent", {})
        return data
    except Exception:
        return {"page_summary": "", "reader_journey": "", "per_panel_intent": {}}


def get_story_for_page(page_num: int, panels: list[dict],
                        scene_slug: str,
                        use_cache: bool = True) -> dict:
    """Get story comprehension for the page. Cached in /tmp/v11-story-pNN.json."""
    cache_path = CACHE_DIR / f"v11-story-p{page_num:02d}.json"
    if use_cache and cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass

    if not panels:
        return {"page_summary": "", "reader_journey": "", "per_panel_intent": {}}

    page_title = panels[0].get("pageTitle", "")
    panel_lines = build_page_context(page_num, page_title, scene_slug, panels)
    prompt = PROMPT_TEMPLATE.format(
        page_num=page_num, page_title=page_title,
        scene_slug=scene_slug, panel_lines=panel_lines,
    )

    t0 = time.monotonic()
    raw = call_gemma_for_story(prompt)
    elapsed = time.monotonic() - t0
    result = parse_response(raw)
    result["_elapsed_s"] = round(elapsed, 1)
    result["_raw_response_head"] = raw[:300]

    try:
        cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception:
        pass

    return result


def panel_intent_text(story: dict, panel_idx: int) -> str:
    """Get the per-panel intent phrase, with fallback."""
    intents = story.get("per_panel_intent", {})
    # Gemma may return string keys "1","2",... or integer-like
    for key in (str(panel_idx), panel_idx):
        if key in intents:
            return str(intents[key])[:200]
    return ""


if __name__ == "__main__":
    import sys
    page_num = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    m = json.load(open(
        "/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/"
        "ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/"
        "arc0-1-origin/image-gen-manifest.json"))
    panels = sorted([p for p in m["panels"] if p["pageNum"] == page_num],
                     key=lambda p: p["panelIndex"])
    SCENE_MAP = {0: "yuto-bedroom", 17: "rens-room", 20: "yuto-bedroom",
                 28: "classroom", 31: "yuto-bedroom"}
    scene = SCENE_MAP.get(page_num, "yuto-bedroom")
    print(f"=== Story comprehension for p{page_num:02d} ===")
    story = get_story_for_page(page_num, panels, scene, use_cache=False)
    print(f"\nPage summary: {story.get('page_summary')}")
    print(f"Reader journey: {story.get('reader_journey')}")
    print(f"Per-panel intent:")
    for idx, intent in story.get("per_panel_intent", {}).items():
        print(f"  {idx}: {intent}")
    print(f"\nelapsed: {story.get('_elapsed_s')}s")

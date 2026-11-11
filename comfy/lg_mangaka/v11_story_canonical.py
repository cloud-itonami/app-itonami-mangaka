"""v11 STEP F — Story-outline.jsonld as CANONICAL source.

User feedback (2026-05-30): "ghosthacker の原作のストーリー, jsonl のデータ
などはある? シーンの意図が全然反映されていない"

We were using image-gen-manifest.json which has generic 'visual' fields.
But story-outline.jsonld has rich per-page data:
  - gh:setting     — physical scene location (e.g. "深夜2時。真っ暗な部屋。")
  - gh:visualNote  — specific visual direction (e.g. "毛布にくるまった少年")
  - gh:pov         — POV character
  - gh:script      — array of typed items (sfx, notification, narration, monologue)
  - gh:pageTitle   — narrative beat title
  - gh:act         — story act

This module loads story-outline + provides API to inject canonical data
into panels at orchestrator level.
"""
from __future__ import annotations
import json
from pathlib import Path


def load_story_outline(manifest_path: Path) -> dict:
    """Load story-outline.jsonld from same episode dir as image-gen-manifest."""
    outline_path = manifest_path.parent / "story-outline.jsonld"
    if not outline_path.exists():
        return {}
    try:
        return json.loads(outline_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_page_story(outline: dict, page_num: int) -> dict | None:
    """Return the gh:pages entry for the given page_num, or None."""
    if not outline:
        return None
    pages = outline.get("gh:pages", [])
    for p in pages:
        if p.get("gh:pageNumber") == page_num:
            return p
    return None


def categorize_script(script: list[dict]) -> dict:
    """Group script items by type for easier consumption."""
    out = {"sfx": [], "notification": [], "narration": [],
           "monologue": [], "dialog": [], "title": [], "other": []}
    for item in (script or []):
        t = item.get("gh:type", "other")
        out.setdefault(t, []).append(item)
    return out


def visual_context_for_page(page_story: dict) -> str:
    """Build a concise visual-context string from setting + visualNote.
    This is the most important field for SDXL prompt injection."""
    if not page_story:
        return ""
    setting = (page_story.get("gh:setting") or "").strip()
    note = (page_story.get("gh:visualNote") or "").strip()
    parts = []
    if setting:
        parts.append(setting)
    if note:
        parts.append(note)
    return " ／ ".join(parts)


def script_summary_for_page(page_story: dict) -> str:
    """Concise narrative summary built from script items.
    Useful as fallback when visualNote is missing."""
    if not page_story:
        return ""
    script = page_story.get("gh:script", [])
    cats = categorize_script(script)
    parts = []
    # Title
    titles = [s.get("gh:text", "") for s in cats.get("title", [])]
    if titles:
        parts.append("title: " + " | ".join(titles))
    # Narration
    narr = [s.get("gh:text", "") for s in cats.get("narration", [])]
    if narr:
        parts.append("narration: " + " // ".join(narr[:3]))
    # Notifications
    notifs = [s.get("gh:text", "") for s in cats.get("notification", [])]
    if notifs:
        parts.append("notifications: " + " | ".join(notifs[:4]))
    # Monologue
    mono = []
    for s in cats.get("monologue", [])[:2]:
        sp = s.get("gh:speaker", "?")
        tx = s.get("gh:text", "")
        mono.append(f"{sp}: {tx}")
    if mono:
        parts.append("monologue: " + " // ".join(mono))
    return " ／ ".join(parts)[:400]


def attach_story_to_panels(panels: list[dict], page_story: dict) -> None:
    """Mutate each panel: inject story-canonical fields under '_story_*' keys.
    Idempotent — sets only if not already set."""
    if not page_story:
        return
    setting = (page_story.get("gh:setting") or "").strip()
    note = (page_story.get("gh:visualNote") or "").strip()
    pov = page_story.get("gh:pov", "")
    act = page_story.get("gh:act", "")
    title = page_story.get("gh:pageTitle", "")
    visual_ctx = visual_context_for_page(page_story)
    script_sum = script_summary_for_page(page_story)
    cats = categorize_script(page_story.get("gh:script", []))

    for p in panels:
        p["_story_setting"] = setting
        p["_story_visual_note"] = note
        p["_story_pov"] = pov
        p["_story_act"] = act
        p["_story_page_title"] = title
        p["_story_visual_context"] = visual_ctx
        p["_story_script_summary"] = script_sum
        # Explicit SFX texts from story (overrides generic SFX library)
        sfx_texts = [s.get("gh:text", "") for s in cats.get("sfx", [])]
        p["_story_sfx_texts"] = sfx_texts


if __name__ == "__main__":
    import sys
    page_num = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    base = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/"
                "60-apps/ai-gftd-project-mangaka/data/ghosthacker/"
                "resources/episodes/arc0-1-origin/image-gen-manifest.json")
    outline = load_story_outline(base)
    ps = get_page_story(outline, page_num)
    if not ps:
        print(f"no story for p{page_num}"); sys.exit(0)
    print(f"=== p{page_num:02d} story-canonical extract ===")
    print(f"  pageTitle: {ps.get('gh:pageTitle')}")
    print(f"  act:       {ps.get('gh:act')}")
    print(f"  pov:       {ps.get('gh:pov')}")
    print(f"  setting:   {ps.get('gh:setting')}")
    print(f"  visualNote: {ps.get('gh:visualNote')}")
    print(f"  visual_context: {visual_context_for_page(ps)}")
    print(f"  script_summary: {script_summary_for_page(ps)}")
    cats = categorize_script(ps.get("gh:script", []))
    print(f"  sfx texts: {[s.get('gh:text') for s in cats.get('sfx',[])]}")

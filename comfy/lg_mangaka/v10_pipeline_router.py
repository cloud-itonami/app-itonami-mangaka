"""v10 pipeline router — per-panel pipeline selection.

User (2026-05-25): "openusd のシーン設計が結構、イメージ通りが難しいので、
v10 の pipeline として、openusd を使わない, comfyui を中心とした生成
プロセスで score 評価。openusd はアシスタント的に背景を後で panel に
入れる、最後に必要であれば合成するという pipeline で. また panel
ごとに 生成パイプラインを切り替えられるようにも設計してください"

Design:
  v7-v9: USD-first (scene_graph → Blender → ControlNet → SDXL stylize)
         Stage A pose / Stage B camera / Stage C char / Stage D bg / Stage E composite
         Plateau at ~80-87 because USD scene rarely matches imagined output.

  v10:   ComfyUI-first, USD optional/late
         Each panel = ONE SDXL workflow with full scene + character + action
         Router picks per-panel pipeline based on:
           - explicit panel_pipeline field in manifest, or
           - heuristic from shot / tone / focusedCharacters

Per-panel pipelines:
  cu_color       : ComfyUI single-pass color (Animagine XL color prompt)
                    Best for: conversation, slice-of-life, character panels
  cu_ink         : ComfyUI single-pass B&W manga ink (Death Note style)
                    Best for: dramatic monologue, narrative panels
  cu_color_usd   : ComfyUI color + USD bg composited at end (rare)
                    Best for: specific architectural scenes where USD detail wins
  cu_ink_usd     : ComfyUI ink + USD bg composited at end (rare)
                    Best for: dense urban or interior bg required
  cu_action      : ComfyUI single-pass with motion lines + SFX emphasis
                    Best for: shock, action, impact panels

The router can be overridden per-panel via manifest panel_pipeline field.
"""
from __future__ import annotations
from typing import Optional


def select_pipeline(panel: dict, page_default: str = "cu_color") -> str:
    """Select v10 pipeline for a single panel.

    Priority:
      1. Explicit panel.panel_pipeline if set in manifest
      2. Heuristic from tone / shot / focusedCharacters
      3. page_default

    Returns: pipeline name (cu_color / cu_ink / cu_action / cu_color_usd / cu_ink_usd)
    """
    explicit = panel.get("panel_pipeline")
    if explicit:
        return explicit

    tone = (panel.get("tone") or "").lower()
    shot = (panel.get("shot") or "").lower()
    has_focal = bool(panel.get("focusedCharacters") or [])

    # Action / shock / dramatic — emphasize SFX + motion lines
    if any(t in tone for t in ("shock", "intense", "impact", "dramatic", "tense", "action")):
        return "cu_action"

    # Empty-focal Wide / Establishing — environment matters, USD may help
    if not has_focal and any(s in shot for s in ("wide", "establish", "long")):
        return "cu_color_usd"

    # Empty-focal ECU/Insert — object detail, ComfyUI alone is fine
    if not has_focal and any(s in shot for s in ("extreme close", "insert")):
        return "cu_color"

    # Default character panels — page_default decides (caller sets per page)
    return page_default


# Panel pipeline option presets (Jump genre / preset name → defaults)
PIPELINE_PRESETS = {
    "ghosthacker": {
        "default": "cu_ink",     # cyber-noir mood prefers B&W ink
        "wide":    "cu_ink_usd", # urban environments benefit from USD
        "action":  "cu_action",
    },
    "jump_global_golden": {
        "default": "cu_color",
        "wide":    "cu_color_usd",
        "action":  "cu_action",
    },
    "deathnote": {
        "default": "cu_ink",
        "wide":    "cu_ink_usd",
        "action":  "cu_action",
    },
    "slice_of_life": {
        "default": "cu_color",
        "wide":    "cu_color",
        "action":  "cu_action",
    },
}


def select_pipeline_for_preset(panel: dict, preset_name: str = "ghosthacker") -> str:
    """Higher-level selector: combine preset defaults with per-panel routing."""
    preset = PIPELINE_PRESETS.get(preset_name, PIPELINE_PRESETS["jump_global_golden"])
    explicit = panel.get("panel_pipeline")
    if explicit:
        return explicit

    tone = (panel.get("tone") or "").lower()
    shot = (panel.get("shot") or "").lower()
    has_focal = bool(panel.get("focusedCharacters") or [])

    if any(t in tone for t in ("shock", "intense", "impact", "dramatic", "tense", "action")):
        return preset["action"]
    if not has_focal and any(s in shot for s in ("wide", "establish", "long")):
        return preset["wide"]
    return preset["default"]


if __name__ == "__main__":
    # Test router decisions
    import json
    from pathlib import Path
    MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
    m = json.loads(MANIFEST.read_text())
    p0 = sorted([p for p in m["panels"] if p["pageNum"] == 0], key=lambda x: x["panelIndex"])
    print("=== v10 pipeline router decisions (preset=ghosthacker) ===")
    for p in p0:
        pip = select_pipeline_for_preset(p, "ghosthacker")
        print(f"  panel {p['panelIndex']}: shot={p.get('shot','?'):15s}  "
              f"tone={p.get('tone','?'):15s}  chars={p.get('focusedCharacters',[])}  "
              f"→ {pip}")

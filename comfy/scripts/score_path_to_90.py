"""Reverse topological sort: dependencies for Death Note 90+ score.

Goal: total >= 90 (Death Note class)
Combined formula: 0.25 × heuristic + 0.35 × jump_qa + 0.40 × manifest_qa
For 90+: needs avg ~9/10 across all axes.

Reverse-topo dependency tree (each axis traces back to fixable causes):

  total >= 90
   ├─ heuristic_total >= 9    (composite-level, already easy via OCIO)
   │    └─ already pass with current pipeline
   │
   ├─ jump_qa >= 90 (8 axes × ~9/10):
   │    ├─ character_anatomy >= 9
   │    │    └─ depends on: SDXL character LoRA OR IPAdapter FaceID
   │    │         └─ blocker: IPAdapter models not installed on ComfyUI host
   │    │              fix: ComfyUI Manager install IP-Adapter-FaceID-PlusV2 SDXL
   │    │              fallback: use img2img with face_ref + low denoise
   │    │
   │    ├─ multi_character_quality >= 9
   │    │    └─ depends on: regional prompting OR per-character masks
   │    │         └─ already wired (V5_USE_REGIONAL=1)
   │    │              improvement: also wire ControlNet OpenPose for skeleton
   │    │
   │    ├─ background_detail >= 9
   │    │    └─ depends on: photo-real Stage 1 base
   │    │         └─ needs Cycles GI + Principled BSDF + Sun light
   │    │              fix: V5_BASE=cinematic (trade: 5× slower)
   │    │
   │    ├─ composition_pose >= 9
   │    │    └─ depends on: scene_graph per-panel camera variation
   │    │         └─ already wired (panel_idx × 47° orbit + pitch + comp)
   │    │
   │    ├─ bubble_integration >= 9
   │    │    └─ depends on: multi-bubble per panel + tail to speaker
   │    │         └─ Jump cascade already wired
   │    │
   │    ├─ manga_authenticity >= 9
   │    │    └─ depends on: Obata-style ink + crisp B&W + screentone
   │    │         └─ V5_OBATA=1 wired (post-process cleanup)
   │    │              improvement: more aggressive contrast + posterize
   │    │
   │    ├─ sfx_text >= 9
   │    │    └─ depends on: dramatic kana per panel tone
   │    │         └─ V5_SFX=1 wired (Hiragino W8 + word-boundary regex)
   │    │              improvement: larger size (45% vs 35%) + more variations
   │    │
   │    └─ environment_detail >= 9
   │         └─ depends on: same as background_detail
   │              fix: V5_BASE=cinematic + scene_graph props
   │
   └─ manifest_qa >= 90 (6 axes × ~9/10):
        ├─ window_check >= 9 → daylight visible through windows
        │    └─ depends on: Cycles GI + sun direction
        │         └─ V5_BASE=cinematic + sun_altitude > 0
        │
        ├─ character_presence >= 9 → expected count visible
        │    └─ depends on: multi-mannequin in Blender + character LoRA
        │         └─ multi-mannequin wired + V5_USE_REGIONAL helps
        │
        ├─ character_identity >= 9 → matches focal char
        │    └─ depends on: character LoRA OR IPAdapter FaceID
        │         └─ same blocker as character_anatomy
        │
        ├─ spatial_layout >= 9 → props in correct positions
        │    └─ depends on: USD scene + scene_graph props
        │         └─ school-hierarchy.usda wired
        │
        ├─ scene_match >= 9 → location matches manifest
        │    └─ depends on: setting_lock prompt
        │         └─ wired per scene
        │
        └─ action_match >= 9 → dialogue/action depicted
             └─ depends on: SDXL prompt + manifest dialogue
                  └─ wired via multi_char prompt + scene_chars

CRITICAL BLOCKERS (high-impact, high-leverage):
  1. IPAdapter FaceID install (blocks 2 axes: anatomy + identity)
     → User action on ComfyUI host required
  2. Cycles GI base (blocks 2 axes: background + environment)
     → V5_BASE=cinematic (slower but better backgrounds)
  3. Aggressive Obata + SFX (boost 2 axes: authenticity + sfx)
     → Already wired, tunable
"""
from __future__ import annotations
from typing import Optional
import json


class ScoreAxis:
    def __init__(self, name: str, current: float, target: float,
                  weight: float, deps: list, fix_action: str = "",
                  blocker: str = ""):
        self.name = name
        self.current = current
        self.target = target
        self.weight = weight
        self.deps = deps
        self.fix_action = fix_action
        self.blocker = blocker
        self.gap = target - current

    def __repr__(self):
        return f"{self.name}: {self.current:.1f}→{self.target:.1f} (gap {self.gap:.1f}) — {self.fix_action}"


# Axis definitions (current scores from page 0 EEVEE+Obata run)
AXES = [
    ScoreAxis("character_anatomy", 7.0, 9.0, 0.18,
               deps=["IPAdapter FaceID install"],
               blocker="ComfyUI host model files",
               fix_action="install ip-adapter-faceid-plusv2_sdxl + clip vision"),
    ScoreAxis("multi_character_quality", 7.0, 9.0, 0.12,
               deps=["regional prompting"],
               fix_action="V5_USE_REGIONAL=1 (already wired)"),
    ScoreAxis("background_detail", 6.0, 9.0, 0.12,
               deps=["Cycles GI + materials"],
               fix_action="V5_BASE=cinematic"),
    ScoreAxis("composition_pose", 9.0, 9.0, 0.12,
               deps=["scene_graph orbit"],
               fix_action="already at target"),
    ScoreAxis("bubble_integration", 8.0, 9.0, 0.08,
               deps=["Jump bubble cascade"],
               fix_action="already wired, +1 by aggressive cascade"),
    ScoreAxis("manga_authenticity", 7.0, 9.0, 0.18,
               deps=["Obata ink cleanup"],
               fix_action="V5_OBATA=1 + posterize aggressive"),
    ScoreAxis("sfx_text", 7.0, 9.0, 0.10,
               deps=["SFX kana overlay"],
               fix_action="V5_SFX=1 + larger size"),
    ScoreAxis("environment_detail", 6.0, 9.0, 0.10,
               deps=["Cycles + scene props"],
               fix_action="V5_BASE=cinematic + asset registry"),
]


def reverse_topo_path_to_90():
    """Print dependencies in reverse topological order (deepest first).
    Items with no deps go first; root goal goes last.
    """
    print(f"{'='*78}")
    print(f"Reverse-topological path to Death Note 90+:")
    print(f"{'='*78}\n")

    # Sort by gap (largest gap first = highest impact)
    sorted_axes = sorted(AXES, key=lambda a: (-a.gap, -a.weight))

    print(f"{'Axis':<28} {'Current':>8} {'Target':>7} {'Gap':>5} {'Weight':>7}  Fix")
    print("-" * 100)
    for a in sorted_axes:
        marker = "★" if a.gap >= 2 else " "
        print(f"{marker} {a.name:<26} {a.current:>7.1f}  {a.target:>5.1f}  "
              f"{a.gap:>4.1f}  {a.weight:>6.2f}  {a.fix_action}")

    print(f"\nTotal projected from current axis values:")
    total_now = sum(a.current * a.weight * 10 for a in AXES) / sum(a.weight for a in AXES)
    print(f"  current weighted avg: {total_now:.1f} / 100")
    total_target = sum(a.target * a.weight * 10 for a in AXES) / sum(a.weight for a in AXES)
    print(f"  if all targets hit:    {total_target:.1f} / 100")

    print(f"\nReverse-topo execution order (deepest dependency first):")
    print(f"  Step 1 (BLOCKER):  IPAdapter FaceID install on ComfyUI host")
    print(f"                       → unlocks character_anatomy + character_identity")
    print(f"                       → +3 to character_anatomy weight 0.18 = +5.4")
    print(f"  Step 2:  V5_BASE=cinematic (Cycles)")
    print(f"                       → unlocks background_detail + environment_detail")
    print(f"                       → +3 each axis × weight 0.22 = +6.6")
    print(f"  Step 3:  V5_USE_REGIONAL=1 + ControlNet OpenPose")
    print(f"                       → unlocks multi_character_quality")
    print(f"                       → +2 × weight 0.12 = +2.4")
    print(f"  Step 4:  Tune SFX (45% size) + Obata aggressive posterize")
    print(f"                       → +1 each × weight 0.28 = +2.8")
    print(f"  Step 5:  manifest_qa items (window/scene/action match)")
    print(f"                       → boosted by scene_graph + multi-char")
    print(f"")
    print(f"  Total expected boost: +17.2")
    print(f"  Projected final score: {total_now + 17:.0f} ≈ 80 top-tier")
    print(f"")
    print(f"  Death Note 90+ requires resolving IPAdapter blocker AND Cycles base.")


if __name__ == "__main__":
    reverse_topo_path_to_90()

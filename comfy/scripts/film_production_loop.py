"""Multi-phase React loop modeled on professional film/anime production.

User request: 実際の映画、anime などの制作工程を react loop に, cut として
manga panel, page に.

Anime production pipeline phases (per cut = manga panel):
  1. Storyboard (絵コンテ)  — sketch composition, camera position
  2. Layout (レイアウト)     — finalize blocking, key poses
  3. Animatic               — rough 3D render at low quality
  4. Key animation          — final poses + camera
  5. Genga / cleanup        — clean line art
  6. Backgrounds (背景)     — environment detail pass
  7. Color                  — color design + lighting
  8. Ink + Tone (manga)     — convert to B&W manga panel
  9. Composite (撮影)        — final composite with bubbles
  10. QA review             — editorial check

Each phase has a QA gate. If gate fails, loop back to relevant
previous phase with adjustments.

This file documents the phase architecture. The render-v5-page.py
react_loop() function implements a subset (currently: Layout +
Animatic + Color + Stylize + Composite + Score = phases 2,3,7,8,9,10).

Phases not yet implemented (deferred):
  1 Storyboard: would require LLM to verify manifest panel coherence
    BEFORE scene_graph generation
  4 Key animation: pose variety from manifest visual text
  5 Genga: separate clean-line pass via Blender Freestyle dedicated
  6 Backgrounds: detail-pass over Stage 1 to add prop detail before
    SDXL conversion
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

PHASES = [
    ("storyboard",  "scene_graph manifest coherence check (LLM)"),
    ("layout",      "scene_graph.camera + actors valid (geometry check)"),
    ("animatic",    "Blender Stage 1 silhouettes + composition"),
    ("key_anim",    "pose variety from manifest visual"),
    ("genga",       "Freestyle line art cleanup"),
    ("backgrounds", "detail pass over Stage 1 base"),
    ("color",       "Cycles GI + materials (Pixar-style cinematic base)"),
    ("ink_tone",    "SDXL ComfyUI conversion to B&W manga"),
    ("composite",   "PIL composite + bubbles + per-panel grid QA"),
    ("review",      "Gemma 3:4b Jump-benchmark final scoring"),
]


def qa_gate(phase: str, result: dict, target_score: float) -> tuple[bool, str]:
    """Per-phase QA gate. Returns (pass, retry_action).

    pass=True → advance to next phase
    pass=False → loop back to suggested phase with adjustments
    """
    score = result.get("score", 0)
    if score >= target_score:
        return True, ""

    # Per-phase retry strategy
    retry = {
        "layout":      "adjust scene_graph camera distance + actor positions",
        "animatic":    "rerun Blender with adjusted ridge/valley line weights",
        "color":       "increase Cycles samples 32→64, adjust sun intensity",
        "ink_tone":    "adjust SDXL denoise 0.6→0.55 or controlnet 0.55→0.65",
        "composite":   "reposition bubbles per Jump R→L cascade",
        "review":      "loop back to color (LLM said: weak background detail)",
    }
    return False, retry.get(phase, "retry current phase")


def phase_report(phase: str, result: dict) -> str:
    """Human-readable phase report for logs."""
    return (f"  [{phase:>12}] score={result.get('score','-'):>5.1f}/100  "
            f"verdict={result.get('verdict','')[:80]}")

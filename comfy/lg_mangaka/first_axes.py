"""First-axis weighted vector — generation-order SSoT.

Conversation 2026-05-24: art-style identity is dominated by WHICH thing
the pipeline decides first, not by surface style. Different works don't
differ in "preset" but in which primitive is the function-of which.

  Jump manga (尾田/岸本)       character pose+emotion → bg by assistants
  Ghibli                        layout fuses char+space → 美術 fills余白
  Pixar                         emotion beat (story reels) → set parallel
  Spider-Verse                  character pose → space warped to pose
  攻殻 1995 / イノセンス (押井)  location / atmosphere → character walks
  AKIRA (大友)                  建築 geometry → 群衆 → focal character
  千年女優・パプリカ (今敏)     space/time boundary → char as function
  新海誠                        風景・光・天候 → silhouette
  Nolan                         plot/time structure → char + space follow
  Lynch                         mood/texture → content as excuse
  Tarantino                     dialogue/music → blocking follows
  Death Note (小畑+大場)        character pose + camera grammar → mood

12 axes [0, 1]. Dominant axis = "decided first"; secondaries condition
subsequent stages. The same scene material yields wildly different
artifacts depending on which axis leads.

This module is SSoT for:
  - axis names (immutable order)
  - named presets (auteur signatures)
  - axes → legacy env-flag resolver (forward-compatible with V5_BASE)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


AXES: tuple[str, ...] = (
    "character",   # pose+emotion drive frame (jump, ghibli, spiderverse)
    "space",       # scene geometry drives frame (oshii, otomo, kon)
    "emotion",     # beat/arc drives content (pixar story reels, 少女漫画)
    "mood",        # texture/LUT/atmosphere (shinkai, lynch, malick)
    "shot",        # camera grammar (kubrick, wes anderson, 黒澤)
    "rhythm",      # panel beat / SFX timing (tarantino, 板野サーカス)
    "world",       # lore/setting bible (tolkien, star wars, anno setpieces)
    "plot",        # beat-lattice drives page structure (nolan, mystery)
    "dialogue",    # text drives staging (sorkin, tarantino, sokurov)
    "action",      # choreography drives camera (john wu, mad max, mcq)
    "time",        # temporal structure (memento, kon, arrival)
    "theme",       # thesis drives symbolic objects (kubrick 2001, anno)
)


@dataclass(frozen=True)
class FirstAxes:
    """12-axis generation-order vector + optional preset tag."""
    character: float = 0.0
    space:     float = 0.0
    emotion:   float = 0.0
    mood:      float = 0.0
    shot:      float = 0.0
    rhythm:    float = 0.0
    world:     float = 0.0
    plot:      float = 0.0
    dialogue:  float = 0.0
    action:    float = 0.0
    time:      float = 0.0
    theme:     float = 0.0
    preset:    Optional[str] = None

    def as_map(self) -> dict[str, float]:
        return {a: float(getattr(self, a)) for a in AXES}

    def dominant(self) -> str:
        m = self.as_map()
        # Stable tiebreak: AXES order
        return max(AXES, key=lambda a: (m[a], -AXES.index(a)))

    def top_n(self, n: int = 3) -> list[tuple[str, float]]:
        return sorted(self.as_map().items(), key=lambda kv: -kv[1])[:n]

    def to_dict(self) -> dict:
        out: dict = self.as_map()
        if self.preset:
            out["preset"] = self.preset
        out["dominant"] = self.dominant()
        return out


# ---- Auteur preset signatures ------------------------------------------
#
# Weights are deliberate, not normalized. Dominant axis = leading stage;
# secondaries modulate sub-stage decisions (bg mode / pose lib / lora).

PRESETS: dict[str, dict[str, float]] = {
    "jump": {
        "character": 1.0, "emotion": 0.8, "action": 0.6, "rhythm": 0.5,
    },
    "ghibli": {
        "character": 0.8, "space": 0.6, "mood": 0.6, "emotion": 0.5,
    },
    "pixar": {
        "emotion": 1.0, "character": 0.8, "shot": 0.6, "plot": 0.5,
    },
    "spiderverse": {
        "character": 1.0, "shot": 0.9, "mood": 0.7, "action": 0.6,
    },
    "oshii": {  # 攻殻機動隊 / イノセンス
        "space": 1.0, "mood": 0.8, "theme": 0.6, "shot": 0.5,
    },
    "otomo": {  # AKIRA
        "space": 0.9, "world": 0.8, "action": 0.5, "character": 0.4,
    },
    "shinkai": {
        "mood": 1.0, "space": 0.7, "emotion": 0.6,
    },
    "kon": {  # 今敏
        "space": 0.9, "time": 0.9, "theme": 0.7, "mood": 0.5,
    },
    "nolan": {
        "plot": 1.0, "time": 0.9, "theme": 0.7, "character": 0.4,
    },
    "tarantino": {
        "dialogue": 1.0, "rhythm": 0.9, "mood": 0.6, "character": 0.5,
    },
    "lynch": {
        "mood": 1.0, "theme": 0.8, "space": 0.4,
    },
    "anno": {  # 庵野 / エヴァ
        "world": 0.8, "space": 0.7, "theme": 0.8, "character": 0.5,
    },
    "deathnote": {  # 小畑+大場 — refined from 10-work analysis (2026-05-24)
        "character": 0.9, "plot": 1.0, "shot": 0.9,
        "theme": 0.8, "mood": 0.7, "dialogue": 0.7,
    },
    "kubrick": {
        "theme": 1.0, "shot": 0.9, "mood": 0.7, "space": 0.6,
    },
    "wes_anderson": {
        "shot": 1.0, "mood": 0.8, "character": 0.6, "rhythm": 0.5,
    },

    # ─── Jump-family aggregate tracks (10-work statistical analysis) ──
    # Derived from 呪術 / 鬼滅 / CSM / Death Note / OPM / 進撃 / DBZ /
    # NARUTO / ONE PIECE / ウィッチウォッチ.
    # Universal invariant: character ~0.92, emotion ~0.72.
    # Differentiator: action vs plot (split battle / mind track),
    # mood vs world (split atmosphere / lore track).

    "jump_global_golden": {  # cross-work baseline (any Jump global hit)
        "character": 0.9, "emotion": 0.75, "action": 0.7,
        "shot": 0.65, "mood": 0.6, "world": 0.6, "theme": 0.6,
        "rhythm": 0.55, "plot": 0.55,
    },
    "jump_battle": {  # 8/10 — battle-track default
        "character": 1.0, "action": 0.85, "emotion": 0.8,
        "shot": 0.7, "world": 0.7, "mood": 0.65, "rhythm": 0.6,
    },
    "jump_mind": {  # Death-Note-style intelligence-track
        "character": 0.9, "plot": 1.0, "shot": 0.9,
        "theme": 0.8, "mood": 0.7, "dialogue": 0.7,
    },
    "jump_comedy": {  # SKET DANCE / ウィッチウォッチ rhythm+dialogue track
        "character": 1.0, "rhythm": 0.8, "dialogue": 0.8,
        "emotion": 0.7, "action": 0.6,
    },

    # ─── Project preset (Ghost Hacker — cybersecurity + battle hybrid) ──
    # Jump character baseline + Death Note shot/plot + 押井 mood/theme.
    # 3-track hybrid: battle + mind + cyber-noir atmosphere.
    "ghosthacker": {
        "character": 0.9,  # Jump invariant — Yuto/Ren/Nei readable
        "shot":      0.85, # cyber-noir cinematic framing
        "mood":      0.85, # cyber-dark atmosphere is genre requirement
        "world":     0.8,  # cybersecurity = lore-rich (DNS/exploit/proto)
        "plot":      0.8,  # hacking = puzzle structure
        "action":    0.75, # cyber-battle (abstract, not physical)
        "theme":     0.75, # AI / surveillance / 魂 vs data
        "emotion":   0.7,  # Jump empathy floor
        "dialogue":  0.65, # technical exposition + character banter
        "space":     0.6,  # cyberspace = abstract space (押井 inflection)
        "rhythm":    0.5,
        "time":      0.4,
    },
}


def load_preset(name: str) -> FirstAxes:
    """Load a named preset. Raises KeyError on unknown name."""
    key = name.strip().lower()
    if key not in PRESETS:
        raise KeyError(
            f"unknown preset {name!r}; available: {sorted(PRESETS)}"
        )
    return FirstAxes(preset=key, **PRESETS[key])


def parse_axes_string(spec: str) -> FirstAxes:
    """Parse 'character=1.0,space=0.3,mood=0.5' into FirstAxes."""
    kwargs: dict[str, float] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"axis spec needs '=': {part!r}")
        k, v = part.split("=", 1)
        k = k.strip().lower()
        if k not in AXES:
            raise ValueError(
                f"unknown axis {k!r}; valid: {AXES}"
            )
        kwargs[k] = float(v.strip())
    return FirstAxes(**kwargs)


# ---- Resolver: axes vector → legacy env flags --------------------------
#
# The renderer still reads V5_BASE / V7_BG_MODE / V7_POSE_LIB / V5_USE_*
# env vars. Until those reads are replaced with direct axes lookups,
# this resolver translates a vector into the existing flag space, so
# every preset drives the existing pipeline with no further code path.

def resolve_env(axes: FirstAxes) -> dict[str, str]:
    """Resolve axes → env-var overlay (merge into os.environ).

    Rules (intentionally simple — refine as v7 stages land):
      dominant character → V5_BASE = v7 (if >=0.9) else v6 NPR
      dominant space     → V5_BASE = cinematic (Cycles GI for materials)
      dominant mood/theme→ V5_BASE = cinematic (texture richness)
      dominant shot      → V5_BASE = v6 (clean NPR for camera grammar)
      other dominants    → V5_BASE = manga (fast EEVEE baseline)

      V7_BG_MODE         from secondary mood vs space/world
      V7_POSE_LIB        from action vs character emphasis
      V5_USE_IPADAPTER   high character weight
      V5_USE_REGIONAL    multi-char action panels
      V5_USE_LORA        mood/theme-led stylepack
    """
    env: dict[str, str] = {}
    dom = axes.dominant()

    if dom == "character":
        env["V5_BASE"] = "v7" if axes.character >= 0.9 else "v6"
    elif dom == "space":
        env["V5_BASE"] = "cinematic"
    elif dom in ("mood", "theme"):
        env["V5_BASE"] = "cinematic"
    elif dom == "shot":
        env["V5_BASE"] = "v6"
    else:
        env["V5_BASE"] = "manga"

    if axes.mood >= 0.7:
        env["V7_BG_MODE"] = "mood"
    elif axes.space >= 0.7 or axes.world >= 0.7:
        env["V7_BG_MODE"] = "realistic"
    else:
        env["V7_BG_MODE"] = "symbolic"

    if axes.action >= 0.5:
        env["V7_POSE_LIB"] = "anime"
    elif axes.character >= 0.7:
        env["V7_POSE_LIB"] = "manga"
    else:
        env["V7_POSE_LIB"] = "hybrid"

    # IPAdapter FaceID is wired but disabled by default in resolver:
    # ComfyUI host overhead (~280s per panel with IPAdapter) causes 300s
    # timeouts on tall-aspect panels (p1 school-hierarchy). Opt-in
    # explicitly via --axes "use_ipa=1" or env V5_USE_IPADAPTER=1.
    # Was: if axes.character >= 0.8: env["V5_USE_IPADAPTER"] = "1"
    if axes.character >= 0.7 and axes.action >= 0.5:
        env["V5_USE_REGIONAL"] = "1"
    if axes.mood >= 0.8 or axes.theme >= 0.7:
        env["V5_USE_LORA"] = "1"

    return env


def resolve_from_argv(argv: list[str]) -> tuple[Optional[FirstAxes], list[str]]:
    """Extract --preset/--axes from argv. Returns (axes, remaining_argv).

    Recognized flags (consumed pairwise from argv):
      --preset NAME
      --axes  "k=v,k=v"

    Both can be combined; --axes overrides preset values for listed keys.
    """
    axes: Optional[FirstAxes] = None
    overlay: dict[str, float] = {}
    out: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--preset" and i + 1 < len(argv):
            axes = load_preset(argv[i + 1])
            i += 2
            continue
        if tok.startswith("--preset="):
            axes = load_preset(tok.split("=", 1)[1])
            i += 1
            continue
        if tok == "--axes" and i + 1 < len(argv):
            overlay_axes = parse_axes_string(argv[i + 1])
            overlay = overlay_axes.as_map()
            i += 2
            continue
        if tok.startswith("--axes="):
            overlay_axes = parse_axes_string(tok.split("=", 1)[1])
            overlay = overlay_axes.as_map()
            i += 1
            continue
        out.append(tok)
        i += 1

    if axes is None and not overlay:
        return None, out

    base = axes.as_map() if axes else {}
    base.update({k: v for k, v in overlay.items() if v != 0.0})
    preset_tag = axes.preset if axes else None
    if overlay and preset_tag:
        preset_tag = preset_tag + "+overlay"
    return FirstAxes(preset=preset_tag, **base), out


# ---- v7 stage helpers (direct value lookups, env-bypass) ---------------
#
# v7 modules (pose_designer / v7_character_render / v7_bg_render / v7_orchestrator)
# call these helpers directly with a FirstAxes vector. The legacy
# `resolve_env` path is for v5/v6 scripts that still read env flags.

def bg_mode(axes: FirstAxes, tone: str = "") -> str:
    """Per-panel background mode from axes + tone hint.

    Tone hierarchy (overrides axes for local panel signals):
      shock / intense / dramatic / tense → symbolic (集中線)
      quiet / calm / conversational /
        contemplative / casual / domestic → realistic (chars + room)
    Axes used only when tone is neutral / absent.
    """
    tone_l = (tone or "").lower()
    if any(t in tone_l for t in ("shock", "shout", "intense", "dramatic", "tense")):
        return "symbolic"
    # CRITICAL: narrative quiet tones must keep characters visible — override
    # even high-mood presets (ghosthacker mood=0.85). Otherwise conversational
    # panels degenerate into mood-hatching-only with no character readable.
    if any(t in tone_l for t in ("quiet", "calm", "conversational",
                                    "contemplative", "casual", "warm",
                                    "comedic", "domestic")):
        return "realistic"
    if axes.mood >= 0.7:
        return "mood"
    if axes.space >= 0.7 or axes.world >= 0.7:
        return "realistic"
    if axes.action >= 0.5:
        return "symbolic"
    if any(t in tone_l for t in ("ominous", "anxious")):
        return "mood"
    return "realistic"


def pose_lib(axes: FirstAxes) -> str:
    """Character pose library selection."""
    if axes.action >= 0.5:
        return "anime"
    if axes.character >= 0.7:
        return "manga"
    return "hybrid"


def composite_emphasis(axes: FirstAxes) -> dict[str, float]:
    """Composite-stage weights for SFX overlay / ink strength / hatching.

    Each weight in [0,1]; the v7 composite path interprets these as
    multipliers on existing post-process modules (sfx_overlay,
    obata_ink_cleanup, mood hatch density).
    """
    return {
        "sfx":      max(0.0, min(1.0, 0.3 + 0.4 * axes.rhythm + 0.3 * axes.action)),
        "ink":      max(0.0, min(1.0, 0.5 + 0.3 * axes.character + 0.2 * axes.shot)),
        "hatching": max(0.0, min(1.0, 0.2 + 0.5 * axes.mood + 0.3 * axes.theme)),
    }


def render_realistic_bg_enabled(axes: FirstAxes) -> bool:
    """Whether to fire the SDXL realistic-bg path (vs blank white).

    SDXL bg is slow — only worth it when space/world/mood dominate.
    """
    return axes.space >= 0.7 or axes.world >= 0.7 or axes.mood >= 0.8


def pipeline_priority(axes: FirstAxes) -> dict:
    """Weight-based pipeline budget — which stage gets full quality.

    Based on dominant axis, character-first vs space-first auteur
    conventions. Returns a budget dict the orchestrator uses to decide:
      - char_steps: SDXL steps for character render (16/24/28/32)
      - bg_mode_pref: 'sdxl' / 'mood' / 'white' — bg expense level
      - bg_when: 'before_char' / 'after_char' / 'parallel' — order
      - skip_bg_for_focal: True if character should fill the panel,
                             bg = solid color (Jump shonen convention)

    Conventions:
      character-dominant (Jump shonen): char full, bg minimal → skip
      space-dominant (Oshii):           bg full SDXL, char standard
      mood-dominant (Death Note):       both medium, heavy hatching
      shot-dominant (cinematic):        framing tight, both medium
    """
    dom = axes.dominant()
    if dom == "character":
        return {
            "char_steps":         28,         # full quality
            "bg_mode_pref":       "white",    # let char dominate
            "bg_when":            "after_char",
            "skip_bg_for_focal":  True,       # Jump convention
            "rationale":          "character-first: char takes panel focus, "
                                    "bg simple companion",
        }
    if dom == "space":
        return {
            "char_steps":         16,
            "bg_mode_pref":       "sdxl",     # rich room
            "bg_when":            "before_char",
            "skip_bg_for_focal":  False,
            "rationale":          "space-first: full SDXL bg, char placed in",
        }
    if dom in ("mood", "theme"):
        return {
            "char_steps":         24,
            "bg_mode_pref":       "mood",     # hatching atmosphere
            "bg_when":            "before_char",
            "skip_bg_for_focal":  False,
            "rationale":          "mood-first: atmospheric hatching dominant",
        }
    if dom == "shot":
        return {
            "char_steps":         24,
            "bg_mode_pref":       "sdxl",     # framing-aware
            "bg_when":            "before_char",
            "skip_bg_for_focal":  False,
            "rationale":          "shot-first: cinematic frame matters",
        }
    # action / plot / dialogue / emotion → balanced
    return {
        "char_steps":         20,
        "bg_mode_pref":       "mood",
        "bg_when":            "parallel",
        "skip_bg_for_focal":  False,
        "rationale":          "balanced default",
    }


__all__ = [
    "AXES", "FirstAxes", "PRESETS",
    "load_preset", "parse_axes_string",
    "resolve_env", "resolve_from_argv",
    "bg_mode", "pose_lib", "composite_emphasis",
    "render_realistic_bg_enabled",
]

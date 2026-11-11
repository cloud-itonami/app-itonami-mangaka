"""Per-panel scene graph designer.

Takes a manifest panel (visual + sceneSubject + shot + tone + chars)
and Gemma 3:4b vision LLM, generates a structured scene graph spec
that Stage 1 (Blender) consumes:

  SceneGraphSpec {
    scene_slug: str          which USD scene
    actors: [{
      id, position_xyz, facing_yaw, pose, expression, motion_vector
    }]
    props: [{id, position_xyz, motion_vector}]
    camera: {
      origin_xyz, target_xyz, fov_deg, lens_mm,
      motion_blur, depth_of_field
    }
    lighting: {
      time_of_day, key_intensity, fill_intensity, rim_intensity,
      mood_color_temp
    }
    atmosphere: {
      fog_density, dust_particles, motion_lines_overlay,
      composition_bias
    }
  }

This is the "scene graph design" step the user asked about — converts
the loose manifest panel description into a fully-specified scene
graph that the renderer can execute deterministically.

Currently uses Gemma 3:4b reasoning + manifest fields + scene defaults.
Future: Anthropic Claude vision for higher-quality scene reasoning.
"""
from __future__ import annotations
import json
import math
import re
import urllib.request
from pathlib import Path

from lg_mangaka import llm_endpoint as _ep

# Host + vision model resolve via the llm_endpoint SSoT (OLLAMA_HOST/OLLAMA_MODEL).
# Previously hardcoded — now env-overridable like the rest of the QA suite.
OLLAMA = _ep.ollama_url()
MODEL  = _ep.vision_model()


# Scene-specific defaults (positions in USD Y-up coords)
# Each scene now includes weather / season / sun position / strict setting
# lock prompt to anchor SDXL Stage 2.
SCENE_DEFAULTS = {
    "yuto-bedroom": {
        "actors_anchor": {"Yuto": (3.0, 0.5, 2.0)},
        "props": [
            {"id": "phone",    "position": (3.65, 0.80, 2.15)},
            {"id": "notebook", "position": (3.30, 0.81, 2.05)},
            {"id": "lamp",     "position": (2.45, 0.82, 1.92)},
        ],
        "key_light": "window",
        "time_of_day": "late_night",
        "mood_color_temp": 3200,
        "season":   "early autumn",
        "weather":  "clear",
        "sun_altitude_deg": -20,    # below horizon (night)
        "sun_azimuth_deg":  0,
        "setting_lock": (
            "INTERIOR private teenage boys bedroom, "
            "white painted walls, ceiling visible, wooden floor, "
            "single bed with blanket, study desk with smartphone, "
            "small window with curtain at night, no outdoor, no street, "
            "no neon, no alley, no vendor stalls, no lanterns"
        ),
    },
    "classroom": {
        "actors_anchor": {"Yuto": (4.0, 0.5, 3.5), "Nei": (3.0, 0.5, 3.5),
                            "Ren":  (5.0, 0.5, 3.5), "Akira": (4.0, 0.5, 2.5),
                            "Saki": (5.0, 0.5, 2.5)},
        "props": [
            {"id": "blackboard",  "position": (4.0, 1.5, 0.1)},
            {"id": "teacher_desk","position": (4.0, 0.85, 1.0)},
        ],
        "key_light": "window_west",
        "time_of_day": "afternoon",
        "mood_color_temp": 5500,
        "season":   "early autumn",
        "weather":  "clear bright",
        "sun_altitude_deg": 55,
        "sun_azimuth_deg":  240,
        "setting_lock": (
            "INTERIOR Japanese high school classroom (3-B), "
            "rows of wooden student desks with chairs, large windows on left wall "
            "with afternoon sunlight streaming in, blackboard on front wall, "
            "white ceiling, wooden floor, school uniforms, "
            "NO street, NO alley, NO neon, NO outdoor, NO vendor stalls, "
            "NO lanterns, NO night, NO street lamps"
        ),
    },
    # school-hierarchy: classroom embedded in school building.
    # Classroom_3B local origin → world = (-15, 10.5, -8). All actor
    # anchor positions get + that offset relative to classroom-local
    # space. Floor3 west wing.
    "school-hierarchy": {
        "actors_anchor": {"Yuto":  (4.0 - 15, 0.5 + 10.5, 3.5 - 8),
                            "Nei":   (3.0 - 15, 0.5 + 10.5, 3.5 - 8),
                            "Ren":   (5.0 - 15, 0.5 + 10.5, 3.5 - 8),
                            "Akira": (4.0 - 15, 0.5 + 10.5, 2.5 - 8),
                            "Saki":  (5.0 - 15, 0.5 + 10.5, 2.5 - 8)},
        "props": [
            {"id": "blackboard",  "position": (4.0 - 15, 1.5 + 10.5, 0.1 - 8)},
            {"id": "teacher_desk","position": (4.0 - 15, 0.85 + 10.5, 1.0 - 8)},
        ],
        "key_light": "window_west",
        "time_of_day": "afternoon",
        "mood_color_temp": 5500,
        "season":   "early autumn",
        "weather":  "clear bright",
        "sun_altitude_deg": 55,
        "sun_azimuth_deg":  240,
        "setting_lock": (
            "INTERIOR Japanese high school classroom (3-B), "
            "rows of wooden student desks with chairs, large windows on left wall "
            "with afternoon sunlight streaming in through window aperture, "
            "blackboard on front wall, white ceiling, wooden floor, school uniforms, "
            "natural daylight from west window casting shadows, "
            "NO street, NO alley, NO neon, NO outdoor, NO vendor stalls, "
            "NO lanterns, NO night, NO street lamps"
        ),
    },
    "rens-room": {
        "actors_anchor": {"Ren": (2.8, 0.5, 2.5)},
        "props": [
            {"id": "monitor_wall", "position": (3.5, 1.0, 0.3)},
            {"id": "pinboard",     "position": (0.3, 1.5, 2.0)},
        ],
        "key_light": "monitor_glow",
        "time_of_day": "late_evening",
        "mood_color_temp": 6500,
        "season":   "early autumn",
        "weather":  "clear",
        "sun_altitude_deg": -15,
        "sun_azimuth_deg":  0,
        "setting_lock": (
            "INTERIOR dark hacker den, monitor wall with multiple glowing screens, "
            "research pinboard with papers + photos, gaming chair, "
            "wooden floor, dark walls, single window with closed blinds, "
            "NO outdoor, NO street, NO classroom, NO daylight"
        ),
    },
    "neis-room": {
        "actors_anchor": {"Nei": (0.65, 0.4, 1.5)},
        "props": [
            {"id": "vanity_mirror", "position": (3.5, 1.3, 2.7)},
            {"id": "laptop",        "position": (2.8, 0.81, 0.6)},
            {"id": "phone",         "position": (3.1, 0.80, 0.6)},
        ],
        "key_light": "window",
        "time_of_day": "afternoon",
        "mood_color_temp": 5200,
        "season":   "early autumn",
        "weather":  "clear bright",
        "sun_altitude_deg": 55,
        "sun_azimuth_deg":  240,
        "setting_lock": (
            "INTERIOR teenage girl's bedroom, "
            "vanity mirror with jewelry, wardrobe with clothing, "
            "single bed, posters on wall, large bright window with curtains, "
            "afternoon daylight, fashionable decor, "
            "NO outdoor, NO street, NO classroom, NO alley"
        ),
    },
    "city-street": {
        "actors_anchor": {"Yuto": (5.0, 0.9, 12.0), "Nei": (4.5, 0.9, 12.5),
                            "Ren":  (5.5, 0.9, 12.5)},
        "props": [],
        "key_light": "afternoon_sun",
        "time_of_day": "afternoon",
        "mood_color_temp": 5500,
        "season":   "early autumn",
        "weather":  "clear bright sunny",
        "sun_altitude_deg": 45,      # high afternoon sun
        "sun_azimuth_deg":  240,     # WSW
        "setting_lock": (
            "EXTERIOR Japanese residential street, daylight bright afternoon, "
            "paved sidewalk, low concrete walls, residential houses, "
            "students walking home from school in summer school uniforms, "
            "bright sky, perspective vanishing point ahead, "
            "NO night, NO street lamps lit, NO classroom interior, "
            "NO bedroom, NO indoor, NO dark"
        ),
    },
    "tokyo-zenkei": {
        "actors_anchor": {},
        "props": [
            {"id": "tokyo_tower",  "position": (0, 50, 70)},
            {"id": "skyscraper_a", "position": (40, 40, 40)},
            {"id": "highway",      "position": (0, 12, 30)},
        ],
        "key_light": "sun",
        "time_of_day": "dusk",
        "mood_color_temp": 3800,
    },
}

# Shot-type → camera framing rules (USD-Y-up coords relative to actor)
SHOT_FRAMING = {
    "ECU":  {"distance": 0.4, "height_offset":  0.0, "fov": 35},
    "CU":   {"distance": 1.0, "height_offset":  0.0, "fov": 38},
    "MS":   {"distance": 1.8, "height_offset": -0.1, "fov": 45},
    "MLS":  {"distance": 2.6, "height_offset": -0.05,"fov": 50},
    "LS":   {"distance": 4.0, "height_offset":  0.2, "fov": 55},
    "ELS":  {"distance": 8.0, "height_offset":  0.5, "fov": 70},
    "Wide": {"distance": 6.0, "height_offset":  0.5, "fov": 70},
    "POV":  {"distance": 0.0, "height_offset":  0.0, "fov": 60},
    "OTS":  {"distance": 1.5, "height_offset": -0.1, "fov": 50},
    "Insert": {"distance": 0.4, "height_offset": -0.3, "fov": 30},
    "TWO":  {"distance": 2.8, "height_offset":  0.0, "fov": 55},
    "Medium": {"distance": 1.8, "height_offset": -0.1, "fov": 45},
}

# Tone → atmosphere
TONE_ATMOSPHERE = {
    "tense":         {"fog_density": 0.1,  "motion_lines": "tense_inward",  "contrast_bias": 0.85},
    "ominous":       {"fog_density": 0.3,  "motion_lines": "none",          "contrast_bias": 0.95},
    "emotional":     {"fog_density": 0.05, "motion_lines": "none",          "contrast_bias": 0.7},
    "comedic":       {"fog_density": 0.0,  "motion_lines": "comic_emanate", "contrast_bias": 0.4},
    "contemplative": {"fog_density": 0.0,  "motion_lines": "none",          "contrast_bias": 0.6},
    "quiet":         {"fog_density": 0.0,  "motion_lines": "none",          "contrast_bias": 0.5},
    "intense":       {"fog_density": 0.15, "motion_lines": "speed_radial",  "contrast_bias": 0.9},
    "dramatic":      {"fog_density": 0.2,  "motion_lines": "chiaroscuro",   "contrast_bias": 0.9},
    "shock":         {"fog_density": 0.0,  "motion_lines": "impact_burst",  "contrast_bias": 1.0},
}


def _ollama_describe(prompt: str, timeout: int = 60) -> str:
    """Quick text generation via Gemma 3:4b — no image, just reasoning."""
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                          "options": {"temperature": 0.3, "num_predict": 250}}).encode(),
        headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["response"]
    except Exception as e:
        return ""


def design_scene_graph(panel: dict, scene_slug: str, use_llm: bool = True) -> dict:
    """Generate a per-panel scene graph spec.

    Combines:
      - scene defaults (anchor positions, lighting)
      - shot framing (camera distance/fov from shot type)
      - tone atmosphere (fog/motion-lines/contrast)
      - LLM reasoning (optional): infer actor positions, motion from
                                    panel.visual description
    """
    defaults = SCENE_DEFAULTS.get(scene_slug, SCENE_DEFAULTS["yuto-bedroom"])
    s_lower = (panel.get("shot") or "").lower()
    if "extreme close" in s_lower:   shot_cat = "ECU"
    elif "close" in s_lower:         shot_cat = "CU"
    elif "long" in s_lower:          shot_cat = "LS"
    elif "wide" in s_lower:          shot_cat = "Wide"
    elif "extreme long" in s_lower:  shot_cat = "ELS"
    elif "over the shoulder" in s_lower or "ots" in s_lower: shot_cat = "OTS"
    elif "insert" in s_lower:        shot_cat = "Insert"
    else:                             shot_cat = "MS"

    framing = SHOT_FRAMING[shot_cat]
    tone = (panel.get("tone") or "").lower().split()[0] if panel.get("tone") else "quiet"
    atmosphere = TONE_ATMOSPHERE.get(tone, TONE_ATMOSPHERE["quiet"])

    # Actor placement: focal characters PLUS ambient classroom roster
    # for Wide/LS shots (so the scene shows multiple students, not just
    # one isolated figure).
    focal_chars = panel.get("focusedCharacters") or []
    # For wide-establishing shots in multi-character scenes, populate
    # ambient cast even when only 1 char is focused.
    ambient_chars = []
    if shot_cat in ("Wide", "LS", "ELS", "MLS"):
        # Add scene's full roster (skip focal duplicates)
        for ch in defaults.get("actors_anchor", {}):
            if ch not in focal_chars:
                ambient_chars.append(ch)
    all_chars = list(focal_chars) + ambient_chars
    actors = []
    for ch in all_chars:
        if ch in defaults["actors_anchor"]:
            ax, ay, az = defaults["actors_anchor"][ch]
            actors.append({
                "id": ch,
                "position_xyz": [ax, ay, az],
                "facing_yaw":   -90.0,
                "pose":          "anxious_at_desk" if scene_slug == "yuto-bedroom" else "seated_attentive",
                "expression":    tone if ch in focal_chars else "neutral",
                "motion_vector": [0, 0, 0],
                "is_focal":      ch in focal_chars,
            })

    # Motion vector inference from "visual" text via LLM
    if use_llm and panel.get("visual"):
        prompt = (
            f"Manga panel description: \"{panel['visual'][:200]}\"\n\n"
            f"Is there motion in this panel? If yes, describe in one short sentence "
            f"what moves (character or object) and in which direction "
            f"(forward/backward/left/right/up/down). If static, say STATIC."
        )
        resp = _ollama_describe(prompt, timeout=20)
        if "STATIC" not in resp.upper() and actors:
            # Simple heuristic: extract direction word
            d = resp.lower()
            mv = [0, 0, 0]
            if "forward" in d or "approach" in d or "toward" in d: mv[2] += 0.1
            if "backward" in d or "back" in d:    mv[2] -= 0.1
            if "left" in d:                       mv[0] -= 0.1
            if "right" in d:                      mv[0] += 0.1
            if "up" in d or "stand" in d:         mv[1] += 0.1
            if "down" in d or "sit" in d or "fall" in d: mv[1] -= 0.1
            actors[0]["motion_vector"] = mv

    # Camera derived from CENTROID of all focal actors (multi-char aware)
    # + shot framing
    if actors:
        # Multi-character: aim at centroid + ensure all in frame
        cx = sum(a["position_xyz"][0] for a in actors) / len(actors)
        cy = sum(a["position_xyz"][1] for a in actors) / len(actors)
        cz = sum(a["position_xyz"][2] for a in actors) / len(actors)
        # Spread: max distance between any two actors (used to widen framing)
        spread = 0
        if len(actors) > 1:
            for i in range(len(actors)):
                for j in range(i + 1, len(actors)):
                    p1 = actors[i]["position_xyz"]
                    p2 = actors[j]["position_xyz"]
                    d = ((p1[0]-p2[0])**2 + (p1[2]-p2[2])**2) ** 0.5
                    spread = max(spread, d)
        # Increase distance proportional to actor spread for multi-char shots
        cam_dist = framing["distance"] + spread * 0.7
        cam_h = cy + 1.55 + framing["height_offset"]
        # Per-panel camera variation — film/anime/toonz cinematography:
        # rotate camera around subject by panel_idx × prime angle for spread,
        # vary pitch (high/low/eye), vary composition (thirds_R/L/center).
        # Honors 180°-line rule by clamping rotation to one hemisphere
        # per scene's "screen direction" (panel 1 establishes side).
        panel_idx_for_var = panel.get("panelIndex", 1)
        # Angular orbit around subject — prime 47° per panel for visible
        # variety without crossing 180° line (cap at ±120°)
        orbit_deg = ((panel_idx_for_var - 1) * 47) % 240 - 120   # -120 to +120
        orbit_rad = math.radians(orbit_deg)
        # Pitch variation: high-angle for vulnerable/wide, low-angle for
        # power/CU dramatic; per-panel small drift.
        pitch_options = [0, -10, +5, -5, +15, -15, +10, 0]  # cycle
        pitch_deg = pitch_options[(panel_idx_for_var - 1) % len(pitch_options)]
        pitch_rad = math.radians(pitch_deg)
        # Composition rule per panel (thirds_R / thirds_L / center cycle)
        comp_options = ["thirds_R", "thirds_L", "center", "thirds_R",
                          "thirds_L", "center"]
        comp_rule = comp_options[(panel_idx_for_var - 1) % len(comp_options)]

        # Shot-type base placement (radial distance), then rotate by orbit
        if shot_cat in ("ECU", "CU", "Insert"):
            base_x_factor, base_z_factor = 0.0, -1.0
        elif shot_cat in ("MS", "MLS", "Medium"):
            base_x_factor, base_z_factor = 0.25, -0.95
        elif shot_cat in ("OTS",):
            base_x_factor, base_z_factor = 0.6, -0.5
        else:  # LS / ELS / Wide / TWO
            base_x_factor, base_z_factor = 0.35, -0.85

        # Apply orbit rotation around subject in XZ plane
        base_x = base_x_factor * cam_dist
        base_z = base_z_factor * cam_dist
        rot_x = base_x * math.cos(orbit_rad) - base_z * math.sin(orbit_rad)
        rot_z = base_x * math.sin(orbit_rad) + base_z * math.cos(orbit_rad)
        cam_x = cx + rot_x
        cam_z = cz + rot_z
        # Pitch via height adjustment (proxy for tilt)
        cam_h = cy + 1.55 + framing["height_offset"] + math.tan(pitch_rad) * cam_dist * 0.3

        target_h = cy + 1.40 if shot_cat in ("MS", "MLS", "LS", "ELS", "Wide", "TWO") else cy + 1.55
        # Apply composition rule offset to target
        if comp_rule == "thirds_R":
            comp_x_offset = -cam_dist * 0.10
        elif comp_rule == "thirds_L":
            comp_x_offset = +cam_dist * 0.10
        else:
            comp_x_offset = 0.0
        cam_origin = [cam_x, cam_h, cam_z]
        cam_target = [cx + comp_x_offset, target_h, cz]

        # Subject-aware target offset (Gemma): "where should camera point?"
        if use_llm and panel.get("visual") and shot_cat in ("CU", "ECU", "MS"):
            prompt = (
                f"Manga panel: \"{panel['visual'][:180]}\"\n\n"
                f"In ONE phrase, what is the main subject the camera should focus on? "
                f"e.g. 'character face', 'character hands', 'phone screen', 'object on desk', "
                f"'character eyes only'. Reply with just the phrase."
            )
            resp = _ollama_describe(prompt, timeout=15).strip().lower()
            if "face" in resp:
                cam_target[1] = cy + 1.6   # head height
            elif "hand" in resp or "phone" in resp or "object" in resp:
                cam_target[1] = cy + 0.85  # desktop height
            elif "eye" in resp:
                cam_target[1] = cy + 1.65
    else:
        cam_origin = [2.0, 1.5, 0.5]
        cam_target = [2.0, 1.0, 3.0]

    return {
        "scene_slug": scene_slug,
        "panel_idx":  panel.get("panelIndex"),
        "shot_cat":   shot_cat,
        "actors":     actors,
        "props":      defaults["props"],
        "camera": {
            "origin_xyz":   cam_origin,
            "target_xyz":   cam_target,
            "fov_deg":      framing["fov"],
            "motion_blur":  False,
            "depth_of_field": shot_cat in ("ECU", "CU", "MS"),
        },
        "lighting": {
            "key_light":     defaults["key_light"],
            "time_of_day":   defaults["time_of_day"],
            "key_intensity": 2500 * atmosphere["contrast_bias"],
            "fill_intensity": 800,
            "rim_intensity":  300 if shot_cat in ("CU", "ECU") else 0,
            "mood_color_temp": defaults["mood_color_temp"],
            "sun_altitude_deg": defaults.get("sun_altitude_deg", 45),
            "sun_azimuth_deg":  defaults.get("sun_azimuth_deg", 180),
        },
        "atmosphere": {
            **atmosphere,
            "time_of_day":   defaults["time_of_day"],
            "season":        defaults.get("season", "early autumn"),
            "weather":       defaults.get("weather", "clear"),
        },
        "setting_lock": defaults.get("setting_lock", ""),
        "tone_tag": tone,
    }


if __name__ == "__main__":
    import sys
    panel_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    page_num  = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    manifest = json.loads(Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json").read_text())
    p = next(pn for pn in manifest["panels"] if pn["pageNum"] == page_num and pn["panelIndex"] == panel_idx)
    scene = {0:"yuto-bedroom",1:"classroom",2:"classroom",3:"city-street",4:"yuto-bedroom",5:"yuto-bedroom"}.get(page_num, "yuto-bedroom")
    spec = design_scene_graph(p, scene)
    print(json.dumps(spec, indent=2, ensure_ascii=False))

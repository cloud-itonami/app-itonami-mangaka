"""v7 Stage A — Pose / Emotion / Beat extraction (character-first scene graph).

Per panel, extract:
  - per-character pose_id (from library)
  - emotion
  - panel-local position (left/center/right + top/bottom)
  - sight_line direction
  - hand_action
  - camera derived FROM pose (not from USD scene)

Uses Gemma 3:4b LLM with the manifest visual text + character roster.
Outputs CharacterPoseSpec per character per panel.
"""
from __future__ import annotations
import json, re, urllib.request
from pathlib import Path
from typing import Optional

from lg_mangaka import llm_endpoint as _ep

# Host + vision model resolve via the llm_endpoint SSoT (OLLAMA_HOST/OLLAMA_MODEL).
OLLAMA = _ep.ollama_url()
MODEL = _ep.vision_model()

# Pose library (28 named poses, expandable)
POSE_LIBRARY = {
    "sitting": {
        "sitting_at_desk":      "seated at desk, hands on desk surface",
        "sitting_back_to_camera": "seated facing away, back visible",
        "sitting_legs_crossed": "seated cross-legged",
        "sitting_slumped":       "seated slumped over, head down",
        "sitting_on_bed":        "seated on bed edge, leaning forward",
        "sitting_phone":         "seated, smartphone in hand, gazing screen",
    },
    "standing": {
        "standing_facing":       "standing facing camera",
        "standing_profile":      "standing in profile",
        "standing_back":         "standing facing away",
        "standing_leaning_wall": "leaning against wall casually",
        "standing_arms_crossed": "standing arms crossed",
        "standing_arms_akimbo":  "standing hands on hips",
        "standing_pointing":     "standing pointing forward",
    },
    "walking": {
        "walking_toward":        "walking toward camera",
        "walking_away":          "walking away",
        "walking_side":          "walking in profile",
        "running":               "running forward urgently",
    },
    "leaning": {
        "leaning_over_desk":     "leaning over desk forward",
        "leaning_door":          "leaning in doorway",
        "leaning_railing":       "leaning on railing looking out",
    },
    "gesture": {
        "gesturing_hands_open":  "explaining with open hands",
        "gesturing_finger_point": "pointing finger emphatically",
        "gesturing_holding_object": "holding object out to show",
        "gesturing_brushing_hair": "brushing hair aside",
    },
    "emotion_pose": {
        "shocked_arms_up":       "arms raised in shock",
        "anxious_clutching":     "anxious hands clutching chest",
        "calm_observing":        "calm, observing scene",
        "smug_smile":            "smug confident smile",
    },
}

# Flattened lookup
ALL_POSES = {pid: desc
              for category in POSE_LIBRARY.values()
              for pid, desc in category.items()}


JUDGE_PROMPT_TEMPLATE = """\
You are a manga storyboard layout artist (絵コンテ作家).

Panel script:
  Shot: {shot}
  Tone: {tone}
  Scene action: {scene_subject}
  Visual description: {visual}
  Characters in panel: {characters}

For each character, extract these layout fields. Pick from the pose
library options shown.

Pose library (pick ONE pose_id per character):
{pose_options}

Emotion options: anxious, calm, shocked, smug, sad, angry, comedic,
                   contemplative, surprised, determined

Position options (panel-local, where char appears):
  left, center, right, far-left, far-right, foreground, background

Sight-line options: forward, left, right, down, up, at-other-char

Hand-action options: holding-object, pointing, gesturing, in-pocket,
                       on-desk, hidden, brushing-hair

Output ONE line per character in this exact format:

{character_name}: pose=<pose_id>, emotion=<emotion>, position=<pos>, sight=<dir>, hand=<action>

Be strict — pick exactly one option per field. No commentary.
"""


def _ollama(prompt: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                          "options": {"temperature": 0.2, "num_predict": 250}}).encode(),
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", "")
    except Exception:
        return ""


def extract_poses(panel: dict) -> dict:
    """Returns: {character_name: {pose_id, emotion, position, sight, hand}}.

    Falls back to heuristic defaults if LLM unavailable.
    """
    chars = panel.get("focusedCharacters") or []
    if not chars:
        return {}

    pose_options = "\n".join(f"  {pid}: {desc}" for pid, desc in ALL_POSES.items())
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        shot=panel.get("shot", "MS"),
        tone=panel.get("tone", ""),
        scene_subject=panel.get("sceneSubject", "")[:150],
        visual=panel.get("visual", "")[:250],
        characters=", ".join(chars),
        pose_options=pose_options,
        character_name=chars[0],
    )
    raw = _ollama(prompt, timeout=30)

    results = {}
    for line in raw.splitlines():
        # Match: "<name>: pose=<v>, emotion=<v>, position=<v>, sight=<v>, hand=<v>"
        m = re.match(r"^\s*([A-Z][a-zA-Z]+)\s*:\s*(.+)$", line)
        if not m: continue
        name = m.group(1)
        if name not in chars: continue
        fields = {}
        for kv in m.group(2).split(","):
            kv = kv.strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                fields[k.strip()] = v.strip()
        # Validate pose_id
        if fields.get("pose") not in ALL_POSES:
            fields["pose"] = "standing_facing"  # default fallback
        results[name] = {
            "pose":     fields.get("pose",     "standing_facing"),
            "emotion":  fields.get("emotion",  "calm"),
            "position": fields.get("position", "center"),
            "sight":    fields.get("sight",    "forward"),
            "hand":     fields.get("hand",     "hidden"),
        }
    # Fallback: heuristic defaults for chars not parsed
    for ch in chars:
        if ch not in results:
            results[ch] = _heuristic_pose(panel, ch)
    return results


def _heuristic_pose(panel: dict, char: str) -> dict:
    """No-LLM fallback — derive pose from manifest fields."""
    visual = (panel.get("visual") or "").lower()
    shot = (panel.get("shot") or "").lower()
    tone = (panel.get("tone") or "").lower()
    if "sit" in visual or "desk" in visual: pose = "sitting_at_desk"
    elif "walk" in visual:                   pose = "walking_side"
    elif "lean" in visual:                   pose = "leaning_over_desk"
    elif "stand" in visual:                  pose = "standing_facing"
    elif "back" in visual:                   pose = "standing_back"
    else:                                     pose = "standing_facing"
    return {
        "pose":     pose,
        "emotion":  tone or "calm",
        "position": "center",
        "sight":    "forward",
        "hand":     "hidden",
    }


def camera_from_pose(pose_spec: dict, shot: str = "MS") -> dict:
    """Derive camera position FROM character pose + shot type.

    Reverses v6's "actor centroid → camera" — here it's "pose → camera"
    where camera is panel-local (relative to character position, not USD).
    """
    pos = pose_spec.get("position", "center")
    sight = pose_spec.get("sight", "forward")
    # Panel-local target offset
    x_offset = {"left": -0.3, "right": +0.3, "far-left": -0.5, "far-right": +0.5,
                 "center": 0.0, "foreground": 0.0, "background": 0.0}.get(pos, 0.0)
    # Camera distance from shot type
    cam_dist = {"ECU": 0.4, "CU": 1.0, "MS": 1.8, "MLS": 2.6,
                 "LS": 4.0, "Wide": 6.0}.get(shot, 1.8)
    # Camera FOV
    fov = {"ECU": 35, "CU": 38, "MS": 45, "MLS": 50, "LS": 55, "Wide": 70}.get(shot, 45)
    # Camera position: in front of character (sight direction), offset
    # by composition rule
    return {
        "origin_xyz":  [x_offset * cam_dist, 1.55, -cam_dist],
        "target_xyz":  [x_offset * 0.5, 1.4, 0.0],
        "fov_deg":     fov,
        "panel_local": True,   # marker: this is panel-local, not USD-world
    }


def design_v7_panel(panel: dict) -> dict:
    """Top-level: extract poses + derive cameras for one panel."""
    poses = extract_poses(panel)
    shot = (panel.get("shot") or "MS").upper()
    # Map shot string to category
    shot_cat = "MS"
    s_lower = shot.lower()
    if "extreme close" in s_lower:   shot_cat = "ECU"
    elif "close" in s_lower:         shot_cat = "CU"
    elif "long" in s_lower:          shot_cat = "LS"
    elif "wide" in s_lower:          shot_cat = "Wide"
    elif "medium" in s_lower:        shot_cat = "MS"
    # Per-character camera derivation (character-first!)
    cameras = {ch: camera_from_pose(pose, shot_cat) for ch, pose in poses.items()}
    return {
        "panel_idx":  panel.get("panelIndex"),
        "shot_cat":   shot_cat,
        "poses":      poses,
        "cameras":    cameras,    # per-character panel-local cams
        "tone":       panel.get("tone"),
        "scene":      panel.get("sceneSubject"),
        "dialogue":   [d.get("text") for d in (panel.get("dialogues") or []) if d.get("text")],
    }


if __name__ == "__main__":
    import sys
    page_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
    manifest = json.loads(MANIFEST.read_text())
    panels = sorted([p for p in manifest["panels"] if p["pageNum"]==page_num],
                     key=lambda p: p["panelIndex"])
    for p in panels:
        spec = design_v7_panel(p)
        print(f"=== panel {spec['panel_idx']} ({spec['shot_cat']}) ===")
        for ch, pose in spec["poses"].items():
            print(f"  {ch}: pose={pose['pose']} emotion={pose['emotion']} "
                  f"pos={pose['position']} hand={pose['hand']}")

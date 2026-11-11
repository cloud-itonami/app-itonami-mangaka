"""Enrich USD scenes with narrative customData attributes.

The base USD scenes (yuto-bedroom, classroom, etc.) carry only
geometry. The "Narrative USD" layer adds semantic state per prim or
per camera so the downstream NPR renderer (Blender OSL / RenderMan)
can drive line weight, black fill, screentone density, perspective
distortion from the page's emotional beat.

Schema:
  Camera customData:
    string narrative:shot         "ECU" | "CU" | "MS" | "LS" | ...
    string narrative:angle        "eye_level" | "high" | "low" | ...
    string narrative:rule         "thirds_R" | "center" | ...
    string narrative:beat         "establishing" | "tension" | "climax" | "release"

  Character mesh customData:
    string narrative:emotion      "anxious" | "shocked" | "joyful" | ...
    float  narrative:tension      0.0 - 1.0
    string narrative:posture      "anxious_at_desk" | ...
    string narrative:character_id "Yuto" | "Ren" | "Nei" | ...

  Light customData:
    string narrative:mood         "warm" | "cold" | "dramatic" | "soft"
    float  narrative:contrast_bias 0.0 - 1.0

  Scene root customData:
    string narrative:page_intent  "exposition" | "confrontation" | "reflection"
    float  narrative:overall_tension 0.0 - 1.0

The OSL shaders read these and emit:
  - Line weight = base_weight + tension * 2.0
  - Black fill threshold = 0.5 - tension * 0.3
  - Screentone density = emotion_to_density[emotion]
  - Perspective distortion = panic_distort if emotion == "panic"

Usage:
    python enrich-narrative-customdata.py \
        --scene yuto-bedroom \
        --page-num 5 \
        --manifest /path/to/image-gen-manifest.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from pxr import Usd, UsdGeom, Vt

# Emotion → screentone density (manga convention)
EMOTION_DENSITY = {
    "neutral":      0.30,
    "anxious":      0.55,
    "shocked":      0.75,
    "sad":          0.45,
    "angry":        0.80,
    "joyful":       0.20,
    "determined":   0.50,
    "fearful":      0.70,
    "contemplative":0.25,
    "embarrassed":  0.40,
}

EMOTION_MOOD = {
    "neutral":      "warm",
    "anxious":      "cold",
    "shocked":      "dramatic",
    "sad":          "cold",
    "angry":        "dramatic",
    "joyful":       "warm",
    "determined":   "dramatic",
    "fearful":      "cold",
    "contemplative":"soft",
    "embarrassed":  "warm",
}


def enrich(stage: Usd.Stage, page_data: dict) -> int:
    """Walk every Camera + Light + Mesh prim in the stage and attach
    narrative customData based on the page's manifest entry."""
    enriched = 0
    overall_tension = 0.0
    page_intent = page_data.get("intent", "exposition")
    emotion = page_data.get("emotion", "neutral")
    character = page_data.get("focal_character")

    # Compute overall tension from emotion
    emotion_tension = {
        "neutral": 0.2, "anxious": 0.6, "shocked": 0.9,
        "sad": 0.4, "angry": 0.8, "joyful": 0.2,
        "determined": 0.5, "fearful": 0.7,
        "contemplative": 0.2, "embarrassed": 0.3,
    }
    overall_tension = emotion_tension.get(emotion, 0.4)

    # Stage-level narrative customData
    root = stage.GetDefaultPrim()
    root_meta = root.GetCustomData() or {}
    root_meta["narrative:page_intent"] = page_intent
    root_meta["narrative:overall_tension"] = overall_tension
    root_meta["narrative:emotion"] = emotion
    if character:
        root_meta["narrative:focal_character"] = character
    root.SetCustomData(root_meta)
    enriched += 1

    # Per-prim
    for prim in stage.Traverse():
        cm = dict(prim.GetCustomData() or {})
        if prim.IsA(UsdGeom.Camera):
            cm["narrative:shot"] = page_data.get("shot", "MS")
            cm["narrative:angle"] = page_data.get("angle", "eye_level")
            cm["narrative:rule"] = page_data.get("rule", "center")
            cm["narrative:beat"] = page_data.get("beat", "establishing")
            prim.SetCustomData(cm)
            enriched += 1
        elif "Light" in prim.GetTypeName():
            cm["narrative:mood"] = EMOTION_MOOD.get(emotion, "warm")
            cm["narrative:contrast_bias"] = min(1.0, overall_tension + 0.2)
            prim.SetCustomData(cm)
            enriched += 1
        elif prim.IsA(UsdGeom.Mesh):
            # Tag character meshes only — by name heuristic
            name = prim.GetName().lower()
            if any(k in name for k in ("character", "yuto", "ren", "nei", "char_")):
                cm["narrative:emotion"] = emotion
                cm["narrative:tension"] = overall_tension
                cm["narrative:posture"] = page_data.get("pose", "standing_facing_camera")
                cm["narrative:character_id"] = character or "unknown"
                prim.SetCustomData(cm)
                enriched += 1

    return enriched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True,
                          help="scene slug under data/ghosthacker/resources/usd/")
    parser.add_argument("--page-num", type=int, required=True)
    parser.add_argument("--manifest",
                          default="/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
    parser.add_argument("--out", default="",
                          help="output .usda path; default = in-place")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    panels = [p for p in manifest["panels"] if p["pageNum"] == args.page_num]
    if not panels:
        print(f"no panels for page {args.page_num}")
        return 1
    # Use first panel's intent as page-level (could compute majority later)
    p = panels[0]
    page_data = {
        "intent":            "exposition",
        "emotion":           (p.get("tone") or "neutral").split()[0].lower(),
        "shot":              "MS",
        "angle":             "eye_level",
        "rule":              "center",
        "beat":              "establishing",
        "focal_character":   (p.get("focusedCharacters") or [None])[0],
        "pose":              "anxious_at_desk",
    }
    base = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/usd")
    src = base / f"{args.scene}.usda"
    if not src.exists():
        # fallback to 60-apps active path
        src = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/usd") / f"{args.scene}.usda"
    if not src.exists():
        print(f"scene not found: {args.scene}")
        return 1
    stage = Usd.Stage.Open(str(src))
    n = enrich(stage, page_data)
    out = Path(args.out) if args.out else src
    stage.GetRootLayer().Export(str(out))
    print(f"enriched {n} prims in {out}")
    print(f"page_data: {json.dumps(page_data, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    sys.exit(main() or 0)

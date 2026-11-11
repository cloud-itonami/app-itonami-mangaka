"""Character mannequin + OpenPose skeleton renderer.

Pure Python (no Blender, no torch). Builds a 18-keypoint humanoid
skeleton parameterized by joint angles + world-space position +
overall scale. Projects to 2D via the same pinhole camera used by
build-yuto-bedroom.py, then draws OpenPose-format colored joints
and bones into a PNG suitable for ComfyUI ControlNet OpenPose
(Union Pro Max supports this format directly).

Pose library is just a dict of joint angles per named pose, so
the "edit later" workflow is:
  1. tweak pose dict (or write new entry)
  2. re-render only the character skeleton PNG (~1s)
  3. ComfyUI panel regen (~30-50s)
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

# OpenPose BODY_18 keypoint names — matches what ControlNet OpenPose
# was trained on (COCO 18 keypoints, color-coded by index).
KP_NAMES = [
    "nose", "neck",
    "r_shoulder", "r_elbow", "r_wrist",
    "l_shoulder", "l_elbow", "l_wrist",
    "r_hip", "r_knee", "r_ankle",
    "l_hip", "l_knee", "l_ankle",
    "r_eye", "l_eye", "r_ear", "l_ear",
]
# Standard OpenPose color palette (RGB)
KP_COLORS = [
    (255, 0,   0),   (255, 85,  0),
    (255, 170, 0),   (255, 255, 0),   (170, 255, 0),
    (85,  255, 0),   (0,   255, 0),   (0,   255, 85),
    (0,   255, 170), (0,   255, 255), (0,   170, 255),
    (0,   85,  255), (0,   0,   255), (85,  0,   255),
    (170, 0,   255), (255, 0,   255), (255, 0,   170), (255, 0,   85),
]
# Bone connections — pairs of keypoint indices
LIMBS = [
    (0, 1),  # nose -> neck
    (1, 2),  (2, 3),  (3, 4),     # right arm
    (1, 5),  (5, 6),  (6, 7),     # left arm
    (1, 8),  (8, 9),  (9, 10),    # right leg
    (1, 11), (11, 12),(12, 13),   # left leg
    (0, 14), (0, 15), (14, 16), (15, 17),  # face
]
LIMB_COLORS = [
    (255, 0,   0),
    (255, 85,  0),  (255, 170, 0),  (255, 255, 0),
    (170, 255, 0),  (85,  255, 0),  (0,   255, 0),
    (0,   255, 85), (0,   255, 170),(0,   255, 255),
    (0,   170, 255),(0,   85,  255),(0,   0,   255),
    (85,  0,   255),(170, 0,   255),(255, 0,   255),(255, 0,   170),
]


def deg(d): return math.radians(d)


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


# Default human proportions in meters (assuming ~170cm adult).
SEGMENTS = {
    "neck_to_head":    0.20,
    "shoulder_width":  0.40,
    "shoulder_to_elbow": 0.30,
    "elbow_to_wrist":  0.28,
    "hip_width":       0.30,
    "hip_to_knee":     0.45,
    "knee_to_ankle":   0.42,
    "torso_height":    0.60,
    "head_radius":     0.10,
}


# Pose library — each pose returns a dict of (kp_name -> 3D position
# relative to the pelvis origin).
def pose_anxious_at_desk(pelvis: np.ndarray) -> dict[str, np.ndarray]:
    """Sitting on chair, leaning slightly forward, both hands forward
    over the desk (one holding a phone). Anxious posture: shoulders
    slightly raised, head slightly down."""
    s = SEGMENTS
    p = pelvis
    pose: dict[str, np.ndarray] = {}
    # Torso lean: 5 deg forward
    torso_dir = rot_x(deg(-5)) @ np.array([0, 1, 0])
    pose["pelvis_center"] = p
    neck = p + torso_dir * s["torso_height"]
    pose["neck"] = neck
    # Head slightly down
    head_dir = rot_x(deg(-15)) @ torso_dir
    pose["nose"] = neck + head_dir * s["neck_to_head"]
    # eyes / ears (small offsets near nose)
    pose["r_eye"] = pose["nose"] + np.array([-0.04, 0.03, 0.04])
    pose["l_eye"] = pose["nose"] + np.array([ 0.04, 0.03, 0.04])
    pose["r_ear"] = pose["nose"] + np.array([-0.08, 0.04, -0.02])
    pose["l_ear"] = pose["nose"] + np.array([ 0.08, 0.04, -0.02])
    # Shoulders (slightly elevated for anxiety)
    sh_y = neck[1] + 0.02
    pose["r_shoulder"] = np.array([neck[0] - s["shoulder_width"]/2, sh_y, neck[2]])
    pose["l_shoulder"] = np.array([neck[0] + s["shoulder_width"]/2, sh_y, neck[2]])
    # Both elbows bent ~90, hands forward over desk
    # Right hand reaches further forward holding phone
    pose["r_elbow"] = pose["r_shoulder"] + np.array([-0.05, -0.15, 0.20])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0.05,   0.00, 0.30])
    # Left hand rests on desk / supports
    pose["l_elbow"] = pose["l_shoulder"] + np.array([ 0.05, -0.15, 0.18])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([0.00,   0.00, 0.20])
    # Hips (seated - same height as pelvis)
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    # Knees - bent (sitting), pointing forward
    pose["r_knee"]  = pose["r_hip"] + np.array([0.02, -0.05, s["hip_to_knee"]])
    pose["l_knee"]  = pose["l_hip"] + np.array([-0.02, -0.05, s["hip_to_knee"]])
    # Ankles - hanging down
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -s["knee_to_ankle"], 0.05])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"], 0.05])
    return pose


def pose_standing_facing_camera(pelvis: np.ndarray) -> dict[str, np.ndarray]:
    s = SEGMENTS
    p = pelvis
    pose: dict[str, np.ndarray] = {}
    pose["pelvis_center"] = p
    neck = p + np.array([0, s["torso_height"], 0])
    pose["neck"] = neck
    pose["nose"] = neck + np.array([0, s["neck_to_head"], 0.02])
    pose["r_eye"] = pose["nose"] + np.array([-0.04, 0.03, 0.04])
    pose["l_eye"] = pose["nose"] + np.array([ 0.04, 0.03, 0.04])
    pose["r_ear"] = pose["nose"] + np.array([-0.08, 0.04, -0.02])
    pose["l_ear"] = pose["nose"] + np.array([ 0.08, 0.04, -0.02])
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0.02, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0.02, 0])
    # Arms hanging down at sides
    pose["r_elbow"] = pose["r_shoulder"] + np.array([-0.02, -s["shoulder_to_elbow"], 0])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0,     -s["elbow_to_wrist"],   0])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([ 0.02, -s["shoulder_to_elbow"], 0])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([0,     -s["elbow_to_wrist"],   0])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0, -s["hip_to_knee"], 0])
    pose["l_knee"]  = pose["l_hip"] + np.array([0, -s["hip_to_knee"], 0])
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -s["knee_to_ankle"], 0])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"], 0])
    return pose


def pose_sleeping_at_desk(pelvis):
    """Head down on arms, slumped at desk."""
    s = SEGMENTS; p = pelvis
    pose = {}
    pose["pelvis_center"] = p
    # Torso heavily forward (slumped)
    neck = p + rot_x(deg(-40)) @ np.array([0, s["torso_height"], 0])
    pose["neck"] = neck
    # Head turned to one side, resting on arms
    pose["nose"]  = neck + np.array([0.05, 0.0, 0.20])
    pose["r_eye"] = pose["nose"] + np.array([-0.04, 0.03, 0.04])
    pose["l_eye"] = pose["nose"] + np.array([ 0.04, 0.03, 0.04])
    pose["r_ear"] = pose["nose"] + np.array([-0.08, 0.04, -0.02])
    pose["l_ear"] = pose["nose"] + np.array([ 0.08, 0.04, -0.02])
    # Arms folded forward on desk
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0, 0])
    pose["r_elbow"] = pose["r_shoulder"] + np.array([-0.05, -0.05, 0.30])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0.10,  0.00, 0.20])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([ 0.05, -0.05, 0.30])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([-0.10, 0.00, 0.20])
    # Seated lower body
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0.02, -0.05, s["hip_to_knee"]])
    pose["l_knee"]  = pose["l_hip"] + np.array([-0.02, -0.05, s["hip_to_knee"]])
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -s["knee_to_ankle"], 0.05])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"], 0.05])
    return pose


def pose_talking_animated(pelvis):
    """Standing, talking gesture — one hand raised, body slightly turned."""
    s = SEGMENTS; p = pelvis
    pose = {}
    pose["pelvis_center"] = p
    neck = p + np.array([0, s["torso_height"], 0])
    pose["neck"] = neck
    # Head turned slightly
    pose["nose"] = neck + np.array([0.03, s["neck_to_head"], 0.04])
    pose["r_eye"] = pose["nose"] + np.array([-0.04, 0.03, 0.04])
    pose["l_eye"] = pose["nose"] + np.array([ 0.04, 0.03, 0.04])
    pose["r_ear"] = pose["nose"] + np.array([-0.08, 0.04, -0.02])
    pose["l_ear"] = pose["nose"] + np.array([ 0.08, 0.04, -0.02])
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0.02, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0.02, 0])
    # Right hand raised in talking gesture
    pose["r_elbow"] = pose["r_shoulder"] + np.array([-0.10, -0.05, 0.15])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0.10,  0.20, 0.10])
    # Left arm relaxed at side
    pose["l_elbow"] = pose["l_shoulder"] + np.array([ 0.02, -s["shoulder_to_elbow"], 0])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([0,     -s["elbow_to_wrist"],   0])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0, -s["hip_to_knee"], 0])
    pose["l_knee"]  = pose["l_hip"] + np.array([0, -s["hip_to_knee"], 0])
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -s["knee_to_ankle"], 0])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"], 0])
    return pose


def pose_looking_at_phone(pelvis):
    """Standing, both hands holding phone up at chest height, head tilted down."""
    s = SEGMENTS; p = pelvis
    pose = {}
    pose["pelvis_center"] = p
    neck = p + np.array([0, s["torso_height"], 0])
    pose["neck"] = neck
    # Head tilted down to look at phone
    head_dir = rot_x(deg(-25)) @ np.array([0, 1, 0])
    pose["nose"] = neck + head_dir * s["neck_to_head"]
    pose["r_eye"] = pose["nose"] + np.array([-0.04, 0.03, 0.04])
    pose["l_eye"] = pose["nose"] + np.array([ 0.04, 0.03, 0.04])
    pose["r_ear"] = pose["nose"] + np.array([-0.08, 0.04, -0.02])
    pose["l_ear"] = pose["nose"] + np.array([ 0.08, 0.04, -0.02])
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0, 0])
    # Both hands forward at chest height
    pose["r_elbow"] = pose["r_shoulder"] + np.array([0.02, -0.20, 0.20])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0.05, -0.05, 0.20])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([-0.02, -0.20, 0.20])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([-0.05, -0.05, 0.20])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0, -s["hip_to_knee"], 0])
    pose["l_knee"]  = pose["l_hip"] + np.array([0, -s["hip_to_knee"], 0])
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -s["knee_to_ankle"], 0])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"], 0])
    return pose


def pose_walking_running(pelvis):
    """Mid-stride, one knee up, arms swinging."""
    s = SEGMENTS; p = pelvis
    pose = {}
    pose["pelvis_center"] = p
    # Body slightly tilted forward
    neck = p + rot_x(deg(-8)) @ np.array([0, s["torso_height"], 0])
    pose["neck"] = neck
    pose["nose"] = neck + np.array([0, s["neck_to_head"], 0.04])
    pose["r_eye"] = pose["nose"] + np.array([-0.04, 0.03, 0.04])
    pose["l_eye"] = pose["nose"] + np.array([ 0.04, 0.03, 0.04])
    pose["r_ear"] = pose["nose"] + np.array([-0.08, 0.04, -0.02])
    pose["l_ear"] = pose["nose"] + np.array([ 0.08, 0.04, -0.02])
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0, 0])
    # Right arm forward, left arm back (running swing)
    pose["r_elbow"] = pose["r_shoulder"] + np.array([0.02, -0.15, 0.20])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0,    -0.05, 0.20])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([-0.02, -0.15, -0.20])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([0,     -0.05, -0.15])
    # Right knee up (mid-stride), left leg back-stretched
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0, -0.10, 0.30])
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -0.35, 0.10])
    pose["l_knee"]  = pose["l_hip"] + np.array([0, -s["hip_to_knee"], -0.10])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"], -0.20])
    return pose


POSES = {
    "anxious_at_desk":          pose_anxious_at_desk,
    "standing_facing_camera":   pose_standing_facing_camera,
    "sleeping_at_desk":          pose_sleeping_at_desk,
    "talking_animated":          pose_talking_animated,
    "looking_at_phone":          pose_looking_at_phone,
    "walking_running":           pose_walking_running,
}


def project_pinhole(p3d, cam_origin, cam_target, fov_deg, W, H):
    """Project a 3D world point to 2D pixel coords. Returns (u, v, in_front)."""
    o = np.array(cam_origin, dtype=np.float64)
    t = np.array(cam_target, dtype=np.float64)
    forward = t - o
    forward /= np.linalg.norm(forward) + 1e-9
    world_up = np.array([0, 1, 0], dtype=np.float64)
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right) + 1e-9
    up = np.cross(right, forward)

    diff = p3d - o
    z = diff @ forward
    if z <= 1e-3:
        return None, None, False
    x_cam = diff @ right
    y_cam = diff @ up
    fov = math.radians(fov_deg)
    half_h = math.tan(fov / 2)
    aspect = W / H
    half_w = half_h * aspect
    u = (x_cam / z + half_w) / (2 * half_w) * W
    v = (1.0 - (y_cam / z + half_h) / (2 * half_h)) * H
    return float(u), float(v), True


def render_openpose(pose_3d, cam_origin, cam_target, fov_deg, W=1216, H=832):
    """Render an OpenPose-format skeleton PNG."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    pts2d = {}
    for name in KP_NAMES:
        if name not in pose_3d:
            continue
        u, v, ok = project_pinhole(pose_3d[name], cam_origin, cam_target,
                                     fov_deg, W, H)
        if ok and 0 <= u < W and 0 <= v < H:
            pts2d[name] = (u, v)
    # Draw bones
    for li, (i, j) in enumerate(LIMBS):
        ni = KP_NAMES[i]; nj = KP_NAMES[j]
        if ni in pts2d and nj in pts2d:
            color = LIMB_COLORS[li] if li < len(LIMB_COLORS) else (255, 255, 255)
            draw.line([pts2d[ni], pts2d[nj]], fill=color, width=6)
    # Draw joints
    for idx, name in enumerate(KP_NAMES):
        if name in pts2d:
            u, v = pts2d[name]
            color = KP_COLORS[idx]
            draw.ellipse([u - 6, v - 6, u + 6, v + 6], fill=color)
    return img


def main():
    out_dir = Path("/tmp/arc01-scenes")
    out_dir.mkdir(exist_ok=True)

    # Yuto sitting at desk in the bedroom
    pelvis = np.array([3.0, 0.50, 2.0])  # near east wall, at desk height
    pose_3d = POSES["anxious_at_desk"](pelvis)
    # Use the same yuto_at_desk camera as bedroom render
    cam = ((1.0, 1.5, 1.3), (3.7, 0.85, 2.1), 50.0)
    img = render_openpose(pose_3d, cam[0], cam[1], cam[2])
    out = out_dir / "yuto-bedroom-yuto_at_desk-openpose.png"
    img.save(out)
    print(f"saved {out}")

    # Also: standing facing camera (Yuto standing somewhere in room)
    pelvis2 = np.array([2.0, 0.90, 2.5])
    pose_3d2 = POSES["standing_facing_camera"](pelvis2)
    img2 = render_openpose(pose_3d2, cam[0], cam[1], cam[2])
    out2 = out_dir / "yuto-bedroom-yuto_at_desk-openpose-stand.png"
    img2.save(out2)
    print(f"saved {out2}")


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)

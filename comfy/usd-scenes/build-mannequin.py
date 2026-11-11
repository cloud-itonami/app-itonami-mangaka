"""Build humanoid mannequin USD asset — primitive cylinders + box + sphere.

For v5 score-blocker fix: 'no character mesh in USD scene'.

Output: data/ghosthacker/resources/usd/character-mannequin.usda

The mannequin is referenced into a scene at the focal character's
pelvis position. Two poses supported:
  - seated: torso vertical, thighs horizontal, lower legs vertical
  - standing: all segments vertical

Geometry is intentionally crude (box torso, cylinder limbs, sphere
head) — this gives Workbench cavity + outline a clean silhouette to
trace, which is what the ReAct loop's character_identity axis
actually wants. Detail comes from the OSL ink/screentone pass, not
from polygon count.
"""
import sys, math
from pathlib import Path
from pxr import Usd, UsdGeom, Sdf, Gf
import trimesh
import numpy as np

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/character-mannequin.usda")

# Body segment dimensions (meters, approximating a teen)
SEG = {
    "head_radius":   0.10,
    "torso_w":       0.30, "torso_h": 0.50, "torso_d": 0.18,
    "upper_arm_l":   0.28, "upper_arm_r": 0.04,
    "lower_arm_l":   0.25, "lower_arm_r": 0.04,
    "thigh_l":       0.40, "thigh_r": 0.06,
    "shin_l":        0.40, "shin_r": 0.05,
    "foot_w":        0.12, "foot_h": 0.05, "foot_d": 0.22,
    "neck_l":        0.07,
}


def cylinder_mesh(radius, height, segments=12):
    return trimesh.creation.cylinder(radius=radius, height=height, sections=segments)

def box_mesh(width, height, depth):
    return trimesh.creation.box(extents=(width, height, depth))

def sphere_mesh(radius, subdivisions=2):
    return trimesh.creation.icosphere(radius=radius, subdivisions=subdivisions)


def emit_mesh(stage, path, mesh, transform):
    """Add a trimesh shape to USD stage at `path` with `transform` (4x4)."""
    prim = UsdGeom.Mesh.Define(stage, path)
    verts = np.asarray(mesh.vertices)
    # Apply transform
    h = np.hstack([verts, np.ones((len(verts), 1))])
    verts_t = (transform @ h.T).T[:, :3]
    prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts_t])
    prim.GetFaceVertexCountsAttr().Set([3] * len(mesh.faces))
    prim.GetFaceVertexIndicesAttr().Set(mesh.faces.flatten().tolist())
    # Default to white surface
    prim.CreateDisplayColorAttr().Set([(0.95, 0.95, 0.95)])
    return prim


def trans(x, y, z):
    m = np.eye(4); m[:3, 3] = (x, y, z); return m


def rot_x(angle):
    m = np.eye(4)
    c, s = math.cos(angle), math.sin(angle)
    m[1, 1] = c; m[1, 2] = -s
    m[2, 1] = s; m[2, 2] = c
    return m


def chain(*matrices):
    out = np.eye(4)
    for m in matrices: out = out @ m
    return out


def build_seated(stage, root_path):
    """Seated character: torso vertical, legs L-shaped, head on top."""
    base = chain(trans(0, 0.45, 0))  # pelvis at Y=0.45 (chair seat)
    # Torso — vertical box centered on Y=0.45+torso_h/2
    emit_mesh(stage, f"{root_path}/Torso", box_mesh(SEG["torso_w"], SEG["torso_h"], SEG["torso_d"]),
               chain(trans(0, 0.45 + SEG["torso_h"]/2, 0)))
    # Head — sphere above torso
    head_y = 0.45 + SEG["torso_h"] + SEG["neck_l"] + SEG["head_radius"]
    emit_mesh(stage, f"{root_path}/Head", sphere_mesh(SEG["head_radius"]),
               trans(0, head_y, 0))
    # Neck — small cylinder
    emit_mesh(stage, f"{root_path}/Neck",
               cylinder_mesh(SEG["head_radius"]*0.4, SEG["neck_l"]),
               trans(0, 0.45 + SEG["torso_h"] + SEG["neck_l"]/2, 0))

    # Arms — hanging down at sides
    shoulder_y = 0.45 + SEG["torso_h"] - 0.05
    for side, sign in [("R", -1), ("L", 1)]:
        sx = sign * (SEG["torso_w"]/2 + 0.05)
        emit_mesh(stage, f"{root_path}/UpperArm_{side}",
                   cylinder_mesh(SEG["upper_arm_r"], SEG["upper_arm_l"]),
                   trans(sx, shoulder_y - SEG["upper_arm_l"]/2, 0))
        emit_mesh(stage, f"{root_path}/LowerArm_{side}",
                   cylinder_mesh(SEG["lower_arm_r"], SEG["lower_arm_l"]),
                   trans(sx, shoulder_y - SEG["upper_arm_l"] - SEG["lower_arm_l"]/2, 0.05))

    # Legs — thigh horizontal forward, shin vertical down
    hip_y = 0.45  # pelvis level
    for side, sign in [("R", -1), ("L", 1)]:
        sx = sign * 0.10
        # Thigh: lay horizontal, forward along Z
        thigh_t = chain(trans(sx, hip_y, SEG["thigh_l"]/2), rot_x(math.radians(90)))
        emit_mesh(stage, f"{root_path}/Thigh_{side}",
                   cylinder_mesh(SEG["thigh_r"], SEG["thigh_l"]),
                   thigh_t)
        # Shin: vertical at end of thigh
        shin_y = hip_y - SEG["shin_l"]/2
        emit_mesh(stage, f"{root_path}/Shin_{side}",
                   cylinder_mesh(SEG["shin_r"], SEG["shin_l"]),
                   trans(sx, shin_y, SEG["thigh_l"]))
        # Foot
        emit_mesh(stage, f"{root_path}/Foot_{side}",
                   box_mesh(SEG["foot_w"], SEG["foot_h"], SEG["foot_d"]),
                   trans(sx, hip_y - SEG["shin_l"] + SEG["foot_h"]/2,
                          SEG["thigh_l"] + SEG["foot_d"]/2 - 0.04))


def build_standing(stage, root_path):
    """Standing character: all segments vertical."""
    pelvis_y = 0.95  # pelvis at typical human walking height
    emit_mesh(stage, f"{root_path}/Torso",
               box_mesh(SEG["torso_w"], SEG["torso_h"], SEG["torso_d"]),
               trans(0, pelvis_y + SEG["torso_h"]/2, 0))
    head_y = pelvis_y + SEG["torso_h"] + SEG["neck_l"] + SEG["head_radius"]
    emit_mesh(stage, f"{root_path}/Head", sphere_mesh(SEG["head_radius"]),
               trans(0, head_y, 0))
    emit_mesh(stage, f"{root_path}/Neck",
               cylinder_mesh(SEG["head_radius"]*0.4, SEG["neck_l"]),
               trans(0, pelvis_y + SEG["torso_h"] + SEG["neck_l"]/2, 0))
    shoulder_y = pelvis_y + SEG["torso_h"] - 0.05
    for side, sign in [("R", -1), ("L", 1)]:
        sx = sign * (SEG["torso_w"]/2 + 0.05)
        emit_mesh(stage, f"{root_path}/UpperArm_{side}",
                   cylinder_mesh(SEG["upper_arm_r"], SEG["upper_arm_l"]),
                   trans(sx, shoulder_y - SEG["upper_arm_l"]/2, 0))
        emit_mesh(stage, f"{root_path}/LowerArm_{side}",
                   cylinder_mesh(SEG["lower_arm_r"], SEG["lower_arm_l"]),
                   trans(sx, shoulder_y - SEG["upper_arm_l"] - SEG["lower_arm_l"]/2, 0))
    for side, sign in [("R", -1), ("L", 1)]:
        sx = sign * 0.10
        emit_mesh(stage, f"{root_path}/Thigh_{side}",
                   cylinder_mesh(SEG["thigh_r"], SEG["thigh_l"]),
                   trans(sx, pelvis_y - SEG["thigh_l"]/2, 0))
        emit_mesh(stage, f"{root_path}/Shin_{side}",
                   cylinder_mesh(SEG["shin_r"], SEG["shin_l"]),
                   trans(sx, pelvis_y - SEG["thigh_l"] - SEG["shin_l"]/2, 0))
        emit_mesh(stage, f"{root_path}/Foot_{side}",
                   box_mesh(SEG["foot_w"], SEG["foot_h"], SEG["foot_d"]),
                   trans(sx, pelvis_y - SEG["thigh_l"] - SEG["shin_l"] + SEG["foot_h"]/2,
                          0.05))


def build(out_path, pose="seated"):
    stage = Usd.Stage.CreateNew(str(out_path))
    stage.SetMetadata("upAxis", "Y")
    root = UsdGeom.Xform.Define(stage, "/Character")
    stage.SetDefaultPrim(root.GetPrim())
    if pose == "seated":
        build_seated(stage, "/Character")
    else:
        build_standing(stage, "/Character")
    stage.GetRootLayer().Save()
    print(f"OK: {out_path}  (pose={pose})")


if __name__ == "__main__":
    pose = sys.argv[2] if len(sys.argv) > 2 else "seated"
    build(OUT, pose)

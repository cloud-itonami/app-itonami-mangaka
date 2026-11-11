"""High-fidelity character mannequin v2 — adds face detail for SDXL.

Improvements over v1:
  - Head: bigger sphere + nose bump + 2 eye bumps + chin taper
  - Neck: narrower cylinder + collar shoulder shaping
  - Torso: tapered shoulders (wider top, narrower waist)
  - Hands: small spheres at end of arms
  - Feet: foot boxes
  - Hair: rough hair shape (large cap above head)

Goal: give SDXL more silhouette signal so it recognizes the figure
as a human character, not abstract geometry.

Output: data/.../usd/character-mannequin-{seated,standing}-v2.usda
"""
import sys, math
from pathlib import Path
from pxr import Usd, UsdGeom, Sdf, Gf
import trimesh
import numpy as np


def cyl(r, h, segments=12):
    return trimesh.creation.cylinder(radius=r, height=h, sections=segments)

def box(w, h, d):
    return trimesh.creation.box(extents=(w, h, d))

def sph(r, sub=2):
    return trimesh.creation.icosphere(radius=r, subdivisions=sub)


def emit(stage, path, mesh, transform):
    prim = UsdGeom.Mesh.Define(stage, path)
    verts = np.asarray(mesh.vertices)
    h = np.hstack([verts, np.ones((len(verts), 1))])
    verts_t = (transform @ h.T).T[:, :3]
    prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts_t])
    prim.GetFaceVertexCountsAttr().Set([3] * len(mesh.faces))
    prim.GetFaceVertexIndicesAttr().Set(mesh.faces.flatten().tolist())
    prim.CreateDisplayColorAttr().Set([(0.95, 0.95, 0.95)])
    return prim


def trans(x, y, z):
    m = np.eye(4); m[:3, 3] = (x, y, z); return m


def rot_x(angle):
    m = np.eye(4)
    c, s = math.cos(angle), math.sin(angle)
    m[1, 1] = c; m[1, 2] = -s; m[2, 1] = s; m[2, 2] = c
    return m


def chain(*matrices):
    out = np.eye(4)
    for m in matrices: out = out @ m
    return out


def add_humanoid(stage, root_path, pelvis_y=0.95, facing_forward=True):
    """Add anatomical humanoid centered around pelvis at given Y."""
    # Hair (above head, big floppy)
    head_y = pelvis_y + 0.85
    hair = sph(0.14, sub=2)
    emit(stage, f"{root_path}/Hair", hair, trans(0, head_y + 0.08, -0.03))
    # Head — larger sphere
    emit(stage, f"{root_path}/Head", sph(0.11, sub=2), trans(0, head_y, 0))
    # Nose — small triangular box bump
    emit(stage, f"{root_path}/Nose", box(0.025, 0.035, 0.05),
          trans(0, head_y - 0.01, 0.10))
    # 2 eye sockets (dark, slightly recessed)
    emit(stage, f"{root_path}/Eye_L", sph(0.025),
          trans(-0.045, head_y + 0.025, 0.08))
    emit(stage, f"{root_path}/Eye_R", sph(0.025),
          trans( 0.045, head_y + 0.025, 0.08))
    # Chin — tiny cone below head
    emit(stage, f"{root_path}/Chin", box(0.05, 0.04, 0.03),
          trans(0, head_y - 0.10, 0.05))
    # Neck — narrower than head
    emit(stage, f"{root_path}/Neck", cyl(0.045, 0.10),
          trans(0, head_y - 0.15, 0))

    # Torso — slight shoulder taper
    torso_top_y = head_y - 0.20
    torso_bot_y = pelvis_y
    # Use a box for now (USD-friendly); shoulders implied by separate shoulder caps
    emit(stage, f"{root_path}/Torso", box(0.30, torso_top_y - torso_bot_y, 0.18),
          trans(0, (torso_top_y + torso_bot_y) / 2, 0))
    # Shoulder caps (slight rounded edges)
    emit(stage, f"{root_path}/Shoulder_L", sph(0.08, sub=2),
          trans(-0.17, torso_top_y - 0.04, 0))
    emit(stage, f"{root_path}/Shoulder_R", sph(0.08, sub=2),
          trans( 0.17, torso_top_y - 0.04, 0))
    # Chest plate (collar suggestion)
    emit(stage, f"{root_path}/Collar", box(0.20, 0.04, 0.08),
          trans(0, torso_top_y - 0.04, 0.07))

    # Arms — upper + lower + hand
    arm_top_y = torso_top_y - 0.08
    for side, sign in [("L", 1), ("R", -1)]:
        sx = sign * 0.20
        upper = cyl(0.04, 0.28)
        emit(stage, f"{root_path}/UpperArm_{side}", upper, trans(sx, arm_top_y - 0.14, 0))
        lower = cyl(0.035, 0.25)
        emit(stage, f"{root_path}/LowerArm_{side}", lower, trans(sx, arm_top_y - 0.42, 0))
        # Hand sphere
        emit(stage, f"{root_path}/Hand_{side}", sph(0.05),
              trans(sx, arm_top_y - 0.58, 0.02))

    # Legs — pelvis to ankle + foot
    pelvis_w = 0.18
    for side, sign in [("L", 1), ("R", -1)]:
        sx = sign * (pelvis_w / 2 - 0.02)
        thigh = cyl(0.055, 0.4)
        emit(stage, f"{root_path}/Thigh_{side}", thigh, trans(sx, pelvis_y - 0.22, 0))
        shin = cyl(0.045, 0.38)
        emit(stage, f"{root_path}/Shin_{side}", shin, trans(sx, pelvis_y - 0.62, 0))
        # Foot
        emit(stage, f"{root_path}/Foot_{side}", box(0.10, 0.05, 0.22),
              trans(sx, pelvis_y - 0.84, 0.07))


def build(out_path, pose="standing"):
    stage = Usd.Stage.CreateNew(str(out_path))
    stage.SetMetadata("upAxis", "Y")
    root = UsdGeom.Xform.Define(stage, "/Character")
    stage.SetDefaultPrim(root.GetPrim())

    if pose == "seated":
        # Pelvis at chair height (0.45)
        # Torso vertical from there, but legs split into thigh (forward
        # horizontal) + shin (vertical down). Use the standing build with
        # custom leg adjustments.
        add_humanoid(stage, "/Character", pelvis_y=0.45, facing_forward=True)
        # Re-place legs for seated pose: thighs forward, shins down
        # Override the thighs to be horizontal
        for side, sign in [("L", 1), ("R", -1)]:
            sx = sign * 0.08
            # Remove standing leg parts first (re-define overrides them)
            # Thigh — horizontal forward
            thigh_t = chain(trans(sx, 0.45, 0.20), rot_x(math.radians(90)))
            emit(stage, f"/Character/Thigh_{side}", cyl(0.055, 0.40), thigh_t)
            # Shin — vertical at front of thigh
            emit(stage, f"/Character/Shin_{side}", cyl(0.045, 0.38),
                  trans(sx, 0.27, 0.40))
            emit(stage, f"/Character/Foot_{side}", box(0.10, 0.05, 0.22),
                  trans(sx, 0.05, 0.50))
    else:
        add_humanoid(stage, "/Character", pelvis_y=0.95, facing_forward=True)

    stage.GetRootLayer().Save()
    n = sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))
    print(f"OK: {out_path}  (pose={pose}, {n} meshes)")


if __name__ == "__main__":
    base = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/usd")
    # Also write to /tmp for live testing
    build(Path("/tmp/character-mannequin-seated.usda"), "seated")
    build(Path("/tmp/character-mannequin-standing.usda"), "standing")
    build(base / "character-mannequin-seated.usda", "seated")
    build(base / "character-mannequin-standing.usda", "standing")

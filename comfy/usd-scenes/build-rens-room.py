"""Ren's room — cyberpunk hacker den with monitor wall + research board.

Layout (4m × 5m × 2.7m):
  - Floor / ceiling / 4 walls
  - Wall-mounted monitor array on north wall (4×2 = 8 monitors)
  - Research wall on south wall (papers + photos pinned, abstracted as panels)
  - Computer desk along east wall with multiple stacked PC towers + keyboard
  - Chair (gaming-style)
  - Floor lamp / desk lamp
  - Door on west wall

5 cameras for typical Ren beats:
  cyberden_wide      back-of-room establishing
  monitor_wall       facing the 8-monitor array
  ren_at_desk        over-shoulder of seated Ren
  research_board     facing the south wall pinboard
  door_view          from doorway
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageFilter
from pxr import Usd, UsdGeom, Gf

OUT_DIR = Path("/tmp/arc01-scenes")
OUT_DIR.mkdir(exist_ok=True)

W, D, H = 4.0, 5.0, 2.7


def build():
    m = []
    floor = trimesh.creation.box(extents=[W, 0.01, D]); floor.apply_translation([W/2, 0, D/2])
    m.append(("floor", floor))
    ceil = trimesh.creation.box(extents=[W, 0.01, D]); ceil.apply_translation([W/2, H, D/2])
    m.append(("ceiling", ceil))
    for n, x, y, z, ext in [
        ("wall_n", W/2, H/2, 0, [W, H, 0.1]),
        ("wall_s", W/2, H/2, D, [W, H, 0.1]),
        ("wall_e", W, H/2, D/2, [0.1, H, D]),
        ("wall_w", 0, H/2, D/2, [0.1, H, D]),
    ]:
        b = trimesh.creation.box(extents=ext); b.apply_translation([x, y, z])
        m.append((n, b))

    # 4×2 monitor wall on north wall (z=0+small)
    for r in range(2):
        for c in range(4):
            mon = trimesh.creation.box(extents=[0.7, 0.45, 0.05])
            mon.apply_translation([0.8 + c * 0.85, 1.0 + r * 0.55, 0.08])
            m.append((f"monitor_{r}_{c}", mon))

    # Research pinboard on south wall — 3×2 panels
    for r in range(2):
        for c in range(3):
            pan = trimesh.creation.box(extents=[0.55, 0.4, 0.03])
            pan.apply_translation([0.7 + c * 0.95, 1.0 + r * 0.55, D - 0.06])
            m.append((f"pin_{r}_{c}", pan))

    # Desk along east wall
    desk = trimesh.creation.box(extents=[0.7, 0.05, 2.2]); desk.apply_translation([W - 0.4, 0.75, 2.5])
    m.append(("desk_top", desk))
    for i, dz in enumerate([1.4, 3.6]):
        leg = trimesh.creation.box(extents=[0.05, 0.75, 0.05])
        leg.apply_translation([W - 0.7, 0.375, dz]); m.append((f"desk_leg_a{i}", leg))
        leg = trimesh.creation.box(extents=[0.05, 0.75, 0.05])
        leg.apply_translation([W - 0.1, 0.375, dz]); m.append((f"desk_leg_b{i}", leg))
    # 3 PC towers under desk
    for i in range(3):
        pc = trimesh.creation.box(extents=[0.20, 0.45, 0.40])
        pc.apply_translation([W - 0.3, 0.22, 1.8 + i * 0.5])
        m.append((f"pc_tower_{i}", pc))
    # Keyboard on desk
    kb = trimesh.creation.box(extents=[0.45, 0.03, 0.15]); kb.apply_translation([W - 0.4, 0.785, 2.0])
    m.append(("keyboard", kb))
    # Two monitors on desk
    for i in range(2):
        mon = trimesh.creation.box(extents=[0.05, 0.4, 0.6])
        mon.apply_translation([W - 0.08, 1.05, 2.0 + i * 0.7])
        m.append((f"desk_monitor_{i}", mon))

    # Gaming chair
    seat = trimesh.creation.box(extents=[0.55, 0.05, 0.55]); seat.apply_translation([W - 1.1, 0.45, 2.5])
    m.append(("chair_seat", seat))
    back = trimesh.creation.box(extents=[0.55, 0.8, 0.05]); back.apply_translation([W - 1.1, 0.85, 2.75])
    m.append(("chair_back", back))
    armL = trimesh.creation.box(extents=[0.05, 0.2, 0.5]); armL.apply_translation([W - 1.35, 0.6, 2.5])
    m.append(("chair_armL", armL))
    armR = trimesh.creation.box(extents=[0.05, 0.2, 0.5]); armR.apply_translation([W - 0.85, 0.6, 2.5])
    m.append(("chair_armR", armR))

    # Floor lamp in corner
    lamp_stem = trimesh.creation.cylinder(radius=0.03, height=1.6, sections=8)
    lamp_stem.apply_translation([0.3, 0.8, D - 0.3])
    m.append(("lamp_stem", lamp_stem))
    lamp_head = trimesh.creation.cone(radius=0.18, height=0.25, sections=12)
    lamp_head.apply_translation([0.3, 1.7, D - 0.3])
    m.append(("lamp_head", lamp_head))

    # Door (west wall)
    door = trimesh.creation.box(extents=[0.05, 2.0, 0.85]); door.apply_translation([0.08, 1.0, 0.8])
    m.append(("door", door))
    return m


def write_usd(meshes, path):
    s = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(s, "/RensRoom")
    s.SetDefaultPrim(root.GetPrim())
    s.SetMetadata("upAxis", "Y")
    for n, mesh in meshes:
        p = UsdGeom.Mesh.Define(s, f"/RensRoom/{n.replace('-', '_')}")
        p.GetPointsAttr().Set([Gf.Vec3f(*v) for v in mesh.vertices.tolist()])
        p.GetFaceVertexIndicesAttr().Set(mesh.faces.flatten().tolist())
        p.GetFaceVertexCountsAttr().Set([3] * len(mesh.faces))
    s.GetRootLayer().Save()


CAMERAS = {
    "cyberden_wide":   ((W/2, 1.6, D - 0.6), (W/2, 1.2, 0.5), 70.0),
    "monitor_wall":    ((W/2, 1.4, 2.5),     (W/2, 1.3, 0.2), 60.0),
    "ren_at_desk":     ((W - 1.6, 1.5, 2.1), (W - 0.2, 0.9, 2.5), 50.0),
    "research_board":  ((W/2, 1.5, 1.0),     (W/2, 1.3, D - 0.5), 60.0),
    "door_view":       ((0.4, 1.6, 1.0),     (W * 0.75, 1.3, D - 1.0), 65.0),
}


def render_depth(sm, co, ct, fov, W2=608, H2=416):
    o = np.array(co); t = np.array(ct)
    f = t - o; f /= np.linalg.norm(f) + 1e-9
    r = np.cross(f, [0, 1, 0]); r /= np.linalg.norm(r) + 1e-9
    u = np.cross(r, f)
    fov = np.radians(fov)
    hh = np.tan(fov / 2); hw = hh * (W2 / H2)
    xs = np.linspace(-hw, hw, W2); ys = np.linspace(hh, -hh, H2)
    gx, gy = np.meshgrid(xs, ys)
    dirs = (f[None, None, :] + gx[..., None] * r[None, None, :] + gy[..., None] * u[None, None, :])
    dirs /= np.linalg.norm(dirs, axis=2, keepdims=True) + 1e-9
    df = dirs.reshape(-1, 3); orig = np.tile(o, (df.shape[0], 1))
    print(f"  casting {len(df)} rays", flush=True)
    hits, idx, _ = sm.ray.intersects_location(ray_origins=orig, ray_directions=df, multiple_hits=False)
    depth = np.full(df.shape[0], np.inf)
    if len(hits):
        d = np.linalg.norm(hits - orig[idx], axis=1)
        np.minimum.at(depth, idx, d)
    depth = depth.reshape(H2, W2)
    fin = depth[np.isfinite(depth)]
    far = float(np.percentile(fin, 99)) if len(fin) else 12.0
    depth = np.where(np.isfinite(depth), depth, far)
    near = float(depth.min())
    return ((far - depth) / max(1e-6, far - near) * 255).clip(0, 255).astype(np.uint8)


def canny(arr):
    im = Image.fromarray(arr).filter(ImageFilter.FIND_EDGES)
    a = np.array(im)
    return Image.fromarray(((a > 30).astype(np.uint8) * 255))


def main():
    print("=== building Ren's room ===", flush=True)
    meshes = build()
    print(f"  {len(meshes)} primitives", flush=True)
    write_usd(meshes, OUT_DIR / "rens-room.usda")
    scene = trimesh.util.concatenate([m for _, m in meshes])
    print(f"  combined: {len(scene.vertices)} verts, {len(scene.faces)} faces", flush=True)
    for cn, (o, t, fov) in CAMERAS.items():
        print(f"\n=== {cn} ===", flush=True)
        d = render_depth(scene, o, t, fov)
        im = Image.fromarray(d).resize((1216, 832), Image.NEAREST)
        im.save(OUT_DIR / f"rens-room-{cn}-depth.png")
        canny(np.array(im)).save(OUT_DIR / f"rens-room-{cn}-canny.png")
        print(f"  saved", flush=True)


if __name__ == "__main__":
    sys.exit(main() or 0)

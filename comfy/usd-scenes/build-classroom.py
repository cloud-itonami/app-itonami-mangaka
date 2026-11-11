"""Build a Japanese high-school classroom as a USD scene + render
multi-camera depth/canny passes.

Layout (8m × 9m × 3m room, ~30 student desks in 6 columns × 5 rows):

  - Floor / ceiling / 4 walls
  - Front wall: blackboard + teacher's podium + teacher's desk
  - Back wall: bookshelf + cleaning lockers
  - Side wall (north): row of windows with sills (4 windows)
  - Side wall (south): door + bulletin board
  - 30 student desks in 6 × 5 grid (each 0.6 × 0.45 × 0.7 m)
  - 30 student chairs (0.4 × 0.4 × 0.85 m)

5 camera angles:
  establishing       wide back-of-room view
  student_pov        seated in a back desk, looking at the blackboard
  teacher_view       from teacher's podium looking out at students
  hallway_door       from doorway looking in
  window_side        from window looking across the room

All cameras at human eye level (~1.5 m).
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageFilter
from pxr import Usd, UsdGeom, Gf

OUT_DIR = Path("/tmp/arc01-scenes")
OUT_DIR.mkdir(exist_ok=True, parents=True)

ROOM_W = 8.0    # x — width (east-west)
ROOM_D = 9.0    # z — depth (front-back, blackboard at z=0)
ROOM_H = 3.0    # y

DESK_W = 0.60
DESK_D = 0.45
DESK_H = 0.70
CHAIR_SEAT_H = 0.45
CHAIR_BACK_H = 0.85


def build_meshes():
    m: list[tuple[str, trimesh.Trimesh]] = []

    # Floor / ceiling
    floor = trimesh.creation.box(extents=[ROOM_W, 0.01, ROOM_D])
    floor.apply_translation([ROOM_W/2, 0, ROOM_D/2])
    m.append(("floor", floor))
    ceil = trimesh.creation.box(extents=[ROOM_W, 0.01, ROOM_D])
    ceil.apply_translation([ROOM_W/2, ROOM_H, ROOM_D/2])
    m.append(("ceiling", ceil))

    # 4 walls
    wn = trimesh.creation.box(extents=[ROOM_W, ROOM_H, 0.1])
    wn.apply_translation([ROOM_W/2, ROOM_H/2, 0])
    m.append(("wall_front", wn))     # blackboard wall, z=0
    ws = trimesh.creation.box(extents=[ROOM_W, ROOM_H, 0.1])
    ws.apply_translation([ROOM_W/2, ROOM_H/2, ROOM_D])
    m.append(("wall_back", ws))
    we = trimesh.creation.box(extents=[0.1, ROOM_H, ROOM_D])
    we.apply_translation([ROOM_W, ROOM_H/2, ROOM_D/2])
    m.append(("wall_east", we))      # window side
    ww = trimesh.creation.box(extents=[0.1, ROOM_H, ROOM_D])
    ww.apply_translation([0, ROOM_H/2, ROOM_D/2])
    m.append(("wall_west", ww))      # hallway side

    # Blackboard (front wall, z just in front of wall)
    bb = trimesh.creation.box(extents=[5.0, 1.4, 0.05])
    bb.apply_translation([ROOM_W/2, 1.6, 0.08])
    m.append(("blackboard", bb))

    # Teacher's podium (front-center, z = 1.5 from front)
    podium = trimesh.creation.box(extents=[1.0, 1.1, 0.5])
    podium.apply_translation([ROOM_W/2, 0.55, 1.0])
    m.append(("podium", podium))

    # Teacher's desk (right of podium)
    tdesk = trimesh.creation.box(extents=[1.6, 0.05, 0.7])
    tdesk.apply_translation([ROOM_W - 1.4, 0.78, 1.2])
    m.append(("teacher_desk", tdesk))
    for i, (dx, dz) in enumerate([(-0.75, -0.30), (-0.75, 0.30), (0.75, -0.30), (0.75, 0.30)]):
        leg = trimesh.creation.box(extents=[0.05, 0.78, 0.05])
        leg.apply_translation([ROOM_W - 1.4 + dx, 0.39, 1.2 + dz])
        m.append((f"teacher_desk_leg_{i}", leg))

    # 6 windows on the east wall (4 panes per gap), with sills
    for i in range(4):
        z = 2.0 + i * 1.5
        # window
        w = trimesh.creation.box(extents=[0.05, 1.4, 1.0])
        w.apply_translation([ROOM_W - 0.08, 1.6, z])
        m.append((f"window_{i}", w))
        # sill
        sill = trimesh.creation.box(extents=[0.20, 0.05, 1.1])
        sill.apply_translation([ROOM_W - 0.15, 0.85, z])
        m.append((f"window_sill_{i}", sill))

    # Door + frame on west wall, near front
    door = trimesh.creation.box(extents=[0.05, 2.0, 0.9])
    door.apply_translation([0.08, 1.0, 1.5])
    m.append(("door", door))

    # Student desks — 4 columns × 4 rows = 16 desks (lighter than 6×5).
    # ControlNet only needs to "see" a classroom pattern, not 30 desks.
    cols = 4
    rows = 4
    col_spacing = (ROOM_W - 1.6) / cols   # leave 0.8m margin each side
    row_spacing = 1.1
    start_x = 0.8 + col_spacing / 2
    start_z = 3.0
    for r in range(rows):
        for c in range(cols):
            cx = start_x + c * col_spacing
            cz = start_z + r * row_spacing
            # desk top
            d = trimesh.creation.box(extents=[DESK_W, 0.04, DESK_D])
            d.apply_translation([cx, DESK_H, cz])
            m.append((f"desk_r{r}c{c}_top", d))
            # 4 desk legs
            for li, (lx, lz) in enumerate([
                (-DESK_W/2 + 0.03, -DESK_D/2 + 0.03),
                ( DESK_W/2 - 0.03, -DESK_D/2 + 0.03),
                (-DESK_W/2 + 0.03,  DESK_D/2 - 0.03),
                ( DESK_W/2 - 0.03,  DESK_D/2 - 0.03),
            ]):
                leg = trimesh.creation.box(extents=[0.03, DESK_H, 0.03])
                leg.apply_translation([cx + lx, DESK_H/2, cz + lz])
                m.append((f"desk_r{r}c{c}_leg{li}", leg))
            # chair behind the desk (further from front)
            chx = cx
            chz = cz + 0.40
            seat = trimesh.creation.box(extents=[0.40, 0.04, 0.40])
            seat.apply_translation([chx, CHAIR_SEAT_H, chz])
            m.append((f"chair_r{r}c{c}_seat", seat))
            back = trimesh.creation.box(extents=[0.40, CHAIR_BACK_H - CHAIR_SEAT_H, 0.05])
            back.apply_translation([chx, (CHAIR_SEAT_H + CHAIR_BACK_H) / 2, chz + 0.20])
            m.append((f"chair_r{r}c{c}_back", back))

    # Bookshelf on back wall
    shelf = trimesh.creation.box(extents=[3.0, 2.0, 0.4])
    shelf.apply_translation([ROOM_W/2, 1.0, ROOM_D - 0.25])
    m.append(("bookshelf", shelf))

    return m


def write_usd(meshes, path: Path):
    stage = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(stage, "/Classroom")
    stage.SetDefaultPrim(root.GetPrim())
    stage.SetMetadata("upAxis", "Y")
    for name, mesh in meshes:
        prim = UsdGeom.Mesh.Define(stage, f"/Classroom/{name.replace('-', '_')}")
        verts = [Gf.Vec3f(*v) for v in mesh.vertices.tolist()]
        prim.GetPointsAttr().Set(verts)
        idx = mesh.faces.flatten().tolist()
        prim.GetFaceVertexIndicesAttr().Set(idx)
        prim.GetFaceVertexCountsAttr().Set([3] * len(mesh.faces))
    stage.GetRootLayer().Save()
    print(f"  USD saved: {path} ({path.stat().st_size//1024} KB)")


CAMERAS = {
    # eye level ~1.5 m, looking at blackboard from back
    "establishing": ((ROOM_W/2, 1.5, ROOM_D - 1.5), (ROOM_W/2, 1.5, 0.5), 65.0),
    # seated in middle desk, eye at 1.2 m, looking forward
    "student_pov":  ((ROOM_W/2, 1.2, 5.5), (ROOM_W/2, 1.5, 0.5), 55.0),
    # from teacher's podium looking back at the class
    "teacher_view": ((ROOM_W/2, 1.6, 1.0), (ROOM_W/2, 1.4, ROOM_D - 1.0), 70.0),
    # from hallway door looking in
    "hallway_door": ((0.4, 1.6, 1.7), (ROOM_W * 0.7, 1.4, ROOM_D / 2), 65.0),
    # from window looking across
    "window_side":  ((ROOM_W - 0.4, 1.5, 4.5), (1.0, 1.5, 4.5), 70.0),
}


def render_depth(scene_mesh, cam_origin, cam_target, fov_deg, W=608, H=416):
    o = np.array(cam_origin, dtype=np.float64)
    t = np.array(cam_target, dtype=np.float64)
    forward = t - o; forward /= np.linalg.norm(forward) + 1e-9
    world_up = np.array([0, 1, 0], dtype=np.float64)
    right = np.cross(forward, world_up); right /= np.linalg.norm(right) + 1e-9
    up = np.cross(right, forward)
    fov = np.radians(fov_deg)
    aspect = W / H
    half_h = np.tan(fov / 2)
    half_w = half_h * aspect
    xs = np.linspace(-half_w, half_w, W)
    ys = np.linspace(half_h, -half_h, H)
    gx, gy = np.meshgrid(xs, ys)
    dirs = (forward[None, None, :]
            + gx[..., None] * right[None, None, :]
            + gy[..., None] * up[None, None, :])
    dirs /= np.linalg.norm(dirs, axis=2, keepdims=True) + 1e-9
    df = dirs.reshape(-1, 3)
    origs = np.tile(o, (df.shape[0], 1))
    print(f"  casting {len(df)} rays...")
    hits, idx_ray, _ = scene_mesh.ray.intersects_location(
        ray_origins=origs, ray_directions=df, multiple_hits=False,
    )
    print(f"    hits: {len(hits)}")
    depth = np.full(df.shape[0], np.inf, dtype=np.float64)
    if len(hits):
        d = np.linalg.norm(hits - origs[idx_ray], axis=1)
        np.minimum.at(depth, idx_ray, d)
    depth = depth.reshape(H, W)
    finite = depth[np.isfinite(depth)]
    far = float(np.percentile(finite, 99)) if len(finite) else 15.0
    depth = np.where(np.isfinite(depth), depth, far)
    near = float(depth.min())
    norm = ((far - depth) / max(1e-6, far - near) * 255).clip(0, 255)
    return depth, norm.astype(np.uint8)


def make_canny(d):
    im = Image.fromarray(d)
    e = im.filter(ImageFilter.FIND_EDGES)
    arr = np.array(e)
    arr = (arr > 30).astype(np.uint8) * 255
    return Image.fromarray(arr)


def main():
    print("=== building classroom ===")
    meshes = build_meshes()
    print(f"  {len(meshes)} primitives")
    write_usd(meshes, OUT_DIR / "classroom.usda")
    scene = trimesh.util.concatenate([mm for _, mm in meshes])
    print(f"  combined: {len(scene.vertices)} verts, {len(scene.faces)} faces")
    for cam_name, (o, t, fov) in CAMERAS.items():
        print(f"\n=== {cam_name} ===", flush=True)
        _, du8 = render_depth(scene, o, t, fov)
        # Upscale to 1216x832 (nearest-neighbour) so ControlNet input is
        # standard SDXL bucket; the upscale preserves edges fine.
        im_d = Image.fromarray(du8).resize((1216, 832), Image.NEAREST)
        im_d.save(OUT_DIR / f"classroom-{cam_name}-depth.png")
        make_canny(np.array(im_d)).save(OUT_DIR / f"classroom-{cam_name}-canny.png")
        print(f"  saved", flush=True)


if __name__ == "__main__":
    sys.exit(main() or 0)

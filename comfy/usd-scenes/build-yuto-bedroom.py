"""Build Yuto's bedroom as a USD scene + render depth/canny via trimesh.

Pure Python, no Blender. Uses:
  - pxr.Usd (usd-core) for the scene file (.usda human-readable text)
  - trimesh for primitive geometry + raycasting depth
  - Pillow + numpy for image processing

Yuto's bedroom layout (rough Japanese teen):
  Room    4m W × 4m D × 2.5m H
  Floor   y=0
  Walls   north/east/south/west
  Window  on north wall (1.2m × 1.5m, sill 0.9m up)
  Bed     south wall, 2m × 1m × 0.4m
  Desk    east wall, 1.4m × 0.6m × 0.75m
  Chair   in front of desk
  Lamp    on desk corner, 0.15m radius × 0.4m H
  Smartphone on desk, 0.15m × 0.07m × 0.01m
  Notebook on desk

Camera: 5 fixed angles for the manga page beats:
  ESTABLISH_WIDE     wide-angle establishing shot
  YUTO_AT_DESK       over-the-shoulder of Yuto looking at phone
  PHONE_CLOSEUP      tight on the smartphone
  ROOM_OVERHEAD      slight high angle
  WINDOW_VIEW        from window looking in

Outputs (per camera):
  /tmp/arc01-scenes/yuto-bedroom-{cam}-depth.png   16-bit depth map
  /tmp/arc01-scenes/yuto-bedroom-{cam}-canny.png   8-bit canny edge
  /tmp/arc01-scenes/yuto-bedroom-{cam}-flat.png    flat-shaded view
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

ROOM_W = 4.0    # x
ROOM_D = 4.0    # z
ROOM_H = 2.5    # y


def build_meshes() -> list[tuple[str, trimesh.Trimesh]]:
    """Return list of (name, mesh) for all bedroom geometry."""
    meshes: list[tuple[str, trimesh.Trimesh]] = []

    # Floor
    floor = trimesh.creation.box(extents=[ROOM_W, 0.01, ROOM_D])
    floor.apply_translation([ROOM_W/2, 0, ROOM_D/2])
    meshes.append(("floor", floor))

    # Ceiling
    ceil = trimesh.creation.box(extents=[ROOM_W, 0.01, ROOM_D])
    ceil.apply_translation([ROOM_W/2, ROOM_H, ROOM_D/2])
    meshes.append(("ceiling", ceil))

    # 4 walls (north / south / east / west)
    wn = trimesh.creation.box(extents=[ROOM_W, ROOM_H, 0.1])
    wn.apply_translation([ROOM_W/2, ROOM_H/2, 0])
    meshes.append(("wall_n", wn))
    ws = trimesh.creation.box(extents=[ROOM_W, ROOM_H, 0.1])
    ws.apply_translation([ROOM_W/2, ROOM_H/2, ROOM_D])
    meshes.append(("wall_s", ws))
    we = trimesh.creation.box(extents=[0.1, ROOM_H, ROOM_D])
    we.apply_translation([ROOM_W, ROOM_H/2, ROOM_D/2])
    meshes.append(("wall_e", we))
    ww = trimesh.creation.box(extents=[0.1, ROOM_H, ROOM_D])
    ww.apply_translation([0, ROOM_H/2, ROOM_D/2])
    meshes.append(("wall_w", ww))

    # Window cutout on north wall — placed as a window-frame mesh
    # (we won't carve the wall; the depth diff is enough for ControlNet)
    win = trimesh.creation.box(extents=[1.2, 1.5, 0.05])
    win.apply_translation([ROOM_W/2 + 0.5, 0.9 + 0.75, 0.06])
    meshes.append(("window", win))

    # Bed (south wall, oriented x-long)
    bed = trimesh.creation.box(extents=[2.0, 0.4, 1.0])
    bed.apply_translation([1.0, 0.2, ROOM_D - 0.55])
    meshes.append(("bed", bed))
    pillow = trimesh.creation.box(extents=[0.6, 0.1, 0.4])
    pillow.apply_translation([0.3, 0.45, ROOM_D - 0.55])
    meshes.append(("pillow", pillow))
    blanket = trimesh.creation.box(extents=[1.4, 0.1, 0.9])
    blanket.apply_translation([1.3, 0.45, ROOM_D - 0.55])
    meshes.append(("blanket", blanket))

    # Desk (east wall, x-short, z-long facing the wall)
    desk = trimesh.creation.box(extents=[0.6, 0.05, 1.4])
    desk.apply_translation([ROOM_W - 0.4, 0.75, 2.0])
    meshes.append(("desk_top", desk))
    leg_a = trimesh.creation.box(extents=[0.05, 0.75, 0.05])
    leg_a.apply_translation([ROOM_W - 0.7, 0.375, 1.4])
    meshes.append(("desk_leg_a", leg_a))
    leg_b = trimesh.creation.box(extents=[0.05, 0.75, 0.05])
    leg_b.apply_translation([ROOM_W - 0.7, 0.375, 2.6])
    meshes.append(("desk_leg_b", leg_b))
    leg_c = trimesh.creation.box(extents=[0.05, 0.75, 0.05])
    leg_c.apply_translation([ROOM_W - 0.1, 0.375, 1.4])
    meshes.append(("desk_leg_c", leg_c))
    leg_d = trimesh.creation.box(extents=[0.05, 0.75, 0.05])
    leg_d.apply_translation([ROOM_W - 0.1, 0.375, 2.6])
    meshes.append(("desk_leg_d", leg_d))

    # Chair (in front of desk)
    chair_seat = trimesh.creation.box(extents=[0.5, 0.05, 0.5])
    chair_seat.apply_translation([ROOM_W - 1.1, 0.45, 2.0])
    meshes.append(("chair_seat", chair_seat))
    chair_back = trimesh.creation.box(extents=[0.5, 0.5, 0.05])
    chair_back.apply_translation([ROOM_W - 1.1, 0.7, 2.25])
    meshes.append(("chair_back", chair_back))

    # Lamp on desk corner
    lamp_base = trimesh.creation.cylinder(radius=0.07, height=0.05, sections=12)
    lamp_base.apply_translation([ROOM_W - 0.25, 0.80, 1.5])
    meshes.append(("lamp_base", lamp_base))
    lamp_arm = trimesh.creation.cylinder(radius=0.02, height=0.4, sections=8)
    lamp_arm.apply_translation([ROOM_W - 0.25, 1.0, 1.5])
    meshes.append(("lamp_arm", lamp_arm))
    lamp_shade = trimesh.creation.cone(radius=0.10, height=0.18, sections=12)
    lamp_shade.apply_translation([ROOM_W - 0.25, 1.25, 1.5])
    meshes.append(("lamp_shade", lamp_shade))

    # Smartphone on desk
    phone = trimesh.creation.box(extents=[0.07, 0.01, 0.15])
    phone.apply_translation([ROOM_W - 0.4, 0.785, 2.1])
    meshes.append(("phone", phone))

    # Notebook on desk
    nb = trimesh.creation.box(extents=[0.21, 0.02, 0.3])
    nb.apply_translation([ROOM_W - 0.35, 0.785, 1.7])
    meshes.append(("notebook", nb))

    return meshes


def write_usd(meshes, path: Path):
    """Write the scene as a USD .usda file."""
    stage = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(stage, "/Bedroom")
    stage.SetDefaultPrim(root.GetPrim())
    stage.SetMetadata("upAxis", "Y")
    stage.SetTimeCodesPerSecond(24)
    for name, mesh in meshes:
        prim = UsdGeom.Mesh.Define(stage, f"/Bedroom/{name}")
        # Convert trimesh vertices + faces to USD attrs
        verts = [Gf.Vec3f(*v) for v in mesh.vertices.tolist()]
        prim.GetPointsAttr().Set(verts)
        # Face vertex indices (triangles only) — flat list
        idx = mesh.faces.flatten().tolist()
        prim.GetFaceVertexIndicesAttr().Set(idx)
        # Face vertex counts (3 per face)
        prim.GetFaceVertexCountsAttr().Set([3] * len(mesh.faces))
    stage.GetRootLayer().Save()
    print(f"  USD saved: {path} ({path.stat().st_size//1024} KB)")


# Camera definitions: (origin xyz, target xyz, fov_deg, near/far)
CAMERAS = {
    "establish_wide": ((0.5, 1.6, 0.5), (ROOM_W/2, 0.7, ROOM_D/2), 70.0),
    "yuto_at_desk":   ((1.0, 1.5, 1.3), (ROOM_W - 0.3, 0.85, 2.1), 50.0),
    "phone_closeup":  ((ROOM_W - 0.6, 1.0, 2.4), (ROOM_W - 0.4, 0.785, 2.1), 35.0),
    "room_overhead":  ((ROOM_W/2 + 0.5, 2.3, ROOM_D/2 - 0.5), (ROOM_W/2, 0.5, ROOM_D/2), 70.0),
    "window_view":    ((ROOM_W/2 + 0.5, 1.4, 0.5), (ROOM_W/2, 1.0, ROOM_D - 1.0), 60.0),
}


def render_depth(scene_mesh, cam_origin, cam_target, fov_deg, W=1216, H=832):
    """Cast rays per pixel, compute depth via trimesh.ray.contains_points.
    Returns: depth (H,W) float32, depth_normalized (H,W) uint8."""
    o = np.array(cam_origin, dtype=np.float64)
    t = np.array(cam_target, dtype=np.float64)
    forward = t - o
    forward /= np.linalg.norm(forward) + 1e-9
    world_up = np.array([0, 1, 0], dtype=np.float64)
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right) + 1e-9
    up = np.cross(right, forward)

    fov = np.radians(fov_deg)
    aspect = W / H
    half_h = np.tan(fov / 2)
    half_w = half_h * aspect

    # Per-pixel ray dirs (uniform sampling at z=1 plane in camera frame)
    xs = np.linspace(-half_w, half_w, W)
    ys = np.linspace(half_h, -half_h, H)
    gx, gy = np.meshgrid(xs, ys)
    dirs = (forward[None, None, :] +
            gx[..., None] * right[None, None, :] +
            gy[..., None] * up[None, None, :])
    dirs /= np.linalg.norm(dirs, axis=2, keepdims=True) + 1e-9
    dirs_flat = dirs.reshape(-1, 3)
    origins = np.tile(o, (dirs_flat.shape[0], 1))

    # Trimesh ray intersect — returns first hit per ray
    print(f"  casting {len(dirs_flat)} rays...")
    hits, idx_ray, _ = scene_mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=dirs_flat, multiple_hits=False,
    )
    print(f"    hits: {len(hits)}")

    # Build depth buffer
    depth = np.full(dirs_flat.shape[0], np.inf, dtype=np.float64)
    if len(hits):
        d = np.linalg.norm(hits - origins[idx_ray], axis=1)
        np.minimum.at(depth, idx_ray, d)
    depth = depth.reshape(H, W)

    # Replace inf with the max finite depth (background distance)
    finite = depth[np.isfinite(depth)]
    if len(finite):
        far = float(np.percentile(finite, 99))
    else:
        far = 10.0
    depth = np.where(np.isfinite(depth), depth, far)

    # Normalize to 0-255 (closer = brighter, ControlNet Depth convention)
    near = float(depth.min())
    norm = ((far - depth) / max(1e-6, far - near) * 255).clip(0, 255)
    return depth, norm.astype(np.uint8)


def make_canny(depth_u8: np.ndarray) -> Image.Image:
    """Compute Canny edges from the depth image."""
    # Use Pillow's FIND_EDGES then threshold — simpler than installing opencv
    im = Image.fromarray(depth_u8)
    edges = im.filter(ImageFilter.FIND_EDGES)
    arr = np.array(edges)
    arr = (arr > 30).astype(np.uint8) * 255
    return Image.fromarray(arr)


def main():
    print("=== building Yuto's bedroom ===")
    meshes = build_meshes()
    print(f"  {len(meshes)} primitives")

    usd_path = OUT_DIR / "yuto-bedroom.usda"
    write_usd(meshes, usd_path)

    # Combine all meshes for raycasting
    scene_mesh = trimesh.util.concatenate([m for _, m in meshes])
    print(f"  combined mesh: {len(scene_mesh.vertices)} verts, "
          f"{len(scene_mesh.faces)} faces")

    for cam_name, (origin, target, fov) in CAMERAS.items():
        print(f"\n=== rendering {cam_name} ===")
        print(f"  cam: origin={origin} target={target} fov={fov}")
        depth_f, depth_u8 = render_depth(scene_mesh, origin, target, fov)
        Image.fromarray(depth_u8).save(OUT_DIR / f"yuto-bedroom-{cam_name}-depth.png")
        make_canny(depth_u8).save(OUT_DIR / f"yuto-bedroom-{cam_name}-canny.png")
        print(f"  saved depth + canny")


if __name__ == "__main__":
    sys.exit(main() or 0)

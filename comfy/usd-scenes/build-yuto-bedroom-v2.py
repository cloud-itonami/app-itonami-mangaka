"""Expanded yuto-bedroom USD scene — adds detail items requested by user.

Inputs preserved (same room dimensions, desk/chair/bed/lamp position).
Added:
  - Closet (wardrobe) on west wall
  - Drawer stack next to desk
  - Bookshelf above desk with 6 books
  - Floor cushion / zabuton near bed
  - Hoodie on chair (cloth drape)
  - Curtain on window (drawn open)
  - Backpack on floor near desk
  - Headphones on desk
  - Smartphone elevated + larger with screen rectangle (so it reads
    as a phone in renders, not a flat sliver)
  - Sneakers + slippers near door
  - Wall poster + clock above bed
  - Floor outlet + cable along wall
  - Trash can next to desk

All items are box / cylinder / sphere primitives — keeps the file
lightweight and Freestyle-friendly.

Output: /Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/
        ai-gftd-project-mangaka/data/ghosthacker/resources/usd/
        yuto-bedroom.usda  (overwrites existing — increase mesh count
                             22 → ~50)
"""
import sys
from pathlib import Path
from pxr import Usd, UsdGeom, UsdLux, Gf
import numpy as np
import trimesh

OUT = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/usd/yuto-bedroom.usda")
ROOM_W, ROOM_D, ROOM_H = 4.0, 4.0, 2.5

stage = Usd.Stage.CreateNew(str(OUT))
stage.SetMetadata("upAxis", "Y")
root = UsdGeom.Xform.Define(stage, "/Bedroom")
stage.SetDefaultPrim(root.GetPrim())


def add_box(path, w, h, d, pos):
    m = trimesh.creation.box(extents=(w, h, d))
    prim = UsdGeom.Mesh.Define(stage, path)
    verts = m.vertices + np.array(pos)
    prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts])
    prim.GetFaceVertexCountsAttr().Set([3] * len(m.faces))
    prim.GetFaceVertexIndicesAttr().Set(m.faces.flatten().tolist())
    return prim


def add_cyl(path, r, h, pos, axis="y"):
    m = trimesh.creation.cylinder(radius=r, height=h, sections=12)
    if axis == "x":
        rot = trimesh.transformations.rotation_matrix(np.pi/2, [0, 1, 0])
        m.apply_transform(rot)
    elif axis == "z":
        rot = trimesh.transformations.rotation_matrix(np.pi/2, [1, 0, 0])
        m.apply_transform(rot)
    prim = UsdGeom.Mesh.Define(stage, path)
    verts = m.vertices + np.array(pos)
    prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts])
    prim.GetFaceVertexCountsAttr().Set([3] * len(m.faces))
    prim.GetFaceVertexIndicesAttr().Set(m.faces.flatten().tolist())
    return prim


def add_sphere(path, r, pos):
    m = trimesh.creation.icosphere(radius=r, subdivisions=2)
    prim = UsdGeom.Mesh.Define(stage, path)
    verts = m.vertices + np.array(pos)
    prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts])
    prim.GetFaceVertexCountsAttr().Set([3] * len(m.faces))
    prim.GetFaceVertexIndicesAttr().Set(m.faces.flatten().tolist())
    return prim


# ─── Room shell ─────────────────────────────────────────────────────────
add_box("/Bedroom/floor",   ROOM_W, 0.02, ROOM_D, (ROOM_W/2, 0.0, ROOM_D/2))
add_box("/Bedroom/ceiling", ROOM_W, 0.02, ROOM_D, (ROOM_W/2, ROOM_H, ROOM_D/2))
add_box("/Bedroom/wall_n",  ROOM_W, ROOM_H, 0.05, (ROOM_W/2, ROOM_H/2, 0.0))
add_box("/Bedroom/wall_s",  ROOM_W, ROOM_H, 0.05, (ROOM_W/2, ROOM_H/2, ROOM_D))
add_box("/Bedroom/wall_e",  0.05, ROOM_H, ROOM_D, (ROOM_W,   ROOM_H/2, ROOM_D/2))
add_box("/Bedroom/wall_w",  0.05, ROOM_H, ROOM_D, (0.0,      ROOM_H/2, ROOM_D/2))

# ─── Window + curtain on north wall (open) ───────────────────────────────
add_box("/Bedroom/window_frame", 1.4, 1.4, 0.04, (ROOM_W/2, 1.5, 0.04))
add_box("/Bedroom/window_pane",  1.2, 1.2, 0.01, (ROOM_W/2, 1.5, 0.06))
add_box("/Bedroom/curtain_l",    0.15, 1.5, 0.04, (ROOM_W/2 - 0.7, 1.5, 0.1))
add_box("/Bedroom/curtain_r",    0.15, 1.5, 0.04, (ROOM_W/2 + 0.7, 1.5, 0.1))

# ─── Bed + bedding + pillow + zabuton ────────────────────────────────────
add_box("/Bedroom/bed",     1.2, 0.35, 2.0, (0.85, 0.20, 1.5))
add_box("/Bedroom/mattress",1.15, 0.12, 1.95, (0.85, 0.43, 1.5))
add_box("/Bedroom/blanket", 1.10, 0.06, 1.65, (0.85, 0.50, 1.30))   # blanket pulled up
add_box("/Bedroom/pillow_a",0.55, 0.10, 0.30, (0.65, 0.55, 2.30))
add_box("/Bedroom/pillow_b",0.50, 0.08, 0.28, (1.05, 0.55, 2.35))
add_box("/Bedroom/zabuton", 0.45, 0.04, 0.45, (1.30, 0.04, 1.20))   # cushion on floor

# ─── Desk + drawer + chair ───────────────────────────────────────────────
add_box("/Bedroom/desk_top",  1.5, 0.05, 0.7, (3.0, 0.78, 2.0))
add_box("/Bedroom/desk_leg_a", 0.05, 0.78, 0.05, (2.30, 0.39, 1.70))
add_box("/Bedroom/desk_leg_b", 0.05, 0.78, 0.05, (2.30, 0.39, 2.30))
add_box("/Bedroom/desk_leg_c", 0.05, 0.78, 0.05, (3.70, 0.39, 1.70))
add_box("/Bedroom/desk_leg_d", 0.05, 0.78, 0.05, (3.70, 0.39, 2.30))

# Drawer stack under desk (3 drawers)
add_box("/Bedroom/drawer_body", 0.45, 0.70, 0.45, (3.55, 0.36, 2.15))
add_box("/Bedroom/drawer_d1",   0.42, 0.20, 0.04, (3.55, 0.18, 1.94))
add_box("/Bedroom/drawer_d2",   0.42, 0.20, 0.04, (3.55, 0.40, 1.94))
add_box("/Bedroom/drawer_d3",   0.42, 0.20, 0.04, (3.55, 0.62, 1.94))
add_sphere("/Bedroom/drawer_h1", 0.025, (3.55, 0.18, 1.92))
add_sphere("/Bedroom/drawer_h2", 0.025, (3.55, 0.40, 1.92))
add_sphere("/Bedroom/drawer_h3", 0.025, (3.55, 0.62, 1.92))

# Chair seat + back + 4 legs + draped hoodie
add_box("/Bedroom/chair_seat", 0.45, 0.05, 0.45, (3.0, 0.45, 1.40))
add_box("/Bedroom/chair_back", 0.45, 0.50, 0.04, (3.0, 0.70, 1.18))
add_box("/Bedroom/chair_leg_a",0.04, 0.45, 0.04, (2.78, 0.22, 1.20))
add_box("/Bedroom/chair_leg_b",0.04, 0.45, 0.04, (3.22, 0.22, 1.20))
add_box("/Bedroom/chair_leg_c",0.04, 0.45, 0.04, (2.78, 0.22, 1.60))
add_box("/Bedroom/chair_leg_d",0.04, 0.45, 0.04, (3.22, 0.22, 1.60))
# Hoodie draped over chair back
add_box("/Bedroom/hoodie_drape", 0.50, 0.40, 0.10, (3.0, 0.65, 1.10))

# ─── Desk-top items ─────────────────────────────────────────────────────
# Notebook + open page
add_box("/Bedroom/notebook",  0.25, 0.015, 0.18, (3.30, 0.81, 2.05))
add_box("/Bedroom/notebook_page", 0.22, 0.005, 0.16, (3.30, 0.82, 2.05))
# Smartphone — bigger + with screen rectangle on top (vertical, tilted)
add_box("/Bedroom/phone_body",  0.085, 0.012, 0.165, (3.65, 0.795, 2.15))
add_box("/Bedroom/phone_screen", 0.075, 0.001, 0.150, (3.65, 0.802, 2.15))
add_sphere("/Bedroom/phone_cam", 0.005, (3.65, 0.808, 2.075))
# Headphones — 2 spheres + arch
add_sphere("/Bedroom/hp_l", 0.045, (2.45, 0.81, 1.78))
add_sphere("/Bedroom/hp_r", 0.045, (2.45, 0.81, 1.88))
add_cyl("/Bedroom/hp_arch", 0.005, 0.12, (2.45, 0.86, 1.83), axis="z")
# Pencil cup with 3 pens
add_cyl("/Bedroom/pen_cup", 0.04, 0.08, (3.55, 0.82, 1.78))
add_cyl("/Bedroom/pen1", 0.005, 0.14, (3.55, 0.90, 1.78))
add_cyl("/Bedroom/pen2", 0.005, 0.14, (3.54, 0.90, 1.79))
add_cyl("/Bedroom/pen3", 0.005, 0.14, (3.56, 0.90, 1.77))

# ─── Lamp ───────────────────────────────────────────────────────────────
add_cyl("/Bedroom/lamp_base",  0.06, 0.02, (2.45, 0.82, 1.92))
add_cyl("/Bedroom/lamp_arm",   0.012, 0.30, (2.45, 0.97, 1.92))
add_cyl("/Bedroom/lamp_shade", 0.08, 0.10, (2.45, 1.17, 1.92))

# ─── Closet on west wall ────────────────────────────────────────────────
add_box("/Bedroom/closet_body", 0.50, 2.10, 1.00, (0.30, 1.05, 0.6))
add_box("/Bedroom/closet_door_l", 0.46, 1.95, 0.03, (0.30, 0.98, 0.10))
add_box("/Bedroom/closet_door_r", 0.46, 1.95, 0.03, (0.30, 0.98, 0.13))
add_sphere("/Bedroom/closet_knob_l", 0.018, (0.07, 0.95, 0.10))
add_sphere("/Bedroom/closet_knob_r", 0.018, (0.07, 0.95, 0.13))

# ─── Bookshelf above desk ───────────────────────────────────────────────
add_box("/Bedroom/shelf",  1.4, 0.03, 0.20, (3.0, 1.45, 1.85))
# 6 books on shelf, varying heights/widths
add_box("/Bedroom/book1", 0.04, 0.20, 0.14, (2.45, 1.57, 1.85))
add_box("/Bedroom/book2", 0.04, 0.22, 0.14, (2.50, 1.58, 1.85))
add_box("/Bedroom/book3", 0.04, 0.18, 0.14, (2.55, 1.56, 1.85))
add_box("/Bedroom/book4", 0.04, 0.21, 0.14, (2.60, 1.575, 1.85))
add_box("/Bedroom/book5", 0.04, 0.24, 0.14, (3.40, 1.59, 1.85))
add_box("/Bedroom/book6", 0.04, 0.19, 0.14, (3.45, 1.565, 1.85))

# ─── Backpack on floor near desk ────────────────────────────────────────
add_box("/Bedroom/backpack_body", 0.30, 0.40, 0.18, (2.20, 0.20, 1.5))
add_box("/Bedroom/backpack_strap", 0.04, 0.30, 0.04, (2.13, 0.40, 1.5))

# ─── Sneakers + slippers near door (east wall) ──────────────────────────
add_box("/Bedroom/sneaker_l", 0.08, 0.08, 0.22, (3.80, 0.04, 0.50))
add_box("/Bedroom/sneaker_r", 0.08, 0.08, 0.22, (3.80, 0.04, 0.30))
add_box("/Bedroom/slipper_l", 0.10, 0.03, 0.18, (3.50, 0.015, 0.50))
add_box("/Bedroom/slipper_r", 0.10, 0.03, 0.18, (3.50, 0.015, 0.30))

# ─── Wall items (north + above bed) ─────────────────────────────────────
add_box("/Bedroom/poster_band", 0.50, 0.70, 0.005, (0.85, 1.60, 0.07))
add_cyl("/Bedroom/wall_clock", 0.12, 0.03, (2.0, 1.80, 0.08), axis="z")

# ─── Trash can next to desk ─────────────────────────────────────────────
add_cyl("/Bedroom/trash", 0.10, 0.30, (2.20, 0.15, 1.85))

# ─── Floor cable + outlet ───────────────────────────────────────────────
add_box("/Bedroom/outlet", 0.06, 0.08, 0.02, (3.95, 0.30, 1.0))


# ─── Lights ─────────────────────────────────────────────────────────────
window_l = UsdLux.RectLight.Define(stage, "/Bedroom/Lights/window")
window_l.GetIntensityAttr().Set(2500.0)
window_l.GetWidthAttr().Set(1.2); window_l.GetHeightAttr().Set(1.5)
xf = UsdGeom.XformCommonAPI(window_l)
xf.SetTranslate((ROOM_W/2, 1.65, 0.1))

lamp_l = UsdLux.SphereLight.Define(stage, "/Bedroom/Lights/desk_lamp")
lamp_l.GetIntensityAttr().Set(600.0); lamp_l.GetRadiusAttr().Set(0.05)
xf2 = UsdGeom.XformCommonAPI(lamp_l)
xf2.SetTranslate((2.45, 1.20, 1.92))

ceil_fill = UsdLux.DistantLight.Define(stage, "/Bedroom/Lights/ceiling_fill")
ceil_fill.GetIntensityAttr().Set(200.0)
xf3 = UsdGeom.XformCommonAPI(ceil_fill)
xf3.SetTranslate((ROOM_W/2, 2.4, ROOM_D/2))


# ─── Named cameras (existing 5 — preserve) ──────────────────────────────
import math
def make_cam(name, origin, target, fov_deg):
    cam = UsdGeom.Camera.Define(stage, f"/Bedroom/Cameras/{name}")
    h_aperture = 36.0
    focal = h_aperture / (2 * math.tan(math.radians(fov_deg) / 2))
    cam.GetFocalLengthAttr().Set(focal)
    cam.GetHorizontalApertureAttr().Set(h_aperture)
    cam.GetVerticalApertureAttr().Set(24.0)
    eye = Gf.Vec3d(*origin); tgt = Gf.Vec3d(*target); up = Gf.Vec3d(0, 1, 0)
    fwd = (tgt - eye).GetNormalized()
    right = Gf.Cross(fwd, up).GetNormalized()
    real_up = Gf.Cross(right, fwd).GetNormalized()
    rot = Gf.Matrix3d(right[0], right[1], right[2],
                       real_up[0], real_up[1], real_up[2],
                       -fwd[0], -fwd[1], -fwd[2])
    m = Gf.Matrix4d(1).SetIdentity()
    m.SetRotateOnly(rot); m.SetTranslateOnly(eye)
    op = UsdGeom.Xformable(cam).AddTransformOp()
    op.Set(m)

make_cam("establish_wide", (0.5, 1.6, 0.5),  (2.0, 0.7, 2.0), 70.0)
make_cam("yuto_at_desk",   (1.0, 1.5, 1.3),  (3.0, 1.0, 2.0), 50.0)
make_cam("phone_closeup",  (3.4, 1.0, 2.4),  (3.65, 0.80, 2.15), 35.0)
make_cam("room_overhead",  (2.5, 2.3, 1.5),  (2.0, 0.5, 2.0), 70.0)
make_cam("window_view",    (2.5, 1.4, 0.5),  (2.0, 1.0, 3.0), 60.0)
make_cam("bed_close",      (1.5, 1.2, 2.5),  (0.85, 0.5, 1.8), 40.0)  # NEW
make_cam("closet_view",    (2.5, 1.3, 2.0),  (0.4, 1.0, 1.0), 55.0)   # NEW

stage.GetRootLayer().Save()

# Print summary
s = Usd.Stage.Open(str(OUT))
mesh_n = sum(1 for p in s.Traverse() if p.IsA(UsdGeom.Mesh))
cam_n = sum(1 for p in s.Traverse() if p.IsA(UsdGeom.Camera))
print(f"OK: {OUT}  meshes={mesh_n} cameras={cam_n} ({OUT.stat().st_size//1024}KB)")

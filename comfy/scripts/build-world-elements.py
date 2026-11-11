"""Build missing world-element USDs + world.jsonld metadata for arc 0-1.

User-requested world coverage (2026-05-23):
  - school name + class roster + seat order  → world.jsonld
  - school exterior building                  → school-exterior.usda
  - school uniform spec                       → world.jsonld (rendered via prompt)
  - casual clothing spec                      → world.jsonld
  - Ren's room (extend existing)              → existing rens-room.usda
  - Nei's room (NEW)                          → neis-room.usda
  - Tokyo cityscape pan view                  → tokyo-zenkei.usda
  - Ghost entity                              → ghost-entity.usda
  - Daemon entity                             → daemon-entity.usda
  - Holographic device                        → holodevice.usda

All primitives (box / cylinder / sphere) — Freestyle-friendly for the
v5+ pipeline. Lights + named UsdGeomCamera prims included where
appropriate.
"""
from pathlib import Path
from pxr import Usd, UsdGeom, UsdLux, Gf
import numpy as np
import trimesh
import math
import json

OUT_DIR = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/usd")
WORLD_JSON = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/world.jsonld")


def _add_box(stage, path, w, h, d, pos):
    m = trimesh.creation.box(extents=(w, h, d))
    prim = UsdGeom.Mesh.Define(stage, path)
    verts = m.vertices + np.array(pos)
    prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts])
    prim.GetFaceVertexCountsAttr().Set([3] * len(m.faces))
    prim.GetFaceVertexIndicesAttr().Set(m.faces.flatten().tolist())
    return prim

def _add_cyl(stage, path, r, h, pos, axis="y"):
    m = trimesh.creation.cylinder(radius=r, height=h, sections=12)
    if axis == "x":
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0, 1, 0]))
    elif axis == "z":
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [1, 0, 0]))
    prim = UsdGeom.Mesh.Define(stage, path)
    verts = m.vertices + np.array(pos)
    prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts])
    prim.GetFaceVertexCountsAttr().Set([3] * len(m.faces))
    prim.GetFaceVertexIndicesAttr().Set(m.faces.flatten().tolist())

def _add_sphere(stage, path, r, pos, subdivisions=2):
    m = trimesh.creation.icosphere(radius=r, subdivisions=subdivisions)
    prim = UsdGeom.Mesh.Define(stage, path)
    verts = m.vertices + np.array(pos)
    prim.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts])
    prim.GetFaceVertexCountsAttr().Set([3] * len(m.faces))
    prim.GetFaceVertexIndicesAttr().Set(m.faces.flatten().tolist())

def _add_cam(stage, root, name, origin, target, fov_deg):
    cam = UsdGeom.Camera.Define(stage, f"{root}/Cameras/{name}")
    h_ap = 36.0
    focal = h_ap / (2 * math.tan(math.radians(fov_deg) / 2))
    cam.GetFocalLengthAttr().Set(focal)
    cam.GetHorizontalApertureAttr().Set(h_ap)
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


# ─── 1. Nei's room — bright, fashionable, K-pop posters, mirror ─────────
def build_neis_room():
    out = OUT_DIR / "neis-room.usda"
    stage = Usd.Stage.CreateNew(str(out))
    stage.SetMetadata("upAxis", "Y")
    root = UsdGeom.Xform.Define(stage, "/NeisRoom")
    stage.SetDefaultPrim(root.GetPrim())
    W, D, H = 4.0, 4.5, 2.5
    # Shell
    _add_box(stage, "/NeisRoom/floor",   W, 0.02, D, (W/2, 0.0, D/2))
    _add_box(stage, "/NeisRoom/ceiling", W, 0.02, D, (W/2, H, D/2))
    _add_box(stage, "/NeisRoom/wall_n",  W, H, 0.05, (W/2, H/2, 0.0))
    _add_box(stage, "/NeisRoom/wall_s",  W, H, 0.05, (W/2, H/2, D))
    _add_box(stage, "/NeisRoom/wall_e",  0.05, H, D, (W, H/2, D/2))
    _add_box(stage, "/NeisRoom/wall_w",  0.05, H, D, (0, H/2, D/2))
    # Window (bigger than Yuto's)
    _add_box(stage, "/NeisRoom/window_frame", 1.6, 1.5, 0.04, (W/2, 1.6, 0.04))
    _add_box(stage, "/NeisRoom/window_pane",  1.4, 1.3, 0.01, (W/2, 1.6, 0.06))
    _add_box(stage, "/NeisRoom/curtain_l",   0.20, 1.8, 0.04, (W/2 - 0.85, 1.6, 0.1))
    _add_box(stage, "/NeisRoom/curtain_r",   0.20, 1.8, 0.04, (W/2 + 0.85, 1.6, 0.1))
    # Bed (single, side wall)
    _add_box(stage, "/NeisRoom/bed",      1.0, 0.30, 2.0, (0.65, 0.18, 1.5))
    _add_box(stage, "/NeisRoom/mattress", 0.95, 0.10, 1.95, (0.65, 0.38, 1.5))
    _add_box(stage, "/NeisRoom/blanket",  0.95, 0.06, 1.50, (0.65, 0.45, 1.4))
    _add_box(stage, "/NeisRoom/pillow",   0.50, 0.10, 0.30, (0.65, 0.50, 2.30))
    # Desk + chair (more compact than Yuto's)
    _add_box(stage, "/NeisRoom/desk_top", 1.20, 0.04, 0.55, (2.8, 0.78, 0.6))
    for i, x in enumerate([2.22, 2.22, 3.38, 3.38]):
        z = 0.34 if i % 2 == 0 else 0.86
        _add_box(stage, f"/NeisRoom/desk_leg_{i}", 0.04, 0.78, 0.04, (x, 0.39, z))
    _add_box(stage, "/NeisRoom/chair_seat", 0.40, 0.04, 0.40, (2.8, 0.42, 1.10))
    _add_box(stage, "/NeisRoom/chair_back", 0.40, 0.50, 0.04, (2.8, 0.67, 1.30))
    # Vanity / mirror — Nei trait
    _add_box(stage, "/NeisRoom/vanity_top", 0.80, 0.03, 0.40, (3.5, 0.75, 2.5))
    _add_box(stage, "/NeisRoom/mirror",    0.70, 0.80, 0.02, (3.5, 1.30, 2.7))
    _add_sphere(stage, "/NeisRoom/jewelry_box", 0.06, (3.3, 0.80, 2.45))
    # Wardrobe (fashion-forward)
    _add_box(stage, "/NeisRoom/wardrobe", 1.40, 2.10, 0.50, (0.35, 1.05, 3.5))
    _add_box(stage, "/NeisRoom/wardrobe_door_l", 0.68, 1.95, 0.03, (0.10, 0.98, 3.25))
    _add_box(stage, "/NeisRoom/wardrobe_door_r", 0.68, 1.95, 0.03, (0.10, 0.98, 3.75))
    # Hanger rod with 4 garments visible
    for i, x in enumerate([1.0, 1.15, 1.30, 1.45]):
        _add_box(stage, f"/NeisRoom/garment_{i}", 0.10, 0.40, 0.30, (x, 0.45, 0.35))
    # Posters on wall — 3
    for i, z in enumerate([0.8, 1.5, 2.2]):
        _add_box(stage, f"/NeisRoom/poster_{i}", 0.04, 0.65, 0.45, (W - 0.07, 1.45, z))
    # Floor cushion (yoga / lounging)
    _add_cyl(stage, "/NeisRoom/floor_cushion", 0.40, 0.08, (2.0, 0.04, 2.5))
    # Smartphone + laptop on desk
    _add_box(stage, "/NeisRoom/laptop_base",  0.32, 0.02, 0.22, (2.8, 0.81, 0.6))
    _add_box(stage, "/NeisRoom/laptop_screen", 0.32, 0.20, 0.02, (2.8, 0.91, 0.49))
    _add_box(stage, "/NeisRoom/phone_nei", 0.08, 0.01, 0.16, (3.1, 0.80, 0.6))
    # Lights
    w_light = UsdLux.RectLight.Define(stage, "/NeisRoom/Lights/window")
    w_light.GetIntensityAttr().Set(2800.0)
    w_light.GetWidthAttr().Set(1.4); w_light.GetHeightAttr().Set(1.4)
    UsdGeom.XformCommonAPI(w_light).SetTranslate((W/2, 1.7, 0.08))
    ceil = UsdLux.DistantLight.Define(stage, "/NeisRoom/Lights/ceiling_fill")
    ceil.GetIntensityAttr().Set(300.0)
    UsdGeom.XformCommonAPI(ceil).SetTranslate((W/2, 2.4, D/2))
    # Cameras
    _add_cam(stage, "/NeisRoom", "nei_at_desk", (1.0, 1.5, 0.0), (2.8, 1.0, 0.7), 45.0)
    _add_cam(stage, "/NeisRoom", "mirror_view", (1.5, 1.5, 2.5), (3.5, 1.3, 2.7), 50.0)
    _add_cam(stage, "/NeisRoom", "bed_overhead", (0.65, 2.2, 1.5), (0.65, 0.5, 1.5), 65.0)
    _add_cam(stage, "/NeisRoom", "wardrobe_view", (2.5, 1.4, 1.8), (1.0, 1.0, 3.5), 55.0)
    _add_cam(stage, "/NeisRoom", "establish_wide", (0.5, 1.7, 0.5), (2.5, 0.7, 2.5), 70.0)
    stage.GetRootLayer().Save()
    print(f"  ✓ {out.name}  ({sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))} meshes)")


# ─── 2. Tokyo cityscape (wide pan) ─────────────────────────────────────
def build_tokyo_zenkei():
    out = OUT_DIR / "tokyo-zenkei.usda"
    stage = Usd.Stage.CreateNew(str(out))
    stage.SetMetadata("upAxis", "Y")
    root = UsdGeom.Xform.Define(stage, "/TokyoZenkei")
    stage.SetDefaultPrim(root.GetPrim())
    # Ground plane
    _add_box(stage, "/TokyoZenkei/ground", 200, 0.05, 200, (0, 0, 0))
    # Mid-rise buildings (random grid 8×8)
    import random
    random.seed(42)
    for i in range(8):
        for j in range(8):
            if i in (3, 4) and j in (3, 4): continue   # central plaza
            x = -80 + i * 20 + random.uniform(-2, 2)
            z = -80 + j * 20 + random.uniform(-2, 2)
            h = random.uniform(8, 28)
            w = random.uniform(8, 14); d = random.uniform(8, 14)
            _add_box(stage, f"/TokyoZenkei/bldg_{i}_{j}", w, h, d, (x, h/2, z))
    # Skyscrapers — 3 standout
    for k, (sx, sz, sh) in enumerate([(40, 40, 80), (-40, 60, 65), (60, -50, 100)]):
        _add_box(stage, f"/TokyoZenkei/tower_{k}", 12, sh, 12, (sx, sh/2, sz))
        _add_box(stage, f"/TokyoZenkei/tower_top_{k}", 6, 12, 6, (sx, sh + 6, sz))
        _add_cyl(stage, f"/TokyoZenkei/tower_antenna_{k}", 0.3, 8, (sx, sh + 16, sz))
    # Tokyo Tower iconic — orange lattice (4 leg cone)
    for k, (lx, lz) in enumerate([(-3, -3), (3, -3), (-3, 3), (3, 3)]):
        _add_cyl(stage, f"/TokyoZenkei/tower_leg_{k}", 0.8, 50,
                  (lx * 1.5, 25, 70 + lz * 1.5))
    _add_box(stage, "/TokyoZenkei/tower_observation", 8, 4, 8, (0, 50, 70))
    _add_cyl(stage, "/TokyoZenkei/tower_spire", 0.5, 30, (0, 80, 70))
    # Roads — 2 main avenues + cross streets
    _add_box(stage, "/TokyoZenkei/road_h_main", 200, 0.02, 6, (0, 0.02, 0))
    _add_box(stage, "/TokyoZenkei/road_v_main", 6, 0.02, 200, (0, 0.02, 0))
    # Highway elevated
    _add_box(stage, "/TokyoZenkei/highway", 200, 0.5, 8, (0, 12, 30))
    for k in range(0, 21):
        _add_cyl(stage, f"/TokyoZenkei/hwy_pillar_{k}", 0.8, 12, (-100 + k*10, 6, 30))
    # Sun light
    sun = UsdLux.DistantLight.Define(stage, "/TokyoZenkei/Lights/sun")
    sun.GetIntensityAttr().Set(3500.0)
    UsdGeom.XformCommonAPI(sun).SetTranslate((100, 80, -100))
    # Cameras — pan / aerial / ground-level
    _add_cam(stage, "/TokyoZenkei", "aerial_wide", (0, 120, 120), (0, 20, 0), 60.0)
    _add_cam(stage, "/TokyoZenkei", "tower_view",  (50, 80, 80), (0, 50, 70), 50.0)
    _add_cam(stage, "/TokyoZenkei", "ground_pan",  (-50, 8, -50), (50, 15, 50), 75.0)
    _add_cam(stage, "/TokyoZenkei", "dusk_silhouette", (80, 5, 80), (-50, 30, -50), 65.0)
    stage.GetRootLayer().Save()
    print(f"  ✓ {out.name}  ({sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))} meshes)")


# ─── 3. School building exterior ────────────────────────────────────────
def build_school_exterior():
    out = OUT_DIR / "school-exterior.usda"
    stage = Usd.Stage.CreateNew(str(out))
    stage.SetMetadata("upAxis", "Y")
    UsdGeom.Xform.Define(stage, "/School")
    stage.SetDefaultPrim(stage.GetPrimAtPath("/School"))
    # Main building (5-floor block)
    BW, BH, BD = 50.0, 18.0, 14.0
    _add_box(stage, "/School/main_block", BW, BH, BD, (0, BH/2, 0))
    # Windows row per floor (5 floors × 12 windows wide)
    for f in range(5):
        y = 1.5 + f * 3.5
        for i in range(12):
            x = -22 + i * 4
            _add_box(stage, f"/School/window_f{f}_w{i}", 1.4, 1.5, 0.05, (x, y, BD/2 - 0.05))
    # Entrance — recessed double doors
    _add_box(stage, "/School/entrance_canopy", 8, 0.3, 3, (0, 3.5, BD/2 + 1.5))
    _add_box(stage, "/School/door_l", 1.2, 2.4, 0.05, (-0.7, 1.2, BD/2))
    _add_box(stage, "/School/door_r", 1.2, 2.4, 0.05, (0.7, 1.2, BD/2))
    _add_cyl(stage, "/School/flag_pole", 0.1, 12, (12, 6, BD/2 + 4))
    # Gym building (smaller, beside main)
    _add_box(stage, "/School/gym", 25, 12, 18, (-35, 6, 8))
    # Schoolyard / playground (visible)
    _add_box(stage, "/School/yard_ground", 60, 0.02, 30, (-5, 0.01, BD/2 + 18))
    # Trees lining the path
    for k in range(6):
        x = -25 + k * 10
        _add_cyl(stage, f"/School/tree_trunk_{k}", 0.3, 4, (x, 2, BD/2 + 4))
        _add_sphere(stage, f"/School/tree_crown_{k}", 1.6, (x, 5, BD/2 + 4), subdivisions=2)
    # Gates
    _add_box(stage, "/School/gate_l", 0.4, 3, 0.4, (-5, 1.5, BD/2 + 30))
    _add_box(stage, "/School/gate_r", 0.4, 3, 0.4, (5, 1.5, BD/2 + 30))
    _add_box(stage, "/School/gate_arch", 11, 0.4, 0.4, (0, 3.2, BD/2 + 30))
    # Bike rack
    for k in range(8):
        _add_cyl(stage, f"/School/bike_rack_{k}", 0.05, 1.2, (-18 + k * 1.2, 0.6, BD/2 + 8))
    # Lights
    sun = UsdLux.DistantLight.Define(stage, "/School/Lights/sun")
    sun.GetIntensityAttr().Set(3200.0)
    UsdGeom.XformCommonAPI(sun).SetTranslate((40, 30, 40))
    # Cameras
    _add_cam(stage, "/School", "front_entrance", (0, 4, BD/2 + 25), (0, 5, 0), 55.0)
    _add_cam(stage, "/School", "gate_approach",  (0, 1.6, BD/2 + 28), (0, 3, 0), 60.0)
    _add_cam(stage, "/School", "side_gym",        (-50, 4, 20), (-25, 6, 0), 50.0)
    _add_cam(stage, "/School", "aerial",          (30, 30, 40), (0, 8, 5), 55.0)
    _add_cam(stage, "/School", "yard_pov",        (-5, 1.6, BD/2 + 10), (-5, 4, -5), 70.0)
    stage.GetRootLayer().Save()
    print(f"  ✓ {out.name}  ({sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))} meshes)")


# ─── 4. Ghost entity ────────────────────────────────────────────────────
def build_ghost():
    out = OUT_DIR / "ghost-entity.usda"
    stage = Usd.Stage.CreateNew(str(out))
    stage.SetMetadata("upAxis", "Y")
    UsdGeom.Xform.Define(stage, "/Ghost")
    stage.SetDefaultPrim(stage.GetPrimAtPath("/Ghost"))
    # Floating humanoid silhouette — head + elongated body + wisps
    _add_sphere(stage, "/Ghost/head", 0.18, (0, 1.55, 0))
    _add_box(stage, "/Ghost/torso",   0.40, 0.55, 0.20, (0, 1.10, 0))
    # Trailing wisps (descending cones)
    _add_cyl(stage, "/Ghost/wisp_l",  0.18, 0.6, (-0.15, 0.55, 0))
    _add_cyl(stage, "/Ghost/wisp_r",  0.18, 0.6, ( 0.15, 0.55, 0))
    _add_cyl(stage, "/Ghost/wisp_c",  0.20, 0.4, (0,    0.20, 0))
    # Arms — outstretched
    _add_cyl(stage, "/Ghost/arm_l", 0.05, 0.5, (-0.30, 1.10, 0))
    _add_cyl(stage, "/Ghost/arm_r", 0.05, 0.5, ( 0.30, 1.10, 0))
    # Two glowing eye sockets
    _add_sphere(stage, "/Ghost/eye_l", 0.04, (-0.06, 1.58, 0.16))
    _add_sphere(stage, "/Ghost/eye_r", 0.04, ( 0.06, 1.58, 0.16))
    stage.GetRootLayer().Save()
    print(f"  ✓ {out.name}  ({sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))} meshes)")


# ─── 5. Daemon entity ───────────────────────────────────────────────────
def build_daemon():
    out = OUT_DIR / "daemon-entity.usda"
    stage = Usd.Stage.CreateNew(str(out))
    stage.SetMetadata("upAxis", "Y")
    UsdGeom.Xform.Define(stage, "/Daemon")
    stage.SetDefaultPrim(stage.GetPrimAtPath("/Daemon"))
    # Imp creature — body + horns + tail + wings
    _add_sphere(stage, "/Daemon/head",  0.20, (0, 0.65, 0))
    _add_box(stage, "/Daemon/torso",    0.35, 0.40, 0.25, (0, 0.30, 0))
    # Horns (2 small cones)
    _add_cyl(stage, "/Daemon/horn_l", 0.04, 0.18, (-0.10, 0.85, 0))
    _add_cyl(stage, "/Daemon/horn_r", 0.04, 0.18, ( 0.10, 0.85, 0))
    # Wings — flat batlike
    _add_box(stage, "/Daemon/wing_l", 0.50, 0.30, 0.02, (-0.40, 0.40, 0))
    _add_box(stage, "/Daemon/wing_r", 0.50, 0.30, 0.02, ( 0.40, 0.40, 0))
    # Tail (cylinder curved approximation)
    _add_cyl(stage, "/Daemon/tail",  0.04, 0.45, (0, 0.15, -0.18))
    # Arms + claw
    _add_cyl(stage, "/Daemon/arm_l", 0.05, 0.30, (-0.22, 0.35, 0))
    _add_cyl(stage, "/Daemon/arm_r", 0.05, 0.30, ( 0.22, 0.35, 0))
    _add_sphere(stage, "/Daemon/claw_l", 0.05, (-0.30, 0.15, 0))
    _add_sphere(stage, "/Daemon/claw_r", 0.05, ( 0.30, 0.15, 0))
    # Eyes glowing
    _add_sphere(stage, "/Daemon/eye_l", 0.035, (-0.07, 0.68, 0.16))
    _add_sphere(stage, "/Daemon/eye_r", 0.035, ( 0.07, 0.68, 0.16))
    # Mouth — small box
    _add_box(stage, "/Daemon/mouth", 0.10, 0.04, 0.02, (0, 0.58, 0.18))
    stage.GetRootLayer().Save()
    print(f"  ✓ {out.name}  ({sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))} meshes)")


# ─── 6. Holodevice (handheld holographic projector) ─────────────────────
def build_holodevice():
    out = OUT_DIR / "holodevice.usda"
    stage = Usd.Stage.CreateNew(str(out))
    stage.SetMetadata("upAxis", "Y")
    UsdGeom.Xform.Define(stage, "/Holodevice")
    stage.SetDefaultPrim(stage.GetPrimAtPath("/Holodevice"))
    # Disc-shaped base
    _add_cyl(stage, "/Holodevice/base", 0.10, 0.04, (0, 0.02, 0))
    _add_cyl(stage, "/Holodevice/base_rim", 0.115, 0.01, (0, 0.045, 0))
    # Button (top)
    _add_sphere(stage, "/Holodevice/button", 0.015, (0, 0.06, 0))
    # Holographic projection (above) — 3 stacked rings
    for i, ry in enumerate([0.12, 0.25, 0.40]):
        _add_cyl(stage, f"/Holodevice/holo_ring_{i}", 0.04 + i*0.03, 0.005, (0, ry, 0))
    # Floating data cube
    _add_box(stage, "/Holodevice/holo_cube", 0.06, 0.06, 0.06, (0, 0.32, 0))
    # Side detail (LEDs)
    for k in range(4):
        ang = k * math.pi / 2
        _add_sphere(stage, f"/Holodevice/led_{k}", 0.008,
                     (0.105 * math.cos(ang), 0.03, 0.105 * math.sin(ang)))
    stage.GetRootLayer().Save()
    print(f"  ✓ {out.name}  ({sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))} meshes)")


# ─── 7. world.jsonld — semantic metadata ────────────────────────────────
def build_world_jsonld():
    world = {
        "@context": {"@vocab": "https://ghosthacker.gftd.ai/schema/"},
        "@type": "World",
        "schemaVersion": "0.2",
        "lastUpdated": "2026-05-23",
        "school": {
            "name": "Akabane Tech High School (赤羽工業高校)",
            "type": "private high school (TBT 私立)",
            "city": "Tokyo, Kita-ku, Akabane",
            "established": 1987,
            "grades": ["1", "2", "3"],
            "classes_per_grade": 4,
            "students_per_class": 30,
            "main_characters_class": "3-B",
            "uniform": {
                "season": "summer",
                "male": {
                    "top": "short-sleeve white shirt with school crest",
                    "bottom": "dark navy slacks",
                    "shoes": "black loafers",
                    "accent": "loose dark-blue tie (worn casually open at neck)"
                },
                "female": {
                    "top": "short-sleeve sailor blouse navy/white",
                    "bottom": "pleated navy skirt knee-length",
                    "shoes": "white knee socks + black loafers",
                    "accent": "red ribbon tie"
                },
                "PE_kit": "navy/white tracksuit with school name printed"
            },
            "classroom_3B": {
                "desk_grid": {"rows": 5, "cols": 6, "spacing_m": [1.0, 1.2]},
                "blackboard_position": "north wall, opposite to door",
                "windows": "west wall (afternoon sun)",
                "door": "south wall, slides left",
                "seat_order_by_kana": True,
                "seats": [
                    {"row": 1, "col": 1, "student": "Akabane Akira", "trait": "loud, fashion-obsessed"},
                    {"row": 1, "col": 4, "student": "Numano Yuto", "trait": "anxious, smartphone-addicted"},
                    {"row": 2, "col": 2, "student": "Shirase Nei",  "trait": "calm, perceptive"},
                    {"row": 2, "col": 5, "student": "Fujisaki Ren",  "trait": "sleepy, hacker-prodigy"},
                    {"row": 3, "col": 3, "student": "Saki Marin",   "trait": "skeptical, fashion-critic"}
                ]
            }
        },
        "tokyo_2026": {
            "year": 2026,
            "general_mood": "near-future cyberpunk-lite, AR overlays normalized",
            "key_districts": ["Akabane", "Shibuya", "Akihabara", "Shinjuku"],
            "infrastructure": ["bullet trains", "elevated highway", "5G+ AR mesh"]
        },
        "ghost_entity": {
            "@type": "SupernaturalEntity",
            "name_jp": "幽霊 (Yuurei) — Ghost",
            "appearance": "floating translucent humanoid silhouette, wispy lower body, glowing eyes",
            "size_m": 1.7,
            "behavior": "appears in liminal moments, drawn to networked emotional distress"
        },
        "daemon_entity": {
            "@type": "SupernaturalEntity",
            "name_jp": "悪魔 (Akuma) — Daemon",
            "appearance": "imp-creature with small horns, bat wings, tail, glowing eyes",
            "size_m": 0.7,
            "behavior": "lurks in dark data, manifests near corrupted code"
        },
        "holodevice": {
            "@type": "TechArtifact",
            "name_jp": "ホロデバイス",
            "form": "palm-disc projector",
            "size_m": [0.10, 0.40, 0.10],
            "projection": "stacked translucent rings + floating data cube, AR overlay"
        },
        "casual_clothing": {
            "yuto_home": "loose dark hoodie + grey sweatpants + house slippers",
            "ren_home":  "oversized black t-shirt + cargo shorts (always at PC)",
            "nei_home":  "white oversized sweater + denim shorts + thigh-high socks",
            "akira_home":"sleeveless graphic tee + jeans + designer sneakers"
        }
    }
    WORLD_JSON.write_text(json.dumps(world, indent=2, ensure_ascii=False))
    print(f"  ✓ {WORLD_JSON.name}  (schoolName={world['school']['name']})")


if __name__ == "__main__":
    print("Building world elements:")
    build_neis_room()
    build_tokyo_zenkei()
    build_school_exterior()
    build_ghost()
    build_daemon()
    build_holodevice()
    build_world_jsonld()
    print("Done.")

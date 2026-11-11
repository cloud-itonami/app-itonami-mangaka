"""Enrich the existing yuto-bedroom.usda with UsdLux lights + named
UsdGeomCamera prims so the new MangakaUSDLight and MangakaUSDCameraPrim
nodes have data to consume."""
from pathlib import Path
from pxr import Usd, UsdGeom, UsdLux, Gf, Sdf
import math

PATH = Path("/tmp/arc01-scenes/yuto-bedroom.usda")
stage = Usd.Stage.Open(str(PATH))
root = stage.GetDefaultPrim()

# Add a Lights xform
lights = UsdGeom.Xform.Define(stage, "/Bedroom/Lights")

# Window light (rect on north wall) — primary key light
window_light = UsdLux.RectLight.Define(stage, "/Bedroom/Lights/window")
window_light.GetIntensityAttr().Set(2500.0)
window_light.GetWidthAttr().Set(1.2)
window_light.GetHeightAttr().Set(1.5)
xf = UsdGeom.XformCommonAPI(window_light)
xf.SetTranslate((2.5, 1.65, 0.1))  # at window position (north wall)
xf.SetRotate((0, 0, 0))

# Desk lamp (point light) — secondary fill
lamp = UsdLux.SphereLight.Define(stage, "/Bedroom/Lights/desk_lamp")
lamp.GetIntensityAttr().Set(600.0)
lamp.GetRadiusAttr().Set(0.05)
xf2 = UsdGeom.XformCommonAPI(lamp)
xf2.SetTranslate((3.75, 1.30, 1.5))  # at lamp shade position

# Ceiling fill light (low intensity)
ceil_fill = UsdLux.DistantLight.Define(stage, "/Bedroom/Lights/ceiling_fill")
ceil_fill.GetIntensityAttr().Set(200.0)
xf3 = UsdGeom.XformCommonAPI(ceil_fill)
xf3.SetTranslate((2.0, 2.5, 2.0))


# --- Named cameras (UsdGeomCamera prims) ----------------------------------
def make_camera(name, origin, target, fov_deg):
    """Make a UsdGeomCamera looking from origin to target with the given FOV."""
    cam = UsdGeom.Camera.Define(stage, f"/Bedroom/Cameras/{name}")
    # focal length / aperture choices that give the requested FOV (h_aperture=36mm)
    h_aperture = 36.0
    focal = h_aperture / (2 * math.tan(math.radians(fov_deg) / 2))
    cam.GetFocalLengthAttr().Set(focal)
    cam.GetHorizontalApertureAttr().Set(h_aperture)
    cam.GetVerticalApertureAttr().Set(24.0)
    # Build a lookAt matrix
    eye = Gf.Vec3d(*origin)
    tgt = Gf.Vec3d(*target)
    up = Gf.Vec3d(0, 1, 0)
    # Construct rotation: forward = (target-eye).normalize, right = forward×up, up' = right×forward
    fwd = (tgt - eye).GetNormalized()
    right = Gf.Cross(fwd, up).GetNormalized()
    real_up = Gf.Cross(right, fwd).GetNormalized()
    # Camera looks down -Z in its local frame, so:
    rot = Gf.Matrix3d(
        right[0],   right[1],   right[2],
        real_up[0], real_up[1], real_up[2],
        -fwd[0],    -fwd[1],    -fwd[2],
    )
    # Combine into a 4x4
    m = Gf.Matrix4d(1).SetIdentity()
    m.SetRotateOnly(rot)
    m.SetTranslateOnly(eye)
    xf = UsdGeom.Xformable(cam)
    xf.ClearXformOpOrder()
    op = xf.AddTransformOp()
    op.Set(m)


# Five named angles matching what build-yuto-bedroom.py used
make_camera("establish_wide", (0.5, 1.6, 0.5),  (2.0, 0.7, 2.0), 70.0)
make_camera("yuto_at_desk",   (1.0, 1.5, 1.3),  (3.7, 0.85, 2.1), 50.0)
make_camera("phone_closeup",  (3.4, 1.0, 2.4),  (3.6, 0.785, 2.1), 35.0)
make_camera("room_overhead",  (2.5, 2.3, 1.5),  (2.0, 0.5, 2.0), 70.0)
make_camera("window_view",    (2.5, 1.4, 0.5),  (2.0, 1.0, 3.0), 60.0)

stage.GetRootLayer().Save()
print(f"saved: {PATH} ({PATH.stat().st_size//1024} KB)")

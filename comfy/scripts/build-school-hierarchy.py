"""Compose school exterior + classroom into a hierarchical USD.

Adds the missing spatial relationship: school building (parent) →
classroom 3-B (child Xform at floor 3, west wing). Sun direction
then computes correctly per the building's orientation, and the
classroom interior receives light through its WEST window.

Output:
  data/.../usd/school-hierarchy.usda
    /School (UsdGeomXform)
      /School/Exterior  (references school-exterior.usda)
      /School/Floor3
        /School/Floor3/Classroom_3B  (references classroom.usda
                                       at world position floor 3
                                       west wing)
"""
from pathlib import Path
from pxr import Usd, UsdGeom, UsdLux, Gf, Sdf
import math

USD_DIR = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/usd")
OUT = USD_DIR / "school-hierarchy.usda"


def main():
    stage = Usd.Stage.CreateNew(str(OUT))
    stage.SetMetadata("upAxis", "Y")
    UsdGeom.Xform.Define(stage, "/School")
    stage.SetDefaultPrim(stage.GetPrimAtPath("/School"))

    # Exterior reference — at origin
    ext = UsdGeom.Xform.Define(stage, "/School/Exterior")
    ext.GetPrim().GetReferences().AddReference("./school-exterior.usda")

    # Floor 3 west wing — classroom positioned in building space
    #   school-exterior: main_block 50m wide × 18m tall (5 floors × 3.5m)
    #   floor 3 starts at y=10.5m, ends at y=14m
    #   west wing = x in [-25..-5], so classroom centered at x=-15
    #   classroom-3B local origin is (0,0,0); offset to (-15, 10.5, 0)
    floor3 = UsdGeom.Xform.Define(stage, "/School/Floor3")
    floor3_op = floor3.AddTranslateOp()
    floor3_op.Set((0.0, 10.5, 0.0))

    # Classroom 3B — child of Floor3, placed at west wing
    classroom = UsdGeom.Xform.Define(stage, "/School/Floor3/Classroom_3B")
    cr_op = classroom.AddTranslateOp()
    # Move classroom to west wing inside the building
    cr_op.Set((-15.0, 0.0, -8.0))
    classroom.GetPrim().GetReferences().AddReference("./classroom.usda")

    # Sun — world-level UsdLuxDistantLight oriented by afternoon azimuth
    sun_light = UsdLux.DistantLight.Define(stage, "/School/Lights/Sun")
    sun_light.GetIntensityAttr().Set(3500.0)
    sun_light.GetAngleAttr().Set(0.5)   # solar disk size
    # Sun rotation: 45° altitude, 240° azimuth (WSW afternoon Japan)
    sun_xf = UsdGeom.Xformable(sun_light)
    sun_xf.AddRotateXYZOp().Set((-(90 - 45), -(240 - 180), 0))

    # Window aperture light — at classroom's west wall, derived from sun
    # The classroom has a window on its WEST wall (local x=0 in classroom
    # coords). After parent transforms: classroom local (0, 1.5, 2.0) →
    # world (-15, 12.0, -6.0) approximately.
    win_light = UsdLux.RectLight.Define(stage, "/School/Floor3/Classroom_3B/WindowSunLight")
    win_light.GetIntensityAttr().Set(8000.0)
    win_light.GetWidthAttr().Set(1.4)
    win_light.GetHeightAttr().Set(1.5)
    # Orient window-light to face INTO classroom (along +x direction)
    win_xf = UsdGeom.XformCommonAPI(win_light)
    win_xf.SetTranslate((-0.1, 1.5, 2.0))
    win_xf.SetRotate((0, 90, 0))   # face +X (inward)

    stage.GetRootLayer().Save()

    # Verify
    s = Usd.Stage.Open(str(OUT))
    prim_count = sum(1 for p in s.Traverse())
    mesh_count = sum(1 for p in s.Traverse() if p.IsA(UsdGeom.Mesh))
    cam_count = sum(1 for p in s.Traverse() if p.IsA(UsdGeom.Camera))
    light_count = sum(1 for p in s.Traverse()
                       if "Light" in p.GetTypeName())
    print(f"OK: {OUT}")
    print(f"  total prims: {prim_count}")
    print(f"  meshes:      {mesh_count} (resolved through references)")
    print(f"  cameras:     {cam_count}")
    print(f"  lights:      {light_count}")
    print(f"  size:        {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()

"""Blender headless Freestyle NPR renderer — runs INSIDE Blender as a
bpy script. Invoke from LangGraph render_panel node:

  blender -b -P blender_freestyle_render.py -- \
    --usd /path/to/scene.usda \
    --camera /Bedroom/Cameras/yuto_at_desk \
    --emotion anxious \
    --tension 0.85 \
    --out /tmp/panel.png

This is the alternative `render_panel` backend to ComfyUI subprocess.
Picked when:
  - BLENDER_AVAILABLE env flag set
  - panel intent has explicit `npr=true` annotation (no AI assist)
  - NPR pass separation needed (Beauty / Ink / Tone / Motion-line)

Outputs separate render passes per panel:
  panel-beauty.png        Blender Cycles beauty
  panel-ink.png           Freestyle line render
  panel-tone.png          Grease Pencil screentone fill
  panel-depth.png         Depth EXR (for ControlNet feedback)
  panel-normal.png        Normal pass (for edge enhancement)
  panel-motion.png        Motion vector pass (for speed-line overlay)

The composite_page node in LangGraph blends these via PIL:
  start = beauty * 0.05 + ink * 1.0 + tone * 0.5
  if tension > 0.8: add_speed_lines(motion_vector)
  if emotion == "panic": distort_perspective(0.3)

This file is a scaffold — actual bpy implementation deferred to the
next iteration once Blender 4.x is installed on the host or the
LangGraph pod is rebuilt with `apt install blender`.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# This script is intended to run inside Blender's bpy interpreter.
# Mark its dependencies as soft so the file can be imported on Mac for
# inspection / linting without Blender installed.
try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usd", required=True, help="USD scene file")
    parser.add_argument("--camera", required=True, help="UsdGeomCamera prim path")
    parser.add_argument("--emotion", default="neutral")
    parser.add_argument("--tension", type=float, default=0.0)
    parser.add_argument("--shot", default="MS")
    parser.add_argument("--out", required=True, help="output PNG path")
    parser.add_argument("--width", type=int, default=1216)
    parser.add_argument("--height", type=int, default=832)
    args = parser.parse_args(argv)

    if not BLENDER_AVAILABLE:
        print("ERROR: bpy not available — run this script via `blender -b -P ...`")
        return 1

    # Stage 1: load USD via Blender 4.x USD importer
    bpy.ops.wm.usd_import(filepath=args.usd)

    # Stage 2: set active camera from USD camera prim
    cam_obj = None
    for obj in bpy.data.objects:
        if obj.type == "CAMERA" and args.camera.split("/")[-1] in obj.name:
            cam_obj = obj
            break
    if cam_obj is None:
        print(f"ERROR: camera not found at {args.camera}")
        return 1
    bpy.context.scene.camera = cam_obj

    # Stage 3: enable Freestyle line render
    scene = bpy.context.scene
    scene.render.use_freestyle = True
    view_layer = scene.view_layers[0]
    view_layer.use_freestyle = True
    lineset = view_layer.freestyle_settings.linesets.new("MangaInk")
    lineset.select_silhouette = True
    lineset.select_border = True
    lineset.select_contour = True
    lineset.select_crease = True
    linestyle = lineset.linestyle
    linestyle.color = (0, 0, 0)
    linestyle.thickness = 2.5 + 1.5 * args.tension  # tension → thicker lines
    linestyle.use_chaining = True

    # Stage 4: B&W look — convert all materials to flat shadeless white
    for mat in bpy.data.materials:
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    node.inputs["Base Color"].default_value = (1, 1, 1, 1)
                    node.inputs["Roughness"].default_value = 1.0

    # Stage 5: emotion-driven adjustments
    if args.emotion == "panic" and args.tension > 0.7:
        # Add subtle camera dutch tilt
        cam_obj.rotation_euler[2] += 0.1
    if args.emotion == "shocked":
        # Pull camera in slightly + bump fov
        cam_obj.data.angle += 0.05

    # Stage 6: render Beauty + Freestyle pass
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "BW"
    scene.render.filepath = args.out
    bpy.ops.render.render(write_still=True)

    # Stage 7 (deferred): separate ink / tone / depth / motion passes
    # via Compositor node tree. Skipping in scaffold — single combined PNG.

    print(f"OK render: {args.out}")
    return 0


if __name__ == "__main__":
    # bpy passes script args after `--`
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = sys.argv[1:]
    sys.exit(main(argv) or 0)

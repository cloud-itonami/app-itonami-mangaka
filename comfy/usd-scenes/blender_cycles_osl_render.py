"""Blender Cycles + OSL NPR renderer — manga pipeline v5 backend.

Runs INSIDE Blender as a bpy script:

    blender -b -P blender_cycles_osl_render.py -- \
        --usd /path/to/yuto-bedroom.usda \
        --camera /Bedroom/Cameras/yuto_at_desk \
        --osl-dir /path/to/lg/scripts/usd-scenes/osl/ \
        --out /tmp/panel.png

This is the manga NPR equivalent of the Pixar RenderMan pipeline:

  Narrative USD (with customData)
       ↓
  MaterialX network (manga-ink.mtlx)
       ↓
  OSL shaders (manga_line_weight + manga_screentone)
       ↓
  Blender Cycles backend
       ↓
  PNG panel output

The script:
  1. Loads USD scene including the narrative customData layer.
  2. Switches Blender engine to Cycles + OSL enabled.
  3. Imports each MaterialX-defined surface as a Cycles material
     graph backed by compiled OSL shaders (.oso).
  4. Reads narrative:emotion / narrative:tension from each prim
     and binds them as material inputs.
  5. Renders + writes PNG.
  6. (Optional) Renders separate passes: Beauty / Ink / Tone /
     Depth / Normal / Motion — composited downstream by LangGraph
     composite_page node.

Production: Blender 4.x with USD plugin and Cycles+OSL must be
installed on the render host. For LangGraph cloud deployment use
the official Blender Docker image; for local Mac dev install via
`brew install blender`.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

try:
    import bpy
    BLENDER = True
except ImportError:
    BLENDER = False


def setup_cycles_osl():
    """Switch engine to Cycles + enable OSL shading."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.shading_system = True  # OSL on
    scene.cycles.device = "CPU"          # OSL is CPU-only in Cycles
    scene.cycles.samples = 64            # NPR doesn't need photoreal sampling


def bind_osl_to_material(mat_name: str, osl_path: Path):
    """Replace a material's surface shader with a compiled OSL script."""
    mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Output node
    out_node = nodes.new("ShaderNodeOutputMaterial")
    out_node.location = (300, 0)

    # OSL Script node
    osl_node = nodes.new("ShaderNodeScript")
    osl_node.location = (0, 0)
    osl_node.mode = "EXTERNAL"
    osl_node.filepath = str(osl_path)

    links.new(osl_node.outputs[0], out_node.inputs[0])
    return mat


def apply_narrative_attrs(prim_data: dict):
    """Walk Blender objects, look up customData (carried from USD
    import as object/material custom props), and set OSL inputs."""
    for obj in bpy.data.objects:
        # USD importer puts customData under obj.get("usd:customData")
        meta = obj.get("usd:customData", {}) or {}
        emotion = meta.get("narrative:emotion")
        tension = meta.get("narrative:tension")
        if emotion or tension:
            print(f"  apply narrative to {obj.name}: emotion={emotion} tension={tension}")
            # Find material(s) on the object and tweak OSL inputs
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat.use_nodes:
                    for node in mat.node_tree.nodes:
                        if node.type == "SCRIPT":
                            if "tension" in node.inputs and tension is not None:
                                node.inputs["tension"].default_value = float(tension)
                            if "emotion" in node.inputs and emotion is not None:
                                node.inputs["emotion"].default_value = str(emotion)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usd", required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--osl-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=1216)
    parser.add_argument("--height", type=int, default=832)
    parser.add_argument("--separate-passes", action="store_true",
                          help="render Beauty / Ink / Tone / Depth / Normal / Motion separately")
    args = parser.parse_args(argv)

    if not BLENDER:
        print("ERROR: this script must run inside Blender (bpy unavailable)")
        return 1

    # 1. Engine + OSL
    setup_cycles_osl()

    # 2. Load USD with narrative customData
    bpy.ops.wm.usd_import(filepath=args.usd, import_cameras=True,
                            import_lights=True, import_materials=True,
                            import_meshes=True)

    # 3. Find target camera prim by name suffix
    cam_obj = None
    for obj in bpy.data.objects:
        if obj.type == "CAMERA" and args.camera.split("/")[-1] in obj.name:
            cam_obj = obj
            break
    if cam_obj is None:
        print(f"ERROR: camera {args.camera} not found")
        return 1
    bpy.context.scene.camera = cam_obj

    # 4. Bind OSL shaders to manga materials
    osl_dir = Path(args.osl_dir)
    bind_osl_to_material("MangaInk", osl_dir / "manga_line_weight.osl")
    bind_osl_to_material("MangaScreentone", osl_dir / "manga_screentone.osl")

    # 5. Push narrative customData onto OSL material inputs
    apply_narrative_attrs({})

    # 6. Render
    scene = bpy.context.scene
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "BW"

    if args.separate_passes:
        # Enable render passes via compositor + view layer
        view_layer = scene.view_layers[0]
        view_layer.use_pass_z = True
        view_layer.use_pass_normal = True
        view_layer.cycles.use_pass_freestyle = True
        # Single render — composited passes saved by Blender's File Output node
        # (compositor setup deferred to next iteration)

    scene.render.filepath = args.out
    bpy.ops.render.render(write_still=True)
    print(f"OK render: {args.out}")
    return 0


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = sys.argv[1:]
    sys.exit(main(argv) or 0)

"""Blender Grease Pencil Line Art renderer for manga panels.

User: NPR Shader と Blender Grease Pencil, Open Toonz を統合.

Blender Grease Pencil (GP) is a native 2D drawing system inside the
3D scene. GP "Line Art" modifier traces edges from 3D meshes and
emits them as VECTOR strokes — exactly what we need for manga ink
output that doesn't require SDXL post-processing.

Pipeline using GP:
  USD scene + mannequins (3D)
    ↓
  Grease Pencil "Line Art" object that traces ALL meshes
    ↓
  GP strokes with variable line weight (silhouette + edge)
    ↓
  Direct render → manga line art (no SDXL needed)
    ↓
  Optional: OSL screentone fill via material assignment
    ↓
  Composite + bubble overlay

This file is the Blender script template — embedded as a string in
render-v5-page.py BLENDER_SCRIPT when V5_BASE=grease_pencil.

Usage flag: V5_BASE=grease_pencil
"""

# The actual Blender script content (string, written to /tmp by
# render-v5-page.py):
GREASE_PENCIL_BLENDER_SCRIPT = '''
import bpy, sys, os, mathutils, json, math
args = json.loads(sys.argv[sys.argv.index("--")+1])

# Clear default scene
bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete()
for m in list(bpy.data.materials): bpy.data.materials.remove(m)

scene = bpy.context.scene

# Use EEVEE for fast GP render (GP doesn't need Cycles).
for eng in ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"]:
    try: scene.render.engine = eng; break
    except: continue

# Pure white world (manga paper)
if scene.world is None:
    scene.world = bpy.data.worlds.new("Paper")
scene.world.use_nodes = True
bg = scene.world.node_tree.nodes.get("Background")
if bg: bg.inputs[0].default_value = (1, 1, 1, 1)

# Import USD scene
bpy.ops.wm.usd_import(filepath=args["usd"],
                       import_cameras=True, import_lights=True,
                       import_materials=False, import_meshes=True, scale=100.0)

# Import mannequins
for mq in (args.get("mannequins") or []):
    n_before = set(o.name for o in bpy.data.objects)
    bpy.ops.wm.usd_import(filepath=mq["usd"],
                           import_cameras=False, import_lights=False,
                           import_materials=False, import_meshes=True,
                           scale=100.0)
    n_after = set(o.name for o in bpy.data.objects)
    new_names = n_after - n_before
    px, py, pz = mq["pos"]
    sc = mq.get("scale", 2.5)
    for nm in new_names:
        obj = bpy.data.objects.get(nm)
        if obj and obj.type == "MESH":
            obj.scale = (sc, sc, sc)
            obj.location.x = obj.location.x * sc + px
            obj.location.y = obj.location.y * sc + -pz
            obj.location.z = obj.location.z * sc + py

# Set all meshes to white emission (so GP line art reads clean edges)
white = bpy.data.materials.new("Paper")
white.use_nodes = True
white.node_tree.nodes.clear()
out = white.node_tree.nodes.new("ShaderNodeOutputMaterial")
emit = white.node_tree.nodes.new("ShaderNodeEmission")
emit.inputs[0].default_value = (1, 1, 1, 1)
emit.inputs[1].default_value = 0.5
white.node_tree.links.new(emit.outputs[0], out.inputs[0])
for obj in bpy.data.objects:
    if obj.type == "MESH":
        obj.data.materials.clear()
        obj.data.materials.append(white)

# Add Grease Pencil v3 object + Line Art modifier (Blender 5.1+ API).
bpy.ops.object.grease_pencil_add(type="EMPTY")
gp_obj = bpy.context.active_object
gp_obj.name = "MangaLineArt"

# Line Art modifier — uses scene-wide edge detection (depth-pass).
try:
    la_mod = gp_obj.modifiers.new("LineArt", "LINEART")
    la_mod.use_intersection = True
    la_mod.use_contour = True
    la_mod.use_crease = True
    la_mod.use_edge_mark = True
    la_mod.crease_threshold = math.radians(140)
    la_mod.source_type = "SCENE"
    print(f"  LINEART modifier attached")
except Exception as e:
    print(f"  LINEART modifier FAIL: {e}")

# Bake the line art into strokes (Blender 5.1 requires explicit bake).
try:
    bpy.ops.object.lineart_bake_strokes()
    print(f"  lineart strokes baked")
except Exception as e:
    print(f"  lineart bake FAIL: {e}")

# Force GP layer + material so strokes render
gp_data = gp_obj.data
if gp_data and not gp_data.materials:
    mat = bpy.data.materials.new("BlackInk")
    bpy.data.materials.create_gpencil_data(mat) if hasattr(bpy.data.materials, "create_gpencil_data") else None
    if mat.grease_pencil:
        mat.grease_pencil.color = (0, 0, 0, 1)
        mat.grease_pencil.show_stroke = True
    gp_data.materials.append(mat)

# Camera setup (from spec)
cam_origin = args.get("cam_origin", [3, 1.5, 2])
cam_target = args.get("cam_target", [4, 1, 3.5])
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = args.get("lens", 35)
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
def usd_to_blender(v): return (v[0], -v[2], v[1])
cam.location = usd_to_blender(cam_origin)
tgt_v = mathutils.Vector(usd_to_blender(cam_target)) - cam.location
rot = tgt_v.to_track_quat("-Z", "Y")
cam.rotation_euler = rot.to_euler()
scene.camera = cam

# Output settings
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "BW"
scene.render.resolution_x = args.get("width", 1280)
scene.render.resolution_y = args.get("height", 720)
scene.render.resolution_percentage = 100
scene.render.filepath = args["out"]

# Hide source meshes AFTER line art bake (otherwise nothing to trace).
for obj in bpy.data.objects:
    if obj.type == "MESH":
        obj.hide_render = True
# Move GP object to layer 0 + ensure visible
gp_obj.hide_render = False
gp_obj.hide_viewport = False

bpy.ops.render.render(write_still=True)
print(f"OK GP render: {args['out']}")
'''

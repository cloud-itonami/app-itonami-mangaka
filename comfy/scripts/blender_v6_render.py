
import bpy, sys, os, mathutils, json, math
args = json.loads(sys.argv[sys.argv.index("--")+1])

# Clear scene
bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete()
for m in list(bpy.data.materials): bpy.data.materials.remove(m)

scene = bpy.context.scene

# EEVEE for fast NPR base
for eng in ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"]:
    try: scene.render.engine = eng; chosen = eng; break
    except: continue

# Pure white world (manga paper)
if scene.world is None:
    scene.world = bpy.data.worlds.new("Paper")
scene.world.use_nodes = True
bg = scene.world.node_tree.nodes.get("Background")
if bg: bg.inputs[0].default_value = (1, 1, 1, 1)

# Freestyle ON for outline
scene.render.use_freestyle = True
view_layer = bpy.context.view_layer
view_layer.use_freestyle = True
for fls in view_layer.freestyle_settings.linesets:
    fls.linestyle.thickness = float(args.get("ridge", 2.0))

# Import USD scene
bpy.ops.wm.usd_import(filepath=args["usd"],
                       import_cameras=True, import_lights=True,
                       import_materials=False, import_meshes=True, scale=100.0)

# Import mannequins
for mq in (args.get("mannequins") or []):
    n_before = set(o.name for o in bpy.data.objects)
    bpy.ops.wm.usd_import(filepath=mq["usd"],
                           import_cameras=False, import_lights=False,
                           import_materials=False, import_meshes=True, scale=100.0)
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

# ───── NPR Toon Shader ─────
# Per-object cell-shaded material using ShaderNodeBSDFToon.
# Diffuse Toon BSDF gives flat hard-edge shadow boundaries —
# the actual look of cell-shaded anime / manga base.
def make_toon_material(name, base_color, shadow_threshold=0.3):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    # Toon BSDF (only available in Cycles, fallback to Diffuse for EEVEE).
    # For EEVEE we approximate with a Diffuse BSDF + ColorRamp clamping.
    if scene.render.engine.startswith("CYCLES"):
        toon = nt.nodes.new("ShaderNodeBsdfToon")
        toon.component = "DIFFUSE"
        toon.inputs["Color"].default_value = (*base_color, 1.0)
        toon.inputs["Size"].default_value = shadow_threshold
        toon.inputs["Smooth"].default_value = 0.05
        nt.links.new(toon.outputs[0], out.inputs[0])
    else:
        # EEVEE NPR via diffuse + ColorRamp posterize
        diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
        diffuse.inputs["Color"].default_value = (*base_color, 1.0)
        # Add a ColorRamp to posterize the diffuse output via shader-to-rgb
        # bridge (shader_to_rgb is post-shading, gives a value to remap).
        s2rgb = nt.nodes.new("ShaderNodeShaderToRGB")
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "CONSTANT"   # hard cell boundary
        # 2-band cell shading: shadow (dark) / light (base)
        ramp.color_ramp.elements[0].color = tuple(c*0.45 for c in base_color) + (1.0,)
        ramp.color_ramp.elements[1].position = shadow_threshold
        ramp.color_ramp.elements[1].color = (*base_color, 1.0)
        emission = nt.nodes.new("ShaderNodeEmission")
        emission.inputs["Strength"].default_value = 1.0
        nt.links.new(diffuse.outputs[0], s2rgb.inputs[0])
        nt.links.new(s2rgb.outputs[0], ramp.inputs[0])
        nt.links.new(ramp.outputs[0], emission.inputs[0])
        nt.links.new(emission.outputs[0], out.inputs[0])
    return mat

# Per-mesh color mapping (heuristic by name)
color_map = [
    ("floor",     (0.62, 0.50, 0.38)),
    ("wall",      (0.92, 0.90, 0.85)),
    ("ceiling",   (0.95, 0.95, 0.92)),
    ("desk",      (0.55, 0.40, 0.27)),
    ("chair",     (0.50, 0.35, 0.25)),
    ("blackboard",(0.18, 0.22, 0.20)),
    ("window",    (0.85, 0.92, 0.95)),
    ("bed",       (0.65, 0.55, 0.45)),
    ("mattress",  (0.92, 0.88, 0.80)),
    ("blanket",   (0.40, 0.45, 0.65)),
    ("phone",     (0.18, 0.18, 0.18)),
    ("lamp",      (0.80, 0.70, 0.50)),
    ("road",      (0.35, 0.35, 0.35)),
    ("building",  (0.75, 0.70, 0.60)),
    ("ground",    (0.50, 0.45, 0.40)),
]
default_toon = make_toon_material("DefaultToon", (0.70, 0.70, 0.72))
mat_cache = {}
for obj in bpy.data.objects:
    if obj.type != "MESH": continue
    obj_lower = obj.name.lower()
    assigned = None
    for key, color in color_map:
        if key in obj_lower:
            if key not in mat_cache:
                mat_cache[key] = make_toon_material(f"Toon_{key}", color)
            assigned = mat_cache[key]
            break
    if assigned is None:
        assigned = default_toon
    obj.data.materials.clear()
    obj.data.materials.append(assigned)

# Mannequins get distinct char material
mannequin_toon = make_toon_material("ToonChar", (0.85, 0.78, 0.70), shadow_threshold=0.4)
for obj in bpy.data.objects:
    if obj.type == "MESH" and "Character" in obj.name or "Mannequin" in obj.name:
        obj.data.materials.clear()
        obj.data.materials.append(mannequin_toon)

# ───── Geometry Nodes overlays (optional, V6_GEONODES=1) ─────
if os.environ.get("V6_GEONODES", "0") == "1":
    # Add procedural panel-border decoration as Geometry Nodes object.
    # This is a minimal scaffold; full screentone overlay would need
    # mesh attribute → screen-space UV mapping which is a deeper graph.
    bpy.ops.mesh.primitive_plane_add(size=0.01)
    gn_obj = bpy.context.active_object
    gn_obj.name = "GN_Overlay"
    gn_mod = gn_obj.modifiers.new("GeoNodes", "NODES")
    # Create a minimal geometry node graph that does nothing visible —
    # placeholder. Full screentone/motion-lines GN graph is V6+.
    print(f"  GN scaffold attached: {gn_obj.name}")

# ───── Lighting (NPR-appropriate) ─────
sun_alt = math.radians(args.get("sun_altitude_deg", 55))
sun_az  = math.radians(args.get("sun_azimuth_deg", 240))
sun_data = bpy.data.lights.new("Sun", "SUN")
sun_data.energy = 3.0
sun_data.angle = 0.05
sun_obj = bpy.data.objects.new("Sun", sun_data)
scene.collection.objects.link(sun_obj)
sun_obj.rotation_euler = (math.pi/2 - sun_alt, 0, sun_az - math.pi)

# Fill (so dark side has cell-shade, not pure black)
fill_data = bpy.data.lights.new("Fill", "SUN")
fill_data.energy = 0.8
fill_data.angle = 1.0
fill_obj = bpy.data.objects.new("Fill", fill_data)
scene.collection.objects.link(fill_obj)
fill_obj.rotation_euler = (math.pi/2 - sun_alt * 0.5, 0, sun_az)

# Camera
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

scene.render.resolution_x = args.get("width", 1280)
scene.render.resolution_y = args.get("height", 720)
scene.render.resolution_percentage = 100
scene.render.filepath = args["out"]

bpy.ops.render.render(write_still=True)
print(f"OK v6 render: {args['out']} engine={chosen}")

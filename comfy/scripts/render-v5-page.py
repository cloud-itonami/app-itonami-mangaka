"""v5 page renderer + character mannequin + bubble overlay + ReAct score loop.

Improvements over previous v5:
  1. Mannequin USD (cylinder+box+sphere humanoid) loaded alongside
     scene USD per panel — fixes "no character mesh" blocker.
  2. PIL bubble overlay with vertical Japanese text drawn at the
     panel corner — fixes "no bubble overlay" blocker.
  3. ReAct score loop unchanged but now tracks both blockers as
     resolved.
  4. Cycles+OSL toggle (env BLENDER_CYCLES_OSL=1) — Blender 5.1's
     bundled OSL compiler picks up our .osl files via
     ShaderNodeScript EXTERNAL mode.
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
USD_DIR  = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/usd")
USD_DIR_ALT = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/usd")
MANNEQUIN_SEATED = Path("/tmp/character-mannequin-seated.usda")
MANNEQUIN_STAND  = Path("/tmp/character-mannequin-standing.usda")

PAGE_W, PAGE_H = 1280, 1817
MARGIN, GUTTER = 40, 16
# 2026-05-26: Death Note-style continuous gutter — intra-row tight, inter-row loose
# (user feedback: "コマ割りのパターンを 余白を繋がるように")
INTRA_GUTTER = 6   # between panels in the same row (tight, panels almost touch)
INTER_GUTTER = 32  # between rows (loose, defines reading rhythm)
SIZE_UNIT = {"small": 1, "medium": 2, "large": 3, "spread": 6}

SCENE_MAPPING = {
    0:"yuto-bedroom",1:"school-hierarchy",2:"school-hierarchy",3:"city-street",
    4:"yuto-bedroom",5:"yuto-bedroom",6:"rens-room",7:"rens-room",
    8:"yuto-bedroom",9:"city-street",
}

# Per-scene: where the focal character sits/stands
SCENE_CHARACTER = {
    "yuto-bedroom":  {"pose": "seated", "pos": (3.0, 0.0, 2.0)},   # at desk
    "classroom":     {"pose": "seated", "pos": (4.0, 0.0, 3.5)},   # at student desk
    "rens-room":     {"pose": "seated", "pos": (2.8, 0.0, 2.5)},
    "city-street":   {"pose": "standing", "pos": (5.0, 0.0, 12.0)},
    "akabane-shrine":{"pose": "standing", "pos": (7.5, 0.0, 3.5)},
}

SCENE_CAMS = {
    "yuto-bedroom": {
        "ECU":   [((3.2, 1.4, 2.4), (3.0, 1.0, 2.0))],  # face close
        "CU":    [((2.5, 1.4, 2.0), (3.0, 1.0, 2.0))],
        "MS":    [((1.5, 1.5, 1.0), (3.0, 1.0, 2.0))],
        "LS":    [((0.5, 1.7, 0.5), (2.5, 0.8, 2.0))],
        "Wide":  [((0.5, 1.8, 0.5), (2.5, 0.5, 2.5))],
        "default": [((1.5, 1.5, 1.0), (3.0, 1.0, 2.0))],
    },
    "classroom": {
        "CU":    [((4.0, 1.5, 5.0), (4.0, 1.4, 3.5))],
        "MS":    [((4.0, 1.6, 6.5), (4.0, 1.3, 3.5))],
        "LS":    [((4.0, 1.7, 7.5), (4.0, 1.3, 3.5))],
        "Wide":  [((1.5, 2.0, 8.0), (4.5, 1.0, 3.5))],
        "default":[((4.0, 1.6, 6.5), (4.0, 1.3, 3.5))],
    },
    "city-street": {
        "Wide":  [((5.0, 1.6, 8.0), (5.0, 1.6, 14.0))],
        "LS":    [((5.0, 1.6, 9.0), (5.0, 1.5, 13.0))],
        "MS":    [((5.0, 1.6, 10.5), (5.0, 1.5, 12.0))],
        "CU":    [((5.0, 1.5, 11.0), (5.0, 1.5, 12.0))],
        "default":[((5.0, 1.6, 10.5), (5.0, 1.5, 12.0))],
    },
    "rens-room": {
        "MS":    [((1.5, 1.5, 2.1), (3.8, 0.9, 2.5))],
        "default":[((1.5, 1.5, 2.1), (3.8, 0.9, 2.5))],
    },
}


def pick_camera(scene_slug, shot, iter_idx=0):
    cams = SCENE_CAMS.get(scene_slug, SCENE_CAMS["yuto-bedroom"])
    opts = cams.get(shot, cams.get("default"))
    return opts[iter_idx % len(opts)]


BLENDER_SCRIPT = r"""
import bpy, sys, os, mathutils, json
args = json.loads(sys.argv[sys.argv.index("--")+1])

# Clear default scene
bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete()
for m in list(bpy.data.materials): bpy.data.materials.remove(m)

scene = bpy.context.scene

# EEVEE engine + Freestyle = proper manga line art (replaces Workbench cavity)
# Engine selection.
# V5_BASE=cinematic auto-enables Cycles (real GI + materials).
# V5_BASE=manga keeps EEVEE (faster, flat emission only).
# Explicit args.engine="CYCLES" still wins.
_want_cycles = (args.get("engine") == "CYCLES" or
                 os.environ.get("V5_BASE", "manga") == "cinematic")
# v6 NPR mode forces EEVEE (Toon BSDF cell shading via shader_to_rgb)
if os.environ.get("V5_BASE", "manga") == "v6":
    _want_cycles = False
if _want_cycles:
    engine_candidates = ["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"]
else:
    engine_candidates = ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"]
chosen_engine = None
for eng in engine_candidates:
    try: scene.render.engine = eng; chosen_engine = eng; break
    except: continue
if chosen_engine == "CYCLES":
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True

# Pure white world background
if scene.world is None:
    scene.world = bpy.data.worlds.new("White")
scene.world.use_nodes = True
bg_node = scene.world.node_tree.nodes.get("Background")
if bg_node:
    bg_node.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    bg_node.inputs[1].default_value = 1.5

# Enable Freestyle line render
scene.render.use_freestyle = True
view_layer = scene.view_layers[0]
view_layer.use_freestyle = True
# Clear existing linesets and add manga ink lineset
fs = view_layer.freestyle_settings
while fs.linesets:
    fs.linesets.remove(fs.linesets[0])
lineset = fs.linesets.new("MangaInk")
lineset.select_silhouette = True
lineset.select_border = True
lineset.select_contour = True
lineset.select_crease = True
lineset.select_external_contour = True
ls = lineset.linestyle
ls.color = (0, 0, 0)
ls.thickness = 3.5
ls.use_chaining = True

scene.render.resolution_x = args["width"]
scene.render.resolution_y = args["height"]
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.film_transparent = False

# Import main scene
bpy.ops.wm.usd_import(filepath=args["usd"], import_cameras=True, import_lights=True,
                       import_materials=True, import_meshes=True, scale=100.0)

# Base mode selection:
#   V5_BASE=cinematic (NEW default): keep imported USD materials, apply
#     scene-appropriate Principled BSDF to bare meshes. Cycles GI + sun
#     light renders a Pixar-style 3D preview in COLOR. SDXL Stage 2 then
#     gets a rich semantic base to convert into manga.
#   V5_BASE=manga: flat white emission (original NPR base for clean
#     canny edges; useful for ultra-clean line-art mode).
_v5_base = os.environ.get("V5_BASE", "manga")
if _v5_base == "v6":
    # v6 NPR Toon Shader (EEVEE-fast cell shading)
    def _toon(name, base_color, shadow_threshold=0.3):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree; nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
        diffuse.inputs["Color"].default_value = (*base_color, 1.0)
        s2rgb = nt.nodes.new("ShaderNodeShaderToRGB")
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "CONSTANT"
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
    v6_colors = [
        ("floor",(0.62,0.50,0.38)),("wall",(0.92,0.90,0.85)),("ceiling",(0.95,0.95,0.92)),
        ("desk",(0.55,0.40,0.27)),("chair",(0.50,0.35,0.25)),("blackboard",(0.18,0.22,0.20)),
        ("window",(0.85,0.92,0.95)),("bed",(0.65,0.55,0.45)),("mattress",(0.92,0.88,0.80)),
        ("blanket",(0.40,0.45,0.65)),("phone",(0.18,0.18,0.18)),("lamp",(0.80,0.70,0.50)),
        ("road",(0.35,0.35,0.35)),("building",(0.75,0.70,0.60)),("ground",(0.50,0.45,0.40)),
    ]
    _v6_default = _toon("V6_Default", (0.70,0.70,0.72))
    _v6_cache = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH": continue
        nm = obj.name.lower(); assigned = None
        for key, color in v6_colors:
            if key in nm:
                if key not in _v6_cache:
                    _v6_cache[key] = _toon(f"V6_{key}", color)
                assigned = _v6_cache[key]; break
        if assigned is None: assigned = _v6_default
        obj.data.materials.clear()
        obj.data.materials.append(assigned)
elif _v5_base == "manga":
    white_mat = bpy.data.materials.new("PaperWhite")
    white_mat.use_nodes = True
    white_mat.node_tree.nodes.clear()
    out_node = white_mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    emit_node = white_mat.node_tree.nodes.new("ShaderNodeEmission")
    emit_node.inputs[0].default_value = (1, 1, 1, 1)
    emit_node.inputs[1].default_value = 1.0
    white_mat.node_tree.links.new(emit_node.outputs[0], out_node.inputs[0])
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(white_mat)
else:
    # Cinematic 3D: assign Principled BSDF with scene-appropriate
    # colors to meshes that have no material (or only emission). This
    # gives Cycles real surface response.
    def _pbsdf(name, base_color, roughness=0.6, metallic=0.0):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        mat.node_tree.nodes.clear()
        out = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        p   = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        p.inputs["Base Color"].default_value = (*base_color, 1.0)
        p.inputs["Roughness"].default_value = roughness
        p.inputs["Metallic"].default_value = metallic
        mat.node_tree.links.new(p.outputs[0], out.inputs[0])
        return mat
    # Object-name → color mapping (heuristic by prim name)
    color_map = [
        ("floor",     (0.55, 0.42, 0.30), 0.7, 0.0),  # wood
        ("wall",      (0.92, 0.90, 0.85), 0.8, 0.0),  # cream wall
        ("ceiling",   (0.95, 0.95, 0.92), 0.8, 0.0),
        ("desk",      (0.50, 0.35, 0.22), 0.5, 0.0),  # wooden
        ("chair",     (0.45, 0.30, 0.20), 0.5, 0.0),
        ("blackboard",(0.15, 0.20, 0.18), 0.5, 0.0),  # chalkboard
        ("window",    (0.85, 0.92, 0.95), 0.05, 0.0), # glass
        ("bed",       (0.65, 0.55, 0.45), 0.7, 0.0),
        ("mattress",  (0.92, 0.88, 0.80), 0.9, 0.0),
        ("blanket",   (0.40, 0.45, 0.65), 0.9, 0.0),  # blue
        ("phone",     (0.10, 0.10, 0.10), 0.2, 0.6),  # dark metallic
        ("lamp",      (0.80, 0.75, 0.60), 0.4, 0.2),  # warm brass
        ("book",      (0.65, 0.25, 0.20), 0.7, 0.0),  # red cover
        ("road",      (0.30, 0.30, 0.30), 0.8, 0.0),
        ("building",  (0.75, 0.70, 0.60), 0.7, 0.0),
        ("ground",    (0.50, 0.45, 0.40), 0.8, 0.0),
    ]
    default_mat = _pbsdf("DefaultGray", (0.70, 0.70, 0.72), 0.6, 0.0)
    name_mats = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH": continue
        obj_lower = obj.name.lower()
        assigned = None
        for key, color, rough, met in color_map:
            if key in obj_lower:
                if key not in name_mats:
                    name_mats[key] = _pbsdf(f"Mat_{key}", color, rough, met)
                assigned = name_mats[key]
                break
        if assigned is None:
            assigned = default_mat
        obj.data.materials.clear()
        obj.data.materials.append(assigned)

# Track the focal mannequin object for camera framing
mannequin_focal = None

# Import MULTIPLE mannequin USDs — args["mannequins"] = [{usd, pos, scale?}, ...]
# Falls back to single args["mannequin"]+args["mannequin_pos"] for compat.
mannequins_to_place = args.get("mannequins") or []
if not mannequins_to_place and args.get("mannequin"):
    mannequins_to_place = [{"usd": args["mannequin"],
                              "pos": args["mannequin_pos"]}]

for mq_idx, mq in enumerate(mannequins_to_place):
    args["mannequin"] = mq["usd"]
    args["mannequin_pos"] = mq["pos"]
    if mq.get("scale"): args["mannequin_scale"] = mq["scale"]
    if args.get("mannequin"):
        n_before = set(o.name for o in bpy.data.objects)
        bpy.ops.wm.usd_import(filepath=args["mannequin"],
                               import_cameras=False, import_lights=False,
                               import_materials=False, import_meshes=True, scale=100.0)
        n_after = set(o.name for o in bpy.data.objects)
        new_names = n_after - n_before
        px, py, pz = args["mannequin_pos"]
        mannequin_mat = bpy.data.materials.new(f"Character_{mq_idx}")
        mannequin_mat.use_nodes = True
        mannequin_mat.node_tree.nodes.clear()
        out2 = mannequin_mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        emit2 = mannequin_mat.node_tree.nodes.new("ShaderNodeEmission")
        # Mid-gray (0.6) emission — softer than pure black so SDXL has
        # latitude to render a character, but still distinct from white
        # paper background.
        emit2.inputs[0].default_value = (0.6, 0.6, 0.6, 1)
        emit2.inputs[1].default_value = 1.0
        mannequin_mat.node_tree.links.new(emit2.outputs[0], out2.inputs[0])
        MANNEQUIN_SCALE = args.get("mannequin_scale", 2.5)
        for nm in new_names:
            obj = bpy.data.objects.get(nm)
            if obj and obj.type == "MESH":
                obj.scale = (MANNEQUIN_SCALE, MANNEQUIN_SCALE, MANNEQUIN_SCALE)
                obj.location.x = obj.location.x * MANNEQUIN_SCALE + px
                obj.location.y = obj.location.y * MANNEQUIN_SCALE + -pz
                obj.location.z = obj.location.z * MANNEQUIN_SCALE + py
                obj.data.materials.clear()
                obj.data.materials.append(mannequin_mat)
                try:
                    m = obj.modifiers.new("Subsurf", "SUBSURF")
                    m.levels = 2; m.render_levels = 2
                    m.subdivision_type = "CATMULL_CLARK"
                except Exception: pass
                if nm.startswith("Torso") and mannequin_focal is None:
                    mannequin_focal = obj

def usd_to_blender(v):
    return (v[0], -v[2], v[1])

cam_data = bpy.data.cameras.new("V5Cam"); cam_data.lens = args.get("lens", 35)
cam_obj = bpy.data.objects.new("V5Cam", cam_data)
scene.collection.objects.link(cam_obj)
cam_obj.location = usd_to_blender(args["cam_origin"])
# Auto-target mannequin torso if available, else use cam_target arg
if mannequin_focal is not None:
    target = mannequin_focal.location.copy()
    # Aim slightly above torso center for head visibility
    target.z += 0.3
else:
    target = mathutils.Vector(usd_to_blender(args["cam_target"]))
direction = target - cam_obj.location
rot_quat = direction.to_track_quat('-Z', 'Y')
cam_obj.rotation_euler = rot_quat.to_euler()
scene.camera = cam_obj

# Sun light:
#   V5_BASE=cinematic: ALWAYS enabled (real lighting for materials)
#   V5_BASE=manga + V5_MANGA_MODE=1: skipped (flat emission only)
#   Otherwise: respect V5_MANGA_MODE
import math, os as _os
_cinematic = _os.environ.get("V5_BASE", "manga") == "cinematic"
_v6 = _os.environ.get("V5_BASE", "manga") == "v6"
if _cinematic or _v6 or _os.environ.get("V5_MANGA_MODE", "1") != "1":
    sun_alt = math.radians(args.get("sun_altitude_deg", 45))
    sun_az  = math.radians(args.get("sun_azimuth_deg", 240))
    sun_intensity = args.get("sun_intensity", 5.0)
    sun_data = bpy.data.lights.new("Sun", "SUN")
    sun_data.energy = sun_intensity
    sun_data.angle = 0.05
    sun_obj = bpy.data.objects.new("Sun", sun_data)
    scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (math.pi/2 - sun_alt, 0, sun_az - math.pi)
    fill_data = bpy.data.lights.new("Fill", "SUN")
    fill_data.energy = sun_intensity * 0.25
    fill_data.angle = 1.0
    fill_obj = bpy.data.objects.new("Fill", fill_data)
    scene.collection.objects.link(fill_obj)
    fill_obj.rotation_euler = (math.pi/2 - sun_alt * 0.5, 0, sun_az)

scene.render.filepath = args["out"]

# OpenEXR multi-pass output (for Blender Compositor downstream).
# V5_MULTIPASS=1 enables EXR with Z/Normal/Diffuse passes.
if os.environ.get("V5_MULTIPASS") == "1":
    scene.render.image_settings.file_format = "OPEN_EXR_MULTILAYER"
    scene.render.image_settings.exr_codec = "ZIP"
    scene.render.use_compositing = True
    view_layer.use_pass_z = True
    view_layer.use_pass_normal = True
    view_layer.use_pass_diffuse_color = True
    try:
        view_layer.cycles.use_pass_diffuse_direct = True
        view_layer.cycles.use_pass_diffuse_indirect = True
    except Exception: pass
    scene.render.filepath = args["out"].replace(".png", ".exr")

bpy.ops.render.render(write_still=True)
print(f"OK render: {args['out']} engine={chosen_engine}")
"""
BLENDER_SCRIPT_PATH = Path("/tmp/blender_render_panel.py")
BLENDER_SCRIPT_PATH.write_text(BLENDER_SCRIPT)


def render_panel(scene_slug, shot, panel_idx, page_num, width, height,
                  iter_idx=0, ridge=2.0, valley=2.0, with_mannequin=True,
                  scene_graph=None):
    """Render single panel via Blender.

    If scene_graph (SceneGraphSpec) provided, use its camera/actor/lighting
    instead of SCENE_CAMS / SCENE_CHARACTER hardcoded dicts. This is the
    scene-graph-driven path from scene_graph_designer.py.
    """
    usd = USD_DIR / f"{scene_slug}.usda"
    if not usd.exists():
        usd = USD_DIR_ALT / f"{scene_slug}.usda"
    if not usd.exists():
        return None
    out = Path(f"/tmp/v5-pg{page_num:02d}-p{panel_idx:02d}-i{iter_idx}.png")

    if scene_graph:
        # Scene-graph-driven: use spec.camera + spec.actors + spec.lighting
        cam_origin = scene_graph["camera"]["origin_xyz"]
        cam_target = scene_graph["camera"]["target_xyz"]
        lens = scene_graph["camera"].get("fov_deg", 45)
        # Convert FOV→focal length (36mm horizontal aperture default)
        import math
        focal_len = 36.0 / (2 * math.tan(math.radians(lens) / 2))
    else:
        cam_origin, cam_target = pick_camera(scene_slug, shot, iter_idx)
        focal_len = 35.0

    args = {"usd": str(usd), "cam_origin": list(cam_origin),
            "cam_target": list(cam_target), "out": str(out),
            "width": width, "height": height, "lens": focal_len,
            "ridge": ridge, "valley": valley}

    # Mannequin placement — multi-character aware
    if with_mannequin:
        if scene_graph and scene_graph.get("actors"):
            pose_default = SCENE_CHARACTER.get(scene_slug, {}).get("pose", "seated")
            mannequin_usd = str(MANNEQUIN_SEATED if pose_default == "seated" else MANNEQUIN_STAND)
            args["mannequins"] = [
                {"usd": mannequin_usd, "pos": list(actor["position_xyz"])}
                for actor in scene_graph["actors"]
            ]
            # Also keep legacy single-mannequin args for backward compat
            if args["mannequins"]:
                args["mannequin"] = args["mannequins"][0]["usd"]
                args["mannequin_pos"] = args["mannequins"][0]["pos"]
        else:
            ch = SCENE_CHARACTER.get(scene_slug)
            if ch:
                args["mannequin"] = str(MANNEQUIN_SEATED if ch["pose"] == "seated" else MANNEQUIN_STAND)
                args["mannequin_pos"] = list(ch["pos"])

    # Per-spec lighting strength + sun direction (physics-derived)
    if scene_graph and "lighting" in scene_graph:
        args["key_intensity_mult"] = scene_graph["lighting"].get("key_intensity", 2500) / 2500
        args["sun_altitude_deg"]   = scene_graph["lighting"].get("sun_altitude_deg", 45)
        args["sun_azimuth_deg"]    = scene_graph["lighting"].get("sun_azimuth_deg", 240)
        args["sun_intensity"]      = max(2.0, scene_graph["lighting"].get("key_intensity", 2500) / 500)
    # Engine override via V5_ENGINE=CYCLES, or auto if V5_BASE=cinematic
    if os.environ.get("V5_ENGINE", "").upper() == "CYCLES" or \
       os.environ.get("V5_BASE", "manga") == "cinematic":
        args["engine"] = "CYCLES"
    timeout_s = 240 if args.get("engine") == "CYCLES" else 120
    import time as _time
    blender_t0 = _time.monotonic()
    proc = subprocess.run(
        ["blender", "-b", "-P", str(BLENDER_SCRIPT_PATH), "--", json.dumps(args)],
        capture_output=True, text=True, timeout=timeout_s)
    blender_panel_s = round(_time.monotonic() - blender_t0, 2)
    if "OK render" not in proc.stdout:
        if proc.stderr:
            err = proc.stderr.strip().split("\n")[-1][:200]
            print(f"    [Blender FAIL p{panel_idx}] {err}")
        return None
    # Record per-panel Blender timing
    bp_timings = globals().setdefault("LAST_BLENDER_TIMINGS", {})
    bp_timings[panel_idx] = {
        "engine":      args.get("engine", "EEVEE"),
        "blender_s":   blender_panel_s,
        "shot":        shot,
    }
    return out


def compute_layout(panels):
    rows = {}
    for p in panels:
        r = p.get("panelLayout", {}).get("gh:row") or 1
        rows.setdefault(int(r), []).append(p)
    sorted_rows = sorted(rows.keys())
    avail_h = PAGE_H - 2 * MARGIN - (len(sorted_rows) - 1) * INTER_GUTTER
    row_h = avail_h // len(sorted_rows)
    layout = []
    cur_y = MARGIN
    for r in sorted_rows:
        row_panels = sorted(rows[r],
            key=lambda p: p.get("panelLayout", {}).get("gh:readingOrder", p["panelIndex"]))
        units = [SIZE_UNIT.get(p.get("panelLayout", {}).get("gh:size", "medium"), 2) for p in row_panels]
        avail_w = PAGE_W - 2 * MARGIN - (len(row_panels) - 1) * INTRA_GUTTER
        unit_w = avail_w / sum(units)
        cur_x = PAGE_W - MARGIN
        for i, p in enumerate(row_panels):
            w = int(round(units[i] * unit_w))
            cur_x -= w
            layout.append({"idx": p["panelIndex"], "x": cur_x, "y": cur_y,
                            "w": w, "h": row_h, "panel": p})
            if i < len(row_panels) - 1: cur_x -= INTRA_GUTTER
        cur_y += row_h + INTER_GUTTER
    layout.sort(key=lambda s: s["idx"])
    return layout


# ───── Bubble overlay (PIL vertical Japanese) ─────────────────────────────
_KATAKANA = {"Akira":"アキラ","Yuto":"ユウト","Ren":"レン","Nei":"ネイ",
              "Mei":"メイ","Saki":"サキ","nue":"ヌエ","Chise":"チセ"}
def latinize(s):
    for en, k in _KATAKANA.items(): s = s.replace(en, k)
    return s


def draw_vertical_bubble(draw, font, text, panel_x, panel_y, panel_w, panel_h, anchor):
    text = latinize((text or "")[:30])
    if not text: return
    chars = list(text)
    col_h_max = 7
    cols = [chars[i:i+col_h_max] for i in range(0, len(chars), col_h_max)]
    # 2026-05-28: cap bubble to panel proportions (was unbounded). User
    # feedback: bubbles covering ~half the panel when text is long.
    # bubble width <= 38% panel_w, height <= 55% panel_h. Inside cap,
    # auto-shrink line_h to fit. V11_BUBBLE_SHRINK env (default 1.0)
    # multiplies the cap for ReAct loop adjustments.
    _bub_shrink = float(os.environ.get("V11_BUBBLE_SHRINK", "1.0"))
    max_bw = int(panel_w * 0.38 * _bub_shrink)
    max_bh = int(panel_h * 0.55 * _bub_shrink)
    line_h = 40
    col_w = 44
    inner_pad = 18
    outer_pad = 10
    # Shrink line_h if would exceed bh
    needed_bh = max(len(c) for c in cols) * line_h + inner_pad * 2
    if needed_bh > max_bh:
        line_h = max(22, (max_bh - inner_pad * 2) // max(len(c) for c in cols))
    needed_bw = len(cols) * col_w + inner_pad * 2
    if needed_bw > max_bw:
        col_w = max(28, (max_bw - inner_pad * 2) // len(cols))
    bw = min(max_bw, max(80, len(cols) * col_w + inner_pad * 2))
    bh = min(max_bh, max(120, max(len(c) for c in cols) * line_h + inner_pad * 2))
    if anchor == "top-right":
        bx, by = panel_x + panel_w - bw - outer_pad, panel_y + outer_pad
    elif anchor == "top-left":
        bx, by = panel_x + outer_pad, panel_y + outer_pad
    elif anchor == "middle-right":
        bx, by = panel_x + panel_w - bw - outer_pad, panel_y + (panel_h - bh) // 2
    elif anchor == "middle-left":
        bx, by = panel_x + outer_pad, panel_y + (panel_h - bh) // 2
    elif anchor == "bottom-right":
        bx, by = panel_x + panel_w - bw - outer_pad, panel_y + panel_h - bh - outer_pad
    else:
        bx, by = panel_x + outer_pad, panel_y + panel_h - bh - outer_pad
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=16,
                            fill=(255,255,255), outline=(0,0,0), width=3)
    for ci, col in enumerate(cols):
        cx = bx + bw - inner_pad - col_w//2 - ci * col_w
        for ri, ch in enumerate(col):
            cy = by + inner_pad + ri * line_h + line_h//2
            draw.text((cx, cy), ch, font=font, fill=(0,0,0), anchor="mm")


def _gaze_quadrant_anchor(panel: dict, di: int) -> str:
    """Pick bubble anchor in the QUADRANT OPPOSITE to subject's gaze focus.
    2026-05-28: bubble placement now subject-aware (was fixed cascade)."""
    try:
        import importlib.util
        gf_path = Path(__file__).parent.parent / "lg_mangaka/v10_gaze_flow.py"
        if gf_path.exists():
            spec = importlib.util.spec_from_file_location("gaze_flow", str(gf_path))
            gf = importlib.util.module_from_spec(spec); spec.loader.exec_module(gf)
            gx, gy = gf.gaze_node(panel)
            # Opposite quadrant of subject
            subj_right = gx > 0.5
            subj_bottom = gy > 0.5
            # Primary anchor in opposite quadrant
            if not subj_right and not subj_bottom:
                anchors = ["bottom-right", "middle-right", "top-right"]
            elif subj_right and not subj_bottom:
                anchors = ["bottom-left", "middle-left", "top-left"]
            elif not subj_right and subj_bottom:
                anchors = ["top-right", "middle-right", "bottom-right"]
            else:
                anchors = ["top-left", "middle-left", "bottom-left"]
            return anchors[di % len(anchors)]
    except Exception:
        pass
    # Fall back to original cascade
    return ["top-right", "top-left", "middle-right", "middle-left"][di % 4]


def _draw_bubbles_on_image(image_path: Path, layout) -> None:
    """Re-open final image and draw bubbles ON TOP of SFX + Obata cleanup
    so bubbles are always the topmost layer (user feedback 2026-05-26).
    2026-05-28: subject-aware placement so bubbles never cover the focal
    character's face."""
    im = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(im)
    try:
        font_bub = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", 30)
    except Exception:
        font_bub = ImageFont.load_default()
    # 2026-05-29: v2 bubble renderer with shape variety + proper vertical break
    bv2 = None
    if os.environ.get("BUBBLE_V2", "1") == "1":
        try:
            import importlib.util
            _bv2_path = Path(__file__).parent / "bubble_v2.py"
            spec = importlib.util.spec_from_file_location("bubble_v2", str(_bv2_path))
            bv2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(bv2)
        except Exception as e:
            print(f"  [bubble_v2] load fail, using v1: {e}")
            bv2 = None
    for slot in layout:
        p = slot["panel"]
        dlgs = [d for d in (p.get("dialogues") or []) if (d.get("text") or "")]
        if not dlgs: continue
        for di, d in enumerate(dlgs[:3]):
            anchor = _gaze_quadrant_anchor(p, di)
            if bv2 is not None:
                bv2.draw_bubble_v2(draw, font_bub, d.get("text"),
                                    slot["x"], slot["y"], slot["w"], slot["h"], anchor)
            else:
                draw_vertical_bubble(draw, font_bub, d.get("text"),
                                      slot["x"], slot["y"], slot["w"], slot["h"], anchor)
    im.save(image_path)


def composite_page(page_num, layout, panel_files, iter_idx=0, add_bubbles=True,
                    composite_emphasis: dict | None = None):
    """Composite panels into page + add bubbles, SFX, Obata ink cleanup.

    composite_emphasis: optional {sfx, ink, hatching} ∈ [0,1] from
    FirstAxes.composite_emphasis(). When provided, scales SFX size and
    Obata cleanup intensity (ADR-2605241500).
    """
    page = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    try:
        font_bub = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", 22)
    except:
        font_bub = ImageFont.load_default()

    # v11 (2026-05-27): support bleed + angle from panelLayout.
    _V11 = os.environ.get("V11_LAYOUT", "0") == "1"
    _v11mod = None
    if _V11:
        try:
            import importlib.util
            _spec = importlib.util.spec_from_file_location(
                "v11_layout",
                str(Path(__file__).parent.parent / "lg_mangaka" / "v11_layout.py"))
            _v11mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_v11mod)
        except Exception as e:
            print(f"    [v11] load skipped: {e}")
            _v11mod = None

    for slot in layout:
        idx = slot["idx"]
        path = panel_files.get(idx)
        # v11: expand slot for bleed if set
        eff = slot
        if _v11mod is not None:
            eff = _v11mod.expand_slot_for_bleed(slot, PAGE_W, PAGE_H, MARGIN)
        if not path or not Path(path).exists():
            draw.rectangle([eff["x"], eff["y"], eff["x"] + eff["w"],
                             eff["y"] + eff["h"]], outline=(0, 0, 0),
                             width=3, fill=(240, 240, 240))
            continue
        panel = Image.open(path).convert("RGB")
        sr = panel.width / panel.height
        dr = eff["w"] / eff["h"]
        if sr > dr:
            nh = eff["h"]; nw = int(nh * sr)
        else:
            nw = eff["w"]; nh = int(nw / sr)
        panel = panel.resize((nw, nh), Image.LANCZOS)
        ox = (nw - eff["w"]) // 2; oy = (nh - eff["h"]) // 2
        panel = panel.crop((ox, oy, ox + eff["w"], oy + eff["h"]))
        # v11: rotate within bbox for action panels
        if _v11mod is not None:
            ang = slot.get("panel", {}).get("panelLayout", {}).get("gh:angle", 0)
            if ang and abs(ang) >= 0.5:
                panel = _v11mod.apply_angle_to_panel(panel, ang, eff["w"], eff["h"])
        page.paste(panel, (eff["x"], eff["y"]))
        draw.rectangle([eff["x"]-1, eff["y"]-1,
                        eff["x"]+eff["w"]+1, eff["y"]+eff["h"]+1],
                        outline=(0, 0, 0), width=3)

    # NOTE (2026-05-26): bubbles are NOT drawn here anymore. They are drawn
    # AFTER sfx + obata in _draw_bubbles_on_image() so the bubble layer is
    # always topmost (user feedback: SFX kana was covering bubbles).

    out = Path(f"/tmp/gh-arc0-1-v5-p{page_num:02d}-i{iter_idx}.png")
    page.save(out)
    # Death Note-style SFX kana overlay (2026-05-24, emphasis-aware 2026-05-24b)
    _SCRIPTS_DIR = Path(__file__).parent
    if os.environ.get("V5_SFX", "1") == "1":
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "sfx_overlay", str(_SCRIPTS_DIR / "sfx_overlay.py"))
            if spec and spec.loader:
                sfx_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sfx_mod)
                page_panels = [s["panel"] for s in layout]
                # ADR-2605241500: composite_emphasis.sfx ∈ [0,1] scales size
                # Default 0.35 → emphasis=0.72 → 0.25 + 0.72*0.25 = 0.43
                size_pct = 0.35
                if composite_emphasis:
                    s = max(0.0, min(1.0, composite_emphasis.get("sfx", 0.5)))
                    size_pct = 0.25 + s * 0.25
                _, added = sfx_mod.overlay_sfx_on_composite(
                    out, layout, page_panels, out, size_pct=size_pct)
                if added:
                    sfx_summary = ", ".join(f"p{i}={s}" for i, s in added[:5])
                    print(f"    [SFX] {len(added)} overlays ({size_pct:.2f}h): {sfx_summary}")
        except Exception as e:
            print(f"    [SFX] skipped: {e}")
    # Obata ink cleanup (V5_OBATA=1 default — Death Note crisp ink style)
    if os.environ.get("V5_OBATA", "1") == "1":
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "obata", str(_SCRIPTS_DIR / "obata_ink_cleanup.py"))
            if spec and spec.loader:
                obata = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(obata)
                # ADR-2605241500: composite_emphasis.ink ∈ [0,1] scales params.
                # NOTE: posterize_lv stays >= 4 (bits>=2 = 4-level minimum).
                # posterize=3 → bits=1 → strict B&W which DESTROYS SDXL
                # bg detail (rooms become abstract horizontal bands).
                # Use contrast + sharpen for Obata intensity instead.
                if composite_emphasis:
                    ink = max(0.0, min(1.0, composite_emphasis.get("ink", 0.5)))
                    contrast = 1.2 + ink * 0.5         # 1.2-1.7
                    sharpen_pct = int(120 + ink * 100) # 120-220
                    # Preserve detail: 4-level default, 8-level for low ink
                    posterize_lv = 4 if ink >= 0.5 else 8
                    obata.obata_cleanup(out, out,
                                          contrast_boost=contrast,
                                          sharpen_percent=sharpen_pct,
                                          posterize_levels=posterize_lv)
                    print(f"    [Obata] cleanup ink={ink:.2f} "
                          f"(c={contrast:.2f},s={sharpen_pct}%,p={posterize_lv})")
                else:
                    obata.obata_cleanup(out, out)
                    print(f"    [Obata] cleanup default")
        except Exception as e:
            print(f"    [Obata] skipped: {e}")
    # 2026-05-29: snapshot pre-bubble image for fast iteration
    # (regenerating bubbles without re-rendering panels).
    try:
        pre_bubble = Path(f"/tmp/v10-p{page_num:02d}-pre-bubble.png")
        Image.open(out).save(pre_bubble)
    except Exception:
        pass
    # Bubbles drawn LAST so they sit above SFX + Obata (topmost layer).
    if add_bubbles:
        try:
            _draw_bubbles_on_image(out, layout)
        except Exception as e:
            print(f"    [Bubbles] skipped: {e}")
    return out


# ───── Per-stage QA scorers ───────────────────────────────────────────────
def qa_stage1_blender(blender_panel: Path) -> dict:
    """Stage 1: Blender USD render block-out. Checks:
      - render succeeded (file exists, non-trivial size)
      - Freestyle picked up edges (edge_density > threshold)
      - mannequin in frame (dark-pixel ratio in center region)
      - composition (subject not at edge / cropped)
    """
    from PIL import Image, ImageFilter, ImageStat
    import numpy as np
    if not blender_panel.exists() or blender_panel.stat().st_size < 1000:
        return {"total": 0, "label": "FAIL — no output", "issues": ["Blender render failed"]}
    im = Image.open(blender_panel).convert("RGB")
    arr = np.asarray(im)
    h, w = arr.shape[:2]
    g = im.convert("L")
    # Edge density
    edges = g.filter(ImageFilter.FIND_EDGES)
    edge_density = (np.asarray(edges) > 80).mean()
    # Subject in center region (60% center)
    cy0, cy1 = int(h*0.2), int(h*0.8)
    cx0, cx1 = int(w*0.2), int(w*0.8)
    center = arr[cy0:cy1, cx0:cx1]
    center_dark = (center.mean(axis=2) < 100).mean()
    # White bg
    bg_white = (arr.mean(axis=2) > 220).mean()

    score_edge_density   = min(10, edge_density * 200)
    score_subject_center = min(10, center_dark * 80)
    score_paper_white    = min(10, bg_white * 12)
    total = round((score_edge_density + score_subject_center + score_paper_white) / 3 * 10, 1)
    issues = []
    if score_edge_density < 4:
        issues.append("Freestyle silhouette weak — scene mostly off-camera or features too smooth")
    if score_subject_center < 3:
        issues.append("Subject not in center region — mannequin out of frame")
    if score_paper_white < 5:
        issues.append("Background not paper-white — Workbench or lighting issue")
    return {
        "stage": "stage1_blender",
        "total": total,
        "scores": {
            "edge_density":   round(score_edge_density, 1),
            "subject_center": round(score_subject_center, 1),
            "paper_white":    round(score_paper_white, 1),
        },
        "issues": issues,
        "metrics": {
            "edge_density":   round(float(edge_density), 4),
            "center_dark":    round(float(center_dark), 4),
            "bg_white":       round(float(bg_white), 4),
        },
    }


def qa_stage2_stylize(blender_panel: Path, stylized_panel: Path, focal_char: str | None) -> dict:
    """Stage 2: ComfyUI ControlNet+txt2img stylization. Checks:
      - SDXL output exists + reasonable size
      - composition reasonably matches Blender (canny edge overlap)
      - color tint penalty (saturation should be low for B&W manga)
      - character likely present (very-dark pixel patch in top-half ≈ hair)
      - inking quality (high gradient pixel count)
    """
    from PIL import Image, ImageFilter
    import numpy as np
    if not stylized_panel.exists() or stylized_panel.stat().st_size < 2000:
        return {"total": 0, "label": "FAIL — stylize did not produce output",
                "issues": ["ComfyUI returned no output"]}
    im = Image.open(stylized_panel).convert("RGB")
    arr = np.asarray(im)
    h, w = arr.shape[:2]
    hsv = np.asarray(im.convert("HSV"))
    sat = hsv[..., 1].mean()
    # Color tint penalty: animagine adds blue/purple
    color_penalty = min(10, sat / 8)
    score_bw_purity = max(0, 10 - color_penalty)
    # Inking: gradient density
    g = im.convert("L")
    edges = g.filter(ImageFilter.FIND_EDGES)
    crisp = (np.asarray(edges) > 100).mean()
    score_inking = min(10, crisp * 300)
    # Character hair patch — top half should have a dark cluster
    top_half = arr[:h//2, :, :].mean(axis=2)
    very_dark_top = (top_half < 30).mean()
    if focal_char:
        score_char_hair = min(10, very_dark_top * 50)
    else:
        score_char_hair = 5.0   # no LoRA → don't penalize
    # Composition match: count of pixels with low brightness
    g_arr = np.asarray(g)
    score_composition = min(10, (g_arr < 200).mean() * 30)

    total = round((score_bw_purity * 0.30 + score_inking * 0.30
                    + score_char_hair * 0.25 + score_composition * 0.15) * 10, 1)
    issues = []
    if score_bw_purity < 5:
        issues.append(f"color tint heavy (saturation={sat:.0f}) — strengthen NEG '(color:1.5)'")
    if score_inking < 4:
        issues.append("inking too soft — denoise too low or wrong checkpoint")
    if focal_char and score_char_hair < 3:
        issues.append(f"{focal_char} hair/character missing — increase LoRA strength or denoise")
    return {
        "stage": "stage2_stylize",
        "total": total,
        "scores": {
            "bw_purity":   round(score_bw_purity, 1),
            "inking":      round(score_inking, 1),
            "char_hair":   round(score_char_hair, 1),
            "composition": round(score_composition, 1),
        },
        "issues": issues,
        "metrics": {
            "saturation":      round(float(sat), 1),
            "crisp_edge_pct":  round(float(crisp) * 100, 2),
            "very_dark_top":   round(float(very_dark_top), 4),
        },
    }


def score_per_panel(image_path, layout, panels: list = None, scene_slug: str = None) -> dict:
    """Slice composite page into actual manifest panels and score each.

    Returns dict {panel_idx: {brightness, silhouette, coherence, issues,
                                jump_qa (if panels+scene given via Gemma)}}.
    User feedback (2026-05-24): page-only score not honest; need
    per-panel Gemma evaluation.
    """
    from PIL import Image, ImageFilter
    import numpy as np
    import importlib.util
    im = Image.open(image_path).convert("RGB")
    arr = np.asarray(im)
    results = {}
    # Load Gemma Jump benchmark + manifest QA modules once
    jbq = None; mmq = None
    if (panels is not None and scene_slug is not None
        and os.environ.get("V5_DISABLE_PERPANEL_GEMMA") != "1"):
        try:
            for name, src in [("jbq", "/tmp/jump_benchmark_qa.py"),
                                ("mmq", "/tmp/manifest_match_qa.py")]:
                p = Path(src)
                if p.exists():
                    s = importlib.util.spec_from_file_location(name, str(p))
                    mod = importlib.util.module_from_spec(s); s.loader.exec_module(mod)
                    if name == "jbq": jbq = mod
                    else: mmq = mod
        except Exception as e:
            print(f"  [per-panel Gemma] modules unavailable: {e}")
    panels_by_idx = {p["panelIndex"]: p for p in (panels or [])}
    panel_crop_dir = Path("/tmp")
    for slot in layout:
        idx = slot["idx"]
        x, y, w, h = slot["x"], slot["y"], slot["w"], slot["h"]
        # Crop the panel region (with safety clamp)
        x1 = max(0, x); y1 = max(0, y)
        x2 = min(arr.shape[1], x + w); y2 = min(arr.shape[0], y + h)
        cell = arr[y1:y2, x1:x2]
        if cell.size == 0:
            results[idx] = {"error": "empty cell"}; continue
        # Save crop to disk for Gemma evaluation
        crop_path = None
        if jbq is not None:
            crop_path = panel_crop_dir / f"_panel_crop_p{idx:02d}.png"
            Image.fromarray(cell).save(crop_path)
        gray = cell.mean(axis=2)
        mean_b = float(gray.mean())
        very_dark = float((gray < 30).mean())
        very_light = float((gray > 220).mean())
        mid_tone = float(((gray >= 80) & (gray <= 180)).mean())
        # Edge density
        g_im = Image.fromarray(gray.astype(np.uint8))
        edges = np.asarray(g_im.filter(ImageFilter.FIND_EDGES))
        edge_complexity = float((edges > 100).mean())

        # Per-panel axes
        brightness = min(10, max(0, (mean_b - 100) / 7))
        sil_clarity = min(10, min(very_dark, very_light) * 50)
        if mid_tone > 0.7: sil_clarity *= 0.3   # subject fused with bg
        # Coherence: balanced edge density
        if edge_complexity > 0.15:
            coherence = max(0, 10 - (edge_complexity - 0.15) * 50)
        else:
            coherence = min(10, edge_complexity * 60 + 3)

        issues = []
        if brightness < 5:
            issues.append(f"panel {idx} 暗すぎる (mean={mean_b:.0f})")
        if sil_clarity < 3:
            issues.append(f"panel {idx} 机と人が一体化 (mid_tone={mid_tone:.2f})")
        if coherence < 5:
            issues.append(f"panel {idx} 意味不明 (edge_density={edge_complexity:.2%})")
        rec = {
            "scores": {
                "brightness": round(brightness, 1),
                "silhouette": round(sil_clarity, 1),
                "coherence":  round(coherence, 1),
            },
            "metrics": {
                "mean_brightness": round(mean_b, 1),
                "very_dark":  round(very_dark, 3),
                "very_light": round(very_light, 3),
                "mid_tone":   round(mid_tone, 3),
                "edge_complexity": round(edge_complexity, 4),
            },
            "issues": issues,
        }
        # Per-panel Gemma Jump-benchmark evaluation (if modules available)
        if jbq and crop_path and crop_path.exists():
            try:
                gemma_r = jbq.score_page(crop_path)
                if gemma_r.get("total", 0) > 0:
                    rec["gemma_jump"] = {
                        "total":  gemma_r["total"],
                        "label":  gemma_r.get("label", ""),
                        "scores": gemma_r.get("scores", {}),
                        "verdict": gemma_r.get("verdict", ""),
                        "issues":  gemma_r.get("issues", [])[:2],
                    }
                    rec["scores"]["gemma_jump"] = gemma_r["total"]
            except Exception as e:
                rec["gemma_error"] = str(e)
        # Per-panel manifest-match (if panel description available)
        if mmq and crop_path and crop_path.exists() and idx in panels_by_idx:
            try:
                p = panels_by_idx[idx]
                mm_r = mmq.score_panel(crop_path, p, scene_slug, timeout=45)
                if mm_r.get("total", 0) > 0:
                    rec["gemma_manifest"] = {
                        "total":   mm_r["total"],
                        "scores":  mm_r.get("scores", {}),
                        "verdict": mm_r.get("verdict", ""),
                        "violations": mm_r.get("violations", [])[:2],
                    }
                    rec["scores"]["gemma_manifest"] = mm_r["total"]
            except Exception as e:
                rec["manifest_error"] = str(e)
        # Per-panel total: combine heuristic axes + Gemma axes (if both)
        h_total = (brightness + sil_clarity + coherence) / 3 * 10   # 0-100
        if "gemma_jump" in rec and "gemma_manifest" in rec:
            rec["total"] = round(h_total * 0.20
                                  + rec["gemma_jump"]["total"] * 0.40
                                  + rec["gemma_manifest"]["total"] * 0.40, 1)
        elif "gemma_jump" in rec:
            rec["total"] = round(h_total * 0.30 + rec["gemma_jump"]["total"] * 0.70, 1)
        else:
            rec["total"] = round(h_total, 1)
        # Clean up crop file
        if crop_path and crop_path.exists():
            try: crop_path.unlink()
            except: pass
        results[idx] = rec
    return results


def _panel_grid_metrics(arr):
    """Per-panel-grid metrics — slice page into ~grid panels for issue-specific QA.
    Returns: list of dict per cell with darkness/fusion/coherence diagnostics.
    """
    import numpy as np
    h, w = arr.shape[:2]
    cells = []
    # 3×3 grid (rough page panel approximation)
    for r in range(3):
        for c in range(3):
            cy0, cy1 = int(h*r/3), int(h*(r+1)/3)
            cx0, cx1 = int(w*c/3), int(w*(c+1)/3)
            cell = arr[cy0:cy1, cx0:cx1].mean(axis=2)
            cells.append({
                "mean": float(cell.mean()),
                "std":  float(cell.std()),
                "very_dark": float((cell < 30).mean()),
                "very_light": float((cell > 220).mean()),
                "mid_tone":  float(((cell >= 80) & (cell <= 180)).mean()),
            })
    return cells


def vision_score(image_path: Path) -> dict:
    """Honest manga page scorer — actually inspects pixels for what's
    visible, not just what was attempted.

    Rubric additions per user feedback 2026-05-23:
      - background_white: pure-white paper (0.95+) gets full marks;
        gray-midtone background is penalized severely
      - character_visible: actual dark silhouette pixels in mid-frame,
        not just "mannequin USD was loaded"
      - panel_diversity: compare panel crops; near-identical panels
        crash composition score
      - bubble_text_present: check whether bubble regions contain
        sharp glyph contrast (not just placeholder dots)
      - manga_bimodality: histogram should peak at 0 (ink) and 255
        (paper). Gray-midtone-dominant = "3D render leak" = penalty

    GARBAGE DETECTION (2026-05-25): added preprocessor that detects
    SDXL VAE failures (rainbow horizontal stripes from ComfyUI
    corruption). When v/h edge ratio > 5.0, the image is mostly
    horizontal-stripe noise — force the entire score to 5/100 max
    regardless of what the heuristic axes say (panel_diversity and
    composition_bimodal incorrectly reward stripe variety + B&W
    purity). User feedback 2026-05-25:
      "この状態は正直 score 10 以下なんですが.. なぜこの状態でも 高い score"
    """
    from PIL import Image, ImageStat, ImageFilter
    import numpy as np
    im = Image.open(image_path).convert("RGB")
    arr = np.asarray(im)
    h, w = arr.shape[:2]

    # ─── GARBAGE GATE: detect rendering failures ──────────────────────
    # 2026-05-26: relaxed thresholds — colored manga pages with large
    # solid-color regions (classroom walls, blackboards, etc.) were
    # false-triggering the 0.30 stripe threshold. Real rainbow noise has
    # >70% identical-row stripes; legitimate manga peaks around 50%.
    _arr_f = arr.astype(float) / 255.0
    _gy = float(np.abs(_arr_f[1:, :, :] - _arr_f[:-1, :, :]).mean())
    _gx = float(np.abs(_arr_f[:, 1:, :] - _arr_f[:, :-1, :]).mean())
    _v_over_h = _gy / (_gx + 1e-9)
    _gray = np.asarray(im.convert("L")).astype(float)
    _row_diffs = np.abs(_gray[1:] - _gray[:-1]).mean(axis=1)
    _stripe_rows = int((_row_diffs < 5).sum())
    _stripe_pct = _stripe_rows / max(1, len(_row_diffs))

    # 2026-05-28: further raise stripe to 0.85 — full-page close-ups
    # (single-panel pages, large uniform skin-tone bg) were falsely
    # tripping the gate. Real rainbow noise has stripe ~0.95+.
    if _v_over_h > 8.0 or _stripe_pct > 0.85:
        return {
            "scores": {
                "garbage_gate_v_over_h": round(_v_over_h, 2),
                "garbage_gate_stripe_pct": round(_stripe_pct, 3),
            },
            "total": max(5.0, round(10 * (1 - _stripe_pct), 1)),
            "jump_tier_label": "AI artifact (garbage gate)",
            "heuristic_total": 5.0,
            "issues": [
                f"[GARBAGE GATE] v/h edge={_v_over_h:.2f} stripe_pct={_stripe_pct:.0%}",
                "Image is mostly uniform horizontal stripe pattern",
                ("SDXL VAE rainbow noise" if _v_over_h > 5.0
                  else "Obata posterize destroyed SDXL background detail"),
                "Re-render with v6 path + reduced Obata after ComfyUI recovery",
            ],
            "_diagnostics": {"garbage_detected": True,
                              "v_over_h_edge_ratio": _v_over_h,
                              "stripe_row_pct": _stripe_pct},
        }

    # ─── Background paper character (manga can be white OR black) ──────
    # Death Note pages have BOTH bright bedrooms and pure-black night
    # scenes. Penalize mid-gray indeterminate (SDXL artifact) not dark
    # backgrounds. Score peaks at corners ≥220 OR ≤40, dips for 100-180.
    corners = []
    for cy, cx in [(50, 50), (h-250, 50), (h-250, w-250)]:
        patch = arr[cy:cy+200, cx:cx+200]
        corners.append(patch.mean())
    bg_mean = float(np.mean(corners))
    # Bimodal acceptance: paper-white (≥210) or true-black (≤50) full
    # marks; off-white acceptable; mid-gray (artifact) penalized.
    # Slopes relaxed (round 9, 2026-05-25): a render with bg_mean=215
    # (off-white from SDXL bedroom highlights) shouldn't lose much.
    if bg_mean >= 210:
        bg_whiteness = min(10.0, 7 + (bg_mean - 210) / 5.0)   # 210→7, 225→10
    elif bg_mean <= 50:
        bg_whiteness = min(10.0, 7 + (50 - bg_mean) / 5.0)
    else:
        bg_whiteness = max(0.0, 10 - abs(bg_mean - 130) / 10)
        bg_whiteness = min(7.0, bg_whiteness)

    # ─── Manga bimodality (histogram should be bimodal at 0+255) ──
    gray = np.asarray(im.convert("L"))
    hist, _ = np.histogram(gray, bins=10, range=(0, 255))
    hist_n = hist / hist.sum()
    # Manga: peaks at bins 0 + 9 (ink + paper). Bad: peak in middle bins.
    edge_mass = hist_n[0] + hist_n[1] + hist_n[8] + hist_n[9]
    midtone_mass = hist_n[3] + hist_n[4] + hist_n[5] + hist_n[6]
    bimodality = max(0, min(10, (edge_mass - midtone_mass) * 20 + 5))

    # ─── Inking quality — refined to penalize noise vs reward clean ink ─
    g_pil = im.convert("L")
    edges = g_pil.filter(ImageFilter.FIND_EDGES)
    edge_arr = np.asarray(edges)
    crisp_edge_ratio = (edge_arr > 100).mean()
    # Manga ink density range — widened (2026-05-25 round 5).
    # Old range 0.02-0.12 was too narrow. Real manga varies 0.01-0.20:
    #   sparse line-art chapter pages: 0.01-0.03
    #   conversation pages (Death Note ch 1): 0.03-0.06
    #   detailed bg / chiaroscuro: 0.06-0.12
    #   action with motion lines + screentone: 0.12-0.20
    #   over-dense AI noise: > 0.25
    if crisp_edge_ratio < 0.005:
        inking_quality = crisp_edge_ratio * 400      # empty: 0-2
    elif crisp_edge_ratio < 0.02:
        inking_quality = 4 + (crisp_edge_ratio - 0.005) * 200  # 4-7
    elif crisp_edge_ratio < 0.12:
        inking_quality = 7 + (crisp_edge_ratio - 0.02) * 30    # 7-10 ideal
    elif crisp_edge_ratio < 0.20:
        inking_quality = 10 - (crisp_edge_ratio - 0.12) * 25   # 10-8 dense ok
    elif crisp_edge_ratio < 0.30:
        inking_quality = max(0, 8 - (crisp_edge_ratio - 0.20) * 50)  # noisy
    else:
        inking_quality = max(0, 3 - (crisp_edge_ratio - 0.30) * 30)  # pure noise

    # ─── Character visibility (dark silhouette in mid-frame) ──────
    # For each panel slot, check if there's a recognizable dark blob.
    # Heuristic: count "very dark" pixels (≤30) in the central 60% of
    # each "panel-sized" region. We don't know layout here; just use a
    # uniform 3×3 grid of the page.
    char_visibility_scores = []
    h_step, w_step = h // 3, w // 3
    for r in range(3):
        for c in range(3):
            cell = arr[r*h_step:(r+1)*h_step, c*w_step:(c+1)*w_step]
            cgray = cell.mean(axis=2)
            very_dark = (cgray < 30).mean()
            if very_dark < 0.03: score = 0      # empty / panel gutter
            elif very_dark > 0.6: score = 1     # all black (panel placeholder)
            else: score = min(10, very_dark * 30)
            char_visibility_scores.append(score)
    # Use TOP-5 of 9 cells — "characters present somewhere" matters more
    # than "characters fill every grid cell". Panel gutters / empty bg
    # regions shouldn't drag down a page where characters ARE visible.
    sorted_scores = sorted(char_visibility_scores, reverse=True)
    character_visibility = float(np.mean(sorted_scores[:5]))

    # ─── Panel diversity (variance across page) ────────────────────
    # Hash each grid cell and measure how different they are.
    cell_hashes = []
    for r in range(3):
        for c in range(3):
            cell = arr[r*h_step:(r+1)*h_step, c*w_step:(c+1)*w_step]
            # Downsample to 8x8 and binarize
            from PIL import Image as PILImage
            cell_im = PILImage.fromarray(cell).convert("L").resize((8, 8))
            cell_arr = np.asarray(cell_im)
            cell_hashes.append((cell_arr > cell_arr.mean()).flatten())
    # Pairwise Hamming distance
    if len(cell_hashes) > 1:
        dists = []
        for i in range(len(cell_hashes)):
            for j in range(i+1, len(cell_hashes)):
                dists.append((cell_hashes[i] != cell_hashes[j]).sum())
        diversity_raw = float(np.mean(dists))   # 0..64
        panel_diversity = min(10, diversity_raw / 3.2)
    else:
        panel_diversity = 5.0

    # ─── Saturation (manga = monochrome, hue saturation should be 0) ─
    hsv = np.asarray(im.convert("HSV"))
    sat = hsv[..., 1].mean()
    artifact_freedom = max(0, 10 - sat / 6)   # high saturation = color leak

    # ─── Bubble legibility — actually measure glyph presence ──────────
    # Detect text glyphs by: small-area dark spots with high local
    # contrast (vs hatched bg which is uniform dark mass).
    # Count: pixels where a 3×3 neighborhood has BOTH very-dark AND very-light
    # — that's a glyph edge transition (bubble text against white bg).
    _g = np.asarray(im.convert("L"))
    _local_max = np.maximum(np.maximum(_g[1:, :-1], _g[1:, 1:]),
                              np.maximum(_g[:-1, 1:], _g[:-1, :-1]))
    _local_min = np.minimum(np.minimum(_g[1:, :-1], _g[1:, 1:]),
                              np.minimum(_g[:-1, 1:], _g[:-1, :-1]))
    _local_range = (_local_max.astype(int) - _local_min.astype(int))
    _glyph_pixels = ((_local_range > 100) & (_local_min < 80)).mean()
    # Manga dialogue typically 0.005-0.02 pixel ratio with high contrast.
    # We KNOW bubbles were drawn — give credit if signal present.
    if _glyph_pixels >= 0.008:    bubble_legibility = 9.0
    elif _glyph_pixels >= 0.004:  bubble_legibility = 7.5
    elif _glyph_pixels >= 0.002:  bubble_legibility = 6.0
    elif _glyph_pixels >= 0.001:  bubble_legibility = 4.5
    else:                          bubble_legibility = 3.0
    if "CURRENT_PAGE_PANELS" in globals():
        # Bonus if manifest explicitly has dialogue (we drew bubbles)
        _has_dialog = any(p.get("dialogues") for p in
                           globals().get("CURRENT_PAGE_PANELS", []))
        if _has_dialog and _glyph_pixels >= 0.002:
            bubble_legibility = min(10.0, bubble_legibility + 1.0)

    # ─── Emotional impact — gated by character_visibility ──────────
    emotional_impact = min(10, character_visibility * 0.7 + bimodality * 0.3)

    # ─── Scene continuity — but only if panels VARY appropriately ─
    # scene_continuity — measure if panels share a coherent scene.
    # Round 7 fix (2026-05-25): was hardcoded 7.0, similar to old
    # bubble_legibility 5.0 hardcode bug.
    # Compute via dominant-tone similarity between adjacent panels.
    if panel_diversity < 2.0:
        scene_continuity = 2.0   # "same panel" problem
    else:
        # Compute brightness histogram similarity across grid cells.
        # If adjacent cells share dominant brightness peaks → same scene.
        from PIL import Image as PIL
        cell_brights = []
        for r in range(3):
            for c in range(3):
                cell = arr[r*h_step:(r+1)*h_step, c*w_step:(c+1)*w_step]
                cell_brights.append(cell.mean())
        cell_arr = np.asarray(cell_brights)
        # Coefficient of variation: low = uniform scene, high = varied
        cv_brights = float(cell_arr.std() / (cell_arr.mean() + 1e-9))
        # 0.0-0.15 = same scene (high continuity), 0.15-0.30 = related,
        # > 0.30 = varied (multiple scenes — typical for narrative)
        if cv_brights < 0.15:
            scene_continuity = 9.5    # tight scene
        elif cv_brights < 0.30:
            scene_continuity = 8.5    # related panels
        elif cv_brights < 0.50:
            scene_continuity = 7.5    # narrative variety (normal)
        else:
            scene_continuity = 6.0    # discontinuous

    # ─── NEW: 3 user-flagged issues (2026-05-23 feedback) ────────────────
    # 1. brightness_avg: penalize "画面全体が暗すぎる" (overall too dark)
    overall_mean = float(gray.mean())
    # Manga page typical mean: 150-220 (paper white + ink details).
    # Round 10: also reward cinematic dark scenes (Death Note night
    # spreads have means around 80-130, intentionally). Bimodal accept.
    if overall_mean >= 150:
        brightness_avg = min(10, 7 + (overall_mean - 150) / 14)   # 150→7, 220→12→10
    elif overall_mean >= 80:
        brightness_avg = min(10, 6 + (150 - overall_mean) / 14 if overall_mean <= 100
                              else (overall_mean - 100) / 10 + 5)  # 80→6 (dark cinematic), 100-150→5-7
    else:
        brightness_avg = max(0, overall_mean / 16)   # very dark

    # 2. silhouette_clarity: detect "机と人が一体化" (subject-bg fusion)
    # Per-grid cell, check if there are TWO distinct brightness peaks
    # (subject + bg). If a cell is uniformly dark or uniformly light,
    # there's no silhouette separation.
    cells = _panel_grid_metrics(arr)
    fusion_scores = []
    for cell in cells:
        # Good cell: has both very_dark and very_light pixels (silhouette)
        # Bad cell:  uniformly mid-tone (everything blended together)
        clarity = min(cell["very_dark"], cell["very_light"]) * 4   # 0..1ish
        if cell["mid_tone"] > 0.7: clarity *= 0.3   # mostly midtone = fused
        fusion_scores.append(clarity)
    silhouette_clarity = min(10, max(fusion_scores) * 50) if fusion_scores else 0

    # 3. panel_coherence: detect "意味がわからない" (incoherent panel)
    edge_complexity = (edge_arr > 100).mean()
    if edge_complexity > 0.15:
        coherence_penalty = (edge_complexity - 0.15) * 50
        panel_coherence = max(0, 10 - coherence_penalty)
    else:
        panel_coherence = min(10, edge_complexity * 60 + 3)

    # 4. wasted_lines (NEW): SDXL hatching noise detection
    #    Compute edge entropy across image — uniform high density = noise,
    #    localized clusters = intentional ink.
    h_step = h // 5; w_step = w // 5
    cell_densities = []
    for r in range(5):
        for c in range(5):
            cell_edge = edge_arr[r*h_step:(r+1)*h_step, c*w_step:(c+1)*w_step]
            cell_densities.append((cell_edge > 100).mean())
    cell_densities = np.asarray(cell_densities)
    # Good manga: high variance across cells (some clean, some inked)
    # Noise:     low variance (uniformly textured)
    edge_variance = cell_densities.var()
    # Variance of ~0.005-0.02 = good ink locality
    if edge_variance < 0.001:        # very uniform = pure noise
        wasted_lines = 1.0
    elif edge_variance < 0.005:      # somewhat textured
        wasted_lines = 3.0 + edge_variance * 500
    elif edge_variance < 0.025:      # ideal locality
        wasted_lines = 7.0 + (edge_variance - 0.005) * 100
    else:
        wasted_lines = min(10, 9 + edge_variance * 50)
    # Penalty for excessive uniform busyness (Obata pages have DENSE
    # hatching by design — was 0.13, bumped to 0.25 to match real manga).
    # Below 0.25: real manga territory (chiaroscuro + screentone).
    # 0.25-0.35: probably AI noise.
    # Above 0.35: pure noise.
    if edge_complexity > 0.35:
        wasted_lines *= 0.5
    elif edge_complexity > 0.25:
        wasted_lines *= 0.75


    # Re-weighted 2026-05-25 (user critique 2 — Obata-collapsed bg gets
    # 56/100 when visually <10/100). Auto-max axes (composition_bimodal,
    # artifact_freedom, brightness_avg, silhouette_clarity, panel_diversity)
    # were inflating scores on rainbow-stripe / hatched-collapse failures.
    # Deflated further to ~0.20 total; content axes promoted to ~0.75.
    WEIGHTS = {
        "character_visible":     0.18,   # ↑ from 0.16 (real content signal)
        "scene_continuity":      0.10,
        "panel_diversity":       0.03,   # ↓ from 0.08 (rewards stripe variety)
        "inking_quality":        0.15,   # ↑ from 0.13 (real content signal)
        "composition_bimodal":   0.02,   # ↓ from 0.04 (B&W noise still bimodal)
        "background_white":      0.08,   # ↑ from 0.06
        "bubble_legibility":     0.10,   # ↑ from 0.08
        "emotional_impact":      0.06,
        "artifact_freedom":      0.02,   # ↓ from 0.03
        "brightness_avg":        0.02,   # ↓ from 0.04
        "silhouette_clarity":    0.04,   # ↓ from 0.08 (rewards small silhouettes)
        "panel_coherence":       0.08,   # ↑ from 0.06
        "wasted_lines":          0.12,   # ↑ from 0.08 (key noise detector)
    }
    scores = {
        "character_visible":    round(character_visibility, 1),
        "scene_continuity":     round(scene_continuity, 1),
        "panel_diversity":      round(panel_diversity, 1),
        "inking_quality":       round(inking_quality, 1),
        "composition_bimodal":  round(bimodality, 1),
        "background_white":     round(bg_whiteness, 1),
        "bubble_legibility":    bubble_legibility,
        "emotional_impact":     round(emotional_impact, 1),
        "artifact_freedom":     round(artifact_freedom, 1),
        "brightness_avg":       round(brightness_avg, 1),
        "silhouette_clarity":   round(silhouette_clarity, 1),
        "panel_coherence":      round(panel_coherence, 1),
        "wasted_lines":         round(wasted_lines, 1),
    }
    total = round(sum(WEIGHTS[k] * scores[k] * 10 for k in WEIGHTS), 1)

    issues, hints = [], []
    if scores["brightness_avg"] < 5:
        issues.append(f"画面全体が暗すぎる (page mean brightness={overall_mean:.0f}, target ≥160)")
        hints.append("apply OCIO gamma lift (gamma 1.4) OR add NEG '(dark scene, low light)' weight 1.3")
    if scores["silhouette_clarity"] < 4:
        issues.append("subject-background fusion — character merged with environment (no clear silhouette)")
        hints.append("increase mannequin material contrast (0.6 → 0.3 gray) OR add ControlNet depth pass")
    if scores["panel_coherence"] < 5:
        issues.append(f"panel content chaotic (edge density {edge_complexity:.2%} > 15%) — meaning unclear")
        hints.append("lower denoise to 0.55 OR strengthen NEG '(blurry, messy, abstract)'")
    if scores["background_white"] < 7:
        issues.append(f"background gray-midtone (bg_mean={bg_mean:.0f}, paper should be ≥240)")
        hints.append("Blender: set single_color=(1,1,1) + film transparent off + world background white")
    if scores["character_visible"] < 4:
        issues.append("character barely visible in any panel — mannequin out of frame or too small")
        hints.append("camera tune: closer + character at thirds_R; check pelvis_pos vs camera target")
    if scores["panel_diversity"] < 4:
        issues.append("panels too similar — same view repeated")
        hints.append("add per-panel camera offset / vary shot type / use ECU + LS variation")
    if scores["inking_quality"] < 4:
        issues.append("ink edges too soft — looks like 3D render, not inked manga")
        hints.append("Cycles+OSL line-weight shader / increase Workbench cavity / outline width")
    if scores["composition_bimodal"] < 5:
        issues.append("histogram gray-midtone-dominant (3D render leak)")
        hints.append("posterize to B&W (no midtones) + add screentone for fills")

    # Heuristic-only total (kept for fast iteration / no-LLM mode)
    heuristic_total = total

    # Integrate Gemma 3:4b Jump-tier benchmark — STRICT scoring against
    # Death Note / Jujutsu Kaisen / Chainsaw Man professional manga.
    # Combined: 0.45 × heuristic + 0.55 × Jump benchmark (LLM dominant).
    # User feedback: "こういう quality を基準に score 基準を整理し直して"
    jump_qa = {}
    if os.environ.get("V5_DISABLE_JUMP_QA") != "1":
        try:
            import importlib.util
            # Load canonical first (has parser fix + 8-axis prompt); /tmp fallback.
            _canon_p = Path(__file__).parent.parent / "lg_mangaka/jump_benchmark_qa.py"
            spec_p = _canon_p if _canon_p.exists() else Path("/tmp/jump_benchmark_qa.py")
            if spec_p.exists():
                spec = importlib.util.spec_from_file_location("jbq", str(spec_p))
                jbq = importlib.util.module_from_spec(spec); spec.loader.exec_module(jbq)
                jump_qa = jbq.score_page(image_path)
        except Exception as e:
            jump_qa = {"error": str(e), "total": 0}

    # Manifest-match narrative QA — strictest scorer (user feedback:
    # 窓の外が映ってない / 教室に人がいない / この人物は?)
    manifest_qa = {}
    if (os.environ.get("V5_DISABLE_MANIFEST_QA") != "1"
        and globals().get("CURRENT_PAGE_PANELS")
        and globals().get("CURRENT_SCENE_SLUG")):
        try:
            import importlib.util
            # Canonical first (has fixes); /tmp fallback.
            _canon_p = Path(__file__).parent.parent / "lg_mangaka/manifest_match_qa.py"
            spec_p = _canon_p if _canon_p.exists() else Path("/tmp/manifest_match_qa.py")
            if spec_p.exists():
                spec = importlib.util.spec_from_file_location("mmq", str(spec_p))
                mmq = importlib.util.module_from_spec(spec); spec.loader.exec_module(mmq)
                manifest_qa = mmq.score_page(image_path,
                                              globals()["CURRENT_PAGE_PANELS"],
                                              globals()["CURRENT_SCENE_SLUG"])
        except Exception as e:
            manifest_qa = {"error": str(e), "total": 0}

    if jump_qa and "scores" in jump_qa and jump_qa["total"] > 0:
        # Triple combine: heuristic + Jump benchmark + Manifest match.
        # Manifest match is the strictest, weight it as dominant.
        if manifest_qa and manifest_qa.get("total", 0) > 0:
            total = round(heuristic_total * 0.25
                            + jump_qa["total"] * 0.35
                            + manifest_qa["total"] * 0.40, 1)
            scores["manifest_qa_total"] = manifest_qa["total"]
            for k, v in manifest_qa.get("scores", {}).items():
                scores[f"manifest_{k}"] = v
            if manifest_qa.get("violations"):
                issues.extend([f"[Manifest] {v}" for v in manifest_qa["violations"][:5]])
        else:
            total = round(heuristic_total * 0.45 + jump_qa["total"] * 0.55, 1)
        scores["jump_qa_total"] = jump_qa["total"]
        for k, v in jump_qa.get("scores", {}).items():
            scores[f"jump_{k}"] = v
        if jump_qa.get("issues"):
            issues.extend([f"[Jump] {i}" for i in jump_qa["issues"][:3]])

    # New strict thresholds (Jump benchmark calibrated):
    # Death Note as primary 90+ benchmark (2026-05-24 recalibration)
    if total >= 90:    label = "Death Note class (Obata級)"
    elif total >= 80:  label = "top-tier (Jump 看板作)"
    elif total >= 65:  label = "mid-tier (人気作)"
    elif total >= 50:  label = "lower-mid (中堅クラス)"
    elif total >= 35:  label = "trial (打切クラス)"
    elif total >= 20:  label = "AI artifact (要再生成)"
    else:               label = "block-out (3D pre-render only)"

    return {"scores": scores, "total": total, "jump_tier_label": label,
            "heuristic_total": heuristic_total,
            "jump_qa": {k: v for k, v in jump_qa.items() if k != "scores"},
            "issues": issues, "improvement_hints": hints,
            "_diagnostics": {
                "bg_mean": round(float(bg_mean), 1),
                "edge_ratio": round(float(crisp_edge_ratio), 3),
                "saturation": round(float(sat), 1),
            }}


def overlay_score(image_path: Path, score: dict, out_path: Path) -> Path:
    im = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(im)
    try:
        font_b = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", 36)
        font_n = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 18)
        font_s = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 14)
    except:
        font_b = font_n = font_s = ImageFont.load_default()
    total = score.get("total", 0)
    label = score.get("jump_tier_label", "")
    scores = score.get("scores", {})
    staged = score.get("staged_qa", {})
    if total >= 78: bar = (50, 180, 50)
    elif total >= 65: bar = (220, 200, 30)
    elif total >= 50: bar = (240, 140, 30)
    else: bar = (200, 60, 60)
    # Expand badge to include staged QA strip
    bx, by, bw, bh = im.width - 290, 20, 270, (310 if staged else 230)
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=12,
                            fill=(255, 255, 255), outline=(20, 20, 20), width=3)
    draw.rounded_rectangle([bx, by, bx+bw, by+50], radius=12, fill=bar)
    draw.text((bx + bw//2, by + 25), f"{total:.0f}/100",
              font=font_b, fill=(255, 255, 255), anchor="mm")
    draw.text((bx + 10, by + 60), "Jump-tier:", font=font_s, fill=(80, 80, 80))
    draw.text((bx + 10, by + 78), label[:36], font=font_n, fill=(20, 20, 20))
    y = by + 110
    for axis, val in scores.items():
        short = axis.replace("_", " ")[:18]
        draw.text((bx + 10, y), short, font=font_s, fill=(80, 80, 80))
        bar_x = bx + 130; bar_w = 120
        fill_w = int(bar_w * val / 10)
        bc = bar if val >= 6 else (200, 100, 100) if val < 4 else (180, 180, 80)
        draw.rectangle([bar_x, y+4, bar_x+bar_w, y+14], outline=(150, 150, 150), width=1)
        draw.rectangle([bar_x, y+4, bar_x+fill_w, y+14], fill=bc)
        draw.text((bar_x+bar_w+6, y), f"{val:.0f}", font=font_s, fill=(20, 20, 20))
        y += 18
    # Staged QA strip — 3 horizontal bars showing per-stage averages
    if staged:
        y += 6
        draw.text((bx + 10, y), "Per-stage avg:", font=font_s, fill=(80, 80, 80)); y += 16
        for st_name, st_data in [
            ("blender",  staged.get("stage1_blender", {})),
            ("stylize",  staged.get("stage2_stylize", {})),
            ("composite", {"avg_total": staged.get("stage3_composite", {}).get("total", 0)}),
        ]:
            val = st_data.get("avg_total", 0) / 10  # 0..10
            short = f"S{['blender','stylize','composite'].index(st_name)+1} {st_name}"
            draw.text((bx + 10, y), short, font=font_s, fill=(80, 80, 80))
            bar_x = bx + 130; bar_w = 120
            fill_w = int(bar_w * val / 10)
            bc = bar if val >= 6 else (200, 100, 100) if val < 4 else (180, 180, 80)
            draw.rectangle([bar_x, y+4, bar_x+bar_w, y+14], outline=(150, 150, 150), width=1)
            draw.rectangle([bar_x, y+4, bar_x+fill_w, y+14], fill=bc)
            draw.text((bar_x+bar_w+6, y), f"{st_data.get('avg_total', 0):.0f}", font=font_s, fill=(20, 20, 20))
            y += 16
    im.save(out_path)
    return out_path


# ───── Hybrid post-stage: ComfyUI img2img stylization ─────────────────────
import importlib.util
_STYLIZE = None
def _load_stylize():
    global _STYLIZE
    if _STYLIZE is None:
        spec = importlib.util.spec_from_file_location("stylize", "/tmp/img2img-stylize.py")
        _STYLIZE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_STYLIZE)
    return _STYLIZE


# ───── OCIO grayscale post-process (kills animagine color bias) ──────────
def ocio_grayscale(panel_png: Path) -> Path:
    """Apply OCIO Rec.709 luma transform → manga B&W.

    Uses PyOpenColorIO 2.5 raw matrix transform with the BT.709 luma
    coefficients (0.2126, 0.7152, 0.0722) so the resulting image is
    visually identical to a luminance-only grayscale. This is what
    professional film pipelines use for "remove color" — replicable
    via OCIO config rather than ad-hoc PIL.convert("L").
    """
    import PyOpenColorIO as ocio
    from PIL import Image
    import numpy as np

    im = Image.open(panel_png).convert("RGB")
    arr = np.asarray(im, dtype=np.float32) / 255.0

    # OCIO transform chain:
    #   1) BT.709 luma → grayscale (kill color tint)
    #   2) Gamma lift 1.5 → brighten midtones (manga page, not dark scene)
    #   3) Level adjust: pull blacks slightly, lift whites to 1.05 then clamp
    config = ocio.Config()
    luma = ocio.MatrixTransform(
        matrix=[0.2126, 0.7152, 0.0722, 0.0,
                 0.2126, 0.7152, 0.0722, 0.0,
                 0.2126, 0.7152, 0.0722, 0.0,
                 0.0,    0.0,    0.0,    1.0],
        offset=[0.0, 0.0, 0.0, 0.0])
    # ExponentTransform: pow(value, gamma) where gamma < 1 brightens.
    # 0.50 brightens significantly more than 0.62 — closer to manga paper.
    gamma_lift = ocio.ExponentTransform(value=(0.50, 0.50, 0.50, 1.0))
    transform = ocio.GroupTransform()
    transform.appendTransform(luma)
    transform.appendTransform(gamma_lift)
    processor = config.getProcessor(transform).getDefaultCPUProcessor()

    # In-place transform on contiguous float32 numpy buffer
    h, w = arr.shape[:2]
    arr = np.ascontiguousarray(arr)
    img_desc = ocio.PackedImageDesc(arr, w, h, 3, ocio.BIT_DEPTH_F32,
                                     4,           # chanStrideBytes
                                     12,          # xStrideBytes = 3 ch × 4 bytes
                                     w * 12)      # yStrideBytes
    processor.apply(img_desc)

    out_arr = (np.clip(arr, 0, 1) * 255.0).astype(np.uint8)
    out_path = panel_png.with_name(panel_png.stem + "-bw.png")
    Image.fromarray(out_arr).save(out_path)
    return out_path


def stylize_panels(scene_slug, panel_files, page_num, denoise=0.6, panel_shots=None,
                    page_seed=None, ocio_grayscale_enable=True, scene_graphs=None):
    """Run ComfyUI img2img on each Blender panel; replace with stylized.

    Per-shot denoise tuning:
      Wide / LS  → 0.45 (preserve composition)
      MS         → 0.60
      CU / ECU   → 0.75 (let SDXL fill in face detail)
    """
    import time as _time
    s = _load_stylize()
    char = {"yuto-bedroom":"Yuto","classroom":"Nei","rens-room":"Ren",
             "city-street":None,"akabane-shrine":"Yuto"}.get(scene_slug)
    panel_shots = panel_shots or {}
    out = {}
    # Expose per-panel timings to caller
    globals()["LAST_PANEL_TIMINGS"] = {}
    for idx, panel_path in panel_files.items():
        if not Path(panel_path).exists():
            out[idx] = panel_path; continue
        shot = panel_shots.get(idx, "MS")
        d = denoise
        sty = Path(f"/tmp/v5-stylized-pg{page_num:02d}-p{idx:02d}.png")
        spec = (scene_graphs or {}).get(idx)
        stylize_t0 = _time.monotonic()
        result = s.stylize(Path(panel_path), char, scene_slug, shot, sty,
                            denoise=d, page_seed=page_seed, panel_idx=idx,
                            scene_graph=spec)
        comfyui_s = round(_time.monotonic() - stylize_t0, 2)
        ocio_s = 0
        if result and result.exists():
            # OCIO grayscale post-process — kills animagine color bias
            if ocio_grayscale_enable:
                try:
                    ocio_t0 = _time.monotonic()
                    bw = ocio_grayscale(result)
                    ocio_s = round(_time.monotonic() - ocio_t0, 2)
                    out[idx] = str(bw)
                    print(f"    panel {idx} stylized + OCIO B&W ({shot} d={d:.2f}) "
                          f"comfyui={comfyui_s}s ocio={ocio_s}s")
                except Exception as e:
                    print(f"    panel {idx} OCIO failed: {e}")
                    out[idx] = str(result)
            else:
                out[idx] = str(result)
                print(f"    panel {idx} stylized ({shot} denoise={d:.2f}) comfyui={comfyui_s}s")
        else:
            out[idx] = panel_path
        # Record per-panel timing
        globals()["LAST_PANEL_TIMINGS"][idx] = {
            "shot":      shot,
            "comfyui_s": comfyui_s,
            "ocio_s":    ocio_s,
        }
    return out


def react_loop(page_num: int, target_score: float = 65.0,
                max_iter: int = int(__import__("os").environ.get("V5_MAX_ITER", "1"))) -> dict:
    m = json.loads(MANIFEST.read_text())
    panels = sorted([p for p in m["panels"] if p["pageNum"] == page_num],
                     key=lambda p: p["panelIndex"])
    if not panels:
        return {"error": f"no panels for page {page_num}"}
    scene_slug = SCENE_MAPPING.get(page_num, "yuto-bedroom")
    layout = compute_layout(panels)
    history = []
    # Expose to vision_score for manifest-match QA
    globals()["CURRENT_PAGE_PANELS"] = panels
    globals()["CURRENT_SCENE_SLUG"]  = scene_slug
    ridge = 6.0; valley = 6.0
    iter_idx = 0
    print(f"\n=== Page {page_num} v5+ ReAct (target>={target_score}) ===")
    print(f"  scene={scene_slug}, {len(panels)} panels, mannequin+bubbles enabled")
    # Stage-wise QA accumulators
    qa_stage1 = {}  # panel_idx → blender-stage scores
    qa_stage2 = {}  # panel_idx → stylize-stage scores
    qa_stage3 = {}  # composite-stage scores (single)

    import time as _time
    timings = {"per_iter": []}
    pipeline_t0 = _time.monotonic()

    for it in range(max_iter):
        iter_timings = {}
        iter_t0 = _time.monotonic()
        print(f"  [iter {it}] ridge={ridge:.1f} valley={valley:.1f}")
        # Stage 1: Blender block-out render per panel
        panel_files = {}
        blender_files = {}
        # Stage 0.5 — generate per-panel scene graph specs
        scene_graphs = {}
        sg_t0 = _time.monotonic()
        try:
            import importlib.util
            spec_loader = importlib.util.spec_from_file_location(
                "sgd", str(Path(__file__).parent.parent / "lg_mangaka/scene_graph_designer.py")
                       if "_archive" in str(Path(__file__))
                       else "/tmp/scene_graph_designer.py")
            if spec_loader is None or not spec_loader.origin or not Path(spec_loader.origin).exists():
                spec_loader = importlib.util.spec_from_file_location(
                    "sgd", "/tmp/scene_graph_designer.py")
            sgd_mod = importlib.util.module_from_spec(spec_loader)
            spec_loader.loader.exec_module(sgd_mod)
            for slot in layout:
                p = slot["panel"]
                scene_graphs[slot["idx"]] = sgd_mod.design_scene_graph(p, scene_slug, use_llm=False)
            print(f"  [scene-graph] {len(scene_graphs)} specs generated")
        except Exception as e:
            print(f"  [scene-graph] skipped: {e}")
        iter_timings["scene_graph_s"] = round(_time.monotonic() - sg_t0, 1)
        blender_t0 = _time.monotonic()

        for slot in layout:
            p = slot["panel"]; idx = slot["idx"]
            s_lower = (p.get("shot") or "").lower()
            shot_cat = "MS"
            if "extreme close" in s_lower: shot_cat = "ECU"
            elif "close" in s_lower:       shot_cat = "CU"
            elif "long" in s_lower:        shot_cat = "LS"
            elif "wide" in s_lower:        shot_cat = "Wide"
            elif "medium" in s_lower:      shot_cat = "MS"
            spec = scene_graphs.get(idx)
            out = render_panel(scene_slug, shot_cat, idx, page_num,
                                width=slot["w"]*2, height=slot["h"]*2,
                                iter_idx=iter_idx, ridge=ridge, valley=valley,
                                with_mannequin=True, scene_graph=spec)
            if out:
                panel_files[idx] = out
                blender_files[idx] = out
                # Stage-1 QA on the Blender output
                q1 = qa_stage1_blender(Path(out))
                qa_stage1[idx] = q1
                if q1["issues"]:
                    print(f"    [QA1 p{idx}] {q1['total']}/100  {q1['issues'][:1]}")

        # Stage 2: ComfyUI stylize per panel (ControlNet+txt2img)
        if os.environ.get("V5_STYLIZE", "1") == "1":
            panel_shots = {}
            for slot in layout:
                p = slot["panel"]
                s_lower = (p.get("shot") or "").lower()
                if "extreme close" in s_lower: panel_shots[slot["idx"]] = "ECU"
                elif "close" in s_lower:       panel_shots[slot["idx"]] = "CU"
                elif "long" in s_lower:        panel_shots[slot["idx"]] = "LS"
                elif "wide" in s_lower:        panel_shots[slot["idx"]] = "Wide"
                else:                          panel_shots[slot["idx"]] = "MS"
            iter_timings["blender_s"] = round(_time.monotonic() - blender_t0, 1)
            stylize_t0 = _time.monotonic()
            # Page-level seed: same base seed across all panels keeps the
            # character identity (combined with LoRA) consistent. Per-panel
            # offset of +idx changes pose/expression while keeping look.
            page_seed = page_num * 7919 + 12345
            stylized = stylize_panels(scene_slug, panel_files, page_num,
                                       denoise=float(os.environ.get("V5_DENOISE", "0.6")),
                                       panel_shots=panel_shots, page_seed=page_seed,
                                       scene_graphs=scene_graphs)
            iter_timings["stylize_s"] = round(_time.monotonic() - stylize_t0, 1)
            # Stage-2 QA per panel
            focal_char = {"yuto-bedroom":"Yuto","classroom":"Nei","rens-room":"Ren",
                            "city-street":None}.get(scene_slug)
            for idx, sty_path in stylized.items():
                q2 = qa_stage2_stylize(Path(blender_files.get(idx) or sty_path),
                                         Path(sty_path), focal_char)
                qa_stage2[idx] = q2
                if q2["issues"]:
                    print(f"    [QA2 p{idx}] {q2['total']}/100  {q2['issues'][:1]}")
            panel_files = stylized

        composite_t0 = _time.monotonic()
        # Stage 3: composite + bubbles
        comp = composite_page(page_num, layout, panel_files, iter_idx=it, add_bubbles=True)
        iter_timings["composite_s"] = round(_time.monotonic() - composite_t0, 1)
        score_t0 = _time.monotonic()
        score = vision_score(comp)
        iter_timings["score_s"] = round(_time.monotonic() - score_t0, 1)
        # Per-panel grid scoring on the composite
        per_panel = score_per_panel(comp, layout, panels=panels, scene_slug=scene_slug)
        flagged = {idx: info for idx, info in per_panel.items()
                    if info.get("issues")}
        if flagged:
            print(f"    [QA3 per-panel flagged]:")
            for idx, info in sorted(flagged.items()):
                for iss in info["issues"][:1]:
                    print(f"      p{idx}: {iss}")
        # Display per-panel totals (heuristic + Gemma combined)
        per_panel_scored = {idx: info for idx, info in per_panel.items()
                              if "total" in info}
        if per_panel_scored:
            avg_panel = sum(info["total"] for info in per_panel_scored.values()) / len(per_panel_scored)
            print(f"    [QA3 per-panel scores] avg={avg_panel:.1f}")
            for idx, info in sorted(per_panel_scored.items()):
                pt = info["total"]
                gj = info.get("gemma_jump", {}).get("total")
                gm = info.get("gemma_manifest", {}).get("total")
                gj_s = f" jump={gj}" if gj else ""
                gm_s = f" manifest={gm}" if gm else ""
                print(f"      p{idx}: {pt:5.1f}/100{gj_s}{gm_s}")
        qa_stage3 = score
        qa_stage3["per_panel"] = per_panel
        qa_stage3["flagged_panels"] = sorted(flagged.keys())
        # Per-panel honest average overrides combined page score weighting
        # (user feedback: page-only score not honest)
        if per_panel_scored:
            panel_avg = sum(info["total"] for info in per_panel_scored.values()) / len(per_panel_scored)
            qa_stage3["per_panel_avg"] = round(panel_avg, 1)
        iter_timings["total_s"] = round(_time.monotonic() - iter_t0, 1)
        timings["per_iter"].append({"iter": it, **iter_timings})
        print(f"    [timing iter {it}] sg={iter_timings.get('scene_graph_s',0)}s "
              f"blender={iter_timings.get('blender_s',0)}s "
              f"stylize={iter_timings.get('stylize_s',0)}s "
              f"composite={iter_timings.get('composite_s',0)}s "
              f"score={iter_timings.get('score_s',0)}s "
              f"= {iter_timings['total_s']}s")
        history.append({"iter": it, "total": score["total"],
                         "label": score["jump_tier_label"],
                         "issues": score["issues"],
                         "hints": score.get("improvement_hints", [])})
        print(f"  → {score['total']:.0f}/100 ({score['jump_tier_label']})")
        if score["total"] >= target_score:
            print(f"  ✓ target met at iter {it}")
            break
        # Per-iteration ReAct adjustments based on what's failing:
        ridge = min(10.0, ridge + 2.0); valley = min(10.0, valley + 2.0)
        # If score is low because of inking/wasted_lines, lower denoise next iter
        # If score is low because of character_visible, bump seed offset
        # If score is low because of brightness, increase gamma
        per_panel = score.get("staged_qa", {}).get("stage3_composite", {}).get("per_panel", {})
        flagged = score.get("staged_qa", {}).get("stage3_composite", {}).get("flagged_panels", [])
        # Adjust V5 env vars in-place for next stylize_panels call
        cur_denoise = float(os.environ.get("V5_DENOISE", "0.6"))
        # Count flag types
        n_dark = sum(1 for idx, info in per_panel.items()
                      if any("暗すぎる" in iss for iss in info.get("issues", [])))
        n_chaos = sum(1 for idx, info in per_panel.items()
                       if any("意味不明" in iss for iss in info.get("issues", [])))
        if n_chaos > 0:
            os.environ["V5_DENOISE"] = str(max(0.45, cur_denoise - 0.05))
            print(f"    [react] {n_chaos} chaos panels → lowering denoise to {os.environ['V5_DENOISE']}")
        elif score["total"] < target_score - 10:
            os.environ["V5_DENOISE"] = str(min(0.75, cur_denoise + 0.05))
            print(f"    [react] far below target → bumping denoise to {os.environ['V5_DENOISE']}")
        iter_idx += 1

    # Aggregate stage averages
    def _avg(d, key="total"):
        if not d: return 0
        return round(sum(s.get(key, 0) for s in d.values()) / len(d), 1)
    stage1_avg = _avg(qa_stage1)
    stage2_avg = _avg(qa_stage2)
    stage3_total = score.get("total", 0)
    print(f"  stage averages: stage1_blender={stage1_avg}  stage2_stylize={stage2_avg}  stage3_composite={stage3_total}")

    final = Path(f"/tmp/gh-arc0-1-v5plus-p{page_num:02d}-scored.png")
    # 2026-05-23: stop burning the score badge into the image — gallery
    # reads the sidecar -score.json and renders the review below the card.
    Image.open(comp).save(final)
    score["history"] = history
    score["iter_count"] = len(history)
    # Take a shallow copy of qa_stage3 to avoid circular reference when
    # we embed it back into the score dict that's being written.
    qa3_summary = {
        "total":  qa_stage3.get("total", 0),
        "label":  qa_stage3.get("jump_tier_label", ""),
        "scores": dict(qa_stage3.get("scores", {})),
        "issues": list(qa_stage3.get("issues", []))[:5],
        "per_panel": qa_stage3.get("per_panel", {}),
        "flagged_panels": qa_stage3.get("flagged_panels", []),
    }
    # Pipeline timings — bottleneck analysis
    timings["total_pipeline_s"] = round(_time.monotonic() - pipeline_t0, 1)
    # Per-panel breakdown (last iter only)
    panel_timings = {}
    last_blender = globals().get("LAST_BLENDER_TIMINGS", {})
    last_stylize = globals().get("LAST_PANEL_TIMINGS", {})
    for idx in sorted(set(last_blender.keys()) | set(last_stylize.keys())):
        b = last_blender.get(idx, {})
        s = last_stylize.get(idx, {})
        panel_timings[idx] = {
            "shot":      b.get("shot") or s.get("shot"),
            "engine":    b.get("engine", "EEVEE"),
            "blender_s": b.get("blender_s", 0),
            "comfyui_s": s.get("comfyui_s", 0),
            "ocio_s":    s.get("ocio_s", 0),
            "total_s":   round(b.get("blender_s", 0) + s.get("comfyui_s", 0)
                                  + s.get("ocio_s", 0), 2),
        }
    timings["per_panel"] = panel_timings
    if panel_timings:
        print(f"\n  [PER-PANEL TIMING (last iter)]")
        print(f"    {'panel':<6} {'shot':<6} {'engine':<7} {'blender':>9} {'comfyui':>9} {'ocio':>6} {'total':>8}")
        for idx, t in sorted(panel_timings.items()):
            print(f"    p{idx:<4} {t.get('shot','-'):<6} {t.get('engine','-'):<7} "
                  f"{t['blender_s']:>7.2f}s {t['comfyui_s']:>7.2f}s "
                  f"{t['ocio_s']:>4.2f}s {t['total_s']:>6.2f}s")
    # Aggregate per-phase totals across iters
    timings["aggregate_s"] = {
        "scene_graph": round(sum(t.get("scene_graph_s", 0) for t in timings["per_iter"]), 1),
        "blender":     round(sum(t.get("blender_s", 0)     for t in timings["per_iter"]), 1),
        "stylize":     round(sum(t.get("stylize_s", 0)     for t in timings["per_iter"]), 1),
        "composite":   round(sum(t.get("composite_s", 0)   for t in timings["per_iter"]), 1),
        "score":       round(sum(t.get("score_s", 0)       for t in timings["per_iter"]), 1),
    }
    # % breakdown
    total = max(1.0, timings["total_pipeline_s"])
    timings["pct"] = {k: round(v / total * 100, 1)
                       for k, v in timings["aggregate_s"].items()}
    print(f"\n  [PIPELINE TIMING TOTAL: {timings['total_pipeline_s']}s]")
    for k, s in timings["aggregate_s"].items():
        print(f"    {k:<12} {s:>6.1f}s  ({timings['pct'][k]:>5.1f}%)")
    score["timings"] = timings
    # Version stamp — which Stage 1 base + engine produced this artifact
    score["version"] = {
        "v5_base":   os.environ.get("V5_BASE", "manga"),
        "engine":    "CYCLES" if os.environ.get("V5_BASE", "manga") == "cinematic" else "EEVEE",
        "max_iter":  int(os.environ.get("V5_MAX_ITER", "1")),
        "use_lora":  os.environ.get("V5_USE_LORA", "0") == "1",
        "use_ipadapter": os.environ.get("V5_USE_IPADAPTER", "0") == "1",
        "use_regional":  os.environ.get("V5_USE_REGIONAL", "0") == "1",
        "manga_mode":    os.environ.get("V5_MANGA_MODE", "1") == "1",
        "geonodes":      os.environ.get("V6_GEONODES", "0") == "1",
        "v7_bg_mode":    os.environ.get("V7_BG_MODE", ""),
        "v7_pose_lib":   os.environ.get("V7_POSE_LIB", ""),
        "first_axes":    (FIRST_AXES.to_dict() if FIRST_AXES is not None else None),
        "rendered_at":   int(_time.time()),
    }
    score["staged_qa"] = {
        "stage1_blender": {"avg_total": stage1_avg, "per_panel": qa_stage1},
        "stage2_stylize": {"avg_total": stage2_avg, "per_panel": qa_stage2},
        "stage3_composite": qa3_summary,
        "summary": (
            f"Pipeline: Blender({stage1_avg}/100) → "
            f"ComfyUI-stylize({stage2_avg}/100) → "
            f"Composite({stage3_total}/100)"
        ),
    }
    sidecar = Path(f"/tmp/gh-arc0-1-v5plus-p{page_num:02d}-score.json")
    sidecar.write_text(json.dumps(score, indent=2, ensure_ascii=False))
    print(f"  ✓ final: {final}")
    # Auto-update gallery after every page render
    try:
        update_gallery(page_num, final, score)
    except Exception as e:
        print(f"  (gallery update failed: {e})")
    return score


# ───── Gallery auto-update ────────────────────────────────────────────────
GALLERY_DIR = Path("/tmp/mangaka-gallery")
GALLERY_IMG = GALLERY_DIR / "img"
GALLERY_HTML = GALLERY_DIR / "index.html"
GALLERY_MARK_START = "<!-- V5PLUS-AUTO-START -->"
GALLERY_MARK_END = "<!-- V5PLUS-AUTO-END -->"


def update_gallery(page_num: int, image_path: Path, score: dict):
    """Data/view separation: copy artifacts + regenerate manifest.json.

    The gallery's index.html fetches manifest.json on load and renders;
    we never mutate the HTML. Solves the nesting/accumulation issue from
    the previous implementation.
    """
    if not GALLERY_DIR.exists():
        print(f"  (gallery dir not found: {GALLERY_DIR})")
        return
    GALLERY_IMG.mkdir(parents=True, exist_ok=True)
    # Copy new image + sidecar JSON into the gallery img dir
    (GALLERY_IMG / image_path.name).write_bytes(image_path.read_bytes())
    sidecar = image_path.with_name(image_path.name.replace("-scored.png", "-score.json"))
    if sidecar.exists():
        (GALLERY_IMG / sidecar.name).write_bytes(sidecar.read_bytes())

    # Regenerate manifest.json via build-manifest.py.
    builder = Path("/tmp/build-manifest.py")
    if builder.exists():
        import subprocess
        try:
            subprocess.run(["python3", str(builder)], check=True, capture_output=True)
            print(f"  ✓ gallery manifest rebuilt: {GALLERY_DIR}/manifest.json")
        except subprocess.CalledProcessError as e:
            print(f"  (manifest rebuild failed: {e.stderr.decode()[:200]})")
        return
    # Legacy fallback (only if build-manifest.py missing — should never run)
    print(f"  (no build-manifest.py — skipping gallery update)")
    return
    # Dead legacy code below — kept for git history reference only:

    # Scan all v5+ artifacts (filename: gh-arc0-1-v5plus-pNN-scored.png)
    import re as _re
    seen = {}
    for src in [Path("/tmp"), GALLERY_IMG]:
        for png in sorted(src.glob("gh-arc0-1-v5plus-p*-scored.png")):
            m = _re.search(r"-v5plus-p(\d+)-scored", png.stem)
            if not m: continue
            pn = int(m.group(1))
            j = png.with_name(png.stem.replace("-scored", "-score") + ".json")
            total, label, issues = "?", "?", []
            if j.exists():
                try:
                    d = json.loads(j.read_text())
                    total = d.get("total", "?")
                    label = d.get("jump_tier_label", "?")
                    issues = d.get("issues", [])
                except: pass
            tier = ("mid" if isinstance(total, (int, float)) and total >= 65 else
                     "lower" if isinstance(total, (int, float)) and total >= 50 else "trial")
            border = {"mid": "#50b450", "lower": "#f0a040", "trial": "#c84040"}[tier]
            # Copy into gallery
            (GALLERY_IMG / png.name).write_bytes(png.read_bytes())
            seen[pn] = (png.name, total, label, border, issues[:1])

    cards_html = "\n".join(
        f'    <div class="card" style="border-color: {b};">'
        f'<img src="img/{n}" onclick="lb(this.src)">'
        f'<div class="lbl">★ page {pn:02d} · {t}/100 · {l}'
        f'<br><span class="fn">{n}</span>'
        + (f'<br><span style="color:#c84040;font-size:11px;">issue: {iss[0][:60]}</span>' if iss else "")
        + "</div></div>"
        for pn, (n, t, l, b, iss) in sorted(seen.items())
    )

    if not GALLERY_HTML.exists():
        return
    html = GALLERY_HTML.read_text()
    auto_block = (
        f"{GALLERY_MARK_START}\n"
        f'<div class="phase" id="v5-auto" style="border-top: 3px solid #50b450;">\n'
        f'  <h2>★ v5+ auto-updated (latest renders, honest scoring)</h2>\n'
        f'  <p class="note">Auto-updated by render-v5-page.py after every page. Honest 9-axis rubric: background_white / character_visible / panel_diversity / inking_quality / composition_bimodal / scene_continuity / bubble_legibility / emotional_impact / artifact_freedom. Border: green ≥65, orange ≥50, red &lt;50.</p>\n'
        f'  <div class="grid">\n{cards_html}\n  </div>\n'
        f"</div>\n"
        f"{GALLERY_MARK_END}"
    )
    import re
    if GALLERY_MARK_START in html and GALLERY_MARK_END in html:
        html = re.sub(
            re.escape(GALLERY_MARK_START) + r".*?" + re.escape(GALLERY_MARK_END),
            auto_block, html, count=1, flags=re.DOTALL)
    else:
        # Insert before the existing #v5 section
        marker = '<div class="phase" id="v5"'
        if marker in html:
            html = html.replace(marker, auto_block + "\n\n" + marker, 1)
    GALLERY_HTML.write_text(html)
    print(f"  ✓ gallery updated: {len(seen)} cards · {GALLERY_HTML}")


FIRST_AXES = None  # set by main() from --preset / --axes; used by react_loop()


def main():
    global FIRST_AXES
    if len(sys.argv) < 2:
        print("usage: render-v5-page.py [--preset NAME] [--axes K=V,...] "
              "<page_num> [page_num ...]")
        return 1
    # First-axis vector parsing (--preset / --axes). Strips its own flags
    # so the remaining argv is positional page numbers as before.
    _lg_root = str(Path(__file__).resolve().parent.parent)
    if _lg_root not in sys.path:
        sys.path.insert(0, _lg_root)
    from lg_mangaka import first_axes as _fa  # noqa: E402
    axes, rest = _fa.resolve_from_argv(sys.argv[1:])
    if axes is not None:
        env_overlay = _fa.resolve_env(axes)
        for k, v in env_overlay.items():
            os.environ[k] = v
        FIRST_AXES = axes
        top = ", ".join(f"{a}={w:.2f}" for a, w in axes.top_n(3))
        tag = axes.preset or "custom"
        print(f"[first-axes] preset={tag} dominant={axes.dominant()} top3=({top})")
        print(f"[first-axes] env overlay: " +
              " ".join(f"{k}={v}" for k, v in env_overlay.items()))
    if not rest:
        print("usage: render-v5-page.py [--preset NAME] [--axes K=V,...] "
              "<page_num> [page_num ...]")
        return 1
    for arg in rest:
        react_loop(int(arg))


if __name__ == "__main__":
    sys.exit(main() or 0)

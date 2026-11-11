import bpy, sys, mathutils
bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete()

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "FLAT"
scene.display.shading.color_type = "SINGLE"
scene.display.shading.single_color = (1, 1, 1)
scene.display.shading.show_object_outline = True
scene.display.shading.object_outline_color = (0, 0, 0)
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.display.shading.curvature_ridge_factor = 2.0
scene.display.shading.curvature_valley_factor = 2.0
scene.render.resolution_x = 1216
scene.render.resolution_y = 832

bpy.ops.wm.usd_import(filepath="/tmp/yuto-bedroom-narrative.usda",
                       import_cameras=True, import_lights=True,
                       import_materials=True, import_meshes=True,
                       scale=100.0)

# Camera INSIDE the room, near "yuto_at_desk" original USD coords:
# USD coords (1.0, 1.5, 1.3) → Blender Y-up→Z-up: (1.0, -1.3, 1.5)
cam_data = bpy.data.cameras.new("V5Cam"); cam_data.lens = 35
cam_obj = bpy.data.objects.new("V5Cam", cam_data)
scene.collection.objects.link(cam_obj)
cam_obj.location = (1.0, -1.3, 1.5)
# Target was (3.7, 0.85, 2.1) → Blender (3.7, -2.1, 0.85)
target = mathutils.Vector((3.7, -2.1, 0.85))
direction = target - cam_obj.location
rot_quat = direction.to_track_quat('-Z', 'Y')
cam_obj.rotation_euler = rot_quat.to_euler()
scene.camera = cam_obj
print(f"cam at {tuple(cam_obj.location)} -> target {tuple(target)}")

# Verify objects in frustum-ish
print(f"meshes: {sum(1 for o in bpy.data.objects if o.type=='MESH')}")

scene.render.filepath = "/tmp/v5-blender-yuto-bedroom-test.png"
bpy.ops.render.render(write_still=True)
print(f"OK")

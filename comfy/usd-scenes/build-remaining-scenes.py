"""Build the remaining 3 arc 0-1 scenes:
  - city-street       3 pages (after-school, urban Japanese)
  - akabane-shrine    2 pages (traditional Japanese)
  - cyberspace        1 page (abstract data flow, page 21)
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageFilter
from pxr import Usd, UsdGeom, Gf

OUT_DIR = Path("/tmp/arc01-scenes")
OUT_DIR.mkdir(exist_ok=True)


def render_depth(sm, co, ct, fov, W2=608, H2=416):
    o = np.array(co); t = np.array(ct)
    f = t - o; f /= np.linalg.norm(f) + 1e-9
    r = np.cross(f, [0, 1, 0]); r /= np.linalg.norm(r) + 1e-9
    u = np.cross(r, f)
    fov = np.radians(fov)
    hh = np.tan(fov / 2); hw = hh * (W2 / H2)
    xs = np.linspace(-hw, hw, W2); ys = np.linspace(hh, -hh, H2)
    gx, gy = np.meshgrid(xs, ys)
    dirs = (f[None, None, :] + gx[..., None] * r[None, None, :] + gy[..., None] * u[None, None, :])
    dirs /= np.linalg.norm(dirs, axis=2, keepdims=True) + 1e-9
    df = dirs.reshape(-1, 3); orig = np.tile(o, (df.shape[0], 1))
    hits, idx, _ = sm.ray.intersects_location(ray_origins=orig, ray_directions=df, multiple_hits=False)
    depth = np.full(df.shape[0], np.inf)
    if len(hits):
        d = np.linalg.norm(hits - orig[idx], axis=1)
        np.minimum.at(depth, idx, d)
    depth = depth.reshape(H2, W2)
    fin = depth[np.isfinite(depth)]
    far = float(np.percentile(fin, 99)) if len(fin) else 25.0
    depth = np.where(np.isfinite(depth), depth, far)
    near = float(depth.min())
    return ((far - depth) / max(1e-6, far - near) * 255).clip(0, 255).astype(np.uint8)


def canny(arr):
    im = Image.fromarray(arr).filter(ImageFilter.FIND_EDGES)
    a = np.array(im)
    return Image.fromarray(((a > 30).astype(np.uint8) * 255))


def write_usd(meshes, path, root_name):
    s = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(s, f"/{root_name}")
    s.SetDefaultPrim(root.GetPrim())
    s.SetMetadata("upAxis", "Y")
    for n, mesh in meshes:
        p = UsdGeom.Mesh.Define(s, f"/{root_name}/{n.replace('-', '_')}")
        p.GetPointsAttr().Set([Gf.Vec3f(*v) for v in mesh.vertices.tolist()])
        p.GetFaceVertexIndicesAttr().Set(mesh.faces.flatten().tolist())
        p.GetFaceVertexCountsAttr().Set([3] * len(mesh.faces))
    s.GetRootLayer().Save()


def render_scene(slug, meshes, cameras, root_name):
    print(f"\n=== {slug} ===", flush=True)
    print(f"  {len(meshes)} primitives", flush=True)
    write_usd(meshes, OUT_DIR / f"{slug}.usda", root_name)
    scene = trimesh.util.concatenate([m for _, m in meshes])
    print(f"  combined: {len(scene.vertices)} verts, {len(scene.faces)} faces", flush=True)
    for cn, (o, t, fov) in cameras.items():
        print(f"  camera {cn}", flush=True)
        d = render_depth(scene, o, t, fov)
        im = Image.fromarray(d).resize((1216, 832), Image.NEAREST)
        im.save(OUT_DIR / f"{slug}-{cn}-depth.png")
        canny(np.array(im)).save(OUT_DIR / f"{slug}-{cn}-canny.png")


# ── city-street ────────────────────────────────────────────────────────────
def city_street():
    m = []
    # ground plane (10m x 30m)
    g = trimesh.creation.box(extents=[10, 0.01, 30]); g.apply_translation([5, 0, 15])
    m.append(("street", g))
    # 2 sidewalks (raised)
    for sx, name in [(1.0, "sidewalk_l"), (9.0, "sidewalk_r")]:
        s = trimesh.creation.box(extents=[2.0, 0.15, 30])
        s.apply_translation([sx, 0.075, 15])
        m.append((name, s))
    # 6 buildings along left side (3-storey, 4m wide each)
    for i in range(6):
        b = trimesh.creation.box(extents=[2.5, 8.0, 4.0])
        b.apply_translation([-0.5, 4.0, 2 + i * 5])
        m.append((f"building_l{i}", b))
    # 6 buildings along right side
    for i in range(6):
        b = trimesh.creation.box(extents=[2.5, 9.5, 4.0])
        b.apply_translation([10.5, 4.75, 2 + i * 5])
        m.append((f"building_r{i}", b))
    # Street lamps (4 along left sidewalk)
    for i in range(4):
        post = trimesh.creation.cylinder(radius=0.05, height=4.5, sections=8)
        post.apply_translation([1.5, 2.25, 4 + i * 6])
        m.append((f"lamp_post_{i}", post))
        head = trimesh.creation.box(extents=[0.3, 0.2, 0.2])
        head.apply_translation([1.5, 4.5, 4 + i * 6])
        m.append((f"lamp_head_{i}", head))
    return m


CITY_CAMS = {
    "wide_perspective": ((5.0, 1.6, 27.0), (5.0, 1.6, 5.0), 60.0),
    "sidewalk_walking": ((2.5, 1.5, 24.0), (3.5, 1.5, 8.0), 55.0),
    "looking_up_at_buildings": ((5.0, 1.5, 15.0), (5.0, 6.0, 5.0), 70.0),
}


# ── akabane-shrine ─────────────────────────────────────────────────────────
def shrine():
    m = []
    # ground
    g = trimesh.creation.box(extents=[15, 0.01, 20]); g.apply_translation([7.5, 0, 10])
    m.append(("ground", g))
    # stone path (raised slightly)
    path = trimesh.creation.box(extents=[2.0, 0.05, 20])
    path.apply_translation([7.5, 0.025, 10])
    m.append(("stone_path", path))
    # torii gate (red gate, simplified) — at z=0
    # left post
    pl = trimesh.creation.cylinder(radius=0.15, height=4.0, sections=8)
    pl.apply_translation([6.0, 2.0, 1.5])
    m.append(("torii_left_post", pl))
    # right post
    pr = trimesh.creation.cylinder(radius=0.15, height=4.0, sections=8)
    pr.apply_translation([9.0, 2.0, 1.5])
    m.append(("torii_right_post", pr))
    # top beam (kasagi)
    top = trimesh.creation.box(extents=[4.0, 0.30, 0.30])
    top.apply_translation([7.5, 4.0, 1.5])
    m.append(("torii_kasagi", top))
    # secondary beam (shimaki)
    sb = trimesh.creation.box(extents=[3.4, 0.20, 0.20])
    sb.apply_translation([7.5, 3.6, 1.5])
    m.append(("torii_shimaki", sb))
    # 2 stone lanterns
    for i, lz in enumerate([6.0, 13.0]):
        lbase = trimesh.creation.box(extents=[0.5, 0.5, 0.5])
        lbase.apply_translation([4.5, 0.25, lz])
        m.append((f"lantern_{i}_base", lbase))
        lcap = trimesh.creation.cylinder(radius=0.25, height=0.4, sections=12)
        lcap.apply_translation([4.5, 0.7, lz])
        m.append((f"lantern_{i}_body", lcap))
        lroof = trimesh.creation.cone(radius=0.4, height=0.35, sections=12)
        lroof.apply_translation([4.5, 1.1, lz])
        m.append((f"lantern_{i}_roof", lroof))
    # 2 stone lanterns on the other side
    for i, lz in enumerate([6.0, 13.0]):
        lbase = trimesh.creation.box(extents=[0.5, 0.5, 0.5])
        lbase.apply_translation([10.5, 0.25, lz])
        m.append((f"lantern_r{i}_base", lbase))
        lcap = trimesh.creation.cylinder(radius=0.25, height=0.4, sections=12)
        lcap.apply_translation([10.5, 0.7, lz])
        m.append((f"lantern_r{i}_body", lcap))
        lroof = trimesh.creation.cone(radius=0.4, height=0.35, sections=12)
        lroof.apply_translation([10.5, 1.1, lz])
        m.append((f"lantern_r{i}_roof", lroof))
    # Main shrine building at end of path (rectangular with steep roof)
    shrine = trimesh.creation.box(extents=[5.0, 3.0, 4.0])
    shrine.apply_translation([7.5, 1.5, 18.0])
    m.append(("shrine_body", shrine))
    # Roof (large pitched, simplified as a wide flat slab)
    roof = trimesh.creation.box(extents=[7.0, 0.4, 5.0])
    roof.apply_translation([7.5, 3.2, 18.0])
    m.append(("shrine_roof", roof))
    # 2 stairs in front of shrine
    for i in range(3):
        st = trimesh.creation.box(extents=[3.0, 0.15, 0.3])
        st.apply_translation([7.5, 0.075 + i * 0.15, 15.5 + i * 0.3])
        m.append((f"shrine_step_{i}", st))
    return m


SHRINE_CAMS = {
    "torii_approach": ((7.5, 1.7, 0.5), (7.5, 1.5, 18.0), 60.0),
    "from_shrine": ((7.5, 1.6, 16.0), (7.5, 1.4, 0.5), 65.0),
    "side_view": ((11.0, 1.5, 10.0), (4.0, 1.5, 10.0), 75.0),
}


# ── cyberspace ─────────────────────────────────────────────────────────────
def cyberspace():
    m = []
    # No floor / ceiling — abstract empty space
    # Glowing data conduits as cylinders crossing the scene
    for i, (x, y, z, dx, dy, dz) in enumerate([
        (5, 2, 0, 0, 0, 10),
        (0, 2, 5, 10, 0, 0),
        (3, 4, 3, 5, 1, 5),
        (7, 1, 2, -3, 2, 6),
        (2, 5, 8, 4, -2, -3),
    ]):
        seg = trimesh.creation.cylinder(radius=0.06, height=np.sqrt(dx*dx + dy*dy + dz*dz), sections=8)
        # Position at midpoint, rotation
        seg.apply_translation([x + dx/2, y + dy/2, z + dz/2])
        m.append((f"data_stream_{i}", seg))
    # Floating data nodes — cubes
    for i, (x, y, z, s) in enumerate([
        (2, 3, 4, 0.4),
        (7, 4, 6, 0.5),
        (5, 1, 2, 0.3),
        (3, 5, 8, 0.6),
        (8, 2, 3, 0.4),
    ]):
        cube = trimesh.creation.box(extents=[s, s, s])
        cube.apply_translation([x, y, z])
        m.append((f"node_{i}", cube))
    # Distant glow boundaries — large box walls (very far)
    for n, x, y, z, ext in [
        ("far_wall", 5, 5, 15, [20, 15, 0.5]),
        ("ceiling_grid", 5, 10, 5, [20, 0.5, 30]),
    ]:
        b = trimesh.creation.box(extents=ext)
        b.apply_translation([x, y, z])
        m.append((n, b))
    return m


CYBER_CAMS = {
    "data_flow_main": ((5.0, 3.0, 0.5), (5.0, 3.0, 10.0), 70.0),
    "abstract_corridor": ((2.0, 2.5, 0.5), (8.0, 3.0, 12.0), 75.0),
}


def main():
    render_scene("city-street", city_street(), CITY_CAMS, "CityStreet")
    render_scene("akabane-shrine", shrine(), SHRINE_CAMS, "AkabaneShrine")
    render_scene("cyberspace", cyberspace(), CYBER_CAMS, "Cyberspace")
    print("\n=== all done ===")


if __name__ == "__main__":
    sys.exit(main() or 0)

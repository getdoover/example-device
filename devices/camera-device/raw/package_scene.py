"""Correct intersections and pack only used texture maps. Called by finish_scene.py."""

from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parent
scene = bpy.context.scene
if not scene.get("detail_intersections_corrected"):
    prefixes = (
        "Ivory clock dial",
        "Clock brass bezel",
        "Roman clock numeral",
        "Clock hand",
    )
    for o in bpy.data.objects:
        if o.name.startswith(prefixes):
            if o.type == "CURVE" and o.data.splines:
                pts = o.data.splines[0].points
                center = (
                    sum((Vector(p.co[:3]) for p in pts), Vector()) / len(pts)
                    + o.location
                )
            else:
                center = o.location.copy()
            radial = center - Vector((0, 14.2, 3.35))
            offset = (
                Vector((0.18 if radial.x > 0 else -0.18, 0, 0))
                if abs(radial.x) > abs(radial.y)
                else Vector((0, 0.18 if radial.y > 0 else -0.18, 0))
            )
            o.location += offset
        if o.name.startswith(("Ivory fascia inset scallop", "Fascia raised pilaster")):
            # These curves use world-space points with a zero object origin.
            x = o.data.splines[0].points[0].co.x
            o.location.x += -0.15 if x > 0 else 0.15
        if o.name.startswith("Ivory atrium edge moulding"):
            for spline in o.data.splines:
                cy = 11.7 if sum(p.co.y for p in spline.points) > 0 else -11.7
                for p in spline.points:
                    p.co.x *= 0.97
                    p.co.y = cy + (p.co.y - cy) * 0.985
        if o.name.startswith("Blown glass globe"):
            mod = o.modifiers.new("Thin blown glass wall", "SOLIDIFY")
            mod.thickness = 0.014
            mod.offset = -1
    scene["detail_intersections_corrected"] = True

if not scene.get("escalator_landings_corrected"):
    # Extend the provisional escalator so both ends meet the side galleries.
    transform = Matrix(
        ((9.8 / 7.5, 0, 0, 0.0653333333), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
    )
    for o in list(bpy.data.objects):
        if o.name.startswith("Escalator"):
            o.matrix_world = transform @ o.matrix_world
    # Continuous stainless housing encloses the step mechanism.
    a = Vector((-4.9, -10.2, -0.1))
    b = Vector((4.9, -15.5, 4.18))
    axis = (b - a).normalized()
    across = Vector((-axis.y, axis.x, 0)).normalized() * 0.78
    verts = [
        tuple(p + side * across + Vector((0, 0, dz)))
        for p in [a, b]
        for side, dz in [(-1, 0), (1, 0), (1, -0.35), (-1, -0.35)]
    ]
    data = bpy.data.meshes.new("Escalator enclosed truss")
    data.from_pydata(
        verts,
        [],
        [
            (0, 1, 2, 3),
            (4, 7, 6, 5),
            (0, 4, 5, 1),
            (3, 2, 6, 7),
            (0, 3, 7, 4),
            (1, 5, 6, 2),
        ],
    )
    data.materials.append(bpy.data.materials["Brushed stainless steel"])
    obj = bpy.data.objects.new("Escalator enclosed truss", data)
    bpy.data.collections["01 Architecture"].objects.link(obj)
    scene["escalator_landings_corrected"] = True

# Discard downloaded maps that have no connection to any rendered material input.
for m in bpy.data.materials:
    if not m.use_nodes:
        continue
    for n in list(m.node_tree.nodes):
        if (
            n.type == "TEX_IMAGE"
            and n.image
            and any(
                s in n.image.name for s in ["_AO.", "_arm.", "_nor_dx.", "_nor_gl."]
            )
        ):
            m.node_tree.nodes.remove(n)
for img in list(bpy.data.images):
    if img.source == "FILE" and img.users == 0:
        bpy.data.images.remove(img)
for img in bpy.data.images:
    if img.source == "FILE":
        img.pack()
        img.filepath = "//textures/" + img.name
for p in (ROOT / "textures").glob("*.jpg"):
    if any(s in p.name for s in ["_AO.", "_arm.", "_nor_dx.", "_nor_gl."]):
        p.unlink()
scene.render.resolution_x = 1920
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.cycles.samples = 128
scene.render.filepath = "//renders/01-clock-atrium.png"
bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(
    filepath=str(ROOT / "qvb-camera-scene.blend"), compress=True
)
print(
    "PACKAGED",
    len(scene.objects),
    sum(bool(i.packed_file) for i in bpy.data.images),
    "packed images",
)

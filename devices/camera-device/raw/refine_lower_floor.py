"""Ground-floor reconstruction from January 2016 Street View; run via Blender MCP.

Apply after refine_shops.py. LOWER_STAGE: prepare, floor, shops, furniture, finish.
Dimensions are estimated; see references/lower-floor/notes.md.
"""

import ast
import hashlib
import json
import math
import random
from math import cos, pi, sin
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
STAGE = globals().get("LOWER_STAGE", "all")
scene = bpy.context.scene
G = -5.0
B1 = -9.2
COLL = "10 Ground floor and visible basement"
ARCHIVE = "11 Archived lower-floor placeholders"
random.seed(2016)
tree = ast.parse((ROOT / "build_scene.py").read_text())
ns = dict(bpy=bpy, Vector=Vector, math=math, pi=pi, sin=sin, cos=cos)
exec(
    compile(
        ast.Module(
            body=[n for n in tree.body if isinstance(n, ast.FunctionDef)],
            type_ignores=[],
        ),
        "geometry_helpers",
        "exec",
    ),
    ns,
)
material, box, curve, mesh, sphere, cylinder, area, text_obj, beam, rounded_path = [
    ns[n]
    for n in (
        "material",
        "box",
        "curve",
        "mesh",
        "sphere",
        "cylinder",
        "area",
        "text_obj",
        "beam",
        "rounded_path",
    )
]
cream = bpy.data.materials["Ivory painted plaster"]
blue = bpy.data.materials["Heritage blue grey"]
iron = bpy.data.materials["Patinated dark green iron"]
wood = bpy.data.materials["Polished walnut"]
black = bpy.data.materials["Shopfront bronze black"]
glass = bpy.data.materials["Clear glass"]
gold = bpy.data.materials["Aged brass"]
white = bpy.data.materials["Warm porcelain"]
silver = bpy.data.materials["Brushed stainless steel"]
ns.update(wood=wood, iron=iron, gold=gold)
palette = [
    material("G mosaic " + str(i), c, 0.53)
    for i, c in enumerate(
        [
            (0.58, 0.46, 0.31),
            (0.72, 0.64, 0.49),
            (0.33, 0.105, 0.047),
            (0.12, 0.13, 0.14),
            (0.25, 0.38, 0.39),
            (0.82, 0.78, 0.66),
        ]
    )
]
for mat in palette:
    n = mat.node_tree.nodes
    if not n.get("Tile seams"):
        tex = n.new("ShaderNodeTexCoord")
        scale = n.new("ShaderNodeVectorMath")
        scale.operation = "SCALE"
        scale.inputs[3].default_value = 9
        vor = n.new("ShaderNodeTexVoronoi")
        vor.name = "Tile seams"
        vor.feature = "DISTANCE_TO_EDGE"
        vor.inputs["Randomness"].default_value = 0
        ramp = n.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.009
        ramp.color_ramp.elements[1].position = 0.023
        bump = n.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.25
        bump.inputs["Distance"].default_value = 0.007
        links = mat.node_tree.links
        links.new(tex.outputs["Object"], scale.inputs[0])
        links.new(scale.outputs[0], vor.inputs["Vector"])
        links.new(vor.outputs["Distance"], ramp.inputs[0])
        links.new(ramp.outputs[0], bump.inputs["Height"])
        links.new(bump.outputs[0], n.get("Principled BSDF").inputs["Normal"])
oak = material("G pale oak", (0.32, 0.17, 0.071), 0.34)
garments = [
    material("G garment " + str(i), c, 0.86)
    for i, c in enumerate(
        [
            (0.035, 0.07, 0.11),
            (0.78, 0.75, 0.65),
            (0.5, 0.08, 0.03),
            (0.13, 0.24, 0.21),
            (0.045, 0.038, 0.031),
            (0.56, 0.43, 0.21),
        ]
    )
]
pastels = [
    material("G opalescent pane " + str(i), c, 0.22, 0, 0.22, 0.13)
    for i, c in enumerate(
        [
            (0.49, 0.61, 0.33),
            (0.76, 0.55, 0.17),
            (0.59, 0.63, 0.51),
            (0.33, 0.52, 0.54),
            (0.62, 0.4, 0.28),
            (0.69, 0.64, 0.47),
        ]
    )
]
glow = material("G warm luminous glass", (1, 0.83, 0.62), 0.25, 0, 0, 2)
HOLES = [(0, -12, 6.6, 16, 1.4), (0, 18, 6.6, 8, 1.4)]


def keep_signature():
    records = []
    for o in scene.objects:
        if o.get("lower_pass") or o.get("archived_lower_pass"):
            continue
        records.append((o.name, tuple(tuple(v) for v in o.matrix_world), o.hide_render))
    return hashlib.sha256(repr(sorted(records)).encode()).hexdigest()


def activate():
    bpy.context.view_layer.active_layer_collection = (
        bpy.context.view_layer.layer_collection.children[COLL]
    )


def polygon(name, pts, mat, z=G + 0.014):
    base = G if z > G - 0.1 else B1
    z = base + (z - base) * 0.02
    return mesh(name, [(x, y, z) for x, y in pts], [tuple(range(len(pts)))], mat)


def ribbon(name, pts, width, mat, z=G + 0.016, closed=False):
    base = G if z > G - 0.1 else B1
    z = base + (z - base) * 0.02
    verts = []
    faces = []
    for a, b in zip(pts, pts[1:] + (pts[:1] if closed else [])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-8:
            continue
        nx, ny = -dy / length * width / 2, dx / length * width / 2
        k = len(verts)
        verts += [
            (a[0] + nx, a[1] + ny, z),
            (a[0] - nx, a[1] - ny, z),
            (b[0] - nx, b[1] - ny, z),
            (b[0] + nx, b[1] + ny, z),
        ]
        faces.append((k, k + 1, k + 2, k + 3))
    return mesh(name, verts, faces, mat)


def medallion(x, y, z, r=0.98):
    for ri, ro, mi in [
        (0, 0.56, 1),
        (0.56, 0.65, 2),
        (0.65, 0.74, 5),
        (0.74, 0.84, 4),
        (0.84, 0.94, 5),
        (0.94, 1, 3),
    ]:
        for k in range(80):
            a = k * 2 * pi / 80
            b = (k + 1) * 2 * pi / 80
            m = palette[mi if mi != 5 or k % 2 else 4]
            polygon(
                "Mosaic circular border",
                [
                    (x + ri * r * cos(a), y + ri * r * sin(a)),
                    (x + ro * r * cos(a), y + ro * r * sin(a)),
                    (x + ro * r * cos(b), y + ro * r * sin(b)),
                    (x + ri * r * cos(b), y + ri * r * sin(b)),
                ],
                m,
                z,
            )
    if z > G - 0.1:
        return  # Ground-floor circles have a plain field of small cream tiles.
    polygon(
        "B1 eight point mosaic star",
        [
            (
                x + r * (0.51 if k % 2 == 0 else 0.28) * cos(k * pi / 8),
                y + r * (0.51 if k % 2 == 0 else 0.28) * sin(k * pi / 8),
            )
            for k in range(16)
        ],
        palette[2],
        z + 0.001,
    )
    polygon(
        "B1 central cream diamond",
        [
            (x + 0.19 * r * cos(k * pi / 2), y + 0.19 * r * sin(k * pi / 2))
            for k in range(4)
        ],
        palette[5],
        z + 0.002,
    )


def cut_holes(ob):
    for h in HOLES:
        pts = rounded_path(*h, steps=16)
        n = len(pts)
        cutter = mesh(
            "Ground opening cutter",
            [(x, y, z) for z in [G - 1, G + 1] for x, y in pts],
            [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
            + [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)],
            None,
        )
        mod = ob.modifiers.new("Basement light well", "BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.object = cutter
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(cutter, do_unlink=True)


if STAGE in ("prepare", "all"):
    old = bpy.data.collections.get(COLL)
    if old:
        bpy.data.batch_remove(ids=list(old.all_objects))
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new(COLL)
    scene.collection.children.link(coll)
    archive = bpy.data.collections.get(ARCHIVE) or bpy.data.collections.new(ARCHIVE)
    if archive.name not in scene.collection.children:
        scene.collection.children.link(archive)
    bpy.context.view_layer.update()
    for o in list(scene.objects):
        if (
            o.get("shop_pass")
            or o.get("archived_shop_pass")
            or o.get("archived_lower_pass")
        ):
            continue
        if o.type not in {"MESH", "CURVE", "FONT", "LIGHT"}:
            continue
        hi = (
            o.location.z
            if o.type == "LIGHT"
            else max((o.matrix_world @ Vector(v)).z for v in o.bound_box)
        )
        if (
            hi < -0.43
            or o.name.startswith("Lower end closure")
            or (o.name.startswith("Continuous crown moulding") and o.location.z < 0)
        ):
            for c in list(o.users_collection):
                c.objects.unlink(o)
            archive.objects.link(o)
            o["archived_lower_pass"] = 1
    archive.hide_render = True
    archive.hide_viewport = True
    scene["lower_unaffected_signature"] = keep_signature()
    print("LOWER_PREPARED", len(archive.objects))

activate()
before = set(scene.objects)
if STAGE in ("floor", "all"):
    slab = box(
        "G gallery with basement light wells",
        (0, 0, G - 0.2),
        (22, 46, 0.4),
        palette[1],
    )
    cut_holes(slab)
    for h in HOLES:
        path = rounded_path(*h, steps=24)
        ns["railing"](path, G, "Ground atrium")
        for dz, r in [(-0.03, 0.055), (-0.19, 0.045), (-0.35, 0.045)]:
            curve(
                "G cream fascia moulding",
                [(x, y, G + dz) for x, y in path],
                r,
                cream,
                True,
            )
        ribbon("G blue glazed edge", path, 0.24, palette[4], G + 0.012, True)
    # Narrow coloured borders, diamond bands and circular junction medallions.
    for side in [-1, 1]:
        for x, width, mi in [
            (3.7, 0.16, 3),
            (3.92, 0.22, 2),
            (4.13, 0.12, 4),
            (7.25, 0.12, 3),
            (7.46, 0.18, 1),
            (7.63, 0.09, 4),
            (8.05, 0.48, 2),
        ]:
            ribbon(
                "G longitudinal mosaic border",
                [(side * x, -22.5), (side * x, 22.5)],
                width,
                palette[mi],
            )
        for j in range(224):
            y = -22.4 + j * 0.2
            polygon(
                "G alternating diamond border",
                [
                    (side * 7.36, y),
                    (side * 7.46, y + 0.1),
                    (side * 7.36, y + 0.2),
                    (side * 7.26, y + 0.1),
                ],
                palette[3 if j % 2 else 5],
                G + 0.018,
            )
        for y in [-20, -12, -4, 4, 12, 20]:
            medallion(side * 5.65, y, G + 0.022, 1.12)
        for y in [-16, -8, 0, 8, 16]:
            for offset, w, mi in [(0, 0.18, 3), (0.23, 0.12, 2), (0.43, 0.10, 5)]:
                ribbon(
                    "G elongated diamond panel",
                    [
                        (side * 5.65, y - 2.75 + offset),
                        (side * (7.05 - offset), y),
                        (side * 5.65, y + 2.75 - offset),
                        (side * (4.25 + offset), y),
                    ],
                    w,
                    palette[mi],
                    G + 0.018,
                    True,
                )
    for y in [-22, 0, 12.8]:
        for d, w, mi in [(0, 0.14, 3), (0.24, 0.18, 2), (0.43, 0.12, 4)]:
            ribbon(
                "G transverse tile border",
                [(-8, y + d), (8, y + d)],
                w,
                palette[mi],
                G + 0.021,
            )
    # B1 is a tiled concourse with rectangular shopfronts, visible through wells.
    box("B1 tiled concourse", (0, 0, B1 - 0.15), (22, 52, 0.3), palette[0])
    for y in range(-20, 23, 6):
        medallion(0, y, B1 + 0.01, 1.2)
    for side in [-1, 1]:
        for x in [3.8, 4.1, 7.8]:
            ribbon(
                "B1 mosaic border",
                [(side * x, -25), (side * x, 25)],
                0.18,
                palette[2],
                B1 + 0.012,
            )
        box("B1 retail rear wall", (side * 10.4, 0, B1 + 2), (0.2, 51, 4), cream)
        for y in [-20, -15, -10, -5, 0, 5, 10, 15, 20]:
            box(
                "B1 oxide pier",
                (side * 8.55, y, B1 + 1.9),
                (0.6, 0.45, 3.8),
                garments[2],
                0.02,
            )
            box(
                "B1 flat shop lintel",
                (side * 8.55, y + 2.4, B1 + 3.3),
                (0.2, 4.35, 0.42),
                cream,
            )
            for dy in [0.3, 4.5]:
                box(
                    "B1 bronze window jamb",
                    (side * 8.5, y + dy, B1 + 1.4),
                    (0.08, 0.06, 2.8),
                    black,
                )
            box(
                "B1 display glazing",
                (side * 8.5, y + 1.2, B1 + 1.4),
                (0.016, 1.6, 2.8),
                glass,
            )
            for z in [0.55, 1.25, 1.95]:
                box(
                    "B1 merchandise shelf",
                    (side * 9.5, y + 2.5, B1 + z),
                    (0.6, 3.7, 0.06),
                    oak,
                )
                for j in range(8):
                    box(
                        "B1 distant product",
                        (side * 9.2, y + 0.85 + j * 0.46, B1 + z + 0.15),
                        (0.18, 0.24, 0.28),
                        garments[j % 6],
                        0.015,
                    )
            area(
                "B1 retail illumination",
                (side * 9.2, y + 2.5, B1 + 3),
                90,
                (1, 0.87, 0.7),
                2,
                (side * 8, y + 2.5, B1 + 1),
            )
    for y in [-23, 23]:
        box("G end continuation floor", (0, y, G - 0.18), (19, 3, 0.36), palette[1])
    # Ground-floor end arches lead into another lit section of arcade.
    for end in [-1, 1]:
        y = end * 23
        wall = box("G oxide end arcade", (0, y, G + 2.3), (21, 0.42, 4.6), garments[2])
        for x in [-5.5, 0, 5.5]:
            path = [(x - 2.15, G - 0.2), (x + 2.15, G - 0.2)] + [
                (x + 2.15 * cos(k * pi / 48), G + 2.2 + 2.15 * sin(k * pi / 48))
                for k in range(49)
            ]
            n = len(path)
            cutter = mesh(
                "G end portal cutter",
                [(xx, yy, zz) for yy in [y - 0.7, y + 0.7] for xx, zz in path],
                [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
                + [(k, (k + 1) % n, (k + 1) % n + n, k + n) for k in range(n)],
                None,
            )
            bm = bmesh.new()
            bm.from_mesh(cutter.data)
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(cutter.data)
            bm.free()
            mod = wall.modifiers.new("Arched passage", "BOOLEAN")
            mod.operation = "DIFFERENCE"
            mod.object = cutter
            bpy.context.view_layer.objects.active = wall
            bpy.ops.object.modifier_apply(modifier=mod.name)
            bpy.data.objects.remove(cutter, do_unlink=True)
            for r, th in [(2.18, 0.11), (2.36, 0.055)]:
                curve(
                    "G end arch sandstone",
                    [
                        (
                            x + r * cos(k * pi / 48),
                            y - end * 0.25,
                            G + 2.2 + r * sin(k * pi / 48),
                        )
                        for k in range(49)
                    ],
                    th,
                    cream,
                )
            for sign in [-1, 1]:
                box(
                    "G end portal jamb",
                    (x + sign * 2.25, y - end * 0.22, G + 1.08),
                    (0.25, 0.34, 2.16),
                    cream,
                    0.025,
                )
        box(
            "G continuing corridor floor",
            (0, end * 26, G - 0.16),
            (21, 7, 0.32),
            palette[0],
        )
        box("G continuing corridor ceiling", (0, end * 26, -0.35), (21, 7, 0.18), cream)
        box("G distant corridor wall", (0, end * 29, G + 2), (21, 0.25, 4.5), cream)
        for x in [-7, -3.5, 0, 3.5, 7]:
            box(
                "G distant retail window",
                (x, end * 28.8, G + 1.55),
                (2.6, 0.04, 2.9),
                black,
            )
            for z in [0.7, 1.5, 2.3]:
                box(
                    "G distant retail shelf",
                    (x, end * 28.65, G + z),
                    (2.4, 0.18, 0.08),
                    oak,
                )
                for j in range(6):
                    box(
                        "G distant displayed merchandise",
                        (x - 1 + j * 0.4, end * 28.5, G + z + 0.16),
                        (0.2, 0.18, 0.25),
                        garments[j],
                        0.02,
                    )
        area(
            "G end corridor light",
            (0, end * 25, -1.1),
            350,
            (1, 0.87, 0.72),
            5,
            (0, end * 25, G),
        )
        box("B1 distant end wall", (0, end * 26, B1 + 1.9), (21, 0.3, 3.8), cream)
    print("LOWER_FLOOR_BUILT")

TENANTS = [
    (-1, -17.5, "COUNTRY ROAD", "fashion"),
    (-1, -12.5, "JIGSAW", "fashion"),
    (-1, -7.5, "DAVID LAWRENCE", "fashion"),
    (-1, -2.5, "COACH", "bags"),
    (-1, 2.5, "LONGCHAMP", "bags"),
    (-1, 7.5, "CUE", "fashion"),
    (-1, 12.5, "CUE", "fashion"),
    (-1, 17.5, "", "fashion"),
    (1, -17.5, "KAREN MILLEN", "fashion"),
    (1, -12.5, "KAREN MILLEN", "fashion"),
    (1, -7.5, "SPORTSCRAFT", "fashion"),
    (1, -2.5, "SPORTSCRAFT", "fashion"),
    (1, 2.5, "MONDIAL", "jewellery"),
    (1, 7.5, "OROTON", "bags"),
    (1, 12.5, "OROTON", "bags"),
    (1, 17.5, "", "fashion"),
]


def shop_text(body, loc, size, side):
    return text_obj(
        "G tenant lettering", body, loc, size, black, (pi / 2, 0, -side * pi / 2)
    )


if STAGE in ("shops", "all"):
    for side in [-1, 1]:
        for y in range(-20, 21, 5):
            x = side * 8.6
            cylinder("G round sandstone column", (x, y, G + 1.28), 0.29, 2.56, cream)
            for z, r, d in [
                (0.10, 0.4, 0.20),
                (0.22, 0.35, 0.06),
                (2.4, 0.35, 0.12),
                (2.59, 0.44, 0.27),
            ]:
                cylinder("G carved column collar", (x, y, G + z), r, d, cream)
            for k in range(12):
                a = k * pi / 6
                curve(
                    "G capital leaf scroll",
                    [
                        (
                            x + 0.405 * cos(a + t * 0.11),
                            y + 0.405 * sin(a + t * 0.11),
                            G + 2.55 + 0.095 * sin(t),
                        )
                        for t in [j * 2 * pi / 24 for j in range(25)]
                    ],
                    0.018,
                    cream,
                )
        box("G upper blue frieze", (side * 8.9, 0, -0.66), (0.3, 46, 0.45), blue)
        for z in [-0.48, -0.57]:
            box("G crown moulding", (side * 8.6, 0, z), (0.35, 46, 0.075), cream, 0.014)
    for side, y, name, kind in TENANTS:
        x = side * 8.55
        spring = G + 2.5
        r = 2.15
        for rad, thickness in [(r + 0.12, 0.095), (r + 0.24, 0.045), (r + 0.32, 0.04)]:
            curve(
                "G full width sandstone arch",
                [
                    (
                        x - side * 0.05,
                        y + rad * cos(i * pi / 64),
                        spring + rad * sin(i * pi / 64),
                    )
                    for i in range(65)
                ],
                thickness,
                cream,
            )
        # Blue spandrels sit outside the arch; no solid panel across the glass.
        for sign in [-1, 1]:
            for j in range(24):
                u = 2.48 * j / 24
                v = 2.48 * (j + 1) / 24
                lowa = spring + math.sqrt(max(0, (r + 0.34) ** 2 - u * u))
                lowb = spring + math.sqrt(max(0, (r + 0.34) ** 2 - v * v))
                if lowa < -0.44 and lowb < -0.44:
                    mesh(
                        "G blue arch spandrel",
                        [
                            (side * 8.7, y + sign * u, lowa),
                            (side * 8.7, y + sign * v, lowb),
                            (side * 8.7, y + sign * v, -0.44),
                            (side * 8.7, y + sign * u, -0.44),
                        ],
                        [(0, 1, 2, 3)],
                        blue,
                    )
        curve(
            "G black fanlight outline",
            [
                (x, y + r * cos(i * pi / 64), spring + r * sin(i * pi / 64))
                for i in range(65)
            ],
            0.045,
            black,
        )
        step = 0.43
        for a in range(-5, 5):
            for b in range(5):
                u = a * step
                v = (a + 1) * step
                top = min((b + 1) * step, math.sqrt(max(0, r * r - max(u * u, v * v))))
                if top > b * step + 0.025:
                    box(
                        "G large coloured glass square",
                        (x, y + (u + v) / 2, spring + (b * step + top) / 2),
                        (0.023, step - 0.025, top - b * step - 0.025),
                        random.choice(pastels),
                    )
        for a in range(-4, 5):
            u = a * step
            beam(
                "G lead upright",
                (x, y + u, spring),
                (x, y + u, spring + math.sqrt(r * r - u * u)),
                0.013,
                black,
            )
        for b in range(5):
            z = b * step
            extent = math.sqrt(r * r - z * z)
            beam(
                "G lead horizontal",
                (x, y - extent, spring + z),
                (x, y + extent, spring + z),
                0.013,
                black,
            )
        box("G transom sill", (x, y, spring), (0.15, 4.4, 0.12), black, 0.012)
        for dy in [-2.15, -0.68, 0.68, 2.15]:
            box(
                "G shop bronze mullion",
                (x, y + dy, G + 1.22),
                (0.10, 0.06, 2.44),
                black,
                0.01,
            )
        for dy in [-1.42, 1.42]:
            box(
                "G shop clear glazing", (x, y + dy, G + 1.22), (0.014, 1.36, 2.4), glass
            )
        box(
            "G retail floor",
            (side * 9.8, y, G + 0.012),
            (2.4, 4.6, 0.03),
            oak if kind == "fashion" else white,
        )
        box(
            "G retail rear lining", (side * 10.75, y, G + 2.25), (0.12, 4.6, 4.5), white
        )
        box("G retail ceiling", (side * 9.8, y, -0.39), (2.4, 4.7, 0.09), cream)
        if name:
            # Blade signs face both directions along the arcade.
            box(
                "G hanging cream sign",
                (side * 7.7, y - 1.9, G + 3.56),
                (1.35, 0.075, 0.43),
                glow,
                0.018,
            )
            for direction in [-1, 1]:
                text_obj(
                    "G blade tenant name",
                    name,
                    (side * 7.7, y - 1.9 + direction * 0.041, G + 3.56),
                    0.105,
                    black,
                    (pi / 2, 0, 0 if direction == -1 else pi),
                )
            for xx in [-0.48, 0.48]:
                beam(
                    "G sign hanger",
                    (side * 7.7 + xx, y - 1.9, G + 3.79),
                    (side * 7.7 + xx, y - 1.9, -0.45),
                    0.014,
                    black,
                )
            shop_text(
                name,
                (side * 8.47, y, G + 2.28),
                0.16 if len(name) < 12 else 0.115,
                side,
            )
        if kind == "fashion":
            for dy in [-1.35, 1.35]:
                yy = y + dy
                cylinder(
                    "G mannequin plinth", (side * 9.0, yy, G + 0.06), 0.27, 0.10, white
                )
                sphere(
                    "G mannequin head",
                    (side * 9.0, yy, G + 1.67),
                    (0.09, 0.085, 0.12),
                    white,
                )
                cylinder(
                    "G mannequin neck", (side * 9.0, yy, G + 1.53), 0.047, 0.12, white
                )
                sphere(
                    "G dressed torso",
                    (side * 9.0, yy, G + 1.29),
                    (0.12, 0.20, 0.25),
                    random.choice(garments),
                )
                for sign in [-1, 1]:
                    beam(
                        "G mannequin leg",
                        (side * 9.0, yy + sign * 0.085, G + 0.12),
                        (side * 9.0, yy + sign * 0.085, G + 1.05),
                        0.05,
                        white,
                    )
                    beam(
                        "G mannequin arm",
                        (side * 9.0, yy + sign * 0.2, G + 1.45),
                        (side * 9.0, yy + sign * 0.28, G + 0.92),
                        0.038,
                        white,
                    )
            for level in [G + 0.55, G + 1.12]:
                box(
                    "G folded clothing shelf",
                    (side * 10.2, y, level),
                    (0.7, 3.8, 0.06),
                    oak,
                )
                for j in range(7):
                    for k in range(3):
                        box(
                            "G folded knitwear",
                            (side * 10.15, y - 1.5 + j * 0.5, level + 0.06 + k * 0.06),
                            (0.4, 0.36, 0.055),
                            garments[(j + k) % 6],
                            0.018,
                        )
            beam(
                "G clothing rail",
                (side * 9.75, y - 1.9, G + 1.8),
                (side * 9.75, y + 1.9, G + 1.8),
                0.018,
                silver,
            )
            for j in range(18):
                yy = y - 1.8 + j * 0.21
                beam(
                    "G hanger",
                    (side * 9.75, yy, G + 1.79),
                    (side * 9.75, yy, G + 1.64),
                    0.007,
                    silver,
                )
                box(
                    "G hanging garment",
                    (side * 9.75, yy, G + 1.25),
                    (0.38, 0.075, 0.75),
                    garments[j % 6],
                    0.025,
                )
        elif kind == "bags":
            for height in [0.45, 1.05, 1.65]:
                box(
                    "G bag display shelf",
                    (side * 9.6, y, G + height),
                    (0.6, 3.9, 0.055),
                    oak if name == "COACH" else white,
                    0.012,
                )
                for j in range(7):
                    yy = y - 1.6 + j * 0.54
                    mat = garments[(j + int(height * 10)) % 6]
                    box(
                        "G displayed leather bag",
                        (side * 9.3, yy, G + height + 0.17),
                        (0.20, 0.32, 0.30),
                        mat,
                        0.04,
                    )
                    curve(
                        "G bag handle",
                        [
                            (
                                side * 9.3,
                                yy + 0.105 * cos(t),
                                G + height + 0.32 + 0.10 * sin(t),
                            )
                            for t in [k * pi / 16 for k in range(17)]
                        ],
                        0.012,
                        mat,
                    )
                    box(
                        "G bag clasp",
                        (side * 9.185, yy, G + height + 0.20),
                        (0.02, 0.045, 0.04),
                        gold,
                        0.006,
                    )
        else:
            for yy in [y - 1.4, y + 1.4]:
                box(
                    "G Mondial black cabinet",
                    (side * 9.0, yy, G + 0.45),
                    (0.7, 1.1, 0.9),
                    black,
                    0.025,
                )
                box(
                    "G Mondial white display pad",
                    (side * 9.0, yy, G + 0.93),
                    (0.68, 1.07, 0.06),
                    white,
                )
                box(
                    "G Mondial glass cover",
                    (side * 9.0, yy, G + 1.10),
                    (0.7, 1.1, 0.30),
                    glass,
                )
                for j in range(4):
                    sphere(
                        "G necklace bust",
                        (side * 9.0, yy - 0.37 + j * 0.25, G + 1.05),
                        (0.07, 0.085, 0.13),
                        white,
                    )
                    curve(
                        "G gold necklace",
                        [
                            (
                                side * 8.92,
                                yy - 0.37 + j * 0.25 + 0.055 * cos(t),
                                G + 1.10 + 0.07 * sin(t),
                            )
                            for t in [k * 2 * pi / 24 for k in range(25)]
                        ],
                        0.006,
                        gold,
                        True,
                    )
        area(
            "G warm shop illumination",
            (side * 9.7, y, G + 3.15),
            180,
            (1, 0.85, 0.67),
            2.5,
            (side * 8.2, y, G + 0.7),
        )
    print("LOWER_SHOPS_BUILT", len(TENANTS))

if STAGE in ("furniture", "all"):
    # Metropole occupies the solid ground-floor crossing, between the wells.
    for x in [-2.7, -0.85, 1, 2.85]:
        for y in [-2.4, -0.5, 1.4, 3.3, 5.2]:
            box("G cafe oak table", (x, y, G + 0.75), (0.76, 0.76, 0.055), oak, 0.025)
            cylinder("G table pedestal", (x, y, G + 0.39), 0.045, 0.71, black)
            cylinder("G table base", (x, y, G + 0.035), 0.25, 0.06, black)
            for sign in [-1, 1]:
                yy = y + sign * 0.63
                cylinder("G bentwood chair seat", (x, yy, G + 0.45), 0.21, 0.035, wood)
                for dx in [-0.14, 0.14]:
                    for dy in [-0.14, 0.14]:
                        beam(
                            "G chair leg",
                            (x + dx * 1.2, yy + dy * 1.2, G + 0.015),
                            (x + dx, yy + dy, G + 0.43),
                            0.019,
                            black,
                        )
                curve(
                    "G bentwood chair back",
                    [
                        (x + 0.22 * cos(t), yy + sign * 0.17, G + 0.64 + 0.25 * sin(t))
                        for t in [k * pi / 32 for k in range(33)]
                    ],
                    0.023,
                    wood,
                )
            cylinder("G cafe cup", (x + 0.18, y + 0.12, G + 0.81), 0.04, 0.07, white)
            box(
                "G table menu",
                (x - 0.18, y, G + 0.91),
                (0.13, 0.035, 0.24),
                cream,
                0.005,
            )
    box("G Metropole timber kiosk", (0, 8.45, G + 0.51), (5.8, 2.7, 1.02), oak, 0.035)
    box("G Metropole dark worktop", (0, 8.45, G + 1.04), (6, 2.85, 0.07), black, 0.025)
    for x in [
        -2.7,
        -2.5,
        -2.3,
        -2.1,
        -1.9,
        -1.7,
        -1.5,
        -1.3,
        -1.1,
        -0.9,
        -0.7,
        -0.5,
        -0.3,
        -0.1,
        0.1,
        0.3,
        0.5,
        0.7,
        0.9,
        1.1,
        1.3,
        1.5,
        1.7,
        1.9,
        2.1,
        2.3,
        2.5,
        2.7,
    ]:
        box("G kiosk oak slat", (x, 7.07, G + 0.51), (0.075, 0.035, 0.93), wood, 0.006)
    box("G pastry glass cabinet", (1.5, 8.5, G + 1.36), (2.1, 1.05, 0.58), glass, 0.01)
    for j in range(9):
        sphere(
            "G pastry",
            (0.65 + j * 0.20, 8.1, G + 1.14),
            (0.08, 0.055, 0.055),
            palette[0],
        )
    box("G espresso machine", (-1.35, 8.5, G + 1.34), (1.25, 0.65, 0.53), silver, 0.055)
    for x in [-1.7, -1.35, -1.0]:
        cylinder("G espresso cup stack", (x, 8.5, G + 1.66), 0.055, 0.17, white)
        beam(
            "G espresso group handle",
            (x, 8.1, G + 1.24),
            (x, 7.88, G + 1.24),
            0.019,
            black,
        )
    box(
        "G Metropole freestanding sign",
        (0, 9.7, G + 1.65),
        (0.8, 0.06, 1.1),
        black,
        0.015,
    )
    text_obj("G Metropole sign M", "M", (0, 9.662, G + 1.85), 0.54, gold)
    text_obj("G Metropole sign name", "METROPOLE", (0, 9.66, G + 1.39), 0.105, gold)
    # Escalator G -> L1, below the existing L1 -> L2 flight.
    for lane in [-0.68, 0.68]:
        a = Vector((4.5 + lane, -18, G))
        b = Vector((-5.45 + lane, -7.3, -0.02))
        direction = b - a
        across = Vector((-direction.y, direction.x, 0)).normalized()
        for i in range(52):
            p = a + direction * (i + 0.5) / 52
            ob = box(
                "G escalator tread", p, (1.02, direction.xy.length / 52, 0.085), silver
            )
            ob.rotation_euler.z = math.atan2(-direction.x, direction.y)
        for sign in [-1, 1]:
            aa = a + across * sign * 0.60
            bb = b + across * sign * 0.60
            mesh(
                "G escalator glass side",
                [
                    tuple(aa + Vector((0, 0, 0.18))),
                    tuple(bb + Vector((0, 0, 0.18))),
                    tuple(bb + Vector((0, 0, 1))),
                    tuple(aa + Vector((0, 0, 1))),
                ],
                [(0, 1, 2, 3)],
                glass,
            )
            beam(
                "G escalator rubber handrail",
                aa + Vector((0, 0, 1.03)),
                bb + Vector((0, 0, 1.03)),
                0.043,
                black,
            )
            beam("G escalator stainless stringer", aa, bb, 0.095, silver)
        box("G escalator foot landing", a, (1.3, 1.3, 0.07), silver)
        box("G escalator upper landing", b, (1.3, 1.3, 0.07), silver)
    for side in [-1, 1]:
        for y in [-17.5, -12.5, -7.5, -2.5, 2.5, 7.5, 12.5, 17.5]:
            x = side * 7.6
            beam("G pendant rod", (x, y, -0.46), (x, y, -1.65), 0.022, black)
            sphere("G pendant blown globe", (x, y, -1.8), (0.21, 0.21, 0.25), glass)
            cylinder("G pendant luminous core", (x, y, -1.8), 0.065, 0.20, glow)
            cylinder("G pendant dark rim", (x, y, -1.65), 0.215, 0.035, black)
            area("G pendant pool", (x, y, -1.96), 80, (1, 0.87, 0.68), 0.6, (x, y, G))
    print("LOWER_FURNITURE_BUILT")

for o in set(scene.objects) - before:
    o["lower_pass"] = 1
if STAGE in ("finish", "all"):
    origin = bpy.data.objects.get("G mosaic coordinates")
    if origin is None:
        origin = bpy.data.objects.new("G mosaic coordinates", None)
        bpy.context.collection.objects.link(origin)
        origin["lower_pass"] = 1
    for mat in palette:
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        tex = next(n for n in nodes if n.type == "TEX_COORD")
        tex.object = origin
        vor = nodes["Tile seams"]
        vor.voronoi_dimensions = "2D"
        vor.inputs["Scale"].default_value = 1
        principled = nodes.get("Principled BSDF")
        mix = nodes.get("Tile grout colour") or nodes.new("ShaderNodeMixRGB")
        mix.name = "Tile grout colour"
        mix.inputs[1].default_value = mat.diffuse_color
        mix.inputs[2].default_value = (0.085, 0.072, 0.055, 1)
        threshold = nodes.get("Tile grout width") or nodes.new("ShaderNodeMath")
        threshold.name = "Tile grout width"
        threshold.operation = "LESS_THAN"
        threshold.inputs[1].default_value = 0.014
        links.new(vor.outputs["Distance"], threshold.inputs[0])
        links.new(threshold.outputs[0], mix.inputs[0])
        links.new(mix.outputs[0], principled.inputs["Base Color"])
        bump = next(n for n in nodes if n.type == "BUMP")
        bump.inputs["Distance"].default_value = 0.0015
        bump.inputs["Strength"].default_value = 0.16
    bpy.context.view_layer.update()
    assert keep_signature() == scene["lower_unaffected_signature"], (
        "An object outside the lower-floor pass changed"
    )
    lower = list(bpy.data.collections[COLL].all_objects)
    bpy.ops.object.select_all(action="DESELECT")
    texts = [o for o in lower if o.type == "FONT"]
    if texts:
        for o in texts:
            o.select_set(True)
        bpy.context.view_layer.objects.active = texts[0]
        bpy.ops.object.convert(target="MESH")
        bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.update()
    scene["ground_floor_z"] = G
    scene["basement_floor_z"] = B1
    scene["lower_floor_reference"] = (
        "Google Street View Jan 2016; photographed layout, estimated dimensions"
    )
    floor_checks = []
    deps = bpy.context.evaluated_depsgraph_get()
    for label, x, y, expected in [
        ("escalator well", 0, -14, B1),
        ("clockward well", 0, 18, B1),
        ("cafe crossing", 0, 0, G),
        ("side walkway", 5, -12, G),
    ]:
        hit, loc, normal, index, obj, matrix = scene.ray_cast(
            deps, Vector((x, y, G + 0.03)), Vector((0, 0, -1))
        )
        assert hit and abs(loc.z - expected) < 0.005, (label, hit, tuple(loc))
        floor_checks.append(
            dict(area=label, hit_object=obj.name, height=loc.z, expected=expected)
        )
    portal_checks = []
    for end in [-1, 1]:
        for x in [-5.5, 0, 5.5]:
            hit, loc, normal, index, obj, matrix = scene.ray_cast(
                deps, Vector((x, end * 22.6, G + 1)), Vector((0, end, 0))
            )
            assert hit and abs(loc.y) > 28, (
                end,
                x,
                obj.name if obj else None,
                tuple(loc),
            )
            portal_checks.append(
                dict(end=end, x=x, hit_object=obj.name, depth=abs(loc.y))
            )
    report = {
        "ground_z": G,
        "basement_z": B1,
        "openings": HOLES,
        "objects": len(lower),
        "tenants": [
            dict(side=s, y=y, name=n or None, display=k) for s, y, n, k in TENANTS
        ],
        "preserved_upper_scene_signature": keep_signature(),
        "floor_checks": floor_checks,
        "portal_checks": portal_checks,
        "limitations": [
            "Estimated bay widths, heights and opening extents; not a measured survey",
            "Two far-end ground-floor tenant names unresolved",
            "B1 continuation represents observed construction and merchandise, without inferred tenant labels",
        ],
    }
    (ROOT / "lower-floor-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "qvb-camera-scene.blend"))
    print("LOWER_SAVED", json.dumps(report))

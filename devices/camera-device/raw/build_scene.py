"""QVB visual reconstruction. Run in Blender's Python context, or through Blender MCP.

Build in stages by setting QVB_STAGE to foundation, architecture, details, or camera.
All dimensions are visual estimates in metres. No Street View pixels are used as textures.
"""

import json
import math
import random
from math import cos, pi, sin
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
random.seed(73)
STAGE = globals().get("QVB_STAGE", "all")


def material(name, color, rough=0.5, metal=0, transmission=0, emission=0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    p.inputs["Transmission Weight"].default_value = transmission
    p.inputs["Emission Color"].default_value = (*color, 1)
    p.inputs["Emission Strength"].default_value = emission
    m.diffuse_color = (*color, 1)
    return m


def noise_finish(m, scale=35, strength=0.08, distance=0.025):
    n = m.node_tree.nodes
    links_or_link = m.node_tree.links
    p = n.get("Principled BSDF")
    noise = n.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 3
    bump = n.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    links_or_link.new(noise.outputs["Fac"], bump.inputs["Height"])
    links_or_link.new(bump.outputs[0], p.inputs["Normal"])


def mesh(name, verts, faces, mat):
    d = bpy.data.meshes.new(name)
    d.from_pydata(verts, [], faces)
    d.update()
    o = bpy.data.objects.new(name, d)
    bpy.context.collection.objects.link(o)
    if mat:
        d.materials.append(mat)
    return o


def box(name, loc, size, mat, bevel=0):
    x, y, z = [v / 2 for v in size]
    o = mesh(
        name,
        [
            (a * x, b * y, c * z)
            for a, b, c in [
                (-1, -1, -1),
                (-1, -1, 1),
                (-1, 1, -1),
                (-1, 1, 1),
                (1, -1, -1),
                (1, -1, 1),
                (1, 1, -1),
                (1, 1, 1),
            ]
        ],
        [
            (0, 4, 6, 2),
            (1, 3, 7, 5),
            (0, 1, 5, 4),
            (2, 6, 7, 3),
            (0, 2, 3, 1),
            (4, 5, 7, 6),
        ],
        mat,
    )
    o.location = loc
    if bevel:
        b = o.modifiers.new("Rounded edges", "BEVEL")
        b.width = bevel
        b.segments = 3
        o.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    return o


def curve(name, points, radius, mat, cyclic=False):
    d = bpy.data.curves.new(name, "CURVE")
    d.dimensions = "3D"
    d.resolution_u = 1
    d.bevel_depth = radius
    d.bevel_resolution = 2
    s = d.splines.new("POLY")
    s.points.add(len(points) - 1)
    for p, co in zip(s.points, points):
        p.co = (*co, 1)
    s.use_cyclic_u = cyclic
    o = bpy.data.objects.new(name, d)
    bpy.context.collection.objects.link(o)
    d.materials.append(mat)
    return o


def cylinder(name, loc, radius, depth, mat, vertices=32):
    vs = []
    for z in [-depth / 2, depth / 2]:
        vs.extend(
            [
                (
                    radius * cos(i * 2 * pi / vertices),
                    radius * sin(i * 2 * pi / vertices),
                    z,
                )
                for i in range(vertices)
            ]
        )
    fs = [tuple(reversed(range(vertices))), tuple(range(vertices, 2 * vertices))]
    fs += [
        (i, (i + 1) % vertices, (i + 1) % vertices + vertices, i + vertices)
        for i in range(vertices)
    ]
    o = mesh(name, vs, fs, mat)
    o.location = loc
    for p in o.data.polygons:
        p.use_smooth = len(p.vertices) == 4
    return o


def sphere(name, loc, scale, mat):
    # Reuse unit sphere geometry per material.
    key = "_sphere_" + mat.name
    d = bpy.data.meshes.get(key)
    if d is None:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
        o = bpy.context.object
        d = o.data
        d.name = key
        d.materials.append(mat)
        for f in d.polygons:
            f.use_smooth = True
        o.name = name
    else:
        o = bpy.data.objects.new(name, d)
        bpy.context.collection.objects.link(o)
    o.location = loc
    o.scale = scale
    return o


def beam(name, a, b, r, mat):
    return curve(name, [a, b], r, mat)


def text_obj(name, body, loc, size, mat, rot=(pi / 2, 0, 0)):
    d = bpy.data.curves.new(name, "FONT")
    d.body = body
    d.align_x = "CENTER"
    d.align_y = "CENTER"
    d.size = size
    d.extrude = 0.0008
    o = bpy.data.objects.new(name, d)
    bpy.context.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = rot
    d.materials.append(mat)
    return o


def area(name, loc, power, color, size, target):
    d = bpy.data.lights.new(name, "AREA")
    d.energy = power
    d.color = color
    d.shape = "DISK"
    d.size = size
    o = bpy.data.objects.new(name, d)
    bpy.context.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector(target) - o.location).to_track_quat("-Z", "Y").to_euler()
    return o


def rounded_path(cx, cy, w, h, r, steps=16):
    pts = []
    for x, y, start in [
        (cx + w / 2 - r, cy + h / 2 - r, 0),
        (cx - w / 2 + r, cy + h / 2 - r, 90),
        (cx - w / 2 + r, cy - h / 2 + r, 180),
        (cx + w / 2 - r, cy - h / 2 + r, 270),
    ]:
        pts.extend(
            [
                (
                    x + r * cos(math.radians(start + i * 90 / steps)),
                    y + r * sin(math.radians(start + i * 90 / steps)),
                )
                for i in range(steps + 1)
            ]
        )
    return pts


cream = material("Ivory painted plaster", (0.69, 0.65, 0.51), 0.72)
blue = material("Heritage blue grey", (0.24, 0.36, 0.39), 0.68)
gold = material("Aged brass", (0.46, 0.29, 0.095), 0.3, 0.72)
iron = material("Patinated dark green iron", (0.028, 0.048, 0.043), 0.32, 0.65)
wood = material("Polished walnut", (0.11, 0.035, 0.014), 0.25)
black = material("Shopfront bronze black", (0.025, 0.029, 0.025), 0.26, 0.5)
white = material("Warm porcelain", (0.85, 0.82, 0.71), 0.21)
glass = material("Clear glass", (0.91, 0.97, 0.96), 0.065, 0, 1)
red = material("Oxide red wall", (0.34, 0.065, 0.033), 0.8)
lightmat = material("Warm lamp diffuser", (1, 0.82, 0.53), 0.22, 0, 0, 3)
carpet = material("Charcoal woven carpet", (0.042, 0.043, 0.038), 0.98)
carpetgold = material("Carpet ochre embroidery", (0.39, 0.29, 0.16), 1)
silver = material("Brushed stainless steel", (0.5, 0.56, 0.59), 0.21, 0.9)
marble = material("Cafe cream marble", (0.7, 0.66, 0.52), 0.27)

if STAGE in ("foundation", "all"):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for m in [cream, blue, iron, wood, carpet, carpetgold, marble]:
        noise_finish(m)
    s = bpy.context.scene
    s.name = "QVB camera-device"
    s.unit_settings.system = "METRIC"
    s.render.engine = "CYCLES"
    s.cycles.samples = 64
    s.cycles.use_denoising = True
    s.cycles.max_bounces = 8
    s.cycles.transmission_bounces = 6
    s.render.resolution_x = 1600
    s.render.resolution_y = 1000
    s.render.resolution_percentage = 100
    s.render.image_settings.file_format = "PNG"
    s.view_settings.view_transform = "AgX"
    s.world.use_nodes = True
    s.world.node_tree.nodes["Background"].inputs[0].default_value = (
        0.55,
        0.68,
        0.85,
        1,
    )
    s.world.node_tree.nodes["Background"].inputs[1].default_value = 0.35
    # Floors are true apertures. Rounded corners continue through fascia and railing.
    for level, z in [("Ground", -4.4), ("Level 1", 0), ("Level 2", 4.3)]:
        floor = box(level + " gallery slab", (0, 0, z - 0.22), (19, 46, 0.44), cream)
        if z > -1:
            for cy in [-11.7, 11.7]:
                pts = rounded_path(0, cy, 9.5, 16.4, 1.6)
                vs = [(x, y, zz) for zz in [z - 1, z + 1] for x, y in pts]
                n = len(pts)
                fs = [tuple(reversed(range(n))), tuple(range(n, 2 * n))] + [
                    (i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)
                ]
                cut = mesh("Atrium opening cutter", vs, fs, None)
                mod = floor.modifiers.new("Rounded atrium opening", "BOOLEAN")
                mod.operation = "DIFFERENCE"
                mod.object = cut
                bpy.context.view_layer.objects.active = floor
                bpy.ops.object.modifier_apply(modifier=mod.name)
                bpy.data.objects.remove(cut, do_unlink=True)
        if z == 0:
            # Fitted carpet over the gallery geometry.
            o = bpy.data.objects.new("Level 1 fitted carpet", floor.data.copy())
            bpy.context.collection.objects.link(o)
            o.location = floor.location + Vector((0, 0, 0.012))
            o.data.materials.clear()
            o.data.materials.append(carpet)
    # Back walls of deep shop bays and lower retail floor.
    for x in [-11, 11]:
        box("Retail back wall", (x, 0, 1.8), (0.25, 46, 13), cream)
    box("Lower tiled concourse", (0, 0, -4.43), (22, 46, 0.08), marble)
    # Entire opposite arcade remains modelled for pan sweeps.
    for z in [-4.4, 0, 4.3]:
        for side in [-1, 1]:
            for j, y in enumerate(range(-20, 21, 5)):
                x = side * 8.6
                box("Square pier", (x, y, z + 1.8), (0.46, 0.58, 3.6), cream, 0.025)
                for dz, sx, sy, sz in [
                    (0.16, 0.64, 0.74, 0.32),
                    (3.33, 0.68, 0.83, 0.22),
                    (3.48, 0.86, 0.98, 0.16),
                    (3.62, 1.03, 1.14, 0.14),
                ]:
                    box(
                        "Pier plinth or capital",
                        (x, y, z + dz),
                        (sx, sy, sz),
                        cream,
                        0.025,
                    )
                # Tapered corbel under the gallery.
                v = [
                    (x + a * 0.30, y + b * 0.34, z + 3.15)
                    for a, b in [(-1, -1), (1, -1), (1, 1), (-1, 1)]
                ] + [
                    (x + a * 0.52, y + b * 0.57, z + 3.55)
                    for a, b in [(-1, -1), (1, -1), (1, 1), (-1, 1)]
                ]
                mesh(
                    "Splayed plaster corbel",
                    v,
                    [
                        (0, 1, 2, 3),
                        (4, 7, 6, 5),
                        (0, 4, 5, 1),
                        (1, 5, 6, 2),
                        (2, 6, 7, 3),
                        (3, 7, 4, 0),
                    ],
                    cream,
                )
            box("Blue shop frieze", (side * 8.82, 0, z + 3.3), (0.32, 46, 1.02), blue)
            for zz, w in [(3.76, 0.13), (3.88, 0.08), (3.96, 0.12)]:
                box(
                    "Continuous crown moulding",
                    (side * 8.57, 0, z + zz),
                    (0.4, 46, w),
                    cream,
                    0.02,
                )
    print("Foundation complete", len(bpy.data.objects))


def arch_points(x, y, z, r, side):
    return [
        (x, y + r * cos(t), z + r * sin(t)) for t in [i * pi / 40 for i in range(41)]
    ]


def stained_arch(x, y, z, r, side):
    shades = [
        (0.56, 0.4, 0.1),
        (0.68, 0.52, 0.17),
        (0.29, 0.46, 0.3),
        (0.55, 0.67, 0.43),
        (0.25, 0.47, 0.5),
        (0.67, 0.32, 0.1),
    ]
    mats = [
        material("Stained glass " + str(i), c, 0.22, 0.05, 0.18, 0.23)
        for i, c in enumerate(shades)
    ]
    # Leaded squares are individually clipped to the semicircle.
    step = 0.18
    for a in range(-5, 5):
        for b in range(5):
            y0 = a * step
            y1 = (a + 1) * step
            z0 = b * step
            z1 = (b + 1) * step
            if max(abs(y0), abs(y1)) >= r:
                continue
            top = min(z1, math.sqrt(max(0, r * r - max(y0 * y0, y1 * y1))))
            if top <= z0:
                continue
            box(
                "Amber and sage leaded pane",
                (x, y + (y0 + y1) / 2, z + (z0 + top) / 2),
                (0.025, step - 0.014, top - z0 - 0.014),
                random.choice(mats),
            )
    for rr, mat, rad in [
        (r + 0.075, black, 0.065),
        (r + 0.005, gold, 0.024),
        (r - 0.07, red, 0.033),
    ]:
        curve(
            "Semicircular shop transom",
            arch_points(x - side * 0.025, y, z, rr, side),
            rad,
            mat,
        )
    beam("Transom sill", (x, y - r, z), (x, y + r, z), 0.047, black)
    # Curled central motif in stained glass.
    for sign in [-1, 1]:
        curve(
            "Leaded glass flourish",
            [
                (
                    x - side * 0.036,
                    y + sign * (0.1 + 0.085 * cos(t)),
                    z + 0.16 + 0.085 * sin(t),
                )
                for t in [i * 2 * pi / 28 for i in range(29)]
            ],
            0.012,
            black,
        )


def shop(side, y, z, index):
    x = side * 8.55
    for dy in [-1.48, 0, 1.48]:
        stained_arch(x, y + dy, z + 2.58, 0.7, side)
    box("Shop door lintel", (x, y, z + 2.46), (0.16, 4.54, 0.17), black, 0.012)
    for dy in [-2.22, -0.74, 0.74, 2.22]:
        box(
            "Glazed shop mullion",
            (x, y + dy, z + 1.22),
            (0.12, 0.075, 2.46),
            black,
            0.012,
        )
    # Glass sheets in front of merchandise, including actual recess depth.
    for dy in [-1.48, 1.48]:
        box("Display window glass", (x, y + dy, z + 1.22), (0.016, 1.4, 2.4), glass)
    box("Shop interior carpet", (side * 9.85, y, z + 0.015), (2.5, 4.6, 0.035), marble)
    box("Shop ceiling", (side * 9.85, y, z + 3.78), (2.5, 4.6, 0.08), cream)
    for dz in [0.35, 0.95, 1.55]:
        box(
            "Illuminated display shelf",
            (side * 9.35, y, z + dz),
            (0.6, 4.15, 0.085),
            white,
            0.015,
        )
        beam(
            "Shelf warm strip",
            (side * 9.05, y - 2, z + dz + 0.06),
            (side * 9.05, y + 2, z + dz + 0.06),
            0.014,
            lightmat,
        )
        for k in range(8):
            yy = y - 1.8 + k * 0.51 + random.uniform(-0.04, 0.04)
            c = random.choice([wood, black, white, gold, red])
            # Sculpted leather bags with rounded corners, handle and brass clasp.
            box(
                "Leather handbag",
                (side * 9.24, yy, z + dz + 0.18),
                (0.18, 0.29, 0.26),
                c,
                0.035,
            )
            curve(
                "Handbag handle",
                [
                    (side * 9.24, yy + 0.11 * cos(t), z + dz + 0.29 + 0.13 * sin(t))
                    for t in [i * pi / 16 for i in range(17)]
                ],
                0.012,
                c,
            )
            box(
                "Bag brass clasp",
                (side * 9.13, yy, z + dz + 0.17),
                (0.015, 0.045, 0.035),
                gold,
                0.004,
            )
    area(
        "Retail warm display lighting",
        (side * 9.15, y, z + 3.4),
        180,
        (1, 0.79, 0.53),
        3,
        (side * 9.1, y, z + 0.5),
    )
    if z == 0:
        names = [
            "VIA CONDOTTI",
            "BLOOMS",
            "TRIBECA",
            "DOMINIQUE'S",
            "GEORGE",
            "QVB BOUTIQUE",
            "JEWELLERY",
            "COLLECTION",
        ]
        name = names[index % len(names)]
        box(
            "Hanging cream shop sign",
            (side * 7.53, y - 2.15, z + 2.85),
            (1.5, 0.1, 0.43),
            lightmat,
            0.015,
        )
        text_obj(
            "Shop sign lettering",
            name,
            (side * 7.53, y - 2.208, z + 2.85),
            0.115,
            black,
        )
        for xx in [side * 7.53 - 0.62, side * 7.53 + 0.62]:
            beam(
                "Sign hanger",
                (xx, y - 2.15, z + 3.9),
                (xx, y - 2.15, z + 3.05),
                0.018,
                black,
            )
        beam(
            "Sign lower brass rail",
            (side * 7.53 - 0.82, y - 2.15, z + 2.60),
            (side * 7.53 + 0.82, y - 2.15, z + 2.60),
            0.025,
            gold,
        )


def railing(path, z, label):
    # Continuous turned timber cap and three horizontal metal rails.
    for zz, rr, mat in [
        (1.07, 0.065, wood),
        (0.99, 0.027, iron),
        (0.16, 0.024, iron),
        (0.25, 0.017, iron),
    ]:
        curve(
            label + " continuous rail", [(x, y, z + zz) for x, y in path], rr, mat, True
        )
    # Resample evenly by arc length for consistent panel spacing around corners.
    pairs = list(zip(path, path[1:] + path[:1]))
    lengths = [math.dist(a, b) for a, b in pairs]
    total = sum(lengths)
    count = round(total / 0.66)
    spacing = total / count
    for i in range(count):
        dist = i * spacing
        seg = 0
        while dist > lengths[seg]:
            dist -= lengths[seg]
            seg += 1
        a, b = pairs[seg]
        f = dist / lengths[seg]
        x = a[0] + f * (b[0] - a[0])
        y = a[1] + f * (b[1] - a[1])
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        beam(label + " upright", (x, y, z + 0.1), (x, y, z + 1.02), 0.025, iron)
        if i % 4 == 0:
            sphere(
                "Cast brass rail collar", (x, y, z + 0.99), (0.04, 0.04, 0.047), gold
            )
        # Four opposing spiral scrolls per panel, genuine open geometry.
        for row in range(2):
            for sign in [-1, 1]:
                pts = []
                for k in range(35):
                    t = k / 34 * 2.25 * pi
                    r = 0.125 * (1 - k / 42)
                    u = spacing * 0.5 + sign * (0.11 + r * cos(t))
                    zz = z + 0.43 + row * 0.31 + sign * r * sin(t)
                    pts.append((x + u * cos(angle), y + u * sin(angle), zz))
                curve(label + " wrought iron scroll", pts, 0.012, iron)


if STAGE in ("architecture", "all"):
    for z in [-4.4, 0, 4.3]:
        for side in [-1, 1]:
            for i, y in enumerate([-17.5, -12.5, -7.5, -2.5, 2.5, 7.5, 12.5, 17.5]):
                shop(side, y, z, i + (3 if side > 0 else 0))
    for z in [0, 4.3]:
        for cy in [-11.7, 11.7]:
            path = rounded_path(0, cy, 9.65, 16.55, 1.65, 20)
            railing(path, z, "Gallery")
            for dz, rr in [(-0.06, 0.075), (-0.18, 0.06), (-0.39, 0.045)]:
                curve(
                    "Ivory atrium edge moulding",
                    [(x, y, z + dz) for x, y in path],
                    rr,
                    cream,
                    True,
                )
            for i in range(0, len(path), 2):
                x, y = path[i]
                nx, ny = path[(i + 1) % len(path)]
                theta = math.atan2(ny - y, nx - x)
                curve(
                    "Repeating plaster blind arch",
                    [
                        (
                            x + 0.24 * cos(t) * cos(theta),
                            y + 0.24 * cos(t) * sin(theta),
                            z - 0.28 + 0.14 * sin(t),
                        )
                        for t in [j * pi / 16 for j in range(17)]
                    ],
                    0.025,
                    cream,
                )
    # Red transverse end walls, large arch trims and open passages.
    for y in [-22, 22]:
        for x in [-8, -4, 0, 4, 8]:
            box("End wall pier", (x, y, 3.3), (0.9, 0.48, 6.6), red)
        box("Red end wall above arches", (0, y, 7), (19, 0.48, 4), red)
        for x in [-6, -2, 2, 6]:
            for r in [1.5, 1.68]:
                curve(
                    "End arcade sandstone arch",
                    [
                        (x + r * cos(t), y - 0.27, 2.25 + r * sin(t))
                        for t in [i * pi / 40 for i in range(41)]
                    ],
                    0.085,
                    cream,
                )
            for xx in [x - 1.59, x + 1.59]:
                box(
                    "End arch jamb",
                    (xx, y - 0.28, 1.1),
                    (0.22, 0.18, 2.3),
                    cream,
                    0.025,
                )
    # Pitched glazed roof, closely spaced glazing bars, transverse trusses.
    skyglass = material("Blue daylight glazing", (0.48, 0.7, 0.83), 0.18, 0, 0.3, 0.3)
    for side in [-1, 1]:
        mesh(
            "Pitched skylight",
            [
                (0, -23, 11.8),
                (side * 8.8, -23, 8.3),
                (side * 8.8, 23, 8.3),
                (0, 23, 11.8),
            ],
            [(0, 1, 2, 3)],
            skyglass,
        )
        for j in range(47):
            y = -23 + j
            beam(
                "Skylight glazing rib",
                (0, y, 11.76),
                (side * 8.8, y, 8.28),
                0.035,
                iron,
            )
        for j in range(9):
            x = side * j * 1.1
            zz = 11.76 - j * 0.4375
            beam("Skylight longitudinal bar", (x, -23, zz), (x, 23, zz), 0.028, iron)
    for y in [-20, -10, 0, 10, 20]:
        beam("Roof truss tie", (-8.6, y, 8.15), (8.6, y, 8.15), 0.055, cream)
        for side in [-1, 1]:
            beam(
                "Roof principal rafter",
                (side * 8.6, y, 8.15),
                (0, y, 11.65),
                0.09,
                cream,
            )
            for i in range(4):
                x = side * i * 2.1
                beam(
                    "Roof truss diagonal",
                    (x, y, 8.15),
                    (side * (i + 1) * 2.1, y, 11.6 - (i + 1) * 0.85),
                    0.045,
                    cream,
                )
        area(
            "Skylight soft daylight", (0, y, 10.5), 1400, (0.68, 0.82, 1), 8, (0, y, 0)
        )
    print("Architecture complete", len(bpy.data.objects))


def pendant(x, y, z):
    beam("Pendant stem", (x, y, z + 3.83), (x, y, z + 2.6), 0.018, black)
    cylinder("Pendant canopy", (x, y, z + 3.83), 0.11, 0.04, black)
    cylinder("Pendant socket", (x, y, z + 2.56), 0.07, 0.26, gold)
    cylinder("Pendant shade rim", (x, y, z + 2.44), 0.28, 0.035, cream)
    sphere("Blown glass globe", (x, y, z + 2.29), (0.255, 0.255, 0.26), glass)
    cylinder("Pendant glowing lamp", (x, y, z + 2.30), 0.072, 0.19, lightmat)
    area("Pendant pool", (x, y, z + 2.2), 36, (1, 0.83, 0.59), 0.42, (x, y, z))


def chair(x, y, angle):
    def p(a, b, c):
        return (
            x + a * cos(angle) - b * sin(angle),
            y + a * sin(angle) + b * cos(angle),
            c,
        )

    cylinder("Bentwood chair seat", (x, y, 0.46), 0.225, 0.045, wood)
    for a in [-1, 1]:
        for b in [-1, 1]:
            beam(
                "Splayed bentwood leg",
                p(a * 0.21, b * 0.2, 0.04),
                p(a * 0.15, b * 0.14, 0.45),
                0.022,
                wood,
            )
    curve(
        "Bentwood chair outer back",
        [
            p(0.235 * cos(t), 0.16, 0.46 + 0.53 * sin(t))
            for t in [i * pi / 36 for i in range(37)]
        ],
        0.021,
        wood,
    )
    curve(
        "Bentwood chair inner loop",
        [
            p(0.135 * cos(t), 0.165, 0.51 + 0.34 * sin(t))
            for t in [i * pi / 32 for i in range(33)]
        ],
        0.015,
        wood,
    )
    curve(
        "Chair underseat hoop",
        [
            p(0.17 * cos(t), 0.17 * sin(t), 0.22)
            for t in [i * 2 * pi / 32 for i in range(32)]
        ],
        0.014,
        wood,
        True,
    )


def table(x, y, i):
    box("Cafe square walnut tabletop", (x, y, 0.76), (0.72, 0.72, 0.045), wood, 0.035)
    cylinder("Cast iron pedestal", (x, y, 0.4), 0.045, 0.71, iron)
    for a in range(4):
        t = a * pi / 2
        curve(
            "Cafe table claw foot",
            [
                (x, y, 0.18),
                (x + 0.15 * cos(t), y + 0.15 * sin(t), 0.06),
                (x + 0.32 * cos(t), y + 0.32 * sin(t), 0.035),
            ],
            0.022,
            iron,
        )
    for a in [-1, 1]:
        chair(x + 0.61 * a, y + random.uniform(-0.09, 0.09), -pi / 2 * a)
    # Table dressing gives the camera close-scale cues.
    menu = box(
        "Upright cream menu",
        (x + 0.13, y + 0.13, 0.96),
        (0.16, 0.018, 0.34),
        white,
        0.008,
    )
    menu.rotation_euler[2] = 0.2
    text_obj("Menu title", "QVB\nCAFE", (x + 0.13, y + 0.118, 1.0), 0.036, black)
    cylinder("Porcelain saucer", (x - 0.15, y - 0.13, 0.8), 0.074, 0.009, white)
    cylinder("Coffee cup", (x - 0.15, y - 0.13, 0.838), 0.043, 0.07, white)
    cylinder("Coffee surface", (x - 0.15, y - 0.13, 0.875), 0.038, 0.002, wood)
    curve(
        "Cup handle",
        [
            (x - 0.15 + 0.06 * cos(t), y - 0.13, 0.84 + 0.033 * sin(t))
            for t in [i * 2 * pi / 24 for i in range(25)]
        ],
        0.009,
        white,
    )
    box(
        "Folded linen napkin",
        (x + 0.12, y - 0.16, 0.795),
        (0.12, 0.16, 0.01),
        white,
        0.004,
    )


def clock():
    # Octagonal hanging clock with sculpted cornices and four usable clock faces.
    cx, cy = 0, 14.2
    beam("Clock suspension", (cx, cy, 11.5), (cx, cy, 7.6), 0.07, iron)
    for z, r, d, mat in [
        (2.5, 0.5, 0.28, gold),
        (2.8, 0.86, 0.19, gold),
        (3.35, 1.1, 1.05, gold),
        (4.0, 1.24, 0.18, gold),
        (4.25, 1.35, 0.28, gold),
        (4.5, 1.38, 0.23, blue),
        (4.8, 1.42, 0.2, gold),
        (5.35, 1.30, 0.95, blue),
        (5.95, 1.5, 0.2, gold),
        (6.2, 1.38, 0.3, gold),
        (6.5, 1.25, 0.25, blue),
        (6.8, 1.4, 0.22, gold),
    ]:
        cylinder("Great clock octagonal tier", (cx, cy, z), r, d, mat, 8)
    for a in range(4):
        ang = a * pi / 2
        normal = Vector((sin(ang), -cos(ang), 0))
        right = Vector((cos(ang), sin(ang), 0))
        center = Vector((cx, cy, 3.35)) + normal * 1.025
        face = cylinder("Ivory clock dial", center, 0.48, 0.026, white, 80)
        face.rotation_euler = Vector(normal).to_track_quat("Z", "Y").to_euler()
        curve(
            "Clock brass bezel",
            [
                tuple(center + right * (0.51 * cos(t)) + Vector((0, 0, 0.51 * sin(t))))
                for t in [i * 2 * pi / 80 for i in range(80)]
            ],
            0.038,
            gold,
            True,
        )
        romans = [
            "XII",
            "I",
            "II",
            "III",
            "IV",
            "V",
            "VI",
            "VII",
            "VIII",
            "IX",
            "X",
            "XI",
        ]
        for i, label in enumerate(romans):
            t = i * pi / 6
            pos = (
                center
                + normal * 0.021
                + right * (0.381 * sin(t))
                + Vector((0, 0, 0.381 * cos(t)))
            )
            text_obj("Roman clock numeral", label, pos, 0.094, black, (pi / 2, 0, ang))
        for t, length in [(-pi / 3, 0.26), (pi * 5 / 6, 0.34)]:
            beam(
                "Clock hand",
                center + normal * 0.036,
                center
                + normal * 0.036
                + right * (length * sin(t))
                + Vector((0, 0, length * cos(t))),
                0.016,
                black,
            )
        sphere("Clock hand boss", center + normal * 0.049, (0.034, 0.034, 0.034), gold)
    for i in range(16):
        t = i * 2 * pi / 16
        beam(
            "Clock pavilion column",
            (1.25 * cos(t), cy + 1.25 * sin(t), 4.9),
            (1.25 * cos(t), cy + 1.25 * sin(t), 5.93),
            0.027,
            gold,
        )
        sphere(
            "Clock blue enamel medallion",
            (1.36 * cos(t), cy + 1.36 * sin(t), 4.52),
            (0.16, 0.10, 0.085),
            blue,
        )
    for zz in [5.05, 5.75]:
        curve(
            "Clock pavilion railing",
            [
                (1.32 * cos(t), cy + 1.32 * sin(t), zz)
                for t in [i * 2 * pi / 64 for i in range(64)]
            ],
            0.024,
            iron,
            True,
        )
    for i in range(8):
        t = i * pi / 4
        sphere(
            "Clock gilded finial",
            (1.2 * cos(t), cy + 1.2 * sin(t), 7.0),
            (0.11, 0.11, 0.21),
            gold,
        )
    cylinder("Clock crown", (0, cy, 7.1), 0.65, 0.5, gold, 8)
    sphere("Clock crown cap", (0, cy, 7.45), (0.65, 0.65, 0.35), gold)


def escalator():
    # Reverse-pan landmark across the other atrium bay.
    a = Vector((-3.8, -10.2, 0.08))
    b = Vector((3.7, -15.5, 4.38))
    d = b - a
    horizontal = Vector((d.x, d.y, 0)).normalized()
    across = Vector((-horizontal.y, horizontal.x, 0))
    for i in range(37):
        c = a + d * (i / 36)
        step = box("Escalator ribbed step", c, (1.25, 0.30, 0.16), silver)
        step.rotation_euler[2] = math.atan2(horizontal.y, horizontal.x) - pi / 2
        for j in range(9):
            beam(
                "Escalator tread groove",
                c
                + across * (j * 0.13 - 0.52)
                - horizontal * 0.12
                + Vector((0, 0, 0.085)),
                c
                + across * (j * 0.13 - 0.52)
                + horizontal * 0.12
                + Vector((0, 0, 0.085)),
                0.006,
                black,
            )
    for side in [-1, 1]:
        aa = a + across * 0.73 * side
        bb = b + across * 0.73 * side
        mesh(
            "Escalator glass balustrade",
            [
                tuple(aa),
                tuple(bb),
                tuple(bb + Vector((0, 0, 0.85))),
                tuple(aa + Vector((0, 0, 0.85))),
            ],
            [(0, 1, 2, 3)],
            glass,
        )
        beam(
            "Escalator black handrail",
            aa + Vector((0, 0, 0.89)),
            bb + Vector((0, 0, 0.89)),
            0.047,
            black,
        )
        beam("Escalator polished skirt", aa, bb, 0.11, silver)


if STAGE in ("details", "all"):
    for z in [0, 4.3, -4.4]:
        for side in [-1, 1]:
            for y in range(-19, 21, 5):
                pendant(side * 7.0, y, z)
    for x in [-5.8, 5.8]:
        for i, y in enumerate(
            [-17, -14.7, -12.3, -9.8, -7.3, -4.8, 4.8, 7.3, 9.8, 12.3, 14.7, 17]
        ):
            table(x, y, i)
    for x in [-2.5, 0, 2.5]:
        table(x, 1.7, 0)
    # Original floral carpet pattern, constructed from curling stitched stems.
    # Curves sit just above the carpet, not borrowed image textures.
    for side in [-1, 1]:
        for j in range(46):
            y = -22.5 + j
            x = side * 7.5
            for sign in [-1, 1]:
                for k in range(3):
                    pts = []
                    for q in range(48):
                        t = q / 47 * 2.8 * pi
                        r = (0.43 + 0.07 * k) * (1 - q / 57)
                        pts.append(
                            (
                                x + sign * (0.12 + r * cos(t)),
                                y + 0.2 * k + 0.8 * r * sin(t),
                                0.023,
                            )
                        )
                    curve("Woven carpet scroll", pts, 0.009, carpetgold)
    clock()
    escalator()
    # Recessed ceiling fittings over the bridge around the fixed mount.
    for x in [-6, -3, 0, 3, 6]:
        for y in [-2, 2]:
            cylinder("Recessed downlight trim", (x, y, 3.84), 0.09, 0.025, silver)
            cylinder("Recessed downlight lens", (x, y, 3.82), 0.07, 0.015, lightmat)
            area("Bridge downlight", (x, y, 3.77), 38, (1, 0.86, 0.66), 0.22, (x, y, 0))
    print("Details complete", len(bpy.data.objects))

if STAGE in ("camera", "all"):
    mount = bpy.data.objects.new("PTZ_Mount", None)
    bpy.context.collection.objects.link(mount)
    mount.location = (3.4, 2.7, 3.55)
    mount.empty_display_type = "ARROWS"
    mount.empty_display_size = 0.45
    mount["description"] = (
        "Estimated position of the ceiling camera circled in the user reference. Local Z=0 is level 1."
    )
    mount["pan_degrees"] = 0.0
    mount["tilt_degrees"] = 18.0
    mount["pan_limits_degrees"] = [-180.0, 180.0]
    mount["tilt_limits_degrees"] = [-80.0, 80.0]
    pan = bpy.data.objects.new("PTZ_Pan", None)
    bpy.context.collection.objects.link(pan)
    pan.parent = mount
    tilt = bpy.data.objects.new("PTZ_Tilt", None)
    bpy.context.collection.objects.link(tilt)
    tilt.parent = pan
    tilt.rotation_euler = (pi / 2, 0, 0)
    # Zero pan looks along +Y; positive tilt points down. Camera looks along local -Z.
    for obj, index, prop, expr in [
        (pan, 2, "pan_degrees", "-p*pi/180"),
        (tilt, 0, "tilt_degrees", "pi/2-p*pi/180"),
    ]:
        driver = obj.driver_add("rotation_euler", index).driver
        driver.expression = expr
        v = driver.variables.new()
        v.name = "p"
        v.type = "SINGLE_PROP"
        v.targets[0].id = mount
        v.targets[0].data_path = '["' + prop + '"]'
    d = bpy.data.cameras.new("Camera-device optics")
    d.lens = 21
    d.sensor_width = 36
    d.clip_start = 0.05
    d.clip_end = 150
    cam = bpy.data.objects.new("camera-device", d)
    bpy.context.collection.objects.link(cam)
    cam.parent = tilt
    bpy.context.scene.camera = cam
    body = cylinder("PTZ ivory ceiling mount", (3.4, 2.7, 3.82), 0.13, 0.16, cream)
    sphere("PTZ smoked dome", (3.4, 2.7, 3.66), (0.12, 0.12, 0.115), black)
    # Hide physical housing from its own camera while retaining it for model inspection.
    body.visible_camera = False
    bpy.data.objects["PTZ smoked dome"].visible_camera = False
    presets = [
        {"name": "01-clock-atrium", "pan": -16, "tilt": 10, "lens": 20},
        {"name": "02-cafe-gallery", "pan": 30, "tilt": 30, "lens": 20},
        {"name": "03-opposite-shops", "pan": -88, "tilt": 17, "lens": 25},
        {"name": "04-escalator", "pan": -155, "tilt": 5, "lens": 21},
    ]
    (ROOT / "camera-presets.json").write_text(
        json.dumps(
            {
                "units": "metres and degrees",
                "mount": [3.4, 2.7, 3.55],
                "zero_pan": "+Y",
                "positive_pan": "clockwise looking down",
                "positive_tilt": "down",
                "presets": presets,
            },
            indent=2,
        )
        + "\n"
    )
    mount["pan_degrees"] = -16.0
    mount["tilt_degrees"] = 10.0
    s = bpy.context.scene
    s["reference"] = (
        "Google Street View, QVB, Jan 2016, panorama ipZlepagBod9G7cYub8bAw"
    )
    s["model_status"] = (
        "Visual reconstruction from references; approximate dimensions and camera position, no survey calibration."
    )
    s.render.filepath = str(ROOT / "renders" / "01-clock-atrium.png")
    (ROOT / "renders").mkdir(exist_ok=True)
    s.render.film_transparent = False
    bpy.context.view_layer.update()
    for screen in bpy.data.screens:
        for a in screen.areas:
            if a.type == "VIEW_3D":
                a.spaces.active.region_3d.view_perspective = "CAMERA"
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "qvb-camera-scene.blend"))
    print("Saved", bpy.data.filepath, "objects", len(bpy.data.objects))

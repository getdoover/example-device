"""Second pass, researched from January 2016 Street View through Chrome.

Run after finish_scene.py through Blender MCP. Idempotent: replaces its own
collection; archives only Level 1 prototype shop fixtures. Dimensions and outer
bay allocations remain estimates. See references/shops/notes.md.
"""

import ast
import hashlib
import json
import math
import random
from collections import Counter
from math import cos, pi, sin
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
STAGE = globals().get("SHOP_STAGE", "all")
scene = bpy.context.scene
# Load geometry functions only: importing the entire first-pass script would
# reset existing materials, even in its helpers mode.
tree = ast.parse((ROOT / "build_scene.py").read_text())
helpers = ast.Module(
    body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[]
)
helper_ns = dict(bpy=bpy, Vector=Vector, math=math, pi=pi, sin=sin, cos=cos)
exec(compile(helpers, "build_scene.py:geometry_helpers", "exec"), helper_ns)
material = helper_ns["material"]
noise_finish = helper_ns["noise_finish"]
box = helper_ns["box"]
curve = helper_ns["curve"]
sphere = helper_ns["sphere"]
cylinder = helper_ns["cylinder"]
text_obj = helper_ns["text_obj"]
area = helper_ns["area"]
mesh = helper_ns["mesh"]

COLLECTION = "08 Level 1 shops"
ARCHIVE = "09 Archived Level 1 placeholders"


def centre(o):
    if o.type == "CURVE" and o.data.splines:
        pts = [
            o.matrix_world @ Vector(p.co[:3]) for s in o.data.splines for p in s.points
        ]
        return sum(pts, Vector()) / len(pts)
    return o.matrix_world.translation.copy()


def outside_signature():
    records = []
    for o in scene.objects:
        if o.get("shop_pass") == 2 or o.get("archived_shop_pass") == 2:
            continue
        records.append(
            (
                o.name,
                tuple(tuple(row) for row in o.matrix_world),
                o.hide_render,
                tuple(s.material.name if s.material else "" for s in o.material_slots),
            )
        )
    return hashlib.sha256(repr(sorted(records)).encode()).hexdigest()


if STAGE in ("prepare", "all"):
    old = bpy.data.collections.get(COLLECTION)
    if old:
        for o in list(old.all_objects):
            bpy.data.objects.remove(o, do_unlink=True)
        for child in list(old.children):
            bpy.data.collections.remove(child)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new(COLLECTION)
    scene.collection.children.link(coll)
    archive = bpy.data.collections.get(ARCHIVE)
    if archive is None:
        archive = bpy.data.collections.new(ARCHIVE)
        scene.collection.children.link(archive)
    prefixes = (
        "Illuminated display shelf",
        "Shelf warm strip",
        "Leather handbag",
        "Handbag handle",
        "Bag brass clasp",
        "Shop interior carpet",
        "Retail warm display lighting",
        "Hanging cream shop sign",
        "Shop sign lettering",
        "Sign hanger",
        "Sign lower brass rail",
        "Mannequin",
        "Display window glass",
        "Glazed shop mullion",
    )
    for o in list(scene.objects):
        if o.name.startswith(prefixes) and not o.get("archived_shop_pass"):
            p = centre(o)
            if -0.1 <= p.z <= 3.95 and abs(p.x) > 6.5:
                for c in list(o.users_collection):
                    c.objects.unlink(o)
                archive.objects.link(o)
                o["archived_shop_pass"] = 2
    archive.hide_render = True
    archive.hide_viewport = True
    scene["shop_pass_unaffected_signature"] = outside_signature()
    print("Archived", len(archive.objects), "Level 1 prototype objects")

coll = bpy.data.collections.get(COLLECTION)
if coll is None:
    raise RuntimeError("Run the prepare stage first")


def mat(name, color, rough=0.5, metal=0, transmission=0, emission=0):
    name = "L1 · " + name
    existing = bpy.data.materials.get(name)
    return existing or material(name, color, rough, metal, transmission, emission)


ivory = mat("warm lacquer", (0.78, 0.75, 0.67), 0.27)
white = mat("display white", (0.88, 0.88, 0.84), 0.3)
black = mat("charcoal display velvet", (0.015, 0.019, 0.018), 0.78)
frame = bpy.data.materials["Shopfront bronze black"]
brass = mat("brushed gold fittings", (0.56, 0.37, 0.13), 0.24, 0.78)
chrome = mat("mirror polished chrome", (0.8, 0.84, 0.88), 0.09, 1)
glass = mat("low iron display glazing", (0.98, 0.99, 1), 0.035, 0, 1)
glass.node_tree.nodes.get("Principled BSDF").inputs["IOR"].default_value = 1.46
led = mat("white shelf LED", (0.92, 0.96, 1), 0.35, 0, 0, 3.5)
warmled = mat("warm shelf LED", (1, 0.8, 0.52), 0.35, 0, 0, 2)
red = mat("sale red", (0.62, 0.012, 0.015), 0.37)
sage = mat("Crabtree sage", (0.27, 0.36, 0.21), 0.58)
blue = mat("Crabtree navy", (0.015, 0.035, 0.066), 0.5)
tan = mat("champagne wall", (0.57, 0.48, 0.33), 0.8)
oak = mat("cashmere honey oak", (0.39, 0.16, 0.046), 0.32)
velvet = mat("Vienna oxblood upholstery", (0.18, 0.024, 0.016), 0.55)
daylight = mat("diffuse rear window daylight", (0.51, 0.64, 0.77), 0.55, 0, 0, 0.9)
mannequin = mat("ivory display mannequins", (0.72, 0.72, 0.65), 0.46)
darkmannequin = mat("graphite display mannequins", (0.04, 0.048, 0.039), 0.38)
pearl = mat("pearl lustre", (0.9, 0.84, 0.69), 0.18, 0.27)
gem = mat("faceted crystal", (0.85, 0.94, 1), 0.035, 0.05, 0.8)
gem.node_tree.nodes.get("Principled BSDF").inputs["IOR"].default_value = 2.1
leathers = [
    mat("leather " + n, c, 0.23 if n in ("black", "red", "navy") else 0.42)
    for n, c in [
        ("black", (0.012, 0.012, 0.018)),
        ("red", (0.48, 0.017, 0.022)),
        ("navy", (0.022, 0.025, 0.12)),
        ("sand", (0.51, 0.35, 0.21)),
        ("ivory", (0.82, 0.75, 0.57)),
        ("blush", (0.53, 0.30, 0.27)),
        ("gold", (0.48, 0.33, 0.10)),
    ]
]
cloths = [
    mat("fabric " + str(i), c, 0.86)
    for i, c in enumerate(
        [
            (0.025, 0.026, 0.032),
            (0.81, 0.76, 0.61),
            (0.026, 0.045, 0.15),
            (0.55, 0.025, 0.021),
            (0.20, 0.26, 0.12),
            (0.35, 0.20, 0.30),
            (0.62, 0.48, 0.32),
        ]
    )
]
for m in cloths + leathers + [oak, ivory, tan, black]:
    if not m.node_tree.nodes.get("Surface grain"):
        noise_finish(m, 170 if m in cloths else 90, 0.11, 0.002)
        m.node_tree.nodes[-2].name = "Surface grain"

# Black/ivory botanical-like pattern used for the visible Blooms garments.
printed = mat("Blooms monochrome printed fabric", (0.65, 0.64, 0.59), 0.85)
if not printed.node_tree.nodes.get("Cloth print"):
    n = printed.node_tree.nodes.new("ShaderNodeTexNoise")
    n.name = "Cloth print"
    n.inputs["Scale"].default_value = 22
    n.inputs["Roughness"].default_value = 0.75
    ramp = printed.node_tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.46
    ramp.color_ramp.elements[0].color = (0.008, 0.012, 0.016, 1)
    ramp.color_ramp.elements[1].position = 0.54
    ramp.color_ramp.elements[1].color = (0.87, 0.85, 0.77, 1)
    printed.node_tree.links.new(n.outputs["Fac"], ramp.inputs[0])
    printed.node_tree.links.new(
        ramp.outputs[0], printed.node_tree.nodes["Principled BSDF"].inputs["Base Color"]
    )

font_path = Path("/System/Library/Fonts/Supplemental/Georgia.ttf")
serif = bpy.data.fonts.get("QVB Shop Serif")
if serif is None and font_path.exists():
    serif = bpy.data.fonts.load(str(font_path))
    serif.name = "QVB Shop Serif"

SHOPS = [
    dict(
        id="old-vienna",
        name="Old Vienna\nCoffee House",
        side=-1,
        bays=[-17.5],
        kind="cafe",
        refs=["15-old-vienna-coffee-house.png"],
    ),
    dict(
        id="crabtree-evelyn",
        name="CRABTREE & EVELYN",
        side=-1,
        bays=[-12.5, -7.5],
        kind="apothecary",
        refs=["03-crabtree-evelyn.png", "15-old-vienna-coffee-house.png"],
    ),
    dict(
        id="via-condotti",
        name="via Condotti",
        side=-1,
        bays=[-2.5, 2.5],
        kind="accessories",
        refs=["01-opposite-arcade.png", "09-blooms-opposite-clock.png"],
    ),
    dict(
        id="blooms",
        name="BLOOMS",
        side=-1,
        bays=[7.5, 12.5],
        kind="fashion",
        refs=["09-blooms-opposite-clock.png", "10-blooms-display-detail.png"],
    ),
    dict(
        id="unresolved-clockward-fashion",
        name="",
        side=-1,
        bays=[17.5],
        kind="fashion",
        refs=["10-blooms-display-detail.png"],
        confidence="Visible fashion display; tenancy boundary/name unresolved",
    ),
    dict(
        id="george",
        name="G e o r g e",
        side=1,
        bays=[-17.5],
        kind="fashion",
        refs=["14-george-eveningwear.png"],
    ),
    dict(
        id="tribeca",
        name="TRIBECA",
        side=1,
        bays=[-12.5],
        kind="fashion",
        refs=["12-tribeca-dresses.png"],
    ),
    dict(
        id="volls",
        name="Volls\nJewellery",
        side=1,
        bays=[-7.5],
        kind="jewellery",
        refs=["13-volls-jewellery-confirmed.png"],
    ),
    dict(
        id="dominique",
        name="Dominique's",
        side=1,
        bays=[-2.5, 2.5],
        kind="shoes",
        refs=["05-dominique-interior.png", "07-dominique-entry.png"],
    ),
    dict(
        id="cashmere",
        name="QVB\nCashmere Collection",
        side=1,
        bays=[7.5],
        kind="knitwear",
        refs=["06-clockward-neighbours.png", "11-cashmere-window.png"],
    ),
    dict(
        id="gs-diamonds",
        name="GS\nDIAMONDS",
        side=1,
        bays=[12.5, 17.5],
        kind="jewellery",
        refs=["08-gs-diamonds.png"],
    ),
]


class Shop:
    def __init__(self, spec, y):
        self.spec, self.y, self.side = spec, y, spec["side"]
        key = spec["id"] + " · bay " + str(y)
        old = bpy.data.collections.get(key)
        if old:
            for o in list(old.objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(old)
        self.coll = bpy.data.collections.new(key)
        coll.children.link(self.coll)
        self.rng = random.Random(key)

    def p(self, u, v, z):
        # U runs left to right as seen from the gallery; V runs into the shop.
        return (self.side * (8.55 + v), self.y - self.side * u, z)

    def keep(self, o):
        for c in list(o.users_collection):
            c.objects.unlink(o)
        self.coll.objects.link(o)
        o["shop_pass"] = 2
        o["shop_id"] = self.spec["id"]
        o["level"] = 1
        o.name = self.spec["id"] + " · " + o.name
        return o

    def box(self, name, p, size, m, bevel=0.005):
        return self.keep(box(name, self.p(*p), (size[1], size[0], size[2]), m, bevel))

    def curve(self, name, pts, r, m, cyclic=False):
        return self.keep(curve(name, [self.p(*p) for p in pts], r, m, cyclic))

    def sphere(self, name, p, size, m):
        return self.keep(sphere(name, self.p(*p), (size[1], size[0], size[2]), m))

    def cyl(self, name, p, r, depth, m):
        return self.keep(cylinder(name, self.p(*p), r, depth, m, 24))

    def text(self, name, body, p, size, m, serif_font=True):
        o = self.keep(
            text_obj(name, body, self.p(*p), size, m, (pi / 2, 0, -self.side * pi / 2))
        )
        if serif_font and serif:
            o.data.font = serif
        return o

    def light(self, p, target, power=90, color=(1, 0.9, 0.76), size=1.5):
        return self.keep(
            area("shop illumination", self.p(*p), power, color, size, self.p(*target))
        )

    def loft(self, name, u, v, z, rings, m, n=24):
        verts = []
        for height, width, depth in rings:
            for i in range(n):
                t = 2 * pi * i / n
                verts.append(self.p(u + width * cos(t), v + depth * sin(t), z + height))
        faces = [
            tuple(reversed(range(n))),
            tuple(range((len(rings) - 1) * n, len(rings) * n)),
        ]
        for j in range(len(rings) - 1):
            for i in range(n):
                a, b = j * n + i, j * n + (i + 1) % n
                faces.append((a, b, b + n, a + n))
        o = self.keep(mesh(name, verts, faces, m))
        for f in o.data.polygons:
            f.use_smooth = len(f.vertices) == 4
        return o

    def sign(self):
        if not self.spec["name"]:
            return
        # Perpendicular, illuminated cream sign with a bronze U bracket.
        x, y, z = self.side * 7.63, self.y - 2.13, 2.97
        self.keep(
            box(
                "projecting ivory lightbox",
                (x, y, z),
                (1.55, 0.085, 0.48),
                warmled,
                0.012,
            )
        )
        for direction in (-1, 1):
            o = self.keep(
                text_obj(
                    "tenant sign",
                    self.spec["name"],
                    (x, y + direction * 0.049, z),
                    0.113 if "\n" in self.spec["name"] else 0.125,
                    brass if self.spec["id"] == "volls" else frame,
                    (pi / 2, 0, pi if direction == 1 else 0),
                )
            )
            if serif:
                o.data.font = serif
            o.data.space_line = 0.9
            o["reference"] = self.spec["refs"][0]
        for xx in (x - 0.83, x + 0.83):
            self.keep(
                box(
                    "sign U bracket",
                    (xx, y, z + 0.03),
                    (0.038, 0.15, 0.62),
                    frame,
                    0.005,
                )
            )
        self.keep(
            box("sign bracket rail", (x, y, z - 0.27), (1.7, 0.15, 0.065), frame, 0.005)
        )
        self.keep(
            box(
                "sign fluorescent tube",
                (x, y - 0.085, z - 0.24),
                (1.48, 0.025, 0.027),
                led,
                0.006,
            )
        )

    def shell(self, floor=ivory, wall=tan, window=True):
        self.box("continuous shop floor", (0, 1.13, 0.035), (4.6, 2.55, 0.05), floor)
        self.box("interior rear wall lining", (0, 2.12, 1.85), (4.6, 0.09, 3.65), wall)
        for u in (-2.27, 2.27):
            # Only outer tenancy boundaries: two-bay shops remain connected inside.
            world_edge = self.y - self.side * u
            others = [y for y in self.spec["bays"] if y != self.y]
            if not any(abs(world_edge - y) < 2.8 for y in others):
                self.box(
                    "tenancy side partition", (u, 1.2, 1.7), (0.07, 2.4, 3.4), wall
                )
        self.box("mirror soffit", (0, 0.30, 2.36), (4.42, 0.7, 0.11), chrome)
        for u in (-1.75, -0.9, 0.9, 1.75):
            self.cyl("recessed spotlight housing", (u, 0.20, 2.27), 0.066, 0.045, frame)
            self.cyl("spotlight lens", (u, 0.20, 2.24), 0.048, 0.006, led)
        # Wider clear windows and offset entry; projecting side panes are real glass.
        for u in (-2.2, -0.62, 0.63, 2.2):
            self.box(
                "slender bronze jamb", (u, -0.10, 1.15), (0.039, 0.045, 2.3), frame
            )
        for u in (-1.41, 1.415):
            self.box(
                "projecting display front glass",
                (u, -0.12, 1.14),
                (1.52, 0.009, 2.25),
                glass,
                0,
            )
            self.box(
                "display header mirror", (u, -0.10, 2.28), (1.58, 0.06, 0.08), chrome
            )
        for u in (-0.61, 0.62):
            self.box(
                "return glass at recessed entry",
                (u, 0.12, 1.14),
                (0.009, 0.47, 2.25),
                glass,
                0,
            )
        # Door is open on a small angle, with a pair of long pull handles.
        self.box(
            "open entry glass leaf", (0.64, 0.51, 1.15), (0.009, 0.8, 2.27), glass, 0
        )
        self.curve(
            "entry pull handle",
            [(0.615, 0.80, 0.68), (0.615, 0.80, 1.65)],
            0.014,
            chrome,
        )
        if window:
            for u in (-1.35, 1.35):
                self.box(
                    "sash window daylight",
                    (u, 2.062, 2.03),
                    (0.88, 0.012, 2.0),
                    daylight,
                    0,
                )
                for du in (-0.49, 0.49):
                    self.box(
                        "sash window frame",
                        (u + du, 2.01, 2.03),
                        (0.055, 0.07, 2.17),
                        white,
                    )
                for z in (0.96, 1.62, 2.34, 3.1):
                    self.box(
                        "sash window rail", (u, 2.005, z), (1.04, 0.075, 0.043), white
                    )
                self.box(
                    "sash window centre bar", (u, 2, 2.02), (0.025, 0.04, 2.1), white
                )
                self.box("deep window sill", (u, 1.96, 0.94), (1.10, 0.19, 0.06), white)
        self.sign()

    def handbag(self, u, v, z, m, scale=1):
        w, d, h = 0.29 * scale, 0.12 * scale, 0.23 * scale
        self.box(
            "structured leather handbag",
            (u, v, z + h * 0.5),
            (w, d, h),
            m,
            0.028 * scale,
        )
        self.box(
            "folded leather top flap",
            (u, v - d * 0.51, z + h * 0.69),
            (w * 0.93, 0.014, h * 0.41),
            m,
            0.014,
        )
        for vv in (v - d * 0.28, v + d * 0.28):
            self.curve(
                "rounded handbag handle",
                [
                    (u + w * 0.33 * cos(t), vv, z + h * 0.9 + 0.13 * scale * sin(t))
                    for t in [i * pi / 20 for i in range(21)]
                ],
                0.009 * scale,
                m,
            )
        self.curve(
            "stitched front perimeter",
            [
                (u + dx, v - d * 0.55, z + dz)
                for dx, dz in [
                    (-w * 0.42, 0.035 * scale),
                    (-w * 0.42, h * 0.55),
                    (0, h * 0.51),
                    (w * 0.42, h * 0.55),
                    (w * 0.42, 0.035 * scale),
                ]
            ],
            0.0015,
            ivory,
        )
        self.box(
            "bag clasp",
            (u, v - d * 0.64, z + h * 0.54),
            (0.037 * scale, 0.012, 0.025 * scale),
            brass,
            0.003,
        )

    def shoe(self, u, v, z, m, angle=0):
        # Swept sole + hollow upper and a distinct stiletto heel, rather than blocks.
        before = set(self.coll.objects)
        rings = []
        n = 24
        for k in range(n):
            t = 2 * pi * k / n
            vv = 0.16 * cos(t)
            width = 0.049 * (1 - 0.22 * cos(t))
            uu = width * sin(t)
            base = 0.025 + 0.105 * max(0, cos(t)) ** 1.6
            rim = base + (0.073 if vv < -0.025 else 0.031 if vv < 0.09 else 0.09)
            rings.append((uu, vv, base, rim))
        vs = [
            self.p(u + a, v + b, z + (c if j == 0 else d))
            for j in (0, 1)
            for a, b, c, d in rings
        ]
        faces = [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
        o = self.keep(mesh("pump leather upper", vs, faces, m))
        sol = o.modifiers.new("Leather thickness", "SOLIDIFY")
        sol.thickness = 0.002
        for p in o.data.polygons:
            p.use_smooth = True
        self.curve(
            "shoe sole edge",
            [(u + a, v + b, z + c) for a, b, c, d in rings],
            0.006,
            leathers[0],
            True,
        )
        self.loft(
            "shoe insole",
            u,
            v,
            z,
            [(0.034, 0.045, 0.145), (0.04, 0.041, 0.14)],
            leathers[3],
        )
        self.curve(
            "tapered stiletto heel",
            [(u, v + 0.125, z + 0.13), (u, v + 0.12, z + 0.015)],
            0.009,
            m,
        )
        self.sphere(
            "closed toe vamp", (u, v - 0.104, z + 0.045), (0.052, 0.061, 0.025), m
        )
        if angle:
            from mathutils import Matrix

            pivot = Vector(self.p(u, v, z))
            transform = (
                Matrix.Translation(pivot)
                @ Matrix.Rotation(angle, 4, "Z")
                @ Matrix.Translation(-pivot)
            )
            for ob in set(self.coll.objects) - before:
                # New objects' matrix_world may still be stale until a dependency
                # graph update. Compose the assigned transform directly; otherwise
                # the toe instance loses its scale and becomes a metre-sized sphere.
                local = (
                    Matrix.Translation(ob.location)
                    @ ob.rotation_euler.to_matrix().to_4x4()
                    @ Matrix.Diagonal((*ob.scale, 1))
                )
                ob.matrix_world = transform @ local

    def chandelier(self, u=0, v=1.1, z=2.32):
        self.curve(
            "chandelier suspension", [(u, v, z + 0.95), (u, v, z + 0.23)], 0.015, chrome
        )
        self.loft(
            "turned chandelier stem",
            u,
            v,
            z,
            [(0.1, 0.06, 0.06), (0.3, 0.10, 0.10), (0.46, 0.035, 0.035)],
            gem,
        )
        for a in range(6):
            t = 2 * pi * a / 6
            self.curve(
                "chandelier curved arm",
                [
                    (u + r * cos(t), v + r * sin(t), z + h)
                    for r, h in [
                        (0.02, 0.25),
                        (0.18, 0.03),
                        (0.32, 0.04),
                        (0.38, 0.18),
                        (0.38, 0.3),
                    ]
                ],
                0.012,
                chrome,
            )
            self.sphere(
                "chandelier candle",
                (u + 0.38 * cos(t), v + 0.38 * sin(t), z + 0.35),
                (0.022, 0.022, 0.06),
                warmled,
            )
            for j in range(5):
                tt = t + j * pi / 15
                self.sphere(
                    "cut crystal droplet",
                    (u + 0.33 * cos(tt), v + 0.33 * sin(tt), z + 0.09 - 0.025 * j),
                    (0.018, 0.018, 0.032),
                    gem,
                )

    def shoes(self, ornate=False):
        self.shell(wall=tan if ornate else ivory)
        for u in (-1.43, 1.43):
            for k in range(3):
                z = 0.23 + k * 0.40
                v = 0.16 + k * 0.42
                self.box(
                    "stepped display plinth",
                    (u, v, z / 2),
                    (1.46, 0.42, z),
                    ivory if not ornate else tan,
                    0.014,
                )
                self.box(
                    "display plinth cap",
                    (u, v, z + 0.014),
                    (1.47, 0.43, 0.027),
                    white,
                    0.008,
                )
                for j in range(4):
                    uu = u - 0.54 + j * 0.36
                    m = self.rng.choice(leathers)
                    if (j + k) % 3 == 0:
                        self.handbag(
                            uu, v + 0.045, z + 0.031, m, self.rng.uniform(0.8, 1.08)
                        )
                    else:
                        self.shoe(uu, v, z + 0.031, m, self.rng.uniform(-0.7, 0.7))
            self.text(
                "display base brand",
                self.spec["name"],
                (u, -0.058, 0.13),
                0.072,
                brass if ornate else tan,
            )
        # Display shelves along the side walls leave the middle as a real aisle.
        for u in (-2.06, 2.06):
            for k in range(5):
                z = 0.48 + k * 0.35
                self.box(
                    "floating side shelf", (u, 1.22, z), (0.34, 1.65, 0.045), white
                )
                self.curve(
                    "under shelf LED",
                    [(u, 0.45, z - 0.026), (u, 1.98, z - 0.026)],
                    0.006,
                    led,
                )
                for j in range(4):
                    self.shoe(
                        u, 0.63 + j * 0.35, z + 0.025, self.rng.choice(leathers), pi / 2
                    )
        self.box(
            "central sales island", (0, 1.34, 0.42), (0.95, 0.73, 0.80), ivory, 0.015
        )
        for u in (-0.32, 0, 0.32):
            self.handbag(u, 1.35, 0.83, self.rng.choice(leathers), 0.8)
        self.box(
            "wallpaper brand panel",
            (0, 2.004, 2.19),
            (1.12, 0.015, 1.17),
            tan if ornate else ivory,
            0,
        )
        self.text(
            "interior tenant wordmark",
            self.spec["name"].upper(),
            (0, 1.985, 2.17),
            0.105,
            frame,
        )
        # Individually drawn metallic scrolls echo the wallpaper without using photo pixels.
        for a in range(5):
            for b in range(6):
                u = -0.48 + a * 0.23
                z = 1.73 + b * 0.18
                self.curve(
                    "wallpaper damask curl",
                    [
                        (
                            u + 0.075 * (1 - t / (3 * pi)) * cos(t),
                            1.977,
                            z + 0.09 * sin(t),
                        )
                        for t in [i * 2.7 * pi / 30 for i in range(31)]
                    ],
                    0.002,
                    brass if ornate else tan,
                )
        self.chandelier()
        if not ornate and self.y > 0:
            self.text(
                "red window sale decal", "Sale", (-1.43, -0.129, 1.54), 0.43, red, False
            )
        self.light(
            (0, 1, 2.95),
            (0, 0.8, 0.4),
            170,
            (1, 0.78, 0.5) if ornate else (1, 0.94, 0.86),
            2.5,
        )

    def necklace_bust(self, u, v, z, scale=1, dark=False):
        m = black if dark else mannequin
        self.loft(
            "jewellery neck bust",
            u,
            v,
            z,
            [
                (0, 0.13 * scale, 0.075 * scale),
                (0.08 * scale, 0.15 * scale, 0.09 * scale),
                (0.25 * scale, 0.17 * scale, 0.073 * scale),
                (0.40 * scale, 0.07 * scale, 0.047 * scale),
                (0.47 * scale, 0.055 * scale, 0.047 * scale),
            ],
            m,
        )
        self.box(
            "necklace bust foot",
            (u, v, z + 0.012),
            (0.29 * scale, 0.18 * scale, 0.024),
            frame,
        )
        pts = []
        for i in range(33):
            t = pi * i / 32
            pts.append(
                (
                    u + 0.09 * scale * cos(t),
                    v - 0.084 * scale,
                    z + (0.36 - 0.17 * sin(t)) * scale,
                )
            )
        self.curve("displayed necklace", pts, 0.004 * scale, brass)
        for p in pts[::2]:
            self.sphere("pearl necklace bead", p, (0.009 * scale,) * 3, pearl)
        self.sphere(
            "necklace pendant",
            (u, v - 0.09 * scale, z + 0.17 * scale),
            (0.018 * scale, 0.009 * scale, 0.024 * scale),
            gem,
        )

    def jewellery(self, gs=False):
        self.shell(floor=ivory, wall=black if gs else tan)
        for u in (-1.42, 1.42):
            self.box(
                "projecting cabinet dark plinth",
                (u, 0.12, 0.17),
                (1.50, 0.66, 0.27),
                black,
                0.01,
            )
            for z in (0.49, 1.1):
                self.box(
                    "jewellery white presentation shelf",
                    (u, 0.17, z),
                    (1.42, 0.67, 0.038),
                    white,
                )
                for j, sc in enumerate((0.72, 1.08, 0.80)):
                    self.necklace_bust(
                        u - 0.46 + j * 0.45, 0.28, z + 0.027, sc, gs and j % 2 == 0
                    )
                for j in range(4):
                    uu = u - 0.52 + j * 0.34
                    self.box(
                        "ring presentation pad",
                        (uu, -0.012, z + 0.035),
                        (0.26, 0.22, 0.027),
                        black if j % 2 else ivory,
                        0.008,
                    )
                    for k in range(3):
                        p = (uu - 0.073 + k * 0.073, -0.03, z + 0.066)
                        self.curve(
                            "gold ring",
                            [
                                (p[0] + 0.016 * cos(t), p[1] + 0.016 * sin(t), p[2])
                                for t in [a * 2 * pi / 18 for a in range(18)]
                            ],
                            0.002,
                            brass,
                            True,
                        )
                        self.sphere(
                            "ring gemstone",
                            (p[0], p[1] - 0.014, p[2] + 0.007),
                            (0.007, 0.007, 0.008),
                            gem,
                        )
                self.curve(
                    "cabinet strip lighting",
                    [(u - 0.68, 0.42, z + 0.52), (u + 0.68, 0.42, z + 0.52)],
                    0.006,
                    led,
                )
            for uu in (u - 0.73, u + 0.73):
                self.box(
                    "cabinet gilt vertical",
                    (uu, -0.125, 1.1),
                    (0.019, 0.025, 2.0),
                    chrome if gs else brass,
                )
            self.box(
                "cabinet brand header",
                (u, -0.13, 2.05),
                (1.40, 0.03, 0.25),
                black if gs else brass,
            )
            self.text(
                "illuminated cabinet wordmark",
                "GS" if gs else "Volls",
                (u, -0.151, 2.06),
                0.15,
                led,
            )
        self.box(
            "interior glass counter base",
            (0, 1.53, 0.6),
            (3.3, 0.65, 0.83),
            black if gs else tan,
            0.014,
        )
        self.box(
            "interior glass counter lid", (0, 1.51, 1.07), (3.34, 0.69, 0.013), glass, 0
        )
        for u in (-1.35, -0.9, -0.45, 0, 0.45, 0.9, 1.35):
            self.box("interior ring tray", (u, 1.52, 1.0), (0.35, 0.42, 0.025), white)
        if gs:
            self.text(
                "gold window lettering", "imagination", (0, -0.14, 1.79), 0.30, brass
            )
            for i in range(40):
                u = -2 + i * 0.102
                self.curve(
                    "ceiling pin light fringe",
                    [(u, 0.60, 2.23), (u, 0.60, 1.98 + 0.08 * sin(i))],
                    0.004,
                    chrome,
                )
        else:
            for a in range(5):
                t = a * 2 * pi / 5
                self.sphere(
                    "Volls flower emblem",
                    (-0.5 + 0.08 * cos(t), -0.155, 2.07 + 0.08 * sin(t)),
                    (0.035, 0.008, 0.056),
                    led,
                )
        self.light((0, 0.9, 2.75), (0, 0.15, 0.8), 150, (0.9, 0.95, 1), 2.7)

    def dress(self, u, v, material_, long=False, head=True, skin=mannequin):
        self.cyl("mannequin display base", (u, v, 0.07), 0.23, 0.035, chrome)
        for a in (-1, 1):
            self.curve(
                "mannequin leg",
                [(u + a * 0.08, v, 0.13), (u + a * 0.095, v, 0.86)],
                0.043,
                skin,
            )
            self.sphere(
                "mannequin foot",
                (u + a * 0.08, v - 0.055, 0.13),
                (0.053, 0.12, 0.045),
                skin,
            )
        self.loft(
            "tailored dress with flared hem",
            u,
            v,
            0,
            [
                (0.16 if long else 0.66, 0.27 if long else 0.25, 0.19),
                (0.79, 0.21, 0.15),
                (0.94, 0.165, 0.12),
                (1.11, 0.135, 0.095),
                (1.29, 0.195, 0.125),
                (1.43, 0.20, 0.085),
                (1.46, 0.073, 0.075),
            ],
            material_,
        )
        for i in range(14):
            t = i * 2 * pi / 14
            self.curve(
                "dress seam and hem folds",
                [
                    (u + r * cos(t), v + r * 0.68 * sin(t), z)
                    for z, r in [
                        (1.06, 0.14),
                        (0.83, 0.20),
                        (0.17 if long else 0.67, 0.27 if long else 0.25),
                    ]
                ],
                0.002,
                material_,
            )
        self.cyl("mannequin neck", (u, v, 1.50), 0.043, 0.10, skin)
        if head:
            self.sphere(
                "display mannequin head", (u, v, 1.65), (0.092, 0.084, 0.125), skin
            )
            self.sphere(
                "mannequin nose", (u, v - 0.081, 1.655), (0.019, 0.022, 0.025), skin
            )
        for a in (-1, 1):
            self.curve(
                "mannequin articulated arm",
                [
                    (u + a * 0.205, v, 1.41),
                    (u + a * 0.25, v - 0.012, 1.15),
                    (u + a * 0.27, v - 0.08, 0.94),
                ],
                0.033,
                skin,
            )
            self.sphere(
                "mannequin hand",
                (u + a * 0.27, v - 0.08, 0.92),
                (0.033, 0.025, 0.065),
                skin,
            )

    def clothes_rail(self, u, v, width=1.2, material_=None):
        for a in (-1, 1):
            self.curve(
                "rack chrome upright",
                [(u + a * width / 2, v, 0.07), (u + a * width / 2, v, 1.72)],
                0.012,
                chrome,
            )
        self.curve(
            "clothing rail",
            [(u - width / 2, v, 1.71), (u + width / 2, v, 1.71)],
            0.014,
            chrome,
        )
        for i in range(10):
            uu = u - width * 0.44 + width * 0.88 * i / 9
            self.curve(
                "wooden clothes hanger",
                [
                    (uu, v, 1.72),
                    (uu, v - 0.13, 1.53),
                    (uu, v + 0.13, 1.53),
                    (uu, v, 1.72),
                ],
                0.009,
                oak,
            )
            self.box(
                "hanging garment",
                (uu, v, 0.99),
                (0.037, 0.30, 0.95),
                material_ or self.rng.choice(cloths),
                0.017,
            )

    def fashion(self):
        ident = self.spec["id"]
        george = ident == "george"
        tribeca = ident == "tribeca"
        blooms = ident == "blooms"
        self.shell(wall=oak if george else black if tribeca else ivory)
        for u in (-1.41, 1.42):
            self.box(
                "window mannequin stage",
                (u, 0.23, 0.087),
                (1.48, 0.78, 0.095),
                white if not tribeca else frame,
            )
        colors = (
            [printed, cloths[1], cloths[0], cloths[3]]
            if george
            else [cloths[3], cloths[0], cloths[1]]
            if tribeca
            else [cloths[2], printed, cloths[1], cloths[3]]
        )
        for j, u in enumerate((-1.83, -1.02, 1.01, 1.82)):
            self.dress(
                u,
                0.35,
                colors[j % len(colors)],
                long=george or tribeca,
                head=not tribeca,
            )
        for u in (-1.28, 1.28):
            self.clothes_rail(u, 1.55, 1.45, printed if blooms and u < 0 else None)
        if george:
            for i in range(24):
                self.box(
                    "vertical golden display slat",
                    (-0.57 + i * 0.05, 0.99, 1.45),
                    (0.018, 0.032, 2.75),
                    oak,
                )
        if tribeca:
            self.box(
                "dark central accessory table",
                (0, 1.03, 0.86),
                (0.93, 0.58, 0.05),
                frame,
            )
            self.handbag(0, 1.02, 0.90, leathers[3])
            for u in (-1.3, 1.3):
                self.sphere(
                    "perforated globe pendant",
                    (u, 1.23, 2.15),
                    (0.22, 0.22, 0.17),
                    frame,
                )
                for i in range(50):
                    t = i * 2.4
                    zz = -0.14 + 0.28 * (i + 0.5) / 50
                    rr = 0.22 * math.sqrt(max(0, 1 - (zz / 0.17) ** 2))
                    self.sphere(
                        "pendant perforation light",
                        (u + rr * cos(t), 1.23 + rr * sin(t), 2.15 + zz),
                        (0.006, 0.006, 0.006),
                        warmled,
                    )
        if blooms and self.y == 7.5:
            self.box(
                "red sale poster", (-0.91, -0.132, 1.6), (0.49, 0.008, 0.69), red, 0
            )
            self.text(
                "sale poster lettering",
                "up to\n50%\nOFF\nsale",
                (-0.91, -0.14, 1.61),
                0.122,
                white,
                False,
            )
        if blooms:
            self.text(
                "window tenant wordmark", "BLOOMS", (-1.37, -0.13, 2.13), 0.14, frame
            )
        self.light(
            (0, 1, 2.97),
            (0, 0.35, 0.6),
            190,
            (1, 0.83, 0.63) if george or tribeca else (0.91, 0.96, 1),
            2.8,
        )

    def knitwear(self):
        self.shell(floor=oak, wall=oak)
        # Tall honey timber pigeonholes filled with folded sweaters.
        for u in (-1.8, -1.2, -0.6, 0, 0.6, 1.2, 1.8):
            self.box("timber cubby divider", (u, 1.76, 1.32), (0.035, 0.47, 2.25), oak)
        for z in (0.24, 0.68, 1.12, 1.56, 2.0, 2.44):
            self.box("timber cubby shelf", (0, 1.76, z), (4.1, 0.5, 0.05), oak)
            if z > 2.1:
                continue
            for u in (-1.5, -0.9, -0.3, 0.3, 0.9, 1.5):
                for k in range(4):
                    self.box(
                        "folded cashmere sweater",
                        (u, 1.72, z + 0.05 + k * 0.052),
                        (0.48, 0.34, 0.047),
                        self.rng.choice(cloths),
                        0.020,
                    )
        for u, m in [(-1.40, cloths[1]), (1.42, cloths[5])]:
            self.dress(u, 0.26, m, False, True, darkmannequin)
            self.curve(
                "cashmere scarf drape",
                [(u - 0.10, 0.17, 1.43), (u, 0.14, 1.35), (u + 0.10, 0.12, 0.99)],
                0.045,
                m,
            )
        self.box("scarf table", (0, 0.85, 0.55), (1.05, 0.63, 0.12), white)
        for j in range(9):
            self.box(
                "hanging scarf",
                (-0.42 + j * 0.105, 0.55, 0.78),
                (0.074, 0.09, 0.91),
                cloths[j % len(cloths)],
                0.01,
            )
        self.light((0, 0.9, 2.9), (0, 0.8, 0.7), 170, (1, 0.78, 0.50), 2.4)

    def bottle(self, u, v, z, j):
        m = [white, sage, ivory, leathers[5]][j % 4]
        if j % 3:
            self.cyl("lotion bottle", (u, v, z + 0.071), 0.032, 0.14, m)
            self.cyl(
                "bottle screw cap",
                (u, v, z + 0.154),
                0.025,
                0.026,
                brass if j % 2 else white,
            )
            self.box(
                "bottle paper label",
                (u, v - 0.032, z + 0.074),
                (0.048, 0.003, 0.063),
                ivory,
                0,
            )
            self.text("bottle label", "C&E", (u, v - 0.035, z + 0.071), 0.014, blue)
        else:
            self.box(
                "botanical gift carton",
                (u, v, z + 0.10),
                (0.075, 0.065, 0.20),
                m,
                0.004,
            )
            self.box(
                "carton label", (u, v - 0.035, z + 0.1), (0.059, 0.003, 0.05), white, 0
            )

    def flowers(self, u, v, z):
        self.cyl("floral ceramic vase", (u, v, z + 0.13), 0.095, 0.25, ivory)
        for j in range(9):
            t = j * 2.4
            uu = u + 0.19 * cos(t)
            vv = v + 0.13 * sin(t)
            zz = z + 0.45 + 0.09 * sin(j)
            self.curve("floral stem", [(u, v, z + 0.14), (uu, vv, zz)], 0.003, sage)
            for k in range(5):
                a = k * 2 * pi / 5
                self.sphere(
                    "white flower petal",
                    (uu + 0.032 * cos(a), vv + 0.032 * sin(a), zz),
                    (0.035, 0.025, 0.014),
                    white,
                )

    def apothecary(self):
        self.shell(wall=ivory)
        for u in (-1.45, 1.45):
            self.box(
                "cream built in cabinet", (u, 1.75, 1.27), (1.28, 0.47, 2.33), ivory
            )
            self.box(
                "sage cabinet inset back",
                (u, 1.495, 1.50),
                (1.16, 0.018, 1.79),
                sage,
                0,
            )
            for k in range(5):
                z = 0.51 + k * 0.36
                self.box("apothecary shelf", (u, 1.43, z), (1.24, 0.43, 0.035), white)
                for j in range(11):
                    self.bottle(u - 0.53 + j * 0.105, 1.31, z + 0.019, j + k)
            self.box(
                "window merchandising table",
                (u, 0.20, 0.66),
                (1.40, 0.76, 0.065),
                ivory,
            )
            for j in range(12):
                self.bottle(u - 0.56 + (j % 6) * 0.22, 0.05 + (j // 6) * 0.28, 0.695, j)
        self.box("central till cabinet", (0, 1.62, 0.49), (0.88, 0.55, 0.9), ivory)
        self.flowers(-1.47, 0.49, 0.71)
        self.curve(
            "table lamp stem", [(1.44, 0.46, 0.70), (1.44, 0.46, 1.62)], 0.015, brass
        )
        self.loft(
            "sage tapered lampshade",
            1.44,
            0.46,
            1.42,
            [(0, 0.36, 0.25), (0.38, 0.27, 0.20)],
            sage,
        )
        self.sphere(
            "table lamp bulb", (1.44, 0.46, 1.56), (0.045, 0.045, 0.07), warmled
        )
        self.text(
            "Crabtree circular logo name",
            "CRABTREE\n& EVELYN",
            (0, 2.005, 2.08),
            0.115,
            blue,
        )
        self.curve(
            "Crabtree round logo border",
            [
                (0.43 * cos(t), 2.001, 2.13 + 0.43 * sin(t))
                for t in [i * 2 * pi / 70 for i in range(70)]
            ],
            0.009,
            blue,
            True,
        )
        self.curve(
            "Crabtree tree trunk", [(0, 1.998, 2.23), (0, 1.998, 2.44)], 0.014, blue
        )
        for i in range(7):
            t = i * pi / 6
            self.curve(
                "Crabtree tree branch",
                [(0, 1.998, 2.28), (0.15 * cos(t), 1.998, 2.29 + 0.14 * sin(t))],
                0.007,
                blue,
            )
        self.light((0, 1, 2.94), (0, 0.3, 0.75), 175, (0.96, 1, 0.96), 2.7)

    def cafe(self):
        self.shell(wall=tan)
        self.box(
            "red leather banquette seat",
            (1.36, 1.48, 0.43),
            (1.40, 0.65, 0.20),
            velvet,
            0.04,
        )
        self.box(
            "red leather banquette back",
            (1.36, 1.82, 0.86),
            (1.42, 0.17, 0.85),
            velvet,
            0.035,
        )
        self.box(
            "cake display counter base",
            (-1.20, 0.41, 0.39),
            (1.70, 0.86, 0.68),
            frame,
            0.02,
        )
        for z in (0.75, 1.04, 1.33):
            self.box(
                "cake cabinet glass shelf",
                (-1.20, 0.41, z),
                (1.66, 0.82, 0.012),
                glass,
                0,
            )
            for j in range(4):
                u = -1.80 + j * 0.40
                self.cyl("cake stand plate", (u, 0.4, z + 0.03), 0.15, 0.018, white)
                self.cyl(
                    "patisserie cake",
                    (u, 0.4, z + 0.095),
                    0.12,
                    0.11,
                    leathers[3] if j % 2 else velvet,
                )
                self.cyl("cake icing", (u, 0.4, z + 0.15), 0.12, 0.02, ivory)
        self.box(
            "cake cabinet front glass",
            (-1.20, -0.027, 1.04),
            (1.72, 0.009, 0.65),
            glass,
            0,
        )
        for u in (-2.08, -0.33):
            self.box(
                "cake cabinet edge", (u, -0.037, 1.02), (0.025, 0.025, 0.73), chrome
            )
        self.box(
            "espresso machine", (-0.43, 1.68, 1.13), (0.62, 0.40, 0.38), chrome, 0.05
        )
        for u in (-0.59, -0.30):
            self.curve(
                "espresso handle", [(u, 1.44, 1.09), (u, 1.29, 1.09)], 0.025, frame
            )
        for i in range(4):
            self.cyl(
                "stacked coffee cup", (-0.67 + i * 0.13, 1.7, 1.36), 0.044, 0.055, white
            )
        self.cyl("cafe table top", (1.26, 0.67, 0.78), 0.43, 0.04, ivory)
        self.cyl("cafe table pedestal", (1.26, 0.67, 0.4), 0.045, 0.73, brass)
        for u in (0.98, 1.52):
            self.cyl("table saucer", (u, 0.65, 0.815), 0.07, 0.009, white)
            self.cyl("porcelain coffee cup", (u, 0.65, 0.85), 0.045, 0.07, white)
        self.chandelier(0.75, 1, 2.23)
        for u in (-1.93, 1.93):
            for j in range(6):
                self.curve(
                    "burgundy curtain fold",
                    [(u + j * 0.037, 1.96, 0.91), (u + j * 0.037, 1.96, 3.1)],
                    0.028,
                    velvet,
                )
        self.light((0, 1, 2.95), (0, 0.5, 0.7), 160, (1, 0.77, 0.49), 2.5)


for spec in SHOPS:
    if STAGE not in ("all", spec["id"]):
        continue
    for y in spec["bays"]:
        s = Shop(spec, y)
        if spec["kind"] in ("shoes", "accessories"):
            s.shoes(spec["kind"] == "accessories")
        elif spec["kind"] == "jewellery":
            s.jewellery(spec["id"] == "gs-diamonds")
        elif spec["kind"] == "fashion":
            s.fashion()
        elif spec["kind"] == "knitwear":
            s.knitwear()
        elif spec["kind"] == "apothecary":
            s.apothecary()
        elif spec["kind"] == "cafe":
            s.cafe()
    print("SHOP_BUILT", spec["id"], flush=True)

if STAGE in ("finish", "all"):
    for o in list(coll.all_objects):
        if o.get("shop_furniture_support"):
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    table_names = (
        "dark central accessory table",
        "scarf table",
        "window merchandising table",
    )
    for table in list(coll.all_objects):
        if not any(n in table.name for n in table_names):
            continue
        height = table.location.z - table.dimensions.z / 2 - 0.06
        for sx in (-1, 1):
            for sy in (-1, 1):
                loc = (
                    table.location.x + sx * (table.dimensions.x / 2 - 0.06),
                    table.location.y + sy * (table.dimensions.y / 2 - 0.06),
                    0.06 + height / 2,
                )
                leg = box(
                    table.get("shop_id") + " · display table leg",
                    loc,
                    (0.035, 0.035, height),
                    ivory if table.get("shop_id") == "crabtree-evelyn" else chrome,
                    0.004,
                )
                for c in list(leg.users_collection):
                    c.objects.unlink(leg)
                table.users_collection[0].objects.link(leg)
                leg["shop_pass"] = 2
                leg["shop_id"] = table.get("shop_id")
                leg["level"] = 1
                leg["shop_furniture_support"] = True
    bpy.context.view_layer.update()
    assert outside_signature() == scene["shop_pass_unaffected_signature"], (
        "An object outside Level 1 shop fixtures changed"
    )
    counts = Counter(o.get("shop_id") for o in coll.all_objects)
    assert set(counts) == {s["id"] for s in SHOPS}, counts
    assert len(bpy.data.collections[ARCHIVE].objects) > 0
    for o in coll.all_objects:
        assert o.get("level") == 1
        if "closed toe vamp" in o.name:
            assert max(o.dimensions) < 0.18, (o.name, list(o.dimensions))
            assert abs(o.location.x) > 8, (o.name, list(o.location))
    if serif:
        # Convert lettering to mesh so the .blend does not redistribute the system font.
        bpy.ops.object.select_all(action="DESELECT")
        fonts = [o for o in coll.all_objects if o.type == "FONT"]
        if fonts:
            for o in fonts:
                o.select_set(True)
            bpy.context.view_layer.objects.active = fonts[0]
            bpy.ops.object.convert(target="MESH")
            bpy.ops.object.select_all(action="DESELECT")
        for data in list(bpy.data.curves):
            if (
                isinstance(data, bpy.types.TextCurve)
                and data.users == 0
                and data.font == serif
            ):
                bpy.data.curves.remove(data)
        if serif.users == 0:
            bpy.data.fonts.remove(serif)
    scene["shop_refinement_pass"] = 2
    scene["shop_reference_date"] = "January 2016"
    report = {
        "pass": 2,
        "reference_date": "January 2016",
        "shops": SHOPS,
        "objects_per_shop": dict(counts),
        "archived_placeholder_objects": len(bpy.data.collections[ARCHIVE].objects),
        "shoe_geometry_checked": sum(
            "closed toe vamp" in o.name for o in coll.all_objects
        ),
        "unaffected_scene_signature": outside_signature(),
        "notes": "Identities, relative order and display types follow saved Street View captures. Dimensions, individual products, hidden interiors and outer bay widths remain estimated.",
    }
    (ROOT / "shop-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "renders" / "shop-verification.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    bpy.ops.wm.save_as_mainfile(
        filepath=str(ROOT / "qvb-camera-scene.blend"), compress=True
    )
    print("SHOPS_VERIFIED_AND_SAVED", json.dumps(dict(counts)), flush=True)

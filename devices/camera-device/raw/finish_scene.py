"""Final architectural ornament. Apply once after refine_scene.py."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
ns = {"__file__": str(ROOT / "build_scene.py"), "QVB_STAGE": "helpers"}
exec(
    compile(
        (ROOT / "build_scene.py").read_text(), str(ROOT / "build_scene.py"), "exec"
    ),
    ns,
)
# Bind the helpers explicitly so static checks see the names used below.
beam = ns["beam"]
black = ns["black"]
blue = ns["blue"]
box = ns["box"]
bpy = ns["bpy"]
cos = ns["cos"]
cream = ns["cream"]
curve = ns["curve"]
cylinder = ns["cylinder"]
gold = ns["gold"]
iron = ns["iron"]
lightmat = ns["lightmat"]
material = ns["material"]
math = ns["math"]
noise_finish = ns["noise_finish"]
pi = ns["pi"]
red = ns["red"]
sin = ns["sin"]
sphere = ns["sphere"]

# Large glazed arches at the end of the upper gallery.
enamel = [
    material("End window glass " + str(i), c, 0.23, 0, 0.2, 0.35)
    for i, c in enumerate(
        [(0.21, 0.39, 0.43), (0.33, 0.52, 0.57), (0.61, 0.54, 0.32), (0.48, 0.59, 0.48)]
    )
]
for end in [-1, 1]:
    y = end * 21.72
    for x in [-5.8, 0, 5.8]:
        radius = 2.1
        for r in [2.14, 2.30, 2.4]:
            curve(
                "Upper end arch sandstone moulding",
                [
                    (x + r * cos(t), y, 5.7 + r * sin(t))
                    for t in [i * pi / 64 for i in range(65)]
                ],
                0.09,
                cream,
            )
        for side in [-1, 1]:
            box(
                "Upper end arch pilaster",
                (x + side * 2.29, y, 5.07),
                (0.24, 0.2, 1.3),
                cream,
                0.025,
            )
        for i in range(-7, 7):
            a = i * 0.29
            b = (i + 1) * 0.29
            for j in range(-4, 8):
                z0 = j * 0.29
                z1 = (j + 1) * 0.29
                top = min(z1, math.sqrt(max(0, radius**2 - max(a * a, b * b))))
                if top <= z0:
                    continue
                box(
                    "End window coloured glass",
                    (x + (a + b) / 2, y - end * 0.015, 5.7 + (z0 + top) / 2),
                    (0.276, 0.025, top - z0 - 0.014),
                    enamel[(i + j) % 4],
                )
        for i in range(-7, 8):
            xx = i * 0.29
            top = math.sqrt(max(0, radius**2 - xx**2))
            beam(
                "End window lead upright",
                (x + xx, y - end * 0.04, 4.5),
                (x + xx, y - end * 0.04, 5.7 + top),
                0.012,
                black,
            )
        for j in range(-4, 8):
            zz = j * 0.29
            half = math.sqrt(max(0, radius**2 - zz**2)) if zz > 0 else radius
            beam(
                "End window lead horizontal",
                (x - half, y - end * 0.04, 5.7 + zz),
                (x + half, y - end * 0.04, 5.7 + zz),
                0.012,
                black,
            )

# Dark lead bars clarify the shopfront square panes under the arches.
for z in [-4.4, 0, 4.3]:
    for side in [-1, 1]:
        x = side * 8.50
        for y in [-17.5, -12.5, -7.5, -2.5, 2.5, 7.5, 12.5, 17.5]:
            for dy in [-1.48, 0, 1.48]:
                for i in range(-3, 4):
                    v = i * 0.18
                    top = math.sqrt(0.7**2 - v * v)
                    beam(
                        "Shop transom lead upright",
                        (x, y + dy + v, z + 2.58),
                        (x, y + dy + v, z + 2.58 + top),
                        0.009,
                        black,
                    )
                for j in range(1, 4):
                    h = j * 0.18
                    half = math.sqrt(0.7**2 - h * h)
                    beam(
                        "Shop transom lead horizontal",
                        (x, y + dy - half, z + 2.58 + h),
                        (x, y + dy + half, z + 2.58 + h),
                        0.009,
                        black,
                    )

# Smaller scrolls and gently waved bars give the ironwork its dense historic pattern.
for o in list(bpy.data.objects):
    if not o.name.startswith("Gallery upright"):
        continue
    pts = o.data.splines[0].points
    x, y, z = pts[0].co[:3]
    curve(
        "Waved iron baluster",
        [(x + 0.065 * sin(k * pi / 5), y, z + 0.15 + k * 0.053) for k in range(15)],
        0.008,
        iron,
    )
    for zz in [0.28, 0.83]:
        curve(
            "Iron baluster ring",
            [
                (x + 0.055 * cos(t), y - 0.007, z + zz + 0.055 * sin(t))
                for t in [i * 2 * pi / 24 for i in range(24)]
            ],
            0.009,
            iron,
            True,
        )

# Neutral, faceless display mannequins in selected fashion bays.
mannequin = material("Shop mannequin ivory", (0.75, 0.69, 0.56), 0.42)
cloths = [
    material("Display garment " + str(i), c, 0.92)
    for i, c in enumerate(
        [(0.06, 0.075, 0.085), (0.34, 0.14, 0.095), (0.32, 0.29, 0.22)]
    )
]
for side, y in [(-1, 7.5), (-1, 12.5), (1, -7.5), (1, 17.5)]:
    x = side * 8.96
    for offset in [-0.45, 0.45]:
        yy = y + offset
        sphere("Mannequin head", (x, yy, 1.65), (0.1, 0.095, 0.13), mannequin)
        cylinder("Mannequin neck", (x, yy, 1.51), 0.041, 0.07, mannequin)
        sphere(
            "Mannequin clothed torso",
            (x, yy, 1.24),
            (0.14, 0.23, 0.27),
            cloths[int(offset > 0)],
        )
        for a in [-1, 1]:
            beam(
                "Mannequin leg",
                (x, yy + a * 0.09, 0.91),
                (x, yy + a * 0.11, 0.13),
                0.055,
                cloths[0],
            )
            beam(
                "Mannequin arm",
                (x, yy + a * 0.22, 1.42),
                (x - 0.03 * side, yy + a * 0.28, 0.99),
                0.041,
                mannequin,
            )
            sphere(
                "Mannequin shoe",
                (x - 0.055 * side, yy + a * 0.11, 0.075),
                (0.115, 0.059, 0.05),
                black,
            )

# Turned cream ceiling coffers and gentle surface variation.
for x in [-6, -3, 0, 3, 6]:
    for y in [-1.7, 1.7]:
        for yy in [-0.55, 0.55]:
            box(
                "Ceiling coffer moulding",
                (x, y + yy, 3.81),
                (2.65, 0.045, 0.055),
                cream,
                0.012,
            )
        for xx in [-1.32, 1.32]:
            box(
                "Ceiling coffer short moulding",
                (x + xx, y, 3.81),
                (0.045, 1.1, 0.055),
                cream,
                0.012,
            )
for m, color in [
    (cream, (0.69, 0.65, 0.51, 1)),
    (blue, (0.24, 0.36, 0.39, 1)),
    (red, (0.34, 0.065, 0.033, 1)),
]:
    n = m.node_tree.nodes
    links_or_link = m.node_tree.links
    p = n["Principled BSDF"]
    noise = n.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 8
    noise.inputs["Detail"].default_value = 4
    ramp = n.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = tuple(v * 0.82 for v in color[:3]) + (1,)
    ramp.color_ramp.elements[1].color = color
    links_or_link.new(noise.outputs["Fac"], ramp.inputs[0])
    links_or_link.new(ramp.outputs[0], p.inputs["Base Color"])
    noise_finish(m, 110, 0.08, 0.008)
lightmat.node_tree.nodes["Principled BSDF"].inputs[
    "Emission Strength"
].default_value = 0.65
gold.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.22
bpy.context.scene.cycles.samples = 128
bpy.context.scene.render.resolution_x = 1920
bpy.context.scene.render.resolution_y = 1200
bpy.context.scene.render.resolution_percentage = 100
bpy.context.scene.view_settings.exposure = -0.25
bpy.context.scene.render.filepath = "//renders/01-clock-atrium.png"
# Organise the file for model editing without obscuring object names.
collections = {
    name: bpy.data.collections.new(name)
    for name in [
        "01 Architecture",
        "02 Ironwork",
        "03 Retail",
        "04 Cafe",
        "05 Clock",
        "06 Lighting",
        "07 Camera rig",
    ]
}
for c in collections.values():
    bpy.context.scene.collection.children.link(c)
for o in list(bpy.context.scene.objects):
    n = o.name.lower()
    key = (
        "07 Camera rig"
        if "ptz" in n or o.type == "CAMERA"
        else "06 Lighting"
        if o.type == "LIGHT" or "pendant" in n or "downlight" in n
        else "05 Clock"
        if "clock" in n
        else "04 Cafe"
        if any(
            w in n
            for w in [
                "cafe",
                "chair",
                "bentwood",
                "coffee",
                "cup",
                "saucer",
                "menu",
                "napkin",
            ]
        )
        else "03 Retail"
        if any(
            w in n
            for w in [
                "shop",
                "retail",
                "bag",
                "mannequin",
                "display",
                "shelf",
                "transom",
                "pane",
                "leaded",
                "sign",
            ]
        )
        else "02 Ironwork"
        if any(
            w in n
            for w in [
                "iron",
                "gallery continuous",
                "gallery upright",
                "gallery wrought",
                "rail collar",
                "baluster",
            ]
        )
        else "01 Architecture"
    )
    for c in list(o.users_collection):
        c.objects.unlink(o)
    collections[key].objects.link(o)
for img in bpy.data.images:
    if img.source == "FILE":
        img.pack()
        img.filepath = "//textures/" + img.name
bpy.ops.wm.save_as_mainfile(
    filepath=str(ROOT / "qvb-camera-scene.blend"), compress=True
)
package_script = ROOT / "package_scene.py"
exec(
    compile(package_script.read_text(), str(package_script), "exec"),
    {"__file__": str(package_script)},
)
print("Final model saved", len(bpy.data.objects))

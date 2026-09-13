"""Apply material and architectural refinement after build_scene.py, once per build."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Import the helpers into this script's namespace without rebuilding the scene.
ns = {"__file__": str(ROOT / "build_scene.py"), "QVB_STAGE": "helpers"}
exec(
    compile(
        (ROOT / "build_scene.py").read_text(), str(ROOT / "build_scene.py"), "exec"
    ),
    ns,
)
# Bind the helpers explicitly so static checks see the names used below.
area = ns["area"]
beam = ns["beam"]
black = ns["black"]
blue = ns["blue"]
box = ns["box"]
bpy = ns["bpy"]
carpet = ns["carpet"]
carpetgold = ns["carpetgold"]
cos = ns["cos"]
cream = ns["cream"]
curve = ns["curve"]
cylinder = ns["cylinder"]
glass = ns["glass"]
gold = ns["gold"]
iron = ns["iron"]
json = ns["json"]
material = ns["material"]
mesh = ns["mesh"]
pi = ns["pi"]
random = ns["random"]
sin = ns["sin"]
sphere = ns["sphere"]
white = ns["white"]
wood = ns["wood"]

assets = ["american_walnut_veneer", "dirty_carpet", "brown_leather"]
texture_dir = ROOT / "textures"
texture_dir.mkdir(exist_ok=True)
for name in assets:
    m = bpy.data.materials.get(name)
    if m is None:
        m = material(name, (0.2, 0.15, 0.08))
        for suffix in ["Diffuse", "Rough", "Displacement"]:
            p = texture_dir / (name + "_" + suffix + ".jpg")
            if not p.exists():
                raise FileNotFoundError(
                    "Download the documented Poly Haven textures through Blender MCP first: "
                    + str(p)
                )
            n = m.node_tree.nodes.new("ShaderNodeTexImage")
            n.image = bpy.data.images.load(str(p), check_existing=True)
    nodes = m.node_tree.nodes
    links = m.node_tree.links
    p = nodes.get("Principled BSDF")
    coord = nodes.new("ShaderNodeTexCoord")
    scale = nodes.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    scale.inputs[3].default_value = 1.4 if name == "dirty_carpet" else 2
    links.new(coord.outputs["Object"], scale.inputs[0])
    for n in list(nodes):
        if n.type != "TEX_IMAGE":
            continue
        img = n.image
        target = texture_dir / img.name
        if not target.exists():
            if img.packed_file:
                target.write_bytes(img.packed_file.data)
            else:
                shutil.copyfile(bpy.path.abspath(img.filepath), target)
        img.filepath = str(target)
        n.projection = "BOX"
        n.projection_blend = 0.18
        links.new(scale.outputs[0], n.inputs["Vector"])
        if "_Diffuse" in img.name:
            tint = nodes.new("ShaderNodeMixRGB")
            tint.blend_type = "MULTIPLY"
            tint.inputs[0].default_value = 1
            tint.inputs[2].default_value = (
                (0.28, 0.23, 0.19, 1)
                if name == "dirty_carpet"
                else (0.42, 0.25, 0.14, 1)
                if name == "american_walnut_veneer"
                else (0.7, 0.55, 0.4, 1)
            )
            links.new(n.outputs["Color"], tint.inputs[1])
            links.new(tint.outputs[0], p.inputs["Base Color"])
        elif "_Rough" in img.name:
            img.colorspace_settings.name = "Non-Color"
            if name == "american_walnut_veneer":
                p.inputs["Roughness"].default_value = 0.24
            else:
                links.new(n.outputs["Color"], p.inputs["Roughness"])
        elif "_nor_gl" in img.name:
            img.colorspace_settings.name = "Non-Color"
            normal = nodes.new("ShaderNodeNormalMap")
            normal.space = "OBJECT"
            normal.inputs["Strength"].default_value = 0.18
            # Box projection needs a scalar bump map instead of tangent-space normals.
        elif "_Displacement" in img.name:
            img.colorspace_settings.name = "Non-Color"
            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.18
            bump.inputs["Distance"].default_value = 0.013
            links.new(n.outputs[0], bump.inputs["Height"])
            links.new(bump.outputs[0], p.inputs["Normal"])
    if name == "american_walnut_veneer":
        for links_or_link in list(links):
            if (
                links_or_link.to_node == p
                and links_or_link.to_socket.name == "Roughness"
            ):
                links.remove(links_or_link)
        p.inputs["Roughness"].default_value = 0.25
        p.inputs["Coat Weight"].default_value = 0.3

walnut = bpy.data.materials["american_walnut_veneer"]
carpet_scan = bpy.data.materials["dirty_carpet"]
leather = bpy.data.materials["brown_leather"]
for o in bpy.data.objects:
    if o.type in ["MESH", "CURVE"]:
        for slot in o.material_slots:
            if slot.material == wood:
                slot.material = walnut
            elif slot.material == carpet:
                slot.material = carpet_scan
        if o.name.startswith("Leather handbag") and random.random() < 0.55:
            o.data.materials[0] = leather
    if o.name.startswith("Woven carpet scroll"):
        o.hide_render = True
        o.hide_viewport = True

# Richer flowing scrolls and acanthus leaves instead of the provisional repeat.
for side in [-1, 1]:
    for i in range(23):
        x = side * 7.45
        y = -22 + i * 2
        for sign in [-1, 1]:
            for off in [0, 0.05, 0.10]:
                pts = []
                for q in range(100):
                    t = q / 99 * 3.2 * pi
                    r = 0.62 * (1 - q / 116) + off
                    pts.append(
                        (x + sign * (0.05 + r * cos(t)), y + 1.3 * r * sin(t), 0.023)
                    )
                curve("Carpet flowing acanthus stem", pts, 0.009, carpetgold)
            # Tapered leaves follow the outer curling stem, lying flush with the weave.
            for k in range(15):
                t = k / 14 * 2.1 * pi
                r = 0.63 * (1 - k / 20)
                xx = x + sign * (0.05 + r * cos(t))
                yy = y + 1.3 * r * sin(t)
                theta = t + pi / 2
                length = 0.16 + 0.05 * sin(t)
                width = 0.033
                v = [(xx, yy, 0.024)]
                for q in range(13):
                    a = q / 12
                    vx = length * a
                    vy = width * sin(pi * a)
                    v.append(
                        (
                            xx + sign * (vx * cos(theta) - vy * sin(theta)),
                            yy + vx * sin(theta) + vy * cos(theta),
                            0.024,
                        )
                    )
                for q in range(12, -1, -1):
                    a = q / 12
                    vx = length * a
                    vy = -width * sin(pi * a)
                    v.append(
                        (
                            xx + sign * (vx * cos(theta) - vy * sin(theta)),
                            yy + vx * sin(theta) + vy * cos(theta),
                            0.024,
                        )
                    )
                mesh(
                    "Carpet woven acanthus leaf", v, [tuple(range(len(v)))], carpetgold
                )

# Fascia is ivory on its vertical face; the carpet covers only the walking surface.
o = bpy.data.objects["Level 1 fitted carpet"]
o.data.materials.append(cream)
for f in o.data.polygons:
    if f.normal.z < 0.8:
        f.material_index = 1

# Ornament around the entire atrium, spaced uniformly on the long edges.
for z in [0, 4.3]:
    for side in [-1, 1]:
        for cy in [-11.7, 11.7]:
            x = side * 4.84
            for i in range(22):
                y = cy - 6.4 + i * 0.61
                curve(
                    "Ivory fascia inset scallop",
                    [
                        (x, y + 0.235 * cos(t), z - 0.31 + 0.18 * sin(t))
                        for t in [j * pi / 24 for j in range(25)]
                    ],
                    0.025,
                    cream,
                )
                for yy in [y - 0.25, y + 0.25]:
                    beam(
                        "Fascia raised pilaster",
                        (x, yy, z - 0.32),
                        (x, yy, z - 0.08),
                        0.022,
                        cream,
                    )
    for side in [-1, 1]:
        for y in range(-20, 21, 5):
            # Fluted pier insets and abacus beads catch grazed light.
            for dy in [-0.15, -0.075, 0, 0.075, 0.15]:
                beam(
                    "Pier fluted face",
                    (side * 8.345, y + dy, z + 0.5),
                    (side * 8.345, y + dy, z + 2.7),
                    0.012,
                    cream,
                )
            for q in range(7):
                sphere(
                    "Capital egg moulding",
                    (side * 8.21, y - 0.37 + q * 0.12, z + 3.42),
                    (0.055, 0.05, 0.064),
                    cream,
                )

# Close the sight lines beyond end arches with further lit gallery space.
for end in [-1, 1]:
    y = end * 26
    box("Gallery continuation floor", (0, y, -0.22), (19, 8, 0.44), cream)
    box("Gallery continuation carpet", (0, y, 0.01), (19, 8, 0.035), carpet_scan)
    box("Gallery continuation ceiling", (0, y, 4.07), (19, 8, 0.44), cream)
    box("Gallery continuation back wall", (0, end * 30, 1.8), (19, 0.25, 3.6), blue)
    for x in [-6, -2, 2, 6]:
        box("Distant shop glazing", (x, end * 29.6, 1.5), (3, 0.02, 2.9), glass)
        for zz in [0.6, 1.4, 2.2]:
            box(
                "Distant retail shelf",
                (x, end * 29.4, zz),
                (2.8, 0.5, 0.09),
                white,
                0.012,
            )
            for k in range(7):
                box(
                    "Distant retail merchandise",
                    (x - 1.1 + k * 0.36, end * 29.25, zz + 0.16),
                    (0.22, 0.2, 0.25),
                    random.choice([gold, black, white, leather]),
                    0.035,
                )
        area(
            "Beyond arch shop illumination",
            (x, end * 28.2, 3.2),
            120,
            (1, 0.78, 0.5),
            2,
            (x, end * 29, 1),
        )
    # Lower concourse repeats tiled details, benches and planters.
    box("Lower end closure", (0, end * 26, -2.2), (21, 0.3, 4.4), cream)
for x in range(-10, 11):
    beam("Lower stone floor grout", (x, -26, -4.385), (x, 26, -4.385), 0.009, black)
for y in range(-25, 26):
    beam("Lower cross floor grout", (-11, y, -4.385), (11, y, -4.385), 0.009, black)
for side in [-1, 1]:
    for y in [-17, -7, 7, 17]:
        box(
            "Lower concourse timber bench",
            (side * 3, y, -3.95),
            (0.7, 2.2, 0.12),
            walnut,
            0.04,
        )
        for yy in [-0.75, 0.75]:
            box(
                "Bench stone support",
                (side * 3, y + yy, -4.17),
                (0.5, 0.18, 0.42),
                cream,
                0.02,
            )

# Clock decorative lower pavilion and enamel miniature landscape panels.
for z, r, mat in [
    (2.9, 1.16, gold),
    (3.89, 1.22, gold),
    (4.95, 1.4, gold),
    (5.9, 1.46, gold),
]:
    curve(
        "Clock turned gilded rim",
        [
            (r * cos(t), 14.2 + r * sin(t), z)
            for t in [i * 2 * pi / 96 for i in range(96)]
        ],
        0.038,
        mat,
        True,
    )
for a in range(8):
    t = a * pi / 4
    for zz in [3, 3.75, 4.2, 6.05]:
        sphere(
            "Clock corner gold rosette",
            (1.11 * cos(t), 14.2 + 1.11 * sin(t), zz),
            (0.09, 0.09, 0.09),
            gold,
        )
    cylinder(
        "Clock lower pavilion column",
        (0.67 * cos(t), 14.2 + 0.67 * sin(t), 2.42),
        0.045,
        0.73,
        gold,
    )
    sphere(
        "Clock lower arch ornament",
        (0.67 * cos(t), 14.2 + 0.67 * sin(t), 2.67),
        (0.1, 0.1, 0.1),
        gold,
    )
    # Architectural painted scene, mountains and cloud relief.
    x = 1.30 * cos(t)
    y = 14.2 + 1.30 * sin(t)
    sphere("Clock landscape enamel panel", (x, y, 5.43), (0.28, 0.12, 0.30), blue)
    for j in range(4):
        sphere(
            "Clock landscape relief",
            (x + 0.1 * cos(j), y + 0.07 * sin(j), 5.25 + j * 0.05),
            (0.10, 0.07, 0.07),
            cream,
        )
for z, r, d in [(2.03, 0.82, 0.16), (1.88, 0.57, 0.2), (1.67, 0.35, 0.22)]:
    cylinder("Clock lower finial tier", (0, 14.2, z), r, d, gold, 8)
sphere("Clock bottom finial", (0, 14.2, 1.46), (0.18, 0.18, 0.23), gold)

# Improve physical roughness and contrast under daylight and warm luminaires.
for name in ["Warm lamp diffuser"]:
    bpy.data.materials[name].node_tree.nodes["Principled BSDF"].inputs[
        "Emission Strength"
    ].default_value = 0.65
for o in bpy.data.objects:
    if o.type == "LIGHT" and o.name.startswith("Skylight soft"):
        o.data.energy = 2400
    if o.type == "LIGHT" and o.name.startswith("Retail warm"):
        o.data.energy = 115
gold.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.22
iron.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.29
bpy.context.scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.18
bpy.context.scene.view_settings.exposure = -0.25

# Correct mount to the bridge edge estimated from the roof and reverse references.
bpy.data.objects["PTZ_Mount"].location = (3.4, 2.7, 3.55)
for name in ["PTZ ivory ceiling mount", "PTZ smoked dome"]:
    o = bpy.data.objects[name]
    o.location.x = 3.4
    o.location.y = 2.7
bpy.data.objects["PTZ_Mount"]["pan_degrees"] = -16.0
bpy.data.objects["PTZ_Mount"]["tilt_degrees"] = 10.0
bpy.data.objects["camera-device"].data.lens = 20
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
bpy.context.scene.cycles.samples = 96
bpy.context.scene.render.resolution_percentage = 100
bpy.context.view_layer.update()
for img in bpy.data.images:
    if img.source == "FILE":
        img.pack()
bpy.ops.wm.save_as_mainfile(
    filepath=str(ROOT / "qvb-camera-scene.blend"), compress=True
)
print("Refinement saved", len(bpy.data.objects))

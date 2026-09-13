"""Build a reusable clothed-person library through Blender MCP.

Run this script inside the existing QVB scene. The master .blend is never saved;
the result is qvb-camera-series.blend with a separate transparent atlas scene.
"""

import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
MASTER = ROOT / "qvb-camera-scene.blend"
master_sha = hashlib.sha256(MASTER.read_bytes()).hexdigest()
qvb = bpy.context.scene
qvb.name = "QVB Camera Series"
qvb["series_source_sha256"] = master_sha
qvb["series_method"] = (
    "Depth-composited Blender people in shared hourly world positions"
)

old = bpy.data.scenes.get("Series People Atlas")
if old:
    bpy.data.scenes.remove(old)
atlas = bpy.data.scenes.new("Series People Atlas")
atlas.render.engine = "CYCLES"
atlas.cycles.samples = 12
atlas.cycles.use_denoising = True
atlas.render.film_transparent = True
atlas.render.resolution_x = 640
atlas.render.resolution_y = 3840
atlas.render.resolution_percentage = 100
atlas.render.image_settings.file_format = "PNG"
atlas.render.image_settings.color_mode = "RGBA"
atlas.view_settings.view_transform = "AgX"
atlas.world = bpy.data.worlds.new("Series soft daylight")
atlas.world.use_nodes = True
atlas.world.node_tree.nodes["Background"].inputs[0].default_value = (0.8, 0.85, 1, 1)
atlas.world.node_tree.nodes["Background"].inputs[1].default_value = 0.65


def mat(name, color):
    result = bpy.data.materials.new("Series " + name)
    result.diffuse_color = (*color, 1)
    result.use_nodes = True
    shader = result.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = 0.82
    return result


skins = [
    mat("skin " + str(i), c)
    for i, c in enumerate(
        [
            (0.62, 0.34, 0.20),
            (0.88, 0.62, 0.43),
            (0.31, 0.14, 0.073),
            (0.48, 0.24, 0.12),
            (0.77, 0.49, 0.31),
            (0.91, 0.70, 0.55),
        ]
    )
]
shirts = [
    mat("shirt " + str(i), c)
    for i, c in enumerate(
        [
            (0.035, 0.07, 0.12),
            (0.72, 0.035, 0.022),
            (0.68, 0.62, 0.47),
            (0.018, 0.23, 0.24),
            (0.88, 0.87, 0.78),
            (0.08, 0.15, 0.035),
            (0.27, 0.025, 0.19),
            (0.10, 0.22, 0.40),
            (0.53, 0.24, 0.018),
            (0.11, 0.10, 0.095),
            (0.50, 0.25, 0.29),
            (0.19, 0.32, 0.25),
        ]
    )
]
pants = [
    mat("trousers " + str(i), c)
    for i, c in enumerate(
        [
            (0.025, 0.029, 0.036),
            (0.037, 0.081, 0.15),
            (0.24, 0.17, 0.105),
            (0.44, 0.40, 0.31),
        ]
    )
]
hair = [
    mat("hair " + str(i), c)
    for i, c in enumerate(
        [
            (0.017, 0.011, 0.006),
            (0.09, 0.037, 0.012),
            (0.37, 0.21, 0.057),
            (0.30, 0.30, 0.29),
        ]
    )
]
shoe = mat("leather shoes", (0.025, 0.021, 0.017))
sole = mat("shoe sole", (0.32, 0.32, 0.30))
eye = mat("eyes", (0.023, 0.014, 0.008))
bag = mat("tan leather bag", (0.28, 0.12, 0.036))


def person_mesh(identity):
    """Joined, smooth clothed geometry; walking poses vary by identity."""
    vertices, faces, indices = [], [], []
    materials = [
        skins[identity % 6],
        shirts[identity % 12],
        pants[(identity // 3) % 4],
        hair[(identity // 2) % 4],
        shoe,
        sole,
        eye,
        bag,
    ]

    def ellipsoid(center, radii, mi, rotation=None, segments=12, rings=8):
        first = len(vertices)
        for j in range(rings + 1):
            theta = math.pi * j / rings
            for k in range(segments):
                phi = math.tau * k / segments
                v = Vector(
                    (
                        radii[0] * math.sin(theta) * math.cos(phi),
                        radii[1] * math.sin(theta) * math.sin(phi),
                        radii[2] * math.cos(theta),
                    )
                )
                vertices.append(
                    tuple((rotation @ v if rotation else v) + Vector(center))
                )
        for j in range(rings):
            for k in range(segments):
                faces.append(
                    (
                        first + j * segments + k,
                        first + j * segments + (k + 1) % segments,
                        first + (j + 1) * segments + (k + 1) % segments,
                        first + (j + 1) * segments + k,
                    )
                )
                indices.append(mi)

    def limb(a, b, width, depth, mi):
        va, vb = Vector(a), Vector(b)
        rotation = (vb - va).to_track_quat("Z", "Y").to_matrix()
        ellipsoid(
            (va + vb) / 2,
            (width, depth, (vb - va).length / 2 + width * 0.35),
            mi,
            rotation,
        )

    female = identity % 3 == 0
    step = [-0.17, 0, 0.18, 0.10][identity % 4]
    torso_w = 0.176 if female else 0.197
    # Tailored shirt or coat, with a narrower waist and distinct hem/shoulders.
    first = len(vertices)
    sections = [
        (0.91, 0.153, 0.10),
        (1.02, 0.149, 0.099),
        (1.18, torso_w * 0.88, 0.107),
        (1.36, torso_w, 0.115),
        (1.43, torso_w * 0.82, 0.096),
    ]
    for z, rx, ry in sections:
        for k in range(16):
            a = math.tau * k / 16
            vertices.append((rx * math.cos(a), ry * math.sin(a), z))
    for j in range(4):
        for k in range(16):
            faces.append(
                (
                    first + j * 16 + k,
                    first + j * 16 + (k + 1) % 16,
                    first + (j + 1) * 16 + (k + 1) % 16,
                    first + (j + 1) * 16 + k,
                )
            )
            indices.append(1)
    faces.extend(
        [
            tuple(first + k for k in reversed(range(16))),
            tuple(first + 64 + k for k in range(16)),
        ]
    )
    indices.extend([1, 1])
    ellipsoid((0, 0, 0.9), (0.16, 0.106, 0.125), 2)
    for side in [-1, 1]:
        stride = side * step
        hip = (side * 0.092, 0, 0.91)
        knee = (side * 0.105, stride, 0.51)
        ankle = (side * 0.105, -stride, 0.105)
        limb(hip, knee, 0.080, 0.090, 2)
        limb(knee, ankle, 0.059, 0.067, 2)
        ellipsoid((side * 0.105, -stride - 0.065, 0.07), (0.073, 0.15, 0.065), 4)
        ellipsoid((side * 0.105, -stride - 0.069, 0.027), (0.075, 0.15, 0.021), 5)
        shoulder = (side * (torso_w - 0.01), 0, 1.36)
        elbow = (side * 0.244, -side * step * 0.75, 1.09)
        wrist = (side * 0.235, side * step * 0.7, 0.87)
        limb(shoulder, elbow, 0.066, 0.07, 1)
        limb(elbow, wrist, 0.043, 0.049, 0 if identity % 4 == 0 else 1)
        ellipsoid(wrist, (0.04, 0.033, 0.063), 0)
    limb((0, 0, 1.4), (0, 0, 1.51), 0.064, 0.061, 0)
    ellipsoid((0, -0.005, 1.625), (0.107, 0.094, 0.138), 0)
    ellipsoid((0, 0.016, 1.704), (0.109, 0.09, 0.071), 3)
    if identity % 3 == 0:
        ellipsoid((0, 0.075, 1.57), (0.108, 0.053, 0.15), 3)
    if identity % 5 == 0:
        ellipsoid((0, 0.14, 1.61), (0.057, 0.07, 0.068), 3)
    ellipsoid((0, -0.097, 1.619), (0.021, 0.027, 0.028), 0)
    for side in [-1, 1]:
        ellipsoid(
            (side * 0.042, -0.093, 1.65), (0.009, 0.006, 0.007), 6, segments=8, rings=4
        )
        ellipsoid((side * 0.106, 0, 1.623), (0.018, 0.023, 0.035), 0)
    if identity % 4 == 1:
        ellipsoid((0.26, 0.02, 0.77), (0.105, 0.07, 0.145), 7)
        limb((0.22, 0, 0.99), (0.28, 0, 0.88), 0.012, 0.012, 7)
    if identity % 4 == 2:
        ellipsoid((0, 0.135, 1.17), (0.135, 0.095, 0.20), 7)
        for side in [-1, 1]:
            limb(
                (side * 0.125, -0.063, 1.4), (side * 0.13, -0.107, 1.1), 0.013, 0.012, 7
            )
    mesh = bpy.data.meshes.new("Series clothed person %02d" % identity)
    mesh.from_pydata(vertices, [], faces)
    for m in materials:
        mesh.materials.append(m)
    for polygon, mi in zip(mesh.polygons, indices):
        polygon.material_index = mi
        polygon.use_smooth = True
    mesh.update()
    return mesh


for identity in range(24):
    geometry = person_mesh(identity)
    for direction in range(8):
        ob = bpy.data.objects.new(
            "Series person %02d yaw %d" % (identity, direction * 45), geometry
        )
        atlas.collection.objects.link(ob)
        ob.location = ((direction - 3.5) * 1.2, 0, (23 - identity) * 2.4 + 0.18)
        ob.rotation_euler[2] = math.radians(direction * 45)
        ob["identity"] = identity
        ob["direction"] = direction
camera = bpy.data.objects.new(
    "Series Atlas Camera", bpy.data.cameras.new("Series Atlas Camera")
)
atlas.collection.objects.link(camera)
camera.location = (0, -40, 28.8)
camera.rotation_euler = (math.pi / 2, 0, 0)
camera.data.type = "ORTHO"
camera.data.ortho_scale = 57.6
atlas.camera = camera
sun = bpy.data.objects.new(
    "Series soft key", bpy.data.lights.new("Series soft key", "SUN")
)
sun.data.energy = 1.8
sun.data.angle = 0.35
sun.rotation_euler = (math.radians(28), math.radians(-20), math.radians(-25))
atlas.collection.objects.link(sun)
atlas["cell_width_px"] = 80
atlas["cell_height_px"] = 160
atlas["cell_width_m"] = 1.2
atlas["cell_height_m"] = 2.4
atlas["foot_height_in_cell_m"] = 0.18
atlas["identity_count"] = 24
atlas["yaw_count"] = 8
bpy.context.window.scene = qvb
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "qvb-camera-series.blend"))
assert hashlib.sha256(MASTER.read_bytes()).hexdigest() == master_sha
(ROOT / "series-assets.json").write_text(
    json.dumps(
        {
            "master_sha256": master_sha,
            "blend": "qvb-camera-series.blend",
            "identity_count": 24,
            "yaw_count": 8,
            "elevation_degrees": [0, 20, 40, 60],
            "cell_pixels": [80, 160],
            "cell_metres": [1.2, 2.4],
            "foot_height_in_cell_metres": 0.18,
        },
        indent=2,
    )
    + "\n"
)
print("SERIES_BUILT", len(atlas.objects), master_sha, flush=True)

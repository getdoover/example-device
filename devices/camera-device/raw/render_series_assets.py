"""Render static QVB lighting/depth and a small Blender people atlas once."""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "series-cache"
OUT.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument("--backgrounds-only", action="store_true")
parser.add_argument("--atlases-only", action="store_true")
args = parser.parse_args(
    sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
)
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.refresh_devices()
gpu = any(d.type == "METAL" for d in prefs.devices)
for d in prefs.devices:
    d.use = d.type == "METAL" if gpu else d.type == "CPU"
qvb = bpy.data.scenes["QVB Camera Series"]
camera = bpy.data.objects["camera-device"]
mount = bpy.data.objects["PTZ_Mount"]
presets = json.loads((ROOT / "camera-presets.json").read_text())["presets"]
started = time.monotonic()
records = []

if not args.atlases_only:
    scene = qvb
    bpy.context.window.scene = scene
    scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if gpu else "CPU"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.cycles.use_light_tree = True
    scene.render.use_persistent_data = True
    scene.render.resolution_x = 640
    scene.render.resolution_y = 400
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_layers[0].use_pass_z = True
    group = bpy.data.node_groups.new("Series static depth", "CompositorNodeTree")
    group.interface.new_socket(
        name="Image", in_out="OUTPUT", socket_type="NodeSocketColor"
    )
    layers = group.nodes.new("CompositorNodeRLayers")
    layers.scene = scene
    output = group.nodes.new("NodeGroupOutput")
    group.links.new(layers.outputs["Image"], output.inputs["Image"])
    depth_output = group.nodes.new("CompositorNodeOutputFile")
    depth_output.format.file_format = "OPEN_EXR_MULTILAYER"
    depth_output.format.color_depth = "32"
    depth_output.directory = str(OUT)
    depth_output.file_output_items.new("FLOAT", "depth")
    group.links.new(layers.outputs["Depth"], depth_output.inputs[0])
    scene.compositing_node_group = group
    lights = [
        (o.data, float(o.data.energy), o.name)
        for o in scene.objects
        if o.type == "LIGHT"
    ]
    world = scene.world.node_tree.nodes["Background"]
    world_base = float(world.inputs[1].default_value)
    views = {}
    depth_checks = []
    for lighting, sky, retail, exposure in [
        ("day", 1, 1, -0.25),
        ("dusk", 0.20, 0.82, -0.45),
        ("night", 0.005, 0.32, -1.0),
    ]:
        for data, energy, name in lights:
            data.energy = energy * (sky if name.startswith("Skylight soft") else retail)
        world.inputs[1].default_value = world_base * sky
        scene.view_settings.exposure = exposure
        for p in presets:
            mount["pan_degrees"] = float(p["pan"])
            mount["tilt_degrees"] = float(p["tilt"])
            camera.data.lens = p["lens"]
            mount.update_tag()
            scene.frame_set(scene.frame_current)
            bpy.context.view_layer.update()
            name = p["name"]
            depth_output.mute = lighting != "day"
            depth_output.file_name = name + "-depth"
            scene.render.filepath = str(OUT / (name + "-" + lighting + ".png"))
            before = time.monotonic()
            bpy.ops.render.render(write_still=True)
            records.append(
                dict(
                    kind="background",
                    preset=name,
                    lighting=lighting,
                    seconds=round(time.monotonic() - before, 3),
                )
            )
            if lighting == "day":
                deps = bpy.context.evaluated_depsgraph_get()
                evaluated = camera.evaluated_get(deps)
                projection = camera.calc_matrix_camera(
                    deps, x=640, y=400, scale_x=1, scale_y=1
                )
                views[name] = dict(
                    p,
                    matrix_world=[list(row) for row in evaluated.matrix_world],
                    projection=[list(row) for row in projection],
                    resolution=[640, 400],
                )
                files = list(OUT.glob(name + "-depth*.exr"))
                assert len(files) == 1, files
                # Independent geometry evidence for Z-pass conversion/occlusion.
                world_matrix = evaluated.matrix_world
                origin = world_matrix.translation
                for x, y in [(320, 300), (180, 340), (460, 280), (320, 220)]:
                    direction = (
                        world_matrix.to_3x3()
                        @ Vector(
                            (
                                (2 * (x + 0.5) / 640 - 1) / projection[0][0],
                                (1 - 2 * (y + 0.5) / 400) / projection[1][1],
                                -1,
                            )
                        )
                    ).normalized()
                    hit, location, _, _, ob, _ = scene.ray_cast(
                        deps, origin + direction * 0.25, direction
                    )
                    assert hit, (name, x, y)
                    depth_checks.append(
                        dict(
                            preset=name,
                            pixel=[x, y],
                            hit=hit,
                            distance=(location - origin).length,
                            object=ob.name,
                        )
                    )
            print("ASSET_DONE", records[-1], flush=True)
    (OUT / "cameras.json").write_text(json.dumps(views, indent=2) + "\n")
    (OUT / "depth-ray-check.json").write_text(json.dumps(depth_checks, indent=2) + "\n")

if not args.backgrounds_only:
    scene = bpy.data.scenes["Series People Atlas"]
    bpy.context.window.scene = scene
    scene.cycles.device = "GPU" if gpu else "CPU"
    scene.render.use_persistent_data = True
    for elevation in [0, 20, 40, 60]:
        for ob in scene.objects:
            if "identity" in ob:
                ob.rotation_euler = (
                    Matrix.Rotation(math.radians(elevation), 4, "X")
                    @ Matrix.Rotation(math.radians(ob["direction"] * 45), 4, "Z")
                ).to_euler()
        scene.render.filepath = str(OUT / ("people-elevation-%02d.png" % elevation))
        before = time.monotonic()
        bpy.ops.render.render(write_still=True)
        records.append(
            dict(
                kind="people-atlas",
                elevation=elevation,
                seconds=round(time.monotonic() - before, 3),
            )
        )
        print("ASSET_DONE", records[-1], flush=True)

(OUT / "render-benchmark.json").write_text(
    json.dumps(
        dict(seconds=round(time.monotonic() - started, 3), gpu=gpu, renders=records),
        indent=2,
    )
    + "\n"
)
print("SERIES_ASSETS_READY", round(time.monotonic() - started, 3), flush=True)

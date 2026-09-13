"""Render PTZ presets from the saved .blend, without regenerating geometry.

blender --background qvb-camera-scene.blend --python render_views.py
Append -- --preset 01-clock-atrium to render one preset.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--preset")
parser.add_argument("--samples", type=int, default=128)
args = parser.parse_args(
    sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
)
data = json.loads((ROOT / "camera-presets.json").read_text())
presets = [
    p for p in data["presets"] if args.preset is None or p["name"] == args.preset
]
if not presets:
    raise ValueError("Unknown preset: " + str(args.preset))
scene = bpy.context.scene
camera = bpy.data.objects["camera-device"]
mount = bpy.data.objects["PTZ_Mount"]
scene.camera = camera
scene.render.engine = "CYCLES"
scene.cycles.samples = args.samples
scene.cycles.use_denoising = True
scene.render.resolution_x = 1920
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.refresh_devices()
gpus = [d for d in prefs.devices if d.type == "METAL"]
if gpus:
    scene.cycles.device = "GPU"
    for d in prefs.devices:
        d.use = d.type == "METAL"
else:
    scene.cycles.device = "CPU"
output = ROOT / "renders"
output.mkdir(exist_ok=True)
results = []
for preset in presets:
    mount["pan_degrees"] = float(preset["pan"])
    mount["tilt_degrees"] = float(preset["tilt"])
    camera.data.lens = preset["lens"]
    mount.update_tag()
    scene.frame_set(scene.frame_current)
    bpy.context.view_layer.update()
    evaluated = camera.evaluated_get(bpy.context.evaluated_depsgraph_get())
    direction = evaluated.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    pan = math.radians(preset["pan"])
    tilt = math.radians(preset["tilt"])
    expected = Vector(
        (
            math.sin(pan) * math.cos(tilt),
            math.cos(pan) * math.cos(tilt),
            -math.sin(tilt),
        )
    )
    assert (direction - expected).length < 1e-5, (preset, direction[:], expected[:])
    path = output / (preset["name"] + ".png")
    scene.render.filepath = str(path)
    print("RENDER_START", preset["name"], flush=True)
    bpy.ops.render.render(write_still=True)
    assert path.exists() and path.stat().st_size > 10000
    results.append(
        dict(
            preset,
            file=path.name,
            bytes=path.stat().st_size,
            direction=list(direction),
            position=list(evaluated.matrix_world.translation),
        )
    )
    print("RENDER_DONE", preset["name"], path.stat().st_size, flush=True)
report = {
    "blend": Path(bpy.data.filepath).name,
    "blender": bpy.app.version_string,
    "resolution": [1920, 1200],
    "samples": args.samples,
    "objects": len(scene.objects),
    "packed_images": sum(
        bool(i.packed_file) for i in bpy.data.images if i.source == "FILE"
    ),
    "missing_external_images": [
        i.filepath
        for i in bpy.data.images
        if i.source == "FILE"
        and not i.packed_file
        and not Path(bpy.path.abspath(i.filepath)).exists()
    ],
    "renders": results,
}
assert not report["missing_external_images"], report["missing_external_images"]
(
    output
    / ("verification-" + args.preset + ".json" if args.preset else "verification.json")
).write_text(json.dumps(report, indent=2) + "\n")
print("VERIFIED", json.dumps(report), flush=True)

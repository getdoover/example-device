"""Storefront review cameras. These are inspection views, not PTZ presets."""

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
specs = json.loads((ROOT / "shop-manifest.json").read_text())["shops"]
parser = argparse.ArgumentParser()
parser.add_argument("--shop", action="append")
args = parser.parse_args(
    sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
)
if args.shop:
    unknown = set(args.shop) - {s["id"] for s in specs}
    if unknown:
        raise ValueError("Unknown shops: " + repr(unknown))
    specs = [s for s in specs if s["id"] in args.shop]
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.resolution_x = 1440
scene.render.resolution_y = 1080
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.refresh_devices()
if any(d.type == "METAL" for d in prefs.devices):
    scene.cycles.device = "GPU"
    for d in prefs.devices:
        d.use = d.type == "METAL"
camera_data = bpy.data.cameras.new("Storefront review camera")
camera = bpy.data.objects.new("Storefront review camera", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
camera_data.lens = 21
camera_data.sensor_width = 36
camera_data.clip_start = 0.02
output = ROOT / "renders" / "shops"
output.mkdir(exist_ok=True)
results = []
for spec in specs:
    y = spec["bays"][-1] if spec["id"] != "blooms" else spec["bays"][0]
    side = spec["side"]
    camera.location = (side * 5.6, y, 1.9)
    target = Vector((side * 9.0, y, 1.52))
    camera.rotation_euler = (
        (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    path = output / (spec["id"] + ".png")
    scene.render.filepath = str(path)
    print("SHOP_RENDER_START", spec["id"], flush=True)
    bpy.ops.render.render(write_still=True)
    assert path.exists() and path.stat().st_size > 10000
    results.append(
        {
            "shop": spec["id"],
            "file": path.name,
            "bytes": path.stat().st_size,
            "position": list(camera.location),
        }
    )
    print("SHOP_RENDER_DONE", spec["id"], flush=True)
(
    output / ("verification-selected.json" if args.shop else "verification.json")
).write_text(
    json.dumps(
        {
            "blend": bpy.data.filepath,
            "resolution": [1440, 1080],
            "samples": 64,
            "purpose": "Separate storefront inspection cameras, not simulated CCTV output",
            "renders": results,
        },
        indent=2,
    )
    + "\n"
)
print("ALL_SHOPS_RENDERED", len(results), flush=True)

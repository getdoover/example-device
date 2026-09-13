"""Review the saved ground-floor reconstruction; no geometry generation."""

import json
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 96
scene.cycles.use_denoising = True
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.refresh_devices()
if any(d.type == "METAL" for d in prefs.devices):
    scene.cycles.device = "GPU"
    for d in prefs.devices:
        d.use = d.type == "METAL"
scene.render.resolution_x = 1600
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
camera = bpy.data.objects.new(
    "Lower-floor inspection camera", bpy.data.cameras.new("Lower-floor inspection")
)
scene.collection.objects.link(camera)
scene.camera = camera
camera.data.lens = 22
output = ROOT / "renders" / "lower-floor"
output.mkdir(parents=True, exist_ok=True)
views = [
    ("01-ground-arcade", (6.4, -9, -3.25), (0, 5, -3.1)),
    ("02-cafe-and-mosaic", (5.6, 11.3, -1.4), (0, 1, -4.2)),
    ("03-camera-looking-down", (3.4, 2.7, 3.55), (0, 12, -5.0)),
]
records = []
for name, position, target in views:
    camera.location = position
    camera.rotation_euler = (
        (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    scene.render.filepath = str(output / (name + ".png"))
    print("LOWER_RENDER_START", name, flush=True)
    bpy.ops.render.render(write_still=True)
    path = Path(scene.render.filepath)
    assert path.exists() and path.stat().st_size > 10000
    records.append(
        dict(name=name, position=position, target=target, bytes=path.stat().st_size)
    )
(output / "verification.json").write_text(
    json.dumps(dict(resolution=[1600, 1200], samples=96, views=records), indent=2)
    + "\n"
)
print("LOWER_RENDER_VERIFIED", json.dumps(records), flush=True)

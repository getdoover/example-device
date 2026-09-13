"""Generate small, deterministic JPEG camera attachments from Blender layers.

uv run --no-project --with numpy --with pillow --with openexr python \
    devices/camera-device/raw/generate_series.py

The hourly crowd is sampled once in world space, then seen by all four fixed
PTZ positions. Blender depth passes clip people behind architecture. This is a
fast synthetic-data renderer, not a simulation of tracked real shoppers.
"""

import argparse
import hashlib
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import OpenEXR
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
DEVICE = ROOT.parent
CACHE = ROOT / "series-cache"
WIDTH, HEIGHT = 640, 400
QUALITY = 38
BASE_SEED = 2016011449
parser = argparse.ArgumentParser()
parser.add_argument("--benchmark", action="store_true")
parser.add_argument("--verify-only", action="store_true")
args = parser.parse_args()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hour_folder(offset):
    return "hour-" + ("m%04d" % abs(offset) if offset < 0 else "%04d" % offset)


def crowd_for_hour(offset):
    rng = random.Random(BASE_SEED + offset)
    hour = offset % 24
    day = 9 <= hour <= 18
    count = (
        rng.randint(32, 58)
        if day
        else rng.randint(10, 22)
        if 7 <= hour <= 21
        else rng.randint(4, 7)
    )
    people = []
    # A few cleaners/security workers remain during the synthetic overnight shift.
    # Anchor zones keep all four PTZ views informative without placing anyone in voids.
    anchors = [(7.3, 14.5, 0), (-7.25, 15.2, 0), (-7.2, 1.8, 0), (-7.2, -8.5, 0)]
    for i in range(count):
        for attempt in range(100):
            if i < 4:
                x, y, z = anchors[i]
                x += rng.uniform(-0.32, 0.32)
                y += rng.uniform(-1.5, 1.5)
            else:
                floor = rng.choices([0, -5, 4.3], [0.67, 0.24, 0.09])[0]
                side = rng.choice([-1, 1])
                z = floor
                if floor == -5:
                    x = side * rng.uniform(3.95, 6.85)
                    y = rng.uniform(-20.5, 20.5)
                    if x > 3.5 and -19.3 < y < -16.5:
                        continue  # Lower escalator boarding area.
                else:
                    x = side * rng.uniform(6.85, 7.9)
                    y = rng.uniform(-20.7, 20.7)
                    if rng.random() < 0.16:
                        x, y = rng.uniform(-6.5, 6.5), rng.uniform(-2.3, -0.3)
            if all(
                z != p["position"][2]
                or math.hypot(x - p["position"][0], y - p["position"][1]) > 0.58
                for p in people
            ):
                break
        people.append(
            dict(
                id="person-%d-%02d" % (BASE_SEED + offset, i),
                identity=rng.randrange(24),
                position=[round(x, 4), round(y, 4), z],
                heading=rng.uniform(0, 360),
                height_scale=rng.uniform(0.91, 1.12),
            )
        )
    return people


def lighting_for_hour(offset):
    hour = offset % 24
    if 8 <= hour <= 17:
        return "day", 1.0
    if hour in [6, 7, 18, 19]:
        return "dusk", 0.75
    return "night", 0.47


def verify(manifest):
    assert len(manifest["hours"]) == 888
    files, hashes = [], set()
    for hour in manifest["hours"]:
        assert len(hour["images"]) == 4
        for record in hour["images"]:
            path = DEVICE / record["path"]
            with Image.open(path) as image:
                image.load()
                assert image.size == (WIDTH, HEIGHT) and image.format == "JPEG"
            assert path.stat().st_size == record["bytes"]
            assert digest(path) == record["sha256"]
            files.append(path)
            hashes.add(record["sha256"])
    assert len(files) == 3552 and len(set(files)) == 3552
    assert len(hashes) == 3552, "All captures should vary, including night views"
    assert [h["offset_hours"] for h in manifest["hours"]] == list(range(-168, 720))
    assert digest(ROOT / "qvb-camera-scene.blend") == manifest["master_scene_sha256"]
    report = dict(
        images=len(files),
        unique_image_hashes=len(hashes),
        hours=888,
        resolution=[WIDTH, HEIGHT],
        bytes=sum(p.stat().st_size for p in files),
        first_offset_hours=-168,
        last_offset_hours=719,
        master_scene_unchanged=True,
        all_jpegs_decoded=True,
        minimum_visible_people=min(
            r["visible_people"] for h in manifest["hours"] for r in h["images"]
        ),
    )
    depth_checks = json.loads((CACHE / "depth-ray-check.json").read_text())
    report["depth_validation"] = {
        "sampled_rays": len(depth_checks),
        "maximum_error_metres": max(abs(r["difference"]) for r in depth_checks),
        "method": "Compare Euclidean-converted Blender Z pass with scene ray casts",
    }
    assert report["minimum_visible_people"] >= 1
    assert report["depth_validation"]["maximum_error_metres"] <= 0.001
    (ROOT / "series-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    contact_sheet(manifest)
    print("SERIES_VERIFIED", json.dumps(report), flush=True)


def contact_sheet(manifest):
    """Review actual generated files across history, installation and future."""
    selected = [-156, 2, 348, 714]
    sheet = Image.new("RGB", (1280, 956), (24, 28, 31))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=16)
    small = ImageFont.load_default(size=12)
    draw.text(
        (12, 10),
        "QVB camera-device | four PTZ captures each hour | synthetic people",
        font=font,
        fill="white",
    )
    names = ["Clock atrium", "Cafe gallery", "Opposite shops", "Escalator"]
    for row, offset in enumerate(selected):
        hour = next(h for h in manifest["hours"] if h["offset_hours"] == offset)
        top = 42 + row * 228
        draw.text(
            (12, top),
            "Hour %+d | %02d:00 visual time | %s | %d people across the scene"
            % (offset, hour["local_hour"], hour["lighting"], hour["people_count"]),
            font=small,
            fill=(214, 222, 229),
        )
        for col, record in enumerate(hour["images"]):
            with Image.open(DEVICE / record["path"]) as capture:
                sheet.paste(
                    capture.resize((320, 200), Image.Resampling.LANCZOS),
                    (col * 320, top + 23),
                )
            draw.rectangle(
                (col * 320 + 4, top + 27, col * 320 + 130, top + 44), fill=(20, 24, 28)
            )
            draw.text((col * 320 + 8, top + 28), names[col], font=small, fill="white")
    sheet.save(ROOT / "series-contact-sheet.jpg", quality=84, optimize=True)


if args.verify_only:
    verify(json.loads((ROOT / "series-manifest.json").read_text()))
    raise SystemExit

cameras = json.loads((CACHE / "cameras.json").read_text())
assets = json.loads((ROOT / "series-assets.json").read_text())
atlases = {
    angle: Image.open(CACHE / ("people-elevation-%02d.png" % angle)).convert("RGBA")
    for angle in [0, 20, 40, 60]
}
sprites = {
    (angle, identity, yaw): atlas.crop(
        (yaw * 80, identity * 160, (yaw + 1) * 80, (identity + 1) * 160)
    )
    for angle, atlas in atlases.items()
    for identity in range(24)
    for yaw in range(8)
}
renderers = {}
for name, camera in cameras.items():
    matrix = np.array(camera["matrix_world"])
    view = np.linalg.inv(matrix)
    projection = np.array(camera["projection"])
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    camera_rays = np.stack(
        (
            (2 * (xx + 0.5) / WIDTH - 1) / projection[0, 0],
            (1 - 2 * (yy + 0.5) / HEIGHT) / projection[1, 1],
            -np.ones_like(xx),
        ),
        axis=-1,
    )
    rays = camera_rays @ matrix[:3, :3].T
    rays /= np.linalg.norm(rays, axis=-1, keepdims=True)
    exr = OpenEXR.File(str(CACHE / (name + "-depth.exr")))
    depth = next(iter(exr.channels().values())).pixels
    assert depth.shape == (HEIGHT, WIDTH), depth.shape
    # Blender Z pass measures camera-axis distance, while our rays are unit length.
    depth = depth * np.linalg.norm(camera_rays, axis=-1)
    np.savez_compressed(CACHE / (name + "-depth.npz"), depth=depth)
    renderers[name] = dict(
        camera=camera,
        view=view,
        projection=projection,
        origin=matrix[:3, 3],
        rays=rays,
        depth=depth,
        backgrounds={
            lighting: np.array(
                Image.open(CACHE / (name + "-" + lighting + ".png")).convert("RGB"),
                dtype=np.float32,
            )
            for lighting in ["day", "dusk", "night"]
        },
    )

depth_checks = json.loads((CACHE / "depth-ray-check.json").read_text())
for check in depth_checks:
    x, y = check["pixel"]
    measured = float(renderers[check["preset"]]["depth"][y, x])
    check["euclidean_render_depth"] = measured
    check["difference"] = round(measured - check["distance"], 4)
    assert abs(check["difference"]) <= 0.001, check
(CACHE / "depth-ray-check.json").write_text(json.dumps(depth_checks, indent=2) + "\n")


def project(renderer, point):
    local = renderer["view"] @ np.array([*point, 1.0])
    if local[2] >= -0.2:
        return None
    clip = renderer["projection"] @ local
    uv = clip[:2] / clip[3]
    return np.array([(uv[0] + 1) * WIDTH / 2, (1 - uv[1]) * HEIGHT / 2]), -local[2]


def render_people(renderer, people, lighting, brightness):
    canvas = renderer["backgrounds"][lighting].copy()
    zbuffer = renderer["depth"].copy()
    visible = []
    ordered = sorted(
        people,
        key=lambda p: np.linalg.norm(renderer["origin"] - p["position"]),
        reverse=True,
    )
    for p in ordered:
        foot = np.array(p["position"], dtype=float)
        foot[2] += 0.027
        projected = project(renderer, foot)
        if projected is None:
            continue
        (px, py), camera_z = projected
        elevation = math.degrees(
            math.atan2(
                renderer["origin"][2] - foot[2],
                np.linalg.norm(renderer["origin"][:2] - foot[:2]),
            )
        )
        if elevation < -8:
            angle = 0
        else:
            angle = min(atlases, key=lambda a: abs(a - elevation))
        toward_camera = renderer["origin"][:2] - foot[:2]
        # Person front is -Y; atlas front camera is -Y.
        camera_heading = math.degrees(math.atan2(toward_camera[0], -toward_camera[1]))
        yaw = int(round((p["heading"] - camera_heading) / 45)) % 8
        scale = (
            renderer["projection"][0, 0]
            * WIDTH
            / (2 * camera_z)
            / (80 / 1.2)
            * p["height_scale"]
        )
        w, h = max(1, round(80 * scale)), max(1, round(160 * scale))
        if h < 5 or w > WIDTH * 2:
            continue
        left, top = round(px - w * 0.5), round(py - h * (1 - 0.18 / 2.4))
        x0, y0, x1, y1 = (
            max(0, left),
            max(0, top),
            min(WIDTH, left + w),
            min(HEIGHT, top + h),
        )
        if x1 <= x0 or y1 <= y0:
            continue
        sprite = np.array(
            sprites[angle, p["identity"], yaw].resize((w, h), Image.Resampling.LANCZOS),
            dtype=np.float32,
        )[y0 - top : y1 - top, x0 - left : x1 - left]
        alpha = sprite[:, :, 3] / 255
        normal = np.array([*toward_camera, 0.0])
        normal /= np.linalg.norm(normal)
        rays = renderer["rays"][y0:y1, x0:x1]
        denominator = np.sum(rays * normal, axis=-1)
        person_depth = np.dot(foot - renderer["origin"], normal) / denominator
        allowed = person_depth < zbuffer[y0:y1, x0:x1] + 0.025
        alpha *= allowed
        pixels = int(np.count_nonzero(alpha > 0.2))
        if pixels < 3:
            continue
        # Compact contact shadow, clipped to the same floor by the scene depth.
        sw = max(2, w * 0.38)
        sh = max(1, sw * 0.24)
        sx0, sx1 = max(0, int(px - sw * 2)), min(WIDTH, int(px + sw * 2) + 1)
        sy0, sy1 = max(0, int(py - sh * 2)), min(HEIGHT, int(py + sh * 2) + 1)
        if sx1 > sx0 and sy1 > sy0:
            yy, xx = np.mgrid[sy0:sy1, sx0:sx1]
            floor_dist = (foot[2] - renderer["origin"][2]) / renderer["rays"][
                sy0:sy1, sx0:sx1, 2
            ]
            on_floor = np.abs(floor_dist - renderer["depth"][sy0:sy1, sx0:sx1]) < 0.16
            shadow = (
                0.25
                * np.exp(-(((xx - px) / sw) ** 2) - ((yy - py) / sh) ** 2)
                * on_floor
            )
            canvas[sy0:sy1, sx0:sx1] *= 1 - shadow[:, :, None]
        colors = sprite[:, :, :3] * brightness
        region = canvas[y0:y1, x0:x1]
        region[:] = colors * alpha[:, :, None] + region * (1 - alpha[:, :, None])
        depth_region = zbuffer[y0:y1, x0:x1]
        depth_region[alpha > 0.5] = person_depth[alpha > 0.5]
        visible.append(
            dict(
                id=p["id"],
                pixels=pixels,
                screen_foot=[round(float(px), 2), round(float(py), 2)],
            )
        )
    return Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)), visible


started = time.monotonic()
offsets = [2, 12, 18] if args.benchmark else list(range(-168, 720))
hours = []
for offset in offsets:
    people = crowd_for_hour(offset)
    lighting, brightness = lighting_for_hour(offset)
    records = []
    for name, renderer in renderers.items():
        image, visible = render_people(renderer, people, lighting, brightness)
        if args.benchmark:
            path = ROOT / "series-preview" / (hour_folder(offset) + "-" + name + ".jpg")
        else:
            path = DEVICE / "attachments" / hour_folder(offset) / (name + ".jpg")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(
            path,
            format="JPEG",
            quality=QUALITY,
            optimize=True,
            progressive=True,
            subsampling=2,
        )
        records.append(
            dict(
                preset=name,
                path=path.relative_to(DEVICE).as_posix(),
                pan=renderer["camera"]["pan"],
                tilt=renderer["camera"]["tilt"],
                lens=renderer["camera"]["lens"],
                bytes=path.stat().st_size,
                sha256=digest(path),
                visible_people=len(visible),
            )
        )
    hours.append(
        dict(
            offset_hours=offset,
            local_hour=offset % 24,
            seed=BASE_SEED + offset,
            lighting=lighting,
            people_count=len(people),
            people=people,
            images=records,
        )
    )
    if args.benchmark or offset % 24 == 0:
        print(
            "SERIES_HOUR",
            offset,
            "images",
            len(hours) * 4,
            "seconds",
            round(time.monotonic() - started, 2),
            flush=True,
        )

manifest = dict(
    version=1,
    method="Blender backgrounds and clothed 3D people atlases, world-space crowd positions and per-pixel depth occlusion",
    device="camera-device",
    timezone="Australia/Sydney",
    anchor="Install-date local midnight",
    offsets={
        "first": -168,
        "last_inclusive": 719,
        "interval_hours": 1,
        "history_days": 7,
        "forward_days": 30,
    },
    time_semantics="Elapsed hourly offsets anchored at install local midnight; visual local_hour is offset modulo 24, so a DST transition shifts displayed wall-clock hour",
    resolution=[WIDTH, HEIGHT],
    jpeg_quality=QUALITY,
    master_scene_sha256=assets["master_sha256"],
    series_scene="qvb-camera-series.blend",
    presets=list(cameras.values()),
    assumptions=[
        "Thirty days after install is the synthetic month; one week before install",
        "Overnight crowd represents security and cleaning staff",
        "Crowds are resampled each hour, shared across all four simultaneous preset views",
        "Billboard atlas approximation; no reflections of dynamic people or articulated tracking",
    ],
    seconds=round(time.monotonic() - started, 3),
    hours=hours,
)
destination = ROOT / (
    "series-benchmark.json" if args.benchmark else "series-manifest.json"
)
destination.write_text(json.dumps(manifest, indent=2) + "\n")
if not args.benchmark:
    verify(manifest)
else:
    print(
        "BENCHMARK_DONE",
        json.dumps(
            {
                "seconds": manifest["seconds"],
                "images": len(hours) * 4,
                "bytes": sum(r["bytes"] for h in hours for r in h["images"]),
                "visible_people": [
                    [r["visible_people"] for r in h["images"]] for h in hours
                ],
            }
        ),
        flush=True,
    )

# Camera device example

[Open the Blender scene](raw/qvb-camera-scene.blend). The model reconstructs the Queen Victoria Building gallery around the ceiling camera marked in the reference. It is an editable 3D scene with a fixed camera mount, separate pan and tilt controls, and rendered view presets.

The [device configuration](config.json) and [camera history](channels/doover_camera.json) package 888 hourly captures with four views each: 3,552 JPEGs at 960 × 600, quality 75. This is the Balanced quality setting. The series covers offsets -168 through 719 hours, with seven days before installation and 30 days starting at installation midnight.

Each capture contains four native Doover attachments, matching the PTZ camera history on the [reference device](https://dojo.doover.com/agent/144933745630167049). The [format notes](raw/references/doover-ptz.md) record the observed payload and UI contract. Stable view names allow switching between the clock, café gallery, opposite shops, and escalator. The `doover_camera` display app is inert; the example processor publishes its history and tags.

Snapshots use elapsed hourly offsets from the install anchor. The visual day cycle repeats every 24 hours; a daylight-saving transition can shift its displayed wall-clock hour. Live streaming and manual capture are not implemented. The history widget still exposes its standard **Get Now** button, so the example notice explains that captures are scheduled.

## Hourly image series

[Preview the series](raw/series-contact-sheet.jpg), or inspect the [hour-by-hour manifest](raw/series-manifest.json). Every hourly crowd is sampled once in scene coordinates and projected into all four camera views. People differ in clothing, pose, position, and direction, with more shoppers during the day and a few overnight workers.

The separate [series scene](raw/qvb-camera-series.blend) supplies the architecture, lighting, and clothed human models. The generator combines native 1920 × 1200 Blender backgrounds and people using the scene's depth pass, including occlusion by railings and shopfronts. It downsamples each completed image to 960 × 600 with Lanczos filtering and saves a progressive JPEG at quality 75. The detailed master scene, hourly crowds, lighting, and camera positions remain unchanged.

Images are stored under `attachments/hour-m0168/` through `attachments/hour-0719/`, with `hour-0000/` at installation. The complete JPEG set is 280,688,550 bytes, or 280.69 MB, averaging 79.0 kB per image. The previous week's 672 images total 53,104,712 bytes, or 53.10 MB. These are measured JPEG payload sizes in decimal units. The [verification report](raw/series-verification.json) records image counts, sizes, hashes, and dimensions. The processor checks each file's size and SHA-256 before uploading it.

To regenerate from the saved source layers:

```sh
uv run --no-project --with numpy==2.5.3 --with pillow==12.3.0 --with openexr==3.4.15 python devices/camera-device/raw/generate_series.py
uv run python tools/generate_camera_device.py
uv run example-device validate devices/camera-device
uv run example-device simulate devices/camera-device --anchor-ms 1789308000000 --output build/camera-playback.json
```

Create `build/` before using that simulation output path. Initial cloud imports use small attachment batches and resume on subsequent scheduled invocations. Source image rendering is available in Server Runner as `QVB camera-device · render series source layers`; `raw/render_series_assets.py` renders from the saved series scene. The source layers and manifests contain no reference-device credentials or uploaded customer images.

## Rendered views

| View | Render |
| --- | --- |
| Clock and atrium | [01-clock-atrium.png](raw/renders/01-clock-atrium.png) |
| Café gallery | [02-cafe-gallery.png](raw/renders/02-cafe-gallery.png) |
| Opposite shops | [03-opposite-shops.png](raw/renders/03-opposite-shops.png) |
| Escalator | [04-escalator.png](raw/renders/04-escalator.png) |

All four images use the same physical mount. The model includes gallery openings, iron scrollwork, shop interiors, leaded transoms, café furniture, a hanging clock, an escalator, and a glazed roof. Scanned materials and Cycles lighting provide the surface detail.

The architecture, clock ornament, merchandise, carpet, and mount position are visual approximations. They are not survey measurements or a photogrammetric reconstruction. The detailed master has no animated shoppers; the series adds synthetic hourly crowds. The January 2016 imagery establishes the reference appearance, not the present tenant layout.

## Level 1 shop accuracy pass

The second pass replaces the generic displays and cyclic shop names with ten identified businesses and one unresolved fashion bay. It includes individual shoe displays, jewellery cabinets, clothing rails, knitwear shelves, bath-product displays and a coffee-house interior. [Reference notes](raw/references/shops/notes.md) record the observations and remaining dimensional approximations; [shop-manifest.json](raw/shop-manifest.json) maps them to the Blender scene.

These closer renders use separate inspection cameras, rather than the fixed security-camera mount:

| Shop | Inspection render |
| --- | --- |
| Dominique's | [Shoes and bags](raw/renders/shops/dominique.png) |
| Volls Jewellery | [Jewellery cabinets](raw/renders/shops/volls.png) |
| Tribeca | [Dress boutique](raw/renders/shops/tribeca.png) |
| George | [Eveningwear](raw/renders/shops/george.png) |
| QVB Cashmere Collection | [Knitwear](raw/renders/shops/cashmere.png) |
| GS Diamonds | [Diamond displays](raw/renders/shops/gs-diamonds.png) |
| Via Condotti | [Accessories](raw/renders/shops/via-condotti.png) |
| Blooms | [Fashion and sale display](raw/renders/shops/blooms.png) |
| Crabtree & Evelyn | [Product shelves](raw/renders/shops/crabtree-evelyn.png) |
| Old Vienna Coffee House | [Café interior](raw/renders/shops/old-vienna.png) |
| Unresolved clockward fashion bay | [Unlabelled display](raw/renders/shops/unresolved-clockward-fashion.png) |

`raw/render_shops.py` regenerates these views. Its saved Server Runner task is `QVB camera-device · review Level 1 shopfronts`.

## Ground-floor accuracy pass

The ground floor now includes basement openings, iron balustrades, patterned mosaic flooring, large single-arch shopfronts, round columns, ten identified tenants, and the Metropole café crossing. The visible basement has rectangular shopfronts and a tiled concourse. [Reference notes](raw/references/lower-floor/notes.md) distinguish observed features from estimated dimensions; [the manifest](raw/lower-floor-manifest.json) records the model layout.

| Inspection view | Render |
| --- | --- |
| Ground-floor arcade | [Arches and basement opening](raw/renders/lower-floor/01-ground-arcade.png) |
| Café crossing | [Kiosk, seating and mosaic](raw/renders/lower-floor/02-cafe-and-mosaic.png) |
| Downward view from the camera position | [Lower floor and kiosk](raw/renders/lower-floor/03-camera-looking-down.png) |

`raw/render_lower_floor.py` creates these three inspection views. Its saved Server Runner task is `QVB camera-device · review lower floor`. The third view uses the security camera's position with an additional downward inspection angle.

## Move the camera

Open `raw/qvb-camera-scene.blend` in Blender 5.2 or later. Select `PTZ_Mount` in the `07 Camera rig` collection and change its custom properties:

| Property | Meaning |
| --- | --- |
| `pan_degrees` | Clockwise yaw when viewed from above. Zero looks along local scene +Y. |
| `tilt_degrees` | Positive values look down. Zero is horizontal. |

The mount is at `[3.4, 2.7, 3.55]` metres. The Level 1 café floor is Z=0. The stored pan and tilt limits are descriptive metadata, not enforced constraints. Change the `camera-device` camera's focal length for zoom.

`PTZ_Mount → PTZ_Pan → PTZ_Tilt → camera-device` is the parent chain. Drivers convert degrees to rotations. Textures are packed into the Blender file and also supplied under `raw/textures` for rebuilding.

## Render the saved scene

From the repository root on this Mac, run:

```sh
/Applications/Blender.app/Contents/MacOS/Blender \
  --background devices/camera-device/raw/qvb-camera-scene.blend \
  --python devices/camera-device/raw/render_views.py
```

Use Server Runner for the render task when working through an agent. The saved task is named `QVB camera-device · render four PTZ views`.

Append `-- --preset 01-clock-atrium` to render one view. The script writes 1920 × 1200 PNGs and `raw/renders/verification.json`. It checks the evaluated camera direction against each requested pan and tilt, checks that rendered files exist, and checks for missing unpacked image dependencies. It does not save the temporary camera changes back into the scene.

## Rebuild the model

The scene was created through Blender MCP. The construction scripts also run in Blender's Python context. Rebuilding replaces the active scene. Start a new Blender file, then execute these scripts in order:

1. `raw/build_scene.py`
2. `raw/refine_scene.py`
3. `raw/finish_scene.py`
4. `raw/refine_shops.py`
5. `raw/refine_lower_floor.py`

For each script, set `__file__` to its absolute path before executing its contents. `build_scene.py` also accepts `QVB_STAGE` values `foundation`, `architecture`, `details`, and `camera` for separate MCP calls. Run all four stages in that order before refinement.

The local textures allow rebuilding without a network download. A new texture download is only necessary if those source files are removed. The first refinement and finishing scripts run once per fresh build. `refine_shops.py` can be rerun; it rebuilds its own collection. For staged MCP execution, set `SHOP_STAGE` to `prepare`, then each shop ID in `shop-manifest.json`, then `finish`. Omit it to run the whole shop pass. The Mac system Georgia font is used during construction when available, then visible text is converted to geometry.

See [the source notes](raw/references/sources.md) for the Street View references and texture credits.

For staged execution of the lower-floor pass, set `LOWER_STAGE` to `prepare`, `floor`, `shops`, `furniture`, then `finish`. Run these stages after the Level 1 shop pass. The lower-floor script can replace its own collection without rebuilding the upper levels.

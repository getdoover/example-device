# Doover PTZ capture format

The [supplied reference device](https://dojo.doover.com/agent/144933745630167049) was inspected through read-only Doover API requests on 14 September 2026. Its active Dahua PTZ application is `doover_camera`, installed under `doover_camera_1`. The older `test_app_key_ptz` channel is not the active camera history.

Each scheduled capture has four native JPEG attachments. Its payload names each file and view:

```json
{
  "camera_name": "Dahua PTZ",
  "media": [
    {"file": "Shed.jpg", "name": "Shed"},
    {"file": "Cutoff_Saw.jpg", "name": "Cutoff_Saw"},
    {"file": "Whiteboard.jpg", "name": "Whiteboard"},
    {"file": "Possum-Hole.jpg", "name": "Possum-Hole"}
  ],
  "reason": "schedule"
}
```

The native `uiCameraHistory` element reads the channel named by `cameraName`. It matches `media[].file` to the attachment's exact filename and uses `media[].name` as the persistent view selector. Capture times come from message snowflake IDs. Thumbnails are optional; the example JPEGs are already small enough for previews. The optional `night` boolean supports the history's night filter.

The example uses this format with fresh QVB images and the portable app key `doover_camera`. The tag `last_cam_snapshot` uses seconds; the example's `last_capture_ms` UI timestamp uses milliseconds. Both values are rebased from install-relative offsets.

The history widget's built-in **Get Now** action sends a camera-control RPC. The example provides scheduled captures only and explains this in its visible notice. No live-view element is supplied.

No reference-device images, credentials, network addresses, or installation bindings are included in the example dataset.

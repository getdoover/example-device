#!/usr/bin/env python3
"""Package the rendered QVB series as portable Doover PTZ camera history.

The image series must already exist. This command hashes each JPEG, writes the
configuration and channel data, and validates them with the processor loader.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HOUR = 3_600_000
APP = "doover_camera"
VIEWS = (
    ("01-clock-atrium", "Clock and atrium"),
    ("02-cafe-gallery", "Café gallery"),
    ("03-opposite-shops", "Opposite shops"),
    ("04-escalator", "Escalator"),
)
HOURS = range(-168, 720)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def hour_name(hour):
    return f"hour-m{abs(hour):04d}" if hour < 0 else f"hour-{hour:04d}"


def device_config():
    return {
        "schema_version": 1,
        "slug": "camera-device",
        "name": "QVB camera example",
        "processor": {
            "app_key": "example_device",
            "application_name": "example_device",
        },
        "apps": [
            {
                "app_key": APP,
                "application_name": "doover_camera",
                "run": False,
                "config": {
                    "camera_name": "QVB gallery camera",
                    "camera_type": "Dahua (PTZ)",
                    "control_enabled": False,
                    "camera_snapshot_config": {
                        "enabled": True,
                        "period": 3600,
                        "mode": "Image",
                        "duration": 1,
                        "fps": 1,
                        "native_h264": True,
                        "scale": "960:-1",
                    },
                    "dv_app_position": 100,
                },
            }
        ],
        "channels": [APP, "ui_state", "tag_values", "ui_cmds", "deployment_config"],
        "duration_ms": 720 * HOUR,
        "interpolation": [],
        "inputs": [],
    }


def aggregate(data, fields=None):
    entry = {"timestamp": 0, "kind": "aggregate", "mode": "merge", "data": data}
    if fields:
        entry["timestamp_fields"] = fields
    return entry


def camera_ui():
    return {
        "state": {
            "children": {
                APP: {
                    "name": APP,
                    "type": "uiApplication",
                    "displayString": "QVB gallery camera",
                    "hidden": False,
                    "position": 100,
                    "defaultOpen": True,
                    "fullWidth": True,
                    "children": {
                        "example_notice": {
                            "name": "example_notice",
                            "type": "uiVariable",
                            "displayString": "Example camera",
                            "hidden": False,
                            "position": 1,
                            "showActivity": False,
                            "varType": "string",
                            "notGraphable": True,
                            "currentValue": "Simulated QVB snapshots, captured hourly across four views. Choose a view and time in History. Get Now and live controls are unavailable in this example.",
                        },
                        "history": {
                            "name": "history",
                            "type": "uiCameraHistory",
                            "displayString": "History",
                            "hidden": False,
                            "position": 10,
                            "showActivity": True,
                            "cameraName": APP,
                            "presets": [],
                            "ptzControl": True,
                        },
                        "last_capture": {
                            "name": "last_capture",
                            "type": "uiTimestamp",
                            "displayString": "Last capture",
                            "hidden": False,
                            "position": 20,
                            "showActivity": True,
                            "varType": "timestamp",
                            "currentValue": "$tag.app().last_capture_ms:number:null",
                        },
                    },
                }
            }
        }
    }


def generate(directory):
    config = device_config()
    captures, tags = [], []
    timestamp_fields = [
        {"path": [APP, "last_cam_snapshot"], "unit": "s"},
        {"path": [APP, "last_capture_ms"], "unit": "ms"},
    ]
    for hour in HOURS:
        timestamp = hour * HOUR
        attachments = []
        for preset, _label in VIEWS:
            relative = Path("attachments") / hour_name(hour) / f"{preset}.jpg"
            raw = (directory / relative).read_bytes()
            if not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
                raise ValueError(f"Expected a complete JPEG: {relative}")
            attachments.append(
                {
                    "path": relative.as_posix(),
                    "filename": f"{preset}.jpg",
                    "content_type": "image/jpeg",
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        captures.append(
            {
                "timestamp": timestamp,
                "kind": "message",
                "id": f"capture-{hour_name(hour)}",
                "data": {
                    "camera_name": "QVB gallery camera",
                    "media": [
                        {"file": f"{preset}.jpg", "name": label}
                        for preset, label in VIEWS
                    ],
                    "reason": "schedule",
                    "night": hour % 24 < 6 or hour % 24 >= 20,
                },
                "attachments": attachments,
            }
        )
        data = {
            APP: {
                "last_cam_snapshot": timestamp // 1000,
                "last_capture_ms": timestamp,
                "presets": [label for _preset, label in VIEWS],
                "active_preset": VIEWS[-1][1],
            }
        }
        if hour == 0:
            tags.append(aggregate(data, timestamp_fields))
        tag = {
            "timestamp": timestamp,
            "kind": "message",
            "id": f"snapshot-tags-{hour_name(hour)}",
            "data": data,
            "timestamp_fields": timestamp_fields,
        }
        if hour > 0:
            tag["apply_to_aggregate"] = True
        tags.append(tag)

    channels = {
        APP: captures,
        "ui_state": [aggregate(camera_ui())],
        "tag_values": tags,
        "ui_cmds": [aggregate({APP: {}})],
        "deployment_config": [
            aggregate({"applications": {APP: config["apps"][0]["config"]}})
        ],
    }
    write_json(directory / "config.json", config)
    for name, entries in channels.items():
        write_json(directory / "channels" / f"{name}.json", entries)
    from example_device.dataset import load_directory

    load_directory(directory)
    summary = {
        "dataset": "camera-device",
        "captures": len(captures),
        "images": sum(len(entry["attachments"]) for entry in captures),
        "image_bytes": sum(
            file["size"] for entry in captures for file in entry["attachments"]
        ),
        "first_hour": HOURS.start,
        "last_hour": HOURS.stop - 1,
        "history_hours": 168,
        "future_hours": 720,
    }
    write_json(directory / "raw" / "dataset-summary.json", summary)
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "devices" / "camera-device",
    )
    generate(parser.parse_args().output)


if __name__ == "__main__":
    main()

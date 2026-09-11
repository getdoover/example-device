"""Installation settings and manifest generation for the playback processor."""

from __future__ import annotations

import json
from pathlib import Path

from pydoover import config
from pydoover.processor import ManySubscriptionConfig, ScheduleConfig


class ExampleDeviceConfig(config.Schema):
    repository = config.String(
        "Dataset repository", name="repository", default="getdoover/example-device"
    )
    dataset_slug = config.String(
        "Dataset",
        name="dataset_slug",
        description="Directory name under devices/",
        required=True,
    )
    dataset_revision = config.String(
        "Dataset commit",
        name="dataset_revision",
        description="Full immutable Git commit SHA",
        required=True,
    )
    anchor_ms = config.Integer(
        "Start timestamp",
        name="anchor_ms",
        description="Fixed creation-day midnight as epoch milliseconds",
        required=True,
    )
    idle_interval_seconds = config.Integer(
        "Idle publish interval", name="idle_interval_seconds", default=1800, minimum=60
    )
    active_interval_seconds = config.Integer(
        "Viewed publish interval",
        name="active_interval_seconds",
        default=60,
        minimum=60,
    )
    max_batches = config.Integer(
        "Import batches per invocation",
        name="max_batches",
        default=4,
        minimum=1,
        maximum=20,
    )
    subscriptions = ManySubscriptionConfig(
        default=["ui_cmds", "dv-ui-sub"], hidden=True
    )
    schedule = ScheduleConfig(
        default="rate(1 minute)", allowed_modes=["rate", "cron"], hidden=True
    )


def manifest() -> dict:
    from .app_ui import ExampleUI

    return {
        "example_device": {
            "name": "example_device",
            "display_name": "Example Device Manager",
            "type": "PRO",
            "visibility": "PUB",
            "allow_many": False,
            "description": "Publishes precomputed example telemetry and acknowledges demo controls.",
            "depends_on": [],
            "export_config_command": "export-config",
            "export_ui_command": "export-config",
            "lambda_config": {
                "Runtime": "python3.13",
                "Timeout": 300,
                "Handler": "src.example_device.handler",
                "MemorySize": 256,
                "Architectures": ["arm64"],
                "Environment": {},
            },
            "config_schema": ExampleDeviceConfig.to_schema(),
            "ui_schema": ExampleUI(None, None, None).to_schema(),
        }
    }


def export() -> None:
    """Write processor metadata only, never device datasets or design documents."""
    Path("doover_config.json").write_text(json.dumps(manifest(), indent=2) + "\n")

#!/usr/bin/env python3
"""Generate the synthetic water-storage dataset and optional preview charts.

Run from any directory with Python 3.11 or newer. The dataset uses only the
standard library. Add --charts with matplotlib installed to draw preview charts.
No network, source deployment export, or customer data is read.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path

DAY = 86_400_000
MINUTE = 60_000
HOUR = 60 * MINUTE
SEED = 202609
TANK = "vega_level_sensor"
POWER = "solar_power_management"
CAPACITY_ML = 10.0
DEPTH_M = 4.0
SENSOR_M = 4.5
EVENTS = tuple((day * DAY, day * DAY + 30 * HOUR) for day in (-68, -32, -5))


def volume_at(timestamp):
    """A new repeated fill and drawdown scenario, in megalitres."""
    day = timestamp / DAY
    phase = (day + 5) % 9
    if phase < 1.25:
        volume = 2.6 + 6.2 * phase / 1.25
    else:
        volume = 8.8 - 6.2 * (phase - 1.25) / 7.75
    return round(volume + 0.06 * math.sin(2 * math.pi * day), 1)


def tags_at(timestamp):
    day = timestamp / DAY
    hour = (timestamp % DAY) / HOUR
    daylight = max(0.0, math.sin(math.pi * (hour - 6) / 12))
    slow_weather = 0.88 + 0.12 * math.sin(2 * math.pi * day / 7)
    noise = random.Random(SEED + timestamp).uniform(-0.025, 0.025)
    volume = volume_at(timestamp)
    depth = volume * DEPTH_M / CAPACITY_ML
    active_event = next(
        (event for event in EVENTS if event[0] <= timestamp < event[1]), None
    )
    tank = {
        "last_volume": volume,
        "last_rl": round(depth, 3),
        "last_raw_distance": round(SENSOR_M - depth, 3),
        "last_reliability": round(58 + 3 * math.sin(2 * math.pi * day / 5), 1),
        "time_last_update": timestamp,
        "event_active": active_event is not None,
        "event_initial_volume": volume_at(active_event[0]) if active_event else None,
        "event_started_at": active_event[0] // 1000 if active_event else None,
        "event_volume": round(volume - volume_at(active_event[0]), 1)
        if active_event
        else None,
        "start_event_hidden": active_event is not None,
        "stop_event_hidden": active_event is None,
        "warning_name": None,
        "warning_hidden": True,
    }
    power = {
        "system_voltage": round(12.55 + 1.35 * daylight * slow_weather + noise, 2),
        "system_power": round(
            3.2 + 0.7 * daylight + 0.12 * math.sin(2 * math.pi * day), 2
        ),
        "system_temperature": round(
            21
            + 8 * math.sin(2 * math.pi * (hour - 9) / 24)
            + 2 * math.sin(2 * math.pi * day / 11),
            1,
        ),
        "is_online": True,
        "victron_hidden": True,
        "charge_state": None,
        "charge_current": None,
        "charge_voltage": None,
        "charge_power": None,
        "low_battery_warning_sent": False,
        "low_batt_warning_hidden": True,
        "immune_warning_hidden": True,
        "immune_warning_text": "Device in Immunity Mode",
        "about_to_sleep_warning_hidden": True,
        "about_to_sleep_warning_text": "Device is about to sleep",
    }
    return {TANK: tank, POWER: power}


def timestamps():
    result = set(range(-90 * DAY, -45 * DAY, 6 * HOUR))
    result.update(range(-45 * DAY, -14 * DAY, 2 * HOUR))
    result.update(range(-14 * DAY, 30 * DAY + 1, 30 * MINUTE))
    for start, stop in EVENTS:
        for event_time in (start, stop):
            result.update(event_time + offset * MINUTE for offset in (-5, -1, 0, 1, 5))
    return sorted(result)


def timestamp_fields(data):
    fields = [{"path": [TANK, "time_last_update"], "unit": "ms"}]
    if data[TANK]["event_started_at"] is not None:
        fields.append({"path": [TANK, "event_started_at"], "unit": "s"})
    return fields


def aggregate(data, fields=None):
    entry = {"timestamp": 0, "kind": "aggregate", "mode": "merge", "data": data}
    if fields:
        entry["timestamp_fields"] = fields
    return entry


def numeric(name, label, tag, units, precision, position, **extra):
    return {
        "name": name,
        "type": "uiVariable",
        "displayString": label,
        "showActivity": True,
        "position": position,
        "hidden": False,
        "units": units,
        "varType": "float",
        "currentValue": f"$tag.app().{tag}:number:null",
        "decPrecision": precision,
        **extra,
    }


def button(name, label, position, colour="blue"):
    return {
        "name": name,
        "type": "uiButton",
        "displayString": label,
        "position": position,
        "hidden": False,
        "colour": colour,
        "currentValue": f"$cmds.app().{name}",
        "requiresConfirm": False,
    }


def text_variable(name, label, value, position):
    return {
        "name": name,
        "type": "uiVariable",
        "displayString": label,
        "position": position,
        "hidden": False,
        "showActivity": False,
        "varType": "string",
        "currentValue": value,
        "notGraphable": True,
    }


def warning(name, label, hidden, position):
    return {
        "name": name,
        "type": "uiWarningIndicator",
        "displayString": label,
        "position": position,
        "hidden": hidden,
        "can_cancel": False,
    }


def app_ui(key, label, position, children):
    return {
        "name": key,
        "type": "uiApplication",
        "displayString": label,
        "hidden": False,
        "position": position,
        "defaultOpen": True,
        "children": children,
    }


def static_ui():
    """Native Doover UI objects with fresh values and portable app bindings."""
    tank = {
        "volume": numeric(
            "volume",
            "Volume",
            "last_volume",
            "ML",
            1,
            10,
            form="radialGauge",
            ranges=[
                {
                    "min": 0,
                    "max": 4,
                    "colour": "yellow",
                    "label": "Low",
                    "show_on_graph": True,
                },
                {
                    "min": 4,
                    "max": 8,
                    "colour": "blue",
                    "label": "Half",
                    "show_on_graph": True,
                },
                {
                    "min": 8,
                    "max": 10,
                    "colour": "green",
                    "label": "Full",
                    "show_on_graph": True,
                },
            ],
        ),
        "water_rl": numeric("water_rl", "Water RL", "last_rl", "m", 3, 20),
        "event_volume": numeric(
            "event_volume",
            "Event Volume",
            "event_volume",
            "ML",
            2,
            30,
            hidden="$tag.app().stop_event_hidden:boolean:true",
        ),
        "last_read": {
            "name": "last_read",
            "type": "uiTimestamp",
            "displayString": "Last Read",
            "showActivity": True,
            "position": 40,
            "hidden": False,
            "varType": "timestamp",
            "currentValue": "$tag.app().time_last_update:number:null",
        },
        # Both actions stay available because live input only changes ui_cmds.
        "start_event": button("start_event", "Start Event", 50),
        "stop_event": button("stop_event", "Stop Event", 60, "red"),
        "sensor_details": {
            "name": "sensor_details",
            "type": "uiSubmodule",
            "displayString": "Sensor Details",
            "position": 70,
            "hidden": False,
            "defaultOpen": False,
            "children": {
                "sensor_distance": numeric(
                    "sensor_distance",
                    "Sensor Distance",
                    "last_raw_distance",
                    "m",
                    3,
                    10,
                ),
                "measurement_reliability": numeric(
                    "measurement_reliability",
                    "Measurement Reliability",
                    "last_reliability",
                    "dB",
                    1,
                    20,
                ),
            },
        },
        "warning_indicator": warning(
            "warning_indicator",
            "$tag.app().warning_name:string",
            "$tag.app().warning_hidden:boolean:true",
            80,
        ),
    }
    power = {
        "battery_voltage": numeric(
            "battery_voltage",
            "Battery Voltage",
            "system_voltage",
            "V",
            1,
            10,
            ranges=[
                {
                    "min": 11.5,
                    "max": 12.3,
                    "colour": "yellow",
                    "label": "Low",
                    "show_on_graph": True,
                },
                {
                    "min": 12.3,
                    "max": 13,
                    "colour": "blue",
                    "label": "Good",
                    "show_on_graph": True,
                },
                {
                    "min": 13,
                    "max": 14,
                    "colour": "green",
                    "label": "Charging",
                    "show_on_graph": True,
                },
                {
                    "min": 14,
                    "max": 14.5,
                    "colour": "red",
                    "label": "OverCharging",
                    "show_on_graph": True,
                },
            ],
        ),
        "low_battery_alarm": {
            "name": "low_battery_alarm",
            "type": "uiSlider",
            "displayString": "Low Battery Alarm",
            "position": 20,
            "hidden": False,
            "units": "V",
            "currentValue": "$cmds.app().low_battery_alarm::11.0",
            "default": 11.0,
            "min": 6,
            "max": 13,
            "stepSize": 0.25,
            "dualSlider": False,
            "isInverted": False,
        },
        "system_power": numeric(
            "system_power", "System Power", "system_power", "W", 1, 30
        ),
        "temperature": numeric(
            "temperature", "Temperature", "system_temperature", "°C", 1, 40
        ),
        "online_now": {
            "name": "online_now",
            "type": "uiVariable",
            "displayString": "Online Now",
            "position": 50,
            "hidden": False,
            "showActivity": True,
            "varType": "bool",
            "currentValue": "$tag.app().is_online:boolean:true",
        },
        "enable_immunity": button("enable_immunity", "Stay On For 30 Mins", 60),
        "low_battery": warning(
            "low_battery",
            "Low Battery",
            "$tag.app().low_batt_warning_hidden:boolean:true",
            70,
        ),
        "is_immune_warning": warning(
            "is_immune_warning",
            "$tag.app().immune_warning_text:string",
            "$tag.app().immune_warning_hidden:boolean:true",
            80,
        ),
        "about_to_sleep_warning": warning(
            "about_to_sleep_warning",
            "$tag.app().about_to_sleep_warning_text:string",
            "$tag.app().about_to_sleep_warning_hidden:boolean:true",
            90,
        ),
    }
    return {
        "state": {
            "children": {
                TANK: app_ui(TANK, "Water storage", 100, tank),
                POWER: app_ui(POWER, "Power & Battery", 120, power),
            }
        }
    }


def device_config():
    return {
        "schema_version": 1,
        "slug": "water-storage",
        "name": "Example Water Storage",
        "processor": {
            "app_key": "example_device",
            "application_name": "example_device",
        },
        "apps": [
            {
                "app_key": TANK,
                "application_name": TANK,
                "run": False,
                "config": {
                    "sensor_rl": SENSOR_M,
                    "full_rl": DEPTH_M,
                    "empty_rl": 0.0,
                    "modbus_id": 1,
                    "storage_curve": [
                        {"level": 0.0, "volume": 0.0},
                        {"level": DEPTH_M, "volume": CAPACITY_ML},
                    ],
                    "modbus_config": {
                        "bus_type": "serial",
                        "name": "example_bus",
                        "serial_port": "/dev/null",
                        "serial_baud": 9600,
                        "serial_method": "rtu",
                        "serial_data_bits": 8,
                        "serial_parity": "None",
                        "serial_stop_bits": 1,
                        "serial_timeout": 0.3,
                    },
                    "dv_app_position": 100,
                },
            },
            {
                "app_key": POWER,
                "application_name": POWER,
                "run": False,
                "config": {
                    "profile": "Regular (12V)",
                    "sleep_time_thresholds": [],
                    "min_awake_time_thresholds": [],
                    "override_shutdown_permission_in_minutes": 60,
                    "wakeon_voltage": None,
                    "victron_configs": [],
                    "dv_app_position": 120,
                },
            },
        ],
        "channels": [
            "ui_state",
            "tag_values",
            "ui_cmds",
            "deployment_config",
            "ui_overrides",
        ],
        "duration_ms": 30 * DAY,
        "interpolation": [
            {"path": [app, tag], "max_gap_ms": 6 * HOUR}
            for app, tags in (
                (
                    TANK,
                    ("last_volume", "last_rl", "last_raw_distance", "last_reliability"),
                ),
                (POWER, ("system_voltage", "system_power", "system_temperature")),
            )
            for tag in tags
        ],
        "inputs": [
            {"app_key": TANK, "method": "start_event", "value_type": "integer"},
            {"app_key": TANK, "method": "stop_event", "value_type": "integer"},
            {
                "app_key": POWER,
                "method": "low_battery_alarm",
                "value_type": "number",
                "min": 6,
                "max": 13,
            },
            {"app_key": POWER, "method": "enable_immunity", "value_type": "integer"},
        ],
    }


def generate_channels(config):
    samples = []
    for timestamp in timestamps():
        data = tags_at(timestamp)
        if timestamp == 0:
            samples.append(aggregate(data, timestamp_fields(data)))
        record = {
            "timestamp": timestamp,
            "kind": "message",
            "id": f"sample-{timestamp}",
            "data": data,
            "timestamp_fields": timestamp_fields(data),
        }
        if timestamp > 0:
            record["apply_to_aggregate"] = True
        samples.append(record)
    commands = []
    for index, (start, stop) in enumerate(EVENTS, 1):
        for timestamp, method in ((start, "start_event"), (stop, "stop_event")):
            commands.append(
                {
                    "timestamp": timestamp,
                    "kind": "message",
                    "id": f"event-{index}-{method}-rpc",
                    "data": {
                        "type": "rpc",
                        "app_key": TANK,
                        "method": method,
                        "request": timestamp,
                        "status": {"code": "success", "message": None},
                        "response": {"recorded": True},
                    },
                    "timestamp_fields": [{"path": ["request"], "unit": "ms"}],
                }
            )
            commands.append(
                {
                    "timestamp": timestamp,
                    "kind": "message",
                    "id": f"event-{index}-{method}-log",
                    "data": {
                        "type": "log",
                        "app_key": TANK,
                        "key": method,
                        "value": timestamp,
                    },
                    "timestamp_fields": [{"path": ["value"], "unit": "ms"}],
                }
            )
    commands.append(
        aggregate(
            {
                TANK: {"start_event": EVENTS[-1][0], "stop_event": EVENTS[-1][1]},
                POWER: {"low_battery_alarm": 11.0, "enable_immunity": None},
            },
            [
                {"path": [TANK, "start_event"], "unit": "ms"},
                {"path": [TANK, "stop_event"], "unit": "ms"},
            ],
        )
    )
    # This is the portable desired configuration only. The processor adapter
    # reconciles it with newly installed app identities, never with source IDs.
    deployment = {
        "applications": {app["app_key"]: dict(app["config"]) for app in config["apps"]}
    }
    return {
        "ui_state": [aggregate(static_ui())],
        "tag_values": samples,
        "ui_cmds": commands,
        "deployment_config": [aggregate(deployment)],
        "ui_overrides": [
            aggregate(
                {
                    "ops": [
                        {
                            "op": "patch",
                            "target": {"byName": config["processor"]["app_key"]},
                            "changes": {"hidden": True},
                        }
                    ]
                }
            )
        ],
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def verify_written_dataset(directory):
    config = json.loads((directory / "config.json").read_text())
    channels = {
        name: json.loads((directory / "channels" / f"{name}.json").read_text())
        for name in config["channels"]
    }
    samples = [row for row in channels["tag_values"] if row["kind"] == "message"]
    assert [row["timestamp"] for row in samples] == timestamps()
    assert samples[0]["timestamp"] == -90 * DAY and samples[-1]["timestamp"] == 30 * DAY
    assert all(row["timestamp"] <= 0 for row in channels["ui_cmds"])
    assert (
        len([row for row in channels["tag_values"] if row["kind"] == "aggregate"]) == 1
    )
    for sample in samples:
        tank = sample["data"][TANK]
        assert 0 <= tank["last_volume"] <= CAPACITY_ML
        assert math.isclose(
            tank["last_rl"] * CAPACITY_ML / DEPTH_M, tank["last_volume"], abs_tol=1e-9
        )
        assert math.isclose(
            tank["last_rl"] + tank["last_raw_distance"], SENSOR_M, abs_tol=1e-9
        )
        if tank["event_active"]:
            assert math.isclose(
                tank["event_volume"],
                tank["last_volume"] - tank["event_initial_volume"],
                abs_tol=1e-9,
            )
        assert tank["time_last_update"] == sample["timestamp"]
    for start, stop in EVENTS:
        lookup = {sample["timestamp"]: sample for sample in samples}
        assert lookup[start - MINUTE]["data"][TANK]["event_active"] is False
        assert lookup[start]["data"][TANK]["event_active"] is True
        assert lookup[stop - MINUTE]["data"][TANK]["event_volume"] > 0
        assert lookup[stop]["data"][TANK]["event_active"] is False
    return config, channels, samples


def draw_charts(directory, samples):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    days = [row["timestamp"] / DAY for row in samples]
    values = [row["data"][TANK]["last_volume"] for row in samples]
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), constrained_layout=True)
    fig.suptitle(
        "Synthetic water storage • 10 ML • 4 m usable depth",
        fontsize=16,
        fontweight="bold",
    )
    axes[0].plot(days, values, color="#147d92", linewidth=1.3)
    axes[0].set(ylabel="Stored water (ML)", ylim=(0, 10), xlim=(-90, 30))
    axes[0].axvline(0, color="#243b53", linestyle="--", linewidth=1)
    axes[0].axvspan(0, 30, color="#e4f3ee", alpha=0.55)
    for index, (start, stop) in enumerate(EVENTS, 1):
        axes[0].axvspan(start / DAY, stop / DAY, color="#eeb44f", alpha=0.4)
        axes[0].text(start / DAY, 9.25, f"Event {index}", fontsize=8)
    axes[0].set_title(
        "90 days of history, then 30 future days. Gold bands mark historical input events.",
        loc="left",
        fontsize=10,
    )
    recent = [row for row in samples if -2 * DAY <= row["timestamp"] <= 2 * DAY]
    axes[1].plot(
        [row["timestamp"] / DAY for row in recent],
        [row["data"][POWER]["system_voltage"] for row in recent],
        color="#8b5eaa",
        marker=".",
        markersize=3,
    )
    axes[1].set(ylabel="Battery voltage (V)", xlim=(-2, 2), ylim=(12.3, 14.3))
    axes[1].axvline(0, color="#243b53", linestyle="--", linewidth=1)
    axes[1].set_title(
        "Fresh 12 V solar profile; stored points are 30 minutes apart near the anchor.",
        loc="left",
        fontsize=10,
    )
    gaps = [
        (samples[i]["timestamp"] - samples[i - 1]["timestamp"]) / MINUTE
        for i in range(1, len(samples))
    ]
    axes[2].plot(days[1:], gaps, color="#bb6727", linewidth=1)
    axes[2].set(
        ylabel="Sample interval (minutes)",
        xlabel="Days relative to installation midnight",
        xlim=(-90, 30),
        ylim=(0, 390),
    )
    axes[2].set_yticks([1, 30, 120, 360])
    axes[2].axvline(0, color="#243b53", linestyle="--", linewidth=1)
    for ax in axes:
        ax.grid(alpha=0.17)
    fig.savefig(directory / "timeline.png", dpi=150)
    plt.close(fig)

    start, stop = EVENTS[-1]
    event_samples = [
        row for row in samples if start - HOUR <= row["timestamp"] <= stop + HOUR
    ]
    fig, axes = plt.subplots(
        2, 1, figsize=(11, 6), sharex=True, constrained_layout=True
    )
    hours = [(row["timestamp"] - start) / HOUR for row in event_samples]
    axes[0].plot(
        hours,
        [row["data"][TANK]["last_volume"] for row in event_samples],
        color="#147d92",
        marker=".",
    )
    axes[0].set(
        ylabel="Stored water (ML)",
        title="Historical event: precomputed refill and matching input records",
    )
    axes[1].plot(
        hours,
        [row["data"][TANK]["event_volume"] for row in event_samples],
        color="#bb6727",
        marker=".",
    )
    axes[1].set(ylabel="Event volume (ML)", xlabel="Hours after Start Event")
    for ax in axes:
        ax.axvline(0, color="#243b53", linestyle="--", label="Start Event")
        ax.axvline(30, color="#bf4747", linestyle="--", label="Stop Event")
        ax.grid(alpha=0.17)
    axes[0].legend(loc="lower right")
    fig.savefig(directory / "historical-event.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "devices" / "water-storage",
    )
    parser.add_argument(
        "--charts-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "build" / "water-storage",
    )
    parser.add_argument("--charts", action="store_true")
    args = parser.parse_args()
    config = device_config()
    channels = generate_channels(config)
    write_json(args.output / "config.json", config)
    for name, rows in channels.items():
        write_json(args.output / "channels" / f"{name}.json", rows)
    config, channels, samples = verify_written_dataset(args.output)
    if args.charts:
        args.charts_dir.mkdir(parents=True, exist_ok=True)
        draw_charts(args.charts_dir, samples)
    counts = {
        name: dict(Counter(row["kind"] for row in records))
        for name, records in channels.items()
    }
    print(
        json.dumps(
            {
                "dataset": str(args.output),
                "channels": counts,
                "telemetry_samples": len(samples),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate 90 days of VSD operation and 30 days of command-responsive playback."""

import argparse
import hashlib
from pathlib import Path

from generate_water_storage import (
    DAY,
    HOUR,
    MINUTE,
    aggregate,
    app_ui,
    button,
    numeric,
    write_json,
)

from example_device.dataset import load_directory
from example_device.models import TRUSTED_REPOSITORY, ModelSpec, load_model

APP = "schneider_vsd"
ROOT = Path(__file__).resolve().parents[1]


def historical_commands():
    events = []
    for day in range(-90, 0):
        if day % 7 == 0:  # Maintenance/rest day each week.
            continue
        start = day * DAY + (6 + day % 3) * HOUR
        for timestamp, method, value in (
            (start - MINUTE, "frequency_setpoint", 30 + day % 5 * 3),
            (start, "start", start),
            (day * DAY + 11 * HOUR, "frequency_setpoint", 45 + day % 3 * 2),
            (day * DAY + 15 * HOUR, "frequency_setpoint", 32 + day % 4 * 2),
            (
                day * DAY + (18 + day % 2) * HOUR,
                "stop",
                day * DAY + (18 + day % 2) * HOUR,
            ),
        ):
            events.append((timestamp, method, value))
    return sorted(events)


def static_ui():
    fields = {}
    for index, (key, label, tag, unit, precision) in enumerate(
        (
            ("speed", "Speed", "vsd_frequency", "Hz", 1),
            ("motor_power", "Motor Power", "vsd_power", "kW", 2),
            ("thermal_load", "Drive Thermal Load", "drive_thermal_load", "%", 1),
            ("mains_voltage", "Mains Voltage", "mains_voltage", "V", 0),
            ("total_hours", "Total Hours", "total_hours", "hrs", 1),
            ("motor_voltage", "Motor Output Voltage", "vsd_voltage", "V", 1),
            ("motor_current", "Motor Current", "vsd_current", "A", 1),
            ("energy", "Energy", "energy_kwh", "kWh", 1),
        ),
        1,
    ):
        fields[key] = numeric(key, label, tag, unit, precision, index * 10)
    fields["flow_switch"] = {
        "name": "flow_switch",
        "type": "uiVariable",
        "displayString": "Flow Switch",
        "varType": "bool",
        "currentValue": "$tag.app().flow_switch:boolean:false",
        "showActivity": True,
        "position": 90,
        "hidden": False,
    }
    fields["frequency_setpoint"] = {
        "name": "frequency_setpoint",
        "type": "uiSlider",
        "displayString": "Frequency Setpoint",
        "position": 100,
        "hidden": False,
        "units": "Hz",
        "min": 0,
        "max": 50,
        "stepSize": 1,
        "default": 35,
        "dualSlider": False,
        "isInverted": False,
        "currentValue": "$cmds.app().frequency_setpoint::35",
    }
    for method, label, colour, position in (
        ("start", "Start", "blue", 110),
        ("stop", "Stop", "red", 120),
    ):
        fields[method] = button(method, label, position, colour)
        fields[method]["hidden"] = f"$tag.app().hide_{method}_button:boolean:false"
    ui = app_ui(APP, "$tag.app().app_display_name:string:Example VSD", 100, fields)
    return {"state": {"children": {APP: ui}}}


def generate(output):
    raw = (ROOT / "devices/vsd/model.py").read_bytes()
    initial_state = {
        "speed_hz": 0,
        "thermal_pct": 20,
        "total_hours": 0,
        "energy_kwh": 0,
        "elapsed_s": 0,
    }
    commands = {"running": False, "frequency": 35}
    spec = ModelSpec(
        "vsd-v1", APP, hashlib.sha256(raw).hexdigest(), initial_state, commands
    )
    model = load_model(TRUSTED_REPOSITORY, "vsd", spec, raw)
    events = historical_commands()
    times = set(range(-90 * DAY, -45 * DAY, 6 * HOUR))
    times.update(range(-45 * DAY, -14 * DAY, 2 * HOUR))
    times.update(range(-14 * DAY, 30 * DAY + 1, 30 * MINUTE))
    for stamp, _, _ in events:
        times.add(stamp)
        if stamp >= -14 * DAY:
            times.update(stamp + dt for dt in (-MINUTE, 15_000, MINUTE))
    state, previous, index = initial_state, -90 * DAY, 0
    samples, logs, baseline_state, baseline_commands = [], [], None, None
    latest_inputs = {"start": None, "stop": None, "frequency_setpoint": 35}
    for stamp in sorted(times):
        state, tags = model.step(state, commands, (stamp - previous) / 1000)
        while index < len(events) and events[index][0] == stamp:
            _, method, value = events[index]
            commands = model.command(state, commands, method, value)
            latest_inputs[method] = value
            for kind in ("rpc", "log"):
                data = {"type": kind, "app_key": APP}
                if kind == "rpc":
                    data.update(
                        method=method,
                        request=value,
                        status={"code": "success"},
                        response={"recorded": True},
                    )
                else:
                    data.update(key=method, value=value)
                row = {
                    "timestamp": stamp,
                    "kind": "message",
                    "id": f"command-{index}-{kind}",
                    "data": data,
                }
                if method in ("start", "stop"):
                    row["timestamp_fields"] = [
                        {
                            "path": ["request" if kind == "rpc" else "value"],
                            "unit": "ms",
                        }
                    ]
                logs.append(row)
            index += 1
        state, tags = model.step(state, commands, 0)
        tags["time_last_update"] = stamp
        data = {APP: tags}
        fields = [{"path": [APP, "time_last_update"], "unit": "ms"}]
        if stamp == 0:
            baseline_state, baseline_commands = dict(state), dict(commands)
            samples.append(aggregate(data, fields))
        row = {
            "timestamp": stamp,
            "kind": "message",
            "id": f"sample-{stamp}",
            "data": data,
            "timestamp_fields": fields,
        }
        if stamp > 0:
            row["apply_to_aggregate"] = True
        samples.append(row)
        previous = stamp
    config = {
        "schema_version": 1,
        "slug": "vsd",
        "name": "Example VSD",
        "processor": {
            "app_key": "example_device",
            "application_name": "example_device",
        },
        "apps": [
            {
                "app_key": APP,
                "application_name": "schneider_vsd",
                "run": False,
                "config": {
                    "vsd_type": "atv600",
                    "modbus_host": "127.0.0.1",
                    "modbus_port": 502,
                    "modbus_unit_id": 1,
                    "max_frequency_hz": 50,
                    "min_frequency_hz": 0,
                    "motor_rated_power_kw": 7.5,
                    "di_2_name": "Flow Switch",
                    "dv_app_position": 100,
                },
            }
        ],
        "channels": [
            "ui_state",
            "tag_values",
            "ui_cmds",
            "deployment_config",
            "ui_overrides",
        ],
        "duration_ms": 30 * DAY,
        "inputs": [
            {"app_key": APP, "method": "start", "value_type": "integer"},
            {"app_key": APP, "method": "stop", "value_type": "integer"},
            {
                "app_key": APP,
                "method": "frequency_setpoint",
                "value_type": "number",
                "min": 0,
                "max": 50,
            },
        ],
    }
    config["apps"][0]["config"]["example_model"] = {
        "name": spec.name,
        "sha256": spec.sha256,
        "initial_state": baseline_state,
        "initial_commands": baseline_commands,
    }
    logs.append(
        aggregate(
            {APP: latest_inputs},
            [{"path": [APP, method], "unit": "ms"} for method in ("start", "stop")],
        )
    )
    channels = {
        "ui_state": [aggregate(static_ui())],
        "tag_values": samples,
        "ui_cmds": logs,
        "deployment_config": [
            aggregate({"applications": {APP: config["apps"][0]["config"]}})
        ],
        "ui_overrides": [
            aggregate(
                {
                    "ops": [
                        {
                            "op": "patch",
                            "target": {"byName": "example_device"},
                            "changes": {"hidden": True},
                        }
                    ]
                }
            )
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    if (output / "model.py").resolve() != (ROOT / "devices/vsd/model.py").resolve():
        (output / "model.py").write_bytes(raw)
    write_json(output / "config.json", config)
    for name, rows in channels.items():
        write_json(output / "channels" / f"{name}.json", rows)
    dataset = load_directory(output)
    print(
        f"Validated {output}: {len(samples) - 1} telemetry samples, {len(events)} historical commands, {dataset.duration_ms // DAY} future days"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "devices/vsd")
    generate(parser.parse_args().output)

"""Deterministic pump-drive example. No IO, globals holding state, or dependencies.

API version 1. State uses seconds and unrounded engineering values. A linear
frequency ramp and analytic integrals make results independent of tick frequency.
This is an illustrative centrifugal-pump profile, not a motor sizing model.
"""

import math

API_VERSION = 1


def validate(state, commands):
    bounds = {
        "speed_hz": (0, 50),
        "thermal_pct": (0, 100),
        "total_hours": (0, 1e9),
        "energy_kwh": (0, 1e12),
        "elapsed_s": (0, 1e12),
    }
    if set(state) != set(bounds):
        raise ValueError("Invalid VSD state fields")
    for key, (low, high) in bounds.items():
        value = state[key]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError(f"Invalid VSD state: {key}")
    if (
        set(commands) != {"running", "frequency"}
        or type(commands["running"]) is not bool
    ):
        raise ValueError("Invalid VSD commands")
    frequency = commands["frequency"]
    if (
        type(frequency) not in (int, float)
        or not math.isfinite(frequency)
        or not 0 <= frequency <= 50
    ):
        raise ValueError("Frequency must be between 0 and 50 Hz")


def command(commands, method, value):
    result = dict(commands)
    if method == "start":
        result["running"] = True
    elif method == "stop":
        result["running"] = False
    elif method == "frequency_setpoint":
        result["frequency"] = value
    else:
        raise ValueError("Unknown VSD command")
    return result


def step(state, commands, elapsed_seconds):
    target = commands["frequency"] if commands["running"] else 0.0
    start = state["speed_hz"]
    ramp_seconds = abs(target - start)  # 1 Hz per second, up and down.
    moving = min(elapsed_seconds, ramp_seconds)
    slope = 1.0 if target > start else -1.0
    speed = start + slope * moving if moving < ramp_seconds else target
    steady_seconds = elapsed_seconds - moving
    # Integral of frequency cubed across the ramp, then the steady interval.
    integral = (speed**4 - start**4) / (4 * slope) if moving else 0.0
    integral += target**3 * steady_seconds
    running_seconds = elapsed_seconds if target > 0 else moving
    heat_target = 20 + 60 * (target / 50) ** 2
    cooling_time = 1200 if heat_target > state["thermal_pct"] else 2400
    thermal = heat_target + (state["thermal_pct"] - heat_target) * math.exp(
        -elapsed_seconds / cooling_time
    )
    result = {
        "speed_hz": speed,
        "thermal_pct": thermal,
        "total_hours": state["total_hours"] + running_seconds / 3600,
        "energy_kwh": state["energy_kwh"] + 7.5 * integral / 50**3 / 3600,
        "elapsed_s": state["elapsed_s"] + elapsed_seconds,
    }
    power = 7.5 * (speed / 50) ** 3
    mains = 415 + 2 * math.sin(result["elapsed_s"] / 3600)
    status = "running" if speed > 0 else "ready"
    if speed != target:
        status = "starting" if speed < target else "slowing"
    tags = {
        "vsd_running": speed > 0,
        "vsd_state": status,
        "vsd_frequency": round(speed, 3),
        "vsd_power": round(power, 3),
        "vsd_power_pct": round(power / 7.5 * 100, 2),
        "vsd_current": round(power * 1000 / (math.sqrt(3) * mains * 0.9), 2),
        "vsd_voltage": round(415 * speed / 50, 1),
        "mains_voltage": round(mains, 1),
        "drive_thermal_load": round(thermal, 2),
        "total_hours": round(result["total_hours"], 6),
        "energy_kwh": round(result["energy_kwh"], 6),
        "flow_switch": speed >= 15,
        "frequency_setpoint": commands["frequency"],
        "hide_start_button": commands["running"],
        "hide_stop_button": not commands["running"],
        "app_display_name": "Example VSD : " + status.title(),
    }
    return result, tags

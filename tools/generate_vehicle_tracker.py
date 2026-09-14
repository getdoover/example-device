"""Sample the saved Bunnings journey into portable vehicle-tracker channels.

No Google requests or cloud writes. Route geometry stays unchanged; the itinerary uses the installation calendar.
"""

from __future__ import annotations

import argparse
import bisect
import calendar
import hashlib
import json
import math
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

DAY = 86_400_000
HOUR = 3_600_000
MINUTE = 60_000
HISTORY = 46 * DAY
FUTURE = 30 * DAY
RECENT = 7 * DAY
TRACKER = "digital_matter_processor-1"
MAINTENANCE = "maintenance_manager_1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "devices/vehicle-tracker"


def utc_ms(value):
    return round(datetime.fromisoformat(value).timestamp() * 1000)


def iso_ms(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def distance(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    delta = math.radians(b[1] - a[1])
    h = math.sin((lat2 - lat1) / 2) ** 2
    h += math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(min(1, h)))


def decode(encoded):
    values, number, shift = [], 0, 0
    for char in encoded:
        value = ord(char) - 63
        if not 0 <= value <= 63 or shift > 30:
            raise ValueError("Invalid route polyline")
        number |= (value & 31) << shift
        if value & 32:
            shift += 5
        else:
            values.append(~(number >> 1) if number & 1 else number >> 1)
            number = shift = 0
    if shift or len(values) % 2 or not values:
        raise ValueError("Incomplete route polyline")
    lat = lon = 0
    points = []
    for a, b in zip(values[::2], values[1::2]):
        lat += a
        lon += b
        points.append((lat / 100000, lon / 100000))
    return points


def bearing(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    return (
        math.degrees(
            math.atan2(
                math.sin(dlon) * math.cos(lat2),
                math.cos(lat1) * math.sin(lat2)
                - math.sin(lat1) * math.cos(lat2) * math.cos(dlon),
            )
        )
        % 360
    )


class RoadRoute:
    """Distance and position share the same fraction of a navigation step."""

    def __init__(self, route):
        self.duration = route["duration_s"]
        self.metres = route["distance_m"]
        self.steps = []
        self.ends = []
        self.raw_step_metres = sum(s["distance_m"] for s in route["steps"])
        scale = self.metres / self.raw_step_metres if self.raw_step_metres else 0
        elapsed = travelled = 0.0
        for step in route["steps"]:
            points = decode(step["polyline"])
            lengths = [0.0]
            for a, b in zip(points, points[1:]):
                lengths.append(lengths[-1] + distance(a, b))
            metres = step["distance_m"] * scale
            self.steps.append(
                (elapsed, travelled, step["duration_s"], metres, points, lengths)
            )
            elapsed += step["duration_s"]
            travelled += metres
            self.ends.append(elapsed)

    def at(self, seconds):
        seconds = min(self.duration, max(0, seconds))
        i = min(bisect.bisect_right(self.ends, seconds), len(self.steps) - 1)
        start, before, duration, metres, points, lengths = self.steps[i]
        fraction = min(1, max(0, (seconds - start) / duration)) if duration else 1
        target = lengths[-1] * fraction
        if lengths[-1] == 0:
            position, heading = points[-1], 0.0
        else:
            index = min(bisect.bisect_right(lengths, target), len(points) - 1)
            left = max(0, index - 1)
            span = lengths[index] - lengths[left]
            amount = (target - lengths[left]) / span if span else 0
            a, b = points[left], points[index]
            position = (a[0] + (b[0] - a[0]) * amount, a[1] + (b[1] - a[1]) * amount)
            heading = bearing(a, b)
        travelled = (
            self.metres if seconds == self.duration else before + metres * fraction
        )
        speed = metres / duration * 3.6 if duration and seconds < self.duration else 0.0
        return position, travelled, speed, heading


@lru_cache(maxsize=1)
def coordinate_timezones():
    from timezonefinder import TimezoneFinder

    return TimezoneFinder(in_memory=True)


@lru_cache(maxsize=500_000)
def coordinate_timezone(lat, lon):
    name = coordinate_timezones().timezone_at(lat=lat, lng=lon)
    if name is None:
        raise ValueError(f"No timezone for road coordinate {lat}, {lon}")
    return ZoneInfo(name)


def validate_road_calendar(journey):
    """Check every navigation vertex and at most 60 seconds between vertices."""
    routes = {r["id"]: r for r in journey["routes"]}
    for event in journey["events"]:
        if event["kind"] != "drive":
            continue
        start = datetime.fromisoformat(event["start_utc"])
        route = RoadRoute(routes[event["route_id"]])
        for elapsed, _, duration, _, points, lengths in route.steps:
            times = [
                duration * length / lengths[-1] if lengths[-1] else 0
                for length in lengths
            ]
            samples = [(0, points[0])]
            for i in range(1, len(points)):
                intervals = max(1, math.ceil((times[i] - times[i - 1]) / 60))
                for n in range(1, intervals + 1):
                    f = n / intervals
                    point = tuple(
                        a + f * (b - a) for a, b in zip(points[i - 1], points[i])
                    )
                    samples.append(
                        (times[i - 1] + f * (times[i] - times[i - 1]), point)
                    )
            samples.append((duration, points[-1]))
            for seconds, point in samples:
                local = (start + timedelta(seconds=elapsed + seconds)).astimezone(
                    coordinate_timezone(*point)
                )
                if not time(9) <= local.time() <= time(17):
                    raise ValueError(
                        f"{event['id']}: road coordinate {point} is outside 09:00–17:00 "
                        f"at {local.isoformat()}; replan this day for the requested calendar"
                    )


def schedule_journey(journey, anchor_date, anchor_timezone="Australia/Brisbane"):
    """Reuse route durations and daily stops on an explicit installation calendar.

    Overnight and ferry waits absorb UTC-offset changes. Fail if the saved daily
    route no longer fits, instead of silently moving driving outside local hours.
    """
    result = deepcopy(journey)
    zero = datetime.combine(anchor_date, time(), ZoneInfo(anchor_timezone))
    if zero.timestamp() * 1000 < 1735689600000:
        raise ValueError("Installation anchor must be on or after the Doover epoch")
    first_date = anchor_date - timedelta(days=46)
    events = [e for e in result["events"] if e.get("purpose") != "history_padding"]

    def local_hour(day, hour, zone):
        return datetime.combine(
            first_date + timedelta(days=day - 1), time(hour), ZoneInfo(zone)
        ).astimezone(timezone.utc)

    cursor = local_hour(1, 9, events[0]["timezone"])
    for event in events:
        start = cursor
        if event["kind"] == "overnight":
            cursor = local_hour(event["day"] + 1, 9, event["end_timezone"])
        elif event["kind"] == "wait":
            hour = 20 if event["purpose"] == "ferry_check_in" else 9
            cursor = local_hour(event["day"], hour, event["end_timezone"])
        else:
            cursor += timedelta(seconds=event["duration_s"])
        if cursor <= start:
            raise ValueError(
                f"{event['id']}: calendar leaves no time for the planned stay"
            )
        event.update(
            start_utc=start.isoformat(),
            end_utc=cursor.isoformat(),
            start_local=start.astimezone(ZoneInfo(event["timezone"])).isoformat(),
            end_local=cursor.astimezone(ZoneInfo(event["end_timezone"])).isoformat(),
            duration_s=(cursor - start).total_seconds(),
        )
        if event["kind"] == "drive":
            for field in ("start_local", "end_local"):
                local = datetime.fromisoformat(event[field])
                if not time(9) <= local.time() <= time(17):
                    raise ValueError(
                        f"{event['id']}: road travel at {local.isoformat()} is outside 09:00–17:00; "
                        "replan this day's stops for the requested calendar"
                    )
    history_start = zero.astimezone(timezone.utc) - timedelta(days=46)
    first = events[0]
    padding = {
        **first,
        "id": "history-padding",
        "kind": "wait",
        "purpose": "history_padding",
        "start_utc": history_start.isoformat(),
        "end_utc": first["start_utc"],
        "start_local": history_start.astimezone(
            ZoneInfo(first["timezone"])
        ).isoformat(),
        "end_local": first["start_local"],
        "duration_s": (
            datetime.fromisoformat(first["start_utc"]) - history_start
        ).total_seconds(),
        "notes": "Stationary history baseline before the first 09:00 Bunnings visit.",
    }
    if padding["duration_s"] <= 0:
        raise ValueError("History window starts after the first visit")
    result["events"] = [padding, *events]
    result["metadata"]["start_date"] = first_date.isoformat()
    result["metadata"]["calendar"] = {
        "anchor_date": anchor_date.isoformat(),
        "anchor_timezone": anchor_timezone,
        "anchor_ms": round(zero.timestamp() * 1000),
        "policy": "46 elapsed days of history before local midnight; 30 elapsed days of future data. "
        "Daily road trips start at 09:00 local, with original route and visit durations. "
        "Overnight waits use the installation calendar and IANA daylight-saving rules.",
    }
    result["summary"]["duration_s"] = (cursor - history_start).total_seconds()
    validate_road_calendar(result)
    return result


class JourneySampler:
    def __init__(self, journey):
        self.journey = journey
        self.events = journey["events"]
        self.starts = [utc_ms(e["start_utc"]) for e in self.events]
        self.ends = [utc_ms(e["end_utc"]) for e in self.events]
        self.start = self.starts[0]
        self.zero = journey["metadata"]["calendar"]["anchor_ms"]
        self.end = self.zero + FUTURE
        self.routes = {r["id"]: RoadRoute(r) for r in journey["routes"]}
        self.places = {
            p["id"]: p
            for p in journey["stores"]
            + journey["accommodations"]
            + journey["transport_places"]
        }
        self.road_before, self.engine_before = [], []
        metres = hours = 0.0
        for event in self.events:
            self.road_before.append(metres)
            self.engine_before.append(hours)
            if event["kind"] == "drive":
                metres += event["distance_m"]
                hours += event["duration_s"] / 3600
        self.total_metres, self.total_hours = metres, hours
        start = datetime.fromtimestamp(
            self.start / 1000, ZoneInfo(self.events[0]["timezone"])
        )
        month = start.month + 6
        year = start.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        due = start.replace(
            year=year,
            month=month,
            day=min(start.day, calendar.monthrange(year, month)[1]),
        )
        self.service_due = round(due.timestamp() * 1000)

    def event_index(self, source_ms):
        return max(
            0,
            min(bisect.bisect_right(self.starts, source_ms) - 1, len(self.events) - 1),
        )

    def totals(self, source_ms):
        if source_ms <= self.start:
            return 0.0, 0.0
        i = self.event_index(source_ms)
        event = self.events[i]
        metres, hours = self.road_before[i], self.engine_before[i]
        if event["kind"] == "drive":
            elapsed = min(event["duration_s"], (source_ms - self.starts[i]) / 1000)
            metres += self.routes[event["route_id"]].at(elapsed)[1]
            hours += elapsed / 3600
        return metres, hours

    def snapshot(self, offset):
        source_ms = self.zero + offset
        i = self.event_index(source_ms)
        event = self.events[i]
        elapsed = (source_ms - self.starts[i]) / 1000
        moving = event["kind"] in ("drive", "ferry") and source_ms < self.ends[i]
        ignition = event["kind"] == "drive" and moving
        speed = heading = 0.0
        if moving:
            position, _, speed, heading = self.routes[event["route_id"]].at(elapsed)
        else:
            place = self.places[event["place_id"]]
            position = (place["lat"], place["lon"])
        metres, hours = self.totals(source_ms)
        old_metres, old_hours = self.totals(source_ms - 14 * DAY)
        daily_km = (metres - old_metres) / 1000 / 14
        daily_hours = (hours - old_hours) / 14
        km_remaining = 10000 - metres / 1000
        next_service = self.service_due
        if daily_km > 0:
            next_service = min(
                next_service, source_ms + round(max(0, km_remaining) / daily_km * DAY)
            )
        ambient = 22 + 6 * math.sin(2 * math.pi * ((source_ms / DAY) % 1))
        tracker = {
            "speed": round(speed, 3),
            "heading_degrees": round(heading, 2),
            "gps_accuracy": 4 if moving else 6,
            "ignition_on": ignition,
            "run_hours": round(hours, 6),
            "odometer_km": round(metres / 1000, 6),
            "system_voltage": 13.8 if ignition else 12.6,
            "battery_voltage": round(max(3.65, 4.08 - metres / 1000 * 0.0002), 3),
            "signal_strength": round(75 + 15 * math.sin(source_ms / HOUR / 8), 1),
            "device_temp": round(
                ambient + 2.5 + (min(5, speed / 20) if ignition else 0), 1
            ),
            "analog_input_v": None,
            "uplink_reason": {
                "drive": "Driving",
                "visit": "Bunnings stop",
                "overnight": "Parked overnight",
                "ferry": "Ferry crossing (engine off)",
                "wait": "Parked",
            }[event["kind"]],
            "device_time": offset,
        }
        maintenance = {
            "engine_hours": tracker["run_hours"],
            "machine_odometer": tracker["odometer_km"],
            "ave_hours_per_day": round(daily_hours, 6),
            "ave_kms_per_day": round(daily_km, 6),
            "last_service_date": -HISTORY,
            "last_service_hours": 0,
            "last_service_odometer": 0,
            "kms_till_next_service": round(km_remaining, 6),
            "days_till_next_service": round((self.service_due - source_ms) / DAY, 6),
            "next_service_est": next_service - self.zero,
        }
        return {
            "offset_ms": offset,
            "source_utc": iso_ms(source_ms),
            "event_id": event["id"],
            "event_kind": event["kind"],
            "location": {"lat": round(position[0], 7), "long": round(position[1], 7)},
            "tags": {TRACKER: tracker, MAINTENANCE: maintenance},
        }


def sample_times(sampler):
    regular = set(range(-HISTORY, -RECENT, HOUR))
    regular.update(range(-RECENT, FUTURE + 1, 10 * MINUTE))
    # Arrivals/departures preserve short trips and ignition changes between ticks.
    transitions = {
        t - sampler.zero
        for t in sampler.starts + sampler.ends
        if sampler.start <= t <= sampler.end
    }
    return sorted(regular | transitions), regular, transitions


def timestamp_fields():
    return [
        {"path": [TRACKER, "device_time"], "unit": "ms"},
        {"path": [MAINTENANCE, "last_service_date"], "unit": "ms"},
        {"path": [MAINTENANCE, "next_service_est"], "unit": "ms"},
    ]


def aggregate(data, fields=None):
    row = {"timestamp": 0, "kind": "aggregate", "mode": "merge", "data": data}
    if fields:
        row["timestamp_fields"] = fields
    return row


def generate(sampler, applications, ui):
    times, regular, transitions = sample_times(sampler)
    samples = []
    location, tags = [], []
    for timestamp in times:
        sample = sampler.snapshot(timestamp)
        sample["sample_reason"] = (
            "regular_and_transition"
            if timestamp in regular and timestamp in transitions
            else "regular"
            if timestamp in regular
            else "transition"
        )
        samples.append(sample)
        for rows, payload, fields in (
            (location, sample["location"], []),
            (tags, sample["tags"], timestamp_fields()),
        ):
            if timestamp == 0:
                rows.append(aggregate(deepcopy(payload), fields))
            row = {
                "timestamp": timestamp,
                "kind": "message",
                "id": f"sample-{timestamp}",
                "data": payload,
            }
            if fields:
                row["timestamp_fields"] = fields
            if timestamp > 0:
                row["apply_to_aggregate"] = True
            rows.append(row)
    config = {
        "schema_version": 1,
        "slug": "vehicle-tracker",
        "name": "Bunnings vehicle tracker example",
        "processor": {
            "app_key": "example_device",
            "application_name": "example_device",
        },
        "apps": deepcopy(applications),
        "channels": ["ui_state", "tag_values", "location", "deployment_config"],
        "duration_ms": FUTURE,
        "required_anchor_ms": sampler.zero,
        "interpolation": [],
        "inputs": [],
    }
    channels = {
        "ui_state": [aggregate(deepcopy(ui))],
        "tag_values": tags,
        "location": location,
        "deployment_config": [
            aggregate(
                {
                    "applications": {
                        app["app_key"]: app["config"] for app in config["apps"]
                    }
                }
            )
        ],
    }
    return config, channels, samples


def load_journey(raw):
    journey_path = raw / "journey.json"
    content = journey_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    journey = json.loads(content)
    if journey["metadata"]["status"] != "complete":
        raise ValueError("Journey is incomplete")
    source_end = utc_ms(journey["events"][-1]["end_utc"])
    export_end = utc_ms(journey["events"][0]["start_utc"]) + HISTORY + FUTURE
    if export_end > source_end or any(
        utc_ms(e["end_utc"]) > export_end
        for e in journey["events"]
        if e["kind"] != "overnight"
    ):
        raise ValueError("The 76-day export must include all movement and visits")
    return journey, digest


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "journey.json":
        path.write_text(
            json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            + "\n"
        )
    elif path.parent.name == "channels":
        # One record per line keeps long histories below the loader's 8 MiB limit.
        records = [
            json.dumps(row, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            for row in data
        ]
        path.write_text("[\n" + ",\n".join(records) + "\n]\n")
    else:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        )


def export(
    raw, output, template=DEFAULT_OUTPUT, anchor_date=None, anchor_timezone=None
):
    from example_device.dataset import load_directory, parse_dataset

    journey = json.loads((raw / "journey.json").read_text())
    if journey["metadata"]["status"] != "complete":
        raise ValueError("Journey is incomplete")
    saved_calendar = journey["metadata"].get("calendar", {})
    if anchor_date is None:
        if "anchor_date" not in saved_calendar:
            raise ValueError("Specify --anchor-date for the installation calendar")
        anchor_date = date.fromisoformat(saved_calendar["anchor_date"])
    anchor_timezone = anchor_timezone or saved_calendar.get(
        "anchor_timezone", "Australia/Brisbane"
    )
    journey = schedule_journey(journey, anchor_date, anchor_timezone)
    # Validate the complete window before publishing any generated files.
    export_end = journey["metadata"]["calendar"]["anchor_ms"] + FUTURE
    if any(
        utc_ms(e["end_utc"]) > export_end
        for e in journey["events"]
        if e["kind"] != "overnight"
    ):
        raise ValueError("The export would omit movement or visits")
    write_json(raw / "journey.json", journey)
    journey, digest = load_journey(raw)
    sampler = JourneySampler(journey)
    template_config = json.loads((template / "config.json").read_text())
    template_ui = json.loads((template / "channels/ui_state.json").read_text())
    config, channels, samples = generate(
        sampler, template_config["apps"], template_ui[0]["data"]
    )
    parse_dataset(config, channels)
    write_json(output / "config.json", config)
    for channel, rows in channels.items():
        write_json(output / "channels" / f"{channel}.json", rows)
    from example_device.source import MAX_DATASET_BYTES, MAX_FILE_BYTES

    files = [output / "config.json"] + [
        output / "channels" / f"{name}.json" for name in channels
    ]
    if (
        any(path.stat().st_size > MAX_FILE_BYTES for path in files)
        or sum(path.stat().st_size for path in files) > MAX_DATASET_BYTES
    ):
        raise ValueError("Export exceeds the runtime dataset download size limits")
    load_directory(output)
    zero = next(s for s in samples if s["offset_ms"] == 0)
    policy = {
        "journey_sha256": digest,
        "source_start_utc": iso_ms(sampler.start),
        "calendar": journey["metadata"]["calendar"],
        "source_zero_utc": iso_ms(sampler.zero),
        "source_export_end_utc": iso_ms(sampler.end),
        "history_days": 46,
        "future_days": 30,
        "cadence": [
            {
                "from_ms": -HISTORY,
                "until_ms": -RECENT,
                "interval_ms": HOUR,
                "end_inclusive": False,
            },
            {
                "from_ms": -RECENT,
                "until_ms": FUTURE,
                "interval_ms": 10 * MINUTE,
                "end_inclusive": True,
            },
        ],
        "extra_samples": "Exact event starts and ends, deduplicated against regular ticks.",
        "cutoff_note": "Export includes 46 elapsed days before midnight zero and 30 elapsed days after it. Stationary padding before the first 09:00 visit keeps the history window exact. Any remaining final parked accommodation stays in raw data only; its length is source_parked_tail_omitted_ms. All travel and all 334 visits are included.",
        "source_parked_tail_omitted_ms": sampler.ends[-1] - sampler.end,
        "counter_baseline": {"odometer_km": 0, "run_hours": 0},
        "counter_policy": "Integrate Google road step distances and durations, normalizing step distance totals to route totals. Ferry movement adds neither road odometer nor engine hours.",
        "speed_policy": "Instantaneous GPS ground speed from the active navigation step; positive aboard the moving ferry with ignition off.",
        "timestamp_policy": "device_time and maintenance dates are numeric millisecond offsets declared in timestamp_fields and rebound to the runtime anchor; source UTC dates stay in this raw review export.",
        "interpolation_policy": "Hold each paired location/telemetry observation until the next sample. Numeric tag interpolation is disabled so ignition, location and counters stay on the same observation.",
        "maintenance_policy": "Synthetic service at trip start, 10000 km and six source-calendar months, trailing 14-day use. No later service is invented; overdue kilometres remain negative. No engine-hour service interval is configured.",
        "secondary_fields": "Deterministic simulator-style voltage, temperature and signal values. Analog input is unknown; altitude is omitted because the route is two-dimensional.",
        "channels": {
            name: dict(Counter(r["kind"] for r in rows))
            for name, rows in channels.items()
        },
        "tracking_samples": len(samples),
        "sample_reasons": dict(Counter(s["sample_reason"] for s in samples)),
        "period_counts": {
            "older_history": sum(s["offset_ms"] < -RECENT for s in samples),
            "recent_history": sum(-RECENT <= s["offset_ms"] < 0 for s in samples),
            "zero": 1,
            "future": sum(s["offset_ms"] > 0 for s in samples),
        },
        "zero_snapshot": zero,
        "final_snapshot": samples[-1],
        "total_road_km": sampler.total_metres / 1000,
        "total_engine_hours": sampler.total_hours,
    }
    write_json(raw / "sampling-policy.json", policy)
    write_json(
        raw / "tracking-samples.json",
        {
            "journey_sha256": digest,
            "zero_utc": iso_ms(sampler.zero),
            "samples": samples,
        },
    )
    print(
        json.dumps(
            {
                k: policy[k]
                for k in (
                    "tracking_samples",
                    "period_counts",
                    "channels",
                    "source_zero_utc",
                    "total_road_km",
                    "total_engine_hours",
                )
            },
            indent=2,
        )
    )
    return policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=DEFAULT_OUTPUT / "raw")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Existing example config and static UI to preserve",
    )
    parser.add_argument(
        "--anchor-date",
        type=date.fromisoformat,
        help="Installation zero date (YYYY-MM-DD); reuse the saved calendar when omitted",
    )
    parser.add_argument(
        "--anchor-timezone",
        help="IANA timezone for midnight zero; defaults to Australia/Brisbane",
    )
    args = parser.parse_args()
    export(args.raw, args.output, args.template, args.anchor_date, args.anchor_timezone)


if __name__ == "__main__":
    main()

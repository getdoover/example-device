"""Verify route sampling and the actual exported device through local replay."""

import asyncio
import hashlib
import importlib.util
import json
import math
from datetime import datetime
from pathlib import Path

import pytest

from example_device.dataset import load_directory
from example_device.runtime import Runtime
from example_device.simulator import MemoryTransport
from example_device.timeline import rebase_data

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / "devices/vehicle-tracker"
spec = importlib.util.spec_from_file_location(
    "generate_vehicle_tracker", ROOT / "tools/generate_vehicle_tracker.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
TRACKER = generator.TRACKER
MAINTENANCE = generator.MAINTENANCE
DAY = 86_400_000


def millis(value):
    return round(datetime.fromisoformat(value).timestamp() * 1000)


def polyline(points):
    result, previous = [], (0, 0)
    for lat, lon in points:
        current = round(lat * 100000), round(lon * 100000)
        for value in (current[0] - previous[0], current[1] - previous[1]):
            value = ~(value << 1) if value < 0 else value << 1
            while value >= 32:
                result.append(chr((32 | (value & 31)) + 63))
                value >>= 5
            result.append(chr(value + 63))
        previous = current
    return "".join(result)


@pytest.fixture(scope="module")
def exported():
    journey = json.loads((DEVICE / "raw/journey.json").read_text())
    policy = json.loads((DEVICE / "raw/sampling-policy.json").read_text())
    samples = json.loads((DEVICE / "raw/tracking-samples.json").read_text())["samples"]
    dataset = load_directory(DEVICE)
    return journey, policy, samples, dataset


def test_bent_road_follows_vertices_and_normalizes_counter_distance():
    route = generator.RoadRoute(
        {
            "duration_s": 100,
            "distance_m": 2200,
            "steps": [
                {
                    "duration_s": 100,
                    "distance_m": 2000,
                    "polyline": polyline([(0, 0), (0, 0.01), (0.01, 0.01)]),
                }
            ],
        }
    )
    point, metres, speed, heading = route.at(25)
    assert point == pytest.approx((0, 0.005))
    assert metres == 550
    assert speed == 79.2
    assert heading == 90
    assert route.at(50)[0] == pytest.approx((0, 0.01))
    assert route.at(100)[1:3] == (2200, 0)


def test_counter_uses_step_timing_instead_of_average_route_speed():
    route = generator.RoadRoute(
        {
            "duration_s": 100,
            "distance_m": 1000,
            "steps": [
                {
                    "duration_s": 20,
                    "distance_m": 100,
                    "polyline": polyline([(0, 0), (0, 0.001)]),
                },
                {
                    "duration_s": 80,
                    "distance_m": 900,
                    "polyline": polyline([(0, 0.001), (0, 0.01)]),
                },
            ],
        }
    )
    assert route.at(10)[1] == 50
    assert route.at(10)[2] == 18
    assert route.at(20)[1] == 100
    assert route.at(60)[1] == 550
    assert route.at(60)[2] == 40.5


def test_export_cadence_zero_and_coverage(exported):
    journey, policy, samples, dataset = exported
    source_start = millis(journey["events"][0]["start_utc"])
    zero = millis(policy["source_zero_utc"])
    assert zero - source_start == 46 * DAY
    assert dataset.duration_ms == 30 * DAY
    assert samples[0]["offset_ms"] == -46 * DAY
    assert samples[-1]["offset_ms"] == 30 * DAY
    assert millis(policy["source_export_end_utc"]) - zero == 30 * DAY
    assert policy["source_parked_tail_omitted_ms"] == 90 * 60_000
    regular = set(range(-46 * DAY, -7 * DAY, 3_600_000))
    regular.update(range(-7 * DAY, 30 * DAY + 1, 600_000))
    boundaries = {
        millis(event[field]) - zero
        for event in journey["events"]
        for field in ("start_utc", "end_utc")
        if -46 * DAY <= millis(event[field]) - zero <= 30 * DAY
    }
    actual = [s["offset_ms"] for s in samples]
    assert actual == sorted(regular | boundaries)
    assert len(actual) == len(set(actual))
    assert {
        s["offset_ms"] for s in samples if "regular" in s["sample_reason"]
    } == regular
    visited = {s["event_id"] for s in samples if s["event_kind"] == "visit"}
    assert visited == {e["id"] for e in journey["events"] if e["kind"] == "visit"}
    assert len(visited) == 334
    for event in journey["events"]:
        if event["kind"] != "overnight":
            assert millis(event["end_utc"]) <= zero + 30 * DAY


def test_channels_pair_every_sample_and_rebase_dates(exported):
    _, policy, samples, dataset = exported
    anchor = 1_893_456_000_000
    for channel, field in (("tag_values", "tags"), ("location", "location")):
        messages = [e for e in dataset.channels[channel] if e.kind == "message"]
        assert len(messages) == len(samples)
        for message, sample in zip(messages, samples):
            assert message.timestamp == sample["offset_ms"]
            assert message.data == sample[field]
            assert message.apply_to_aggregate == (message.timestamp > 0)
            if channel == "tag_values":
                rebound = rebase_data(message, anchor)
                assert rebound[TRACKER]["device_time"] == anchor + message.timestamp
                assert rebound[MAINTENANCE]["last_service_date"] == anchor - 46 * DAY
                assert (
                    rebound[MAINTENANCE]["next_service_est"]
                    == anchor + sample["tags"][MAINTENANCE]["next_service_est"]
                )
        aggregates = [e for e in dataset.channels[channel] if e.kind == "aggregate"]
        assert len(aggregates) == 1
        assert aggregates[0].data == policy["zero_snapshot"][field]
    assert not dataset.config.interpolation
    assert all(app.run is False for app in dataset.config.apps)
    ui = dataset.channels["ui_state"][0].data["state"]["children"]
    assert ui[TRACKER]["children"]["device_time_utc"]["type"] == "uiTimestamp"
    assert "config" not in ui[MAINTENANCE]["children"]


def test_all_counters_ignition_and_stationary_periods_match_raw_events(exported):
    journey, policy, samples, _ = exported
    events = {e["id"]: e for e in journey["events"]}
    routes = {r["id"]: r for r in journey["routes"]}
    road_before, hours_before = {}, {}
    road = hours = 0
    for e in journey["events"]:
        road_before[e["id"]], hours_before[e["id"]] = road, hours
        if e["kind"] == "drive":
            road += e["distance_m"] / 1000
            hours += e["duration_s"] / 3600
    previous_km = previous_hours = 0
    for sample in samples:
        e = events[sample["event_id"]]
        tags = sample["tags"][TRACKER]
        service = sample["tags"][MAINTENANCE]
        source = millis(sample["source_utc"])
        assert tags["ignition_on"] == (e["kind"] == "drive")
        assert tags["system_voltage"] == (13.8 if e["kind"] == "drive" else 12.6)
        assert tags["odometer_km"] >= previous_km
        assert tags["run_hours"] >= previous_hours
        previous_km, previous_hours = tags["odometer_km"], tags["run_hours"]
        expected_hours = hours_before[e["id"]]
        if e["kind"] == "drive":
            expected_hours += (source - millis(e["start_utc"])) / 3_600_000
            route = routes[e["route_id"]]
            remaining_seconds = (source - millis(e["start_utc"])) / 1000
            step_metres = 0
            for step in route["steps"]:
                if step["duration_s"] <= remaining_seconds:
                    step_metres += step["distance_m"]
                    remaining_seconds -= step["duration_s"]
                else:
                    step_metres += (
                        step["distance_m"] * remaining_seconds / step["duration_s"]
                    )
                    break
            route_metres = (
                step_metres
                * route["distance_m"]
                / sum(step["distance_m"] for step in route["steps"])
            )
            assert tags["odometer_km"] == pytest.approx(
                road_before[e["id"]] + route_metres / 1000, abs=1e-6
            )
        else:
            assert tags["odometer_km"] == pytest.approx(road_before[e["id"]], abs=1e-6)
        assert tags["run_hours"] == pytest.approx(expected_hours, abs=1e-6)
        if e["kind"] not in ("drive", "ferry"):
            assert tags["speed"] == 0
            place = next(
                p
                for p in journey["stores"]
                + journey["accommodations"]
                + journey["transport_places"]
                if p["id"] == e["place_id"]
            )
            assert sample["location"] == pytest.approx(
                {"lat": place["lat"], "long": place["lon"]}, abs=1e-7
            )
        assert service["engine_hours"] == tags["run_hours"]
        assert service["machine_odometer"] == tags["odometer_km"]
        assert service["kms_till_next_service"] == pytest.approx(
            10000 - tags["odometer_km"], abs=1e-6
        )
        assert all(
            math.isfinite(value)
            for value in tags.values()
            if type(value) in (int, float)
        )
    assert previous_km == pytest.approx(road, abs=1e-6)
    assert previous_hours == pytest.approx(hours, abs=1e-6)
    assert road == pytest.approx(journey["summary"]["distance_m"] / 1000)
    assert previous_km == policy["total_road_km"]


def test_ferry_moves_without_road_distance_or_engine_hours(exported):
    _, _, samples, _ = exported
    ferry = [s for s in samples if s["event_kind"] == "ferry"]
    assert len(ferry) > 10
    assert len({tuple(s["location"].values()) for s in ferry}) > 10
    assert len({s["tags"][TRACKER]["odometer_km"] for s in ferry}) == 1
    assert len({s["tags"][TRACKER]["run_hours"] for s in ferry}) == 1
    assert all(not s["tags"][TRACKER]["ignition_on"] for s in ferry)
    assert any(s["tags"][TRACKER]["speed"] > 10 for s in ferry)


def test_generator_is_deterministic_and_keeps_raw_journey(exported, tmp_path):
    _, policy, _, _ = exported
    raw = DEVICE / "raw"
    before = hashlib.sha256((raw / "journey.json").read_bytes()).hexdigest()
    assert before == policy["journey_sha256"]
    journey, _ = generator.load_journey(raw)
    config_template = json.loads((DEVICE / "config.json").read_text())
    ui_template = json.loads((DEVICE / "channels/ui_state.json").read_text())
    config, channels, _ = generator.generate(
        generator.JourneySampler(journey),
        config_template["apps"],
        ui_template[0]["data"],
    )
    for name, data in {
        "config.json": config,
        **{f"channels/{k}.json": v for k, v in channels.items()},
    }.items():
        path = tmp_path / name
        generator.write_json(path, data)
        assert path.read_bytes() == (DEVICE / name).read_bytes()
    assert hashlib.sha256((raw / "journey.json").read_bytes()).hexdigest() == before


def test_real_runtime_imports_history_and_replays_paired_vehicle_state(exported):
    _, policy, samples, dataset = exported
    anchor = 1_893_456_000_000

    async def check():
        transport = MemoryTransport()
        runtime = Runtime(
            dataset,
            transport,
            anchor_ms=anchor,
            revision="vehicle-test",
            installation_id="vehicle-test",
            max_batches=1000,
        )

        async def advance(offset):
            while True:
                result = await runtime.run(anchor + offset, observed=True)
                if not result.needs_continuation:
                    return result

        await advance(0)
        assert transport.aggregates["location"] == policy["zero_snapshot"]["location"]
        assert (
            transport.aggregates["tag_values"][TRACKER]["odometer_km"]
            == policy["zero_snapshot"]["tags"][TRACKER]["odometer_km"]
        )
        assert transport.aggregates["tag_values"][TRACKER]["device_time"] == anchor
        assert len(transport.messages) == 2 * sum(s["offset_ms"] <= 0 for s in samples)
        departure = next(
            s for s in samples if s["offset_ms"] > 0 and s["event_kind"] == "drive"
        )
        await advance(departure["offset_ms"])
        assert transport.aggregates["location"] == departure["location"]
        assert transport.aggregates["tag_values"][TRACKER]["ignition_on"] is True
        # Viewed updates between records must keep telemetry and GPS together.
        await advance(departure["offset_ms"] + 1)
        assert (
            transport.aggregates["tag_values"][TRACKER]["device_time"]
            == anchor + departure["offset_ms"]
        )
        assert transport.aggregates["location"] == departure["location"]
        result = await advance(30 * DAY)
        assert result.phase == "exhausted"
        assert len(transport.messages) == 2 * len(samples)
        assert transport.aggregates["location"] == samples[-1]["location"]
        final = transport.aggregates["tag_values"][TRACKER]
        assert final["odometer_km"] == policy["total_road_km"]
        assert final["run_hours"] == pytest.approx(
            policy["total_engine_hours"], abs=1e-6
        )
        assert final["ignition_on"] is False
        assert final["device_time"] == anchor + 30 * DAY

    asyncio.run(check())


@pytest.mark.asyncio
async def test_export_downloads_through_real_source_loader(monkeypatch, exported):
    from urllib.parse import urlsplit

    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from example_device import source

    dataset = exported[3]
    prefix = "/example/repo/" + "a" * 40 + "/devices/vehicle-tracker/"
    files = {"config.json": (DEVICE / "config.json").read_bytes()}
    files.update(
        {
            f"channels/{name}.json": (DEVICE / "channels" / f"{name}.json").read_bytes()
            for name in dataset.config.channels
        }
    )
    assert max(map(len, files.values())) < source.MAX_FILE_BYTES
    assert sum(map(len, files.values())) < source.MAX_DATASET_BYTES
    calls = []

    async def respond(request):
        assert request.path.startswith(prefix)
        path = request.path.removeprefix(prefix)
        calls.append(path)
        return web.Response(body=files[path])

    app = web.Application()
    app.router.add_route("GET", "/{tail:.*}", respond)
    real_session = aiohttp.ClientSession
    async with TestServer(app) as server:

        class LocalSession:
            def __init__(self, **kwargs):
                self.session = real_session(**kwargs)

            async def __aenter__(self):
                await self.session.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await self.session.__aexit__(*args)

            def get(self, url, **kwargs):
                parsed = urlsplit(url)
                assert parsed.netloc == "raw.githubusercontent.com"
                return self.session.get(server.make_url(parsed.path), **kwargs)

        monkeypatch.setattr(source.aiohttp, "ClientSession", LocalSession)
        fetched = await source.fetch_dataset(
            "example/repo", "a" * 40, "vehicle-tracker"
        )
    assert fetched == dataset
    assert calls == list(files)

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from jsonschema import Draft202012Validator
from test_application_sdk import SDKBackend, make_app, payload, rpc_message
from test_runtime import ANCHOR, FakeTransport

from example_device import application, source
from example_device.commands import CommandError, CommandRequest
from example_device.dataset import DatasetError, load_directory, parse_dataset
from example_device.models import TRUSTED_REPOSITORY, load_model
from example_device.runtime import Runtime, stable_message_id
from example_device.state import PlaybackState

DIRECTORY = Path(__file__).resolve().parents[1] / "devices/vsd"
APP = "schneider_vsd"
MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR


@pytest.fixture(scope="module")
def dataset():
    return load_directory(DIRECTORY)


def runtime(dataset, transport, **options):
    return Runtime(
        dataset,
        transport,
        anchor_ms=ANCHOR,
        revision="a" * 40,
        installation_id="vsd-test",
        **options,
    )


def request(method, seconds, value=None):
    timestamp = ANCHOR + seconds * 1000
    return CommandRequest(
        stable_message_id(timestamp, f"{method}-{seconds}"),
        timestamp,
        APP,
        method,
        value if value is not None else timestamp,
    )


def tags(transport):
    return transport.aggregates["tag_values"][APP]


def test_dataset_history_and_schema(dataset):
    config = json.loads((DIRECTORY / "config.json").read_text())
    schema = json.loads(
        (DIRECTORY.parents[1] / "schemas/device.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(config)
    samples = [row for row in dataset.channels["tag_values"] if row.kind == "message"]
    assert samples[0].timestamp == -90 * DAY
    assert samples[-1].timestamp == 30 * DAY
    assert len(samples) == 3099
    historical = {row.timestamp: row.data[APP] for row in samples if row.timestamp < 0}
    commands = [
        row
        for row in dataset.channels["ui_cmds"]
        if row.kind == "message" and row.data["type"] == "rpc"
    ]
    assert len(commands) == 390
    assert all(row.timestamp < 0 for row in commands)
    for row in commands:
        at = historical[row.timestamp]
        if row.data["method"] == "frequency_setpoint":
            assert at["frequency_setpoint"] == row.data["request"]
        if row.timestamp >= -14 * DAY and row.data["method"] in ("start", "stop"):
            after = historical[row.timestamp + MINUTE]
            assert after["vsd_running"] == (row.data["method"] == "start")
            assert (after["vsd_power"] > 0) == after["vsd_running"]
            assert 410 < after["mains_voltage"] < 420
    assert all(
        a.data[APP]["total_hours"] <= b.data[APP]["total_hours"]
        for a, b in zip(samples, samples[1:])
    )


def test_model_steps_do_not_depend_on_tick_interval(dataset):
    model = dataset.model
    state = model.spec.initial_state
    controls = {"running": True, "frequency": 43}
    one_step, _ = model.step(state, controls, 3600)
    many = state
    for _ in range(3600):
        many, _ = model.step(many, controls, 1)
    assert many == pytest.approx(one_step)
    controls = {"running": False, "frequency": 43}
    stopped, telemetry = model.step(one_step, controls, 3600)
    assert (
        telemetry["vsd_power"]
        == telemetry["vsd_voltage"]
        == telemetry["vsd_frequency"]
        == 0
    )
    assert stopped["total_hours"] - one_step["total_hours"] == pytest.approx(43 / 3600)
    assert 20 < stopped["thermal_pct"] < one_step["thermal_pct"]


def test_unapproved_or_modified_code_never_executes(dataset, tmp_path):
    marker = tmp_path / "executed"
    raw = f"open({str(marker)!r}, 'w').write('bad')".encode()
    for spec in (
        dataset.config.model,
        replace(dataset.config.model, sha256=hashlib.sha256(raw).hexdigest()),
    ):
        with pytest.raises(ValueError, match="approved"):
            load_model(TRUSTED_REPOSITORY, "vsd", spec, raw)
    with pytest.raises(ValueError, match="approved"):
        load_model(
            "someone/else",
            "vsd",
            dataset.config.model,
            (DIRECTORY / "model.py").read_bytes(),
        )
    assert not marker.exists()


def test_model_output_validation(dataset, monkeypatch):
    model = load_directory(DIRECTORY).model
    for bad in (
        {"power": float("nan")},
        {"other_app": {"x": 1}},
        {"_example_device": "bad"},
    ):
        monkeypatch.setattr(
            model.module, "step", lambda state, controls, seconds: (state, bad)
        )
        with pytest.raises(ValueError):
            model.step(model.spec.initial_state, model.spec.initial_commands, 1)


async def test_commands_drive_future_samples_and_survive_restarts(dataset):
    transport = FakeTransport()
    await runtime(dataset, transport).run(ANCHOR)
    base_hours = tags(transport)["total_hours"]
    await runtime(dataset, transport).acknowledge(request("frequency_setpoint", 10, 35))
    await runtime(dataset, transport).acknowledge(request("start", 20))
    assert tags(transport)["vsd_state"] == "starting"
    await runtime(dataset, transport).run(ANCHOR + 30_000, observed=True)
    assert tags(transport)["vsd_frequency"] == 10
    await runtime(dataset, transport).run(ANCHOR + MINUTE * 2, observed=True)
    assert tags(transport)["vsd_frequency"] == 35
    assert tags(transport)["vsd_power"] > 0
    assert tags(transport)["flow_switch"] is True
    await runtime(dataset, transport).acknowledge(
        request("frequency_setpoint", 180, 45)
    )
    await runtime(dataset, transport).run(ANCHOR + 30 * MINUTE, observed=True)
    assert tags(transport)["vsd_frequency"] == 45
    assert tags(transport)["vsd_power"] == pytest.approx(7.5 * 0.9**3, abs=0.001)
    assert tags(transport)["total_hours"] > base_hours
    sample = next(
        item
        for item in transport.messages.values()
        if item.channel == "tag_values" and item.timestamp_ms == ANCHOR + 30 * MINUTE
    )
    assert sample.data[APP]["vsd_frequency"] == 45
    heat = tags(transport)["drive_thermal_load"]
    await runtime(dataset, transport).acknowledge(request("stop", 1900))
    await runtime(dataset, transport).run(ANCHOR + HOUR, observed=True)
    assert tags(transport)["vsd_power"] == tags(transport)["vsd_frequency"] == 0
    assert tags(transport)["flow_switch"] is False
    assert tags(transport)["drive_thermal_load"] < heat
    stopped_hours = tags(transport)["total_hours"]
    await runtime(dataset, transport).acknowledge(
        request("frequency_setpoint", 3700, 25)
    )
    await runtime(dataset, transport).run(ANCHOR + 2 * HOUR, observed=True)
    assert tags(transport)["vsd_frequency"] == 0
    assert tags(transport)["total_hours"] == stopped_hours
    await runtime(dataset, transport).acknowledge(request("start", 7210))
    await runtime(dataset, transport).run(ANCHOR + 3 * HOUR, observed=True)
    assert tags(transport)["vsd_frequency"] == 25
    assert len(PlaybackState.from_dict(transport.state).model_events) == 1


@pytest.mark.parametrize(
    "failure",
    ["lose_rpc_response_once", "lose_message_response_once", "lose_checkpoint_once"],
)
async def test_model_command_retry_is_idempotent(dataset, failure):
    transport = FakeTransport()
    await runtime(dataset, transport).run(ANCHOR)
    command = request("start", 10)
    setattr(transport, failure, True)
    with pytest.raises(OSError):
        await runtime(dataset, transport).acknowledge(command)
    # A failed first pending checkpoint needs RPC redelivery; later failures
    # can recover from the saved pending request on the next scheduled run.
    await runtime(dataset, transport).acknowledge(command)
    response = deepcopy(transport.responses[("ui_cmds", command.message_id)])
    await runtime(dataset, transport).run(ANCHOR + MINUTE, observed=True)
    await runtime(dataset, transport).acknowledge(command)
    assert transport.responses[("ui_cmds", command.message_id)] == response
    assert tags(transport)["vsd_running"] is True
    live = [
        item
        for item in transport.messages.values()
        if item.data.get("_example_device", {}).get("request_id")
        == str(command.message_id)
    ]
    assert len(live) == 2  # One input log, one telemetry transition.
    assert len(PlaybackState.from_dict(transport.state).model_events) == 1


async def test_delayed_stop_does_not_rewrite_published_history(dataset):
    transport = FakeTransport()
    await runtime(dataset, transport).run(ANCHOR)
    await runtime(dataset, transport).acknowledge(request("start", 10))
    transport.lose_message_response_once = True
    with pytest.raises(OSError):
        await runtime(dataset, transport).run(ANCHOR + HOUR)
    saved = deepcopy(
        {
            key: item
            for key, item in transport.messages.items()
            if item.timestamp_ms >= ANCHOR
        }
    )
    late = request("stop", 100)
    await runtime(dataset, transport).acknowledge(late)
    assert (
        transport.responses[("ui_cmds", late.message_id)]["response"]["effective_at_ms"]
        == ANCHOR + HOUR + 1
    )
    await runtime(dataset, transport).run(ANCHOR + HOUR + MINUTE, observed=True)
    assert all(transport.messages[key] == item for key, item in saved.items())
    assert tags(transport)["vsd_frequency"] == 0


async def test_out_of_order_commands_and_invalid_values(dataset):
    transport = FakeTransport()
    await runtime(dataset, transport).run(ANCHOR)
    await runtime(dataset, transport).acknowledge(request("stop", 20))
    result = await runtime(dataset, transport).acknowledge(request("start", 10))
    assert result.status == "superseded"
    before = deepcopy(transport.state)
    for value in (-1, 51, True, float("nan")):
        with pytest.raises(CommandError):
            await runtime(dataset, transport).acknowledge(
                request("frequency_setpoint", 30, value)
            )
    assert transport.state == before


async def test_model_exhaustion_and_device_isolation(dataset):
    first, second = FakeTransport(), FakeTransport()
    await runtime(dataset, first).run(ANCHOR)
    await runtime(dataset, second).run(ANCHOR)
    await runtime(dataset, first).acknowledge(request("start", 10))
    await runtime(dataset, first).run(ANCHOR + HOUR, observed=True)
    await runtime(dataset, second).run(ANCHOR + HOUR, observed=True)
    assert tags(first)["vsd_running"] is True
    assert tags(second)["vsd_running"] is False
    while (
        await runtime(dataset, first, max_batches=100).run(ANCHOR + 30 * DAY)
    ).needs_continuation:
        pass
    with pytest.raises(CommandError, match="end of its timeline"):
        await runtime(dataset, first).acknowledge(request("stop", 30 * DAY // 1000 + 1))


@pytest.mark.parametrize(
    "failure", [None, "tampered", "redirect", "oversized", "unapproved"]
)
async def test_remote_model_download_boundary(monkeypatch, failure):
    paths = []
    real_session = aiohttp.ClientSession
    repository = "someone/else" if failure == "unapproved" else TRUSTED_REPOSITORY
    prefix = f"/{repository}/{'a' * 40}/devices/vsd/"

    async def respond(request):
        assert "Authorization" not in request.headers
        paths.append(request.path)
        relative = request.path.removeprefix(prefix)
        raw = (DIRECTORY / relative).read_bytes()
        if relative == "model.py":
            if failure == "redirect":
                raise web.HTTPFound("/unexpected")
            if failure == "tampered":
                raw += b"\nraise RuntimeError('executed unverified code')"
            if failure == "oversized":
                raw = b" " * (64 * 1024 + 1)
        return web.Response(body=raw)

    app = web.Application()
    app.router.add_get("/{tail:.*}", respond)
    async with TestServer(app) as server:

        class RoutedSession:
            def __init__(self, **kwargs):
                assert kwargs["trust_env"] is False
                self.session = real_session(**kwargs)

            async def __aenter__(self):
                await self.session.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await self.session.__aexit__(*args)

            def get(self, url, **kwargs):
                parsed = urlsplit(url)
                assert (
                    parsed.scheme == "https"
                    and parsed.netloc == "raw.githubusercontent.com"
                )
                assert kwargs["allow_redirects"] is False
                return self.session.get(server.make_url(parsed.path), **kwargs)

        monkeypatch.setattr(source.aiohttp, "ClientSession", RoutedSession)
        if failure:
            with pytest.raises(ValueError):
                await source.fetch_dataset(repository, "a" * 40, "vsd")
        else:
            loaded = await source.fetch_dataset(repository, "a" * 40, "vsd")
            transport = FakeTransport()
            await runtime(loaded, transport).run(ANCHOR)
            await runtime(loaded, transport).acknowledge(request("start", 10))
            await runtime(loaded, transport).run(ANCHOR + MINUTE, observed=True)
            assert tags(transport)["vsd_running"] is True
    assert (prefix + "model.py" in paths) == (failure != "unapproved")


def test_model_cannot_overlap_interpolation_or_skip_loading(dataset):
    config = json.loads((DIRECTORY / "config.json").read_text())
    channels = {
        name: json.loads((DIRECTORY / "channels" / f"{name}.json").read_text())
        for name in config["channels"]
    }
    config["interpolation"] = [{"path": [APP, "vsd_frequency"]}]
    with pytest.raises(DatasetError, match="interpolation"):
        parse_dataset(config, channels)
    with pytest.raises(ValueError, match="verified"):
        runtime(replace(dataset, model=None), FakeTransport())


async def test_real_sdk_dispatches_vsd_command_and_resumes_model(monkeypatch, dataset):
    backend = SDKBackend()
    backend.aggregates["deployment_config"] = {
        "applications": {APP: {"APP_ID": "installed-vsd-test", "run": False}}
    }

    async def dispatch(now, kind="on_schedule", data=None):
        app = make_app(monkeypatch, backend, now)
        monkeypatch.setattr(
            application, "fetch_dataset", AsyncMock(return_value=dataset)
        )
        event = payload(backend, kind, data)
        event["d"]["upgrade"]["deployment_config"]["dataset_slug"] = "vsd"
        result, _ = await app._dispatch_invocation(event, None)
        assert app.failure is None
        return result

    await dispatch(ANCHOR, "on_deployment")
    rpc = rpc_message(backend)
    rpc["message"]["data"].update(app_key=APP, method="start", request=ANCHOR + 1000)
    message_id = int(rpc["message"]["id"])
    backend.messages[("ui_cmds", message_id)] = deepcopy(rpc["message"])
    result = await dispatch(ANCHOR + 1000, "on_message_create", rpc)
    assert result["status"] == "acknowledged"
    assert (
        backend.messages[("ui_cmds", message_id)]["data"]["response"][
            "telemetry_changed"
        ]
        is True
    )
    await dispatch(ANCHOR + MINUTE)
    assert backend.aggregates["tag_values"][APP]["vsd_running"] is True
    assert backend.aggregates["tag_values"][APP]["vsd_frequency"] > 0
    assert (
        backend.aggregates["deployment_config"]["applications"][APP]["APP_ID"]
        == "installed-vsd-test"
    )
    own = backend.aggregates["tag_values"]["example_device"]["playback_state"]
    assert len(PlaybackState.from_dict(own).model_events) == 1
    # Importing historical commands through the actual SDK never drives the model.
    before = deepcopy(backend.aggregates)
    historical = rpc_message(backend, marker={"origin": "dataset"})
    app = make_app(monkeypatch, backend, ANCHOR + MINUTE)
    assert (
        await app.pre_hook_filter(application.MessageCreateEvent.from_dict(historical))
        is False
    )
    assert backend.aggregates == before

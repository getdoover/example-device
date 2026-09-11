"""Run the actual pinned PyDoover dispatcher with HTTP calls replaced in memory."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pydoover.rpc as sdk_rpc
import pytest
from pydoover.api import NotFoundError
from pydoover.processor import ProcessorSkipped
from test_runtime import ANCHOR, make_dataset

from example_device import application
from example_device.config import ExampleDeviceConfig
from example_device.runtime import stable_message_id
from example_device.timeline import merge_data


class SDKBackend:
    def __init__(self):
        self.aggregates = {"tag_values": {}, "dv-ui-sub": {}, "ui_cmds": {}}
        self.messages = {}
        self.calls = []
        self.fail_batches = False

    async def request(self, method, path, *, data=None, params=None, **kwargs):
        self.calls.append((method, path, deepcopy(data)))
        if path == "/agents/messages" and method == "POST":
            if self.fail_batches:
                raise OSError("temporary storage failure")
            results = []
            for item in data["items"]:
                message = {
                    "id": item["message_id"],
                    "author_id": "101",
                    "channel": {
                        "agent_id": item["agent_id"],
                        "name": item["channel_name"],
                    },
                    "data": deepcopy(item["data"]),
                    "attachments": [],
                }
                self.messages[(item["channel_name"], int(item["message_id"]))] = message
                results.append(
                    {
                        "agent_id": item["agent_id"],
                        "channel_name": item["channel_name"],
                        "message_id": item["message_id"],
                        "success": True,
                    }
                )
            return {
                "items": results,
                "count": len(results),
                "succeeded": len(results),
                "failed": 0,
            }
        parts = path.strip("/").split("/")
        if len(parts) < 5 or parts[:3] != ["agents", "101", "channels"]:
            raise AssertionError(f"Unexpected SDK request {method} {path}")
        channel = parts[3]
        if parts[4] == "aggregate":
            if method == "GET":
                if channel not in self.aggregates:
                    raise NotFoundError("aggregate missing")
                return {"data": deepcopy(self.aggregates[channel]), "attachments": []}
            assert method == "PATCH"
            target = self.aggregates.setdefault(channel, {})
            for dotted in (params or {}).get("replace") or []:
                current = target
                keys = dotted.split(".")
                for key in keys[:-1]:
                    current = current.setdefault(key, {})
                current.pop(keys[-1], None)
            self.aggregates[channel] = merge_data(target, data)
            return None
        if parts[4] == "messages":
            key = (channel, int(parts[5]))
            if key not in self.messages:
                raise NotFoundError("message missing")
            if method == "GET":
                return deepcopy(self.messages[key])
            assert method == "PATCH"
            self.messages[key]["data"] = merge_data(
                self.messages[key]["data"], data["data"]
            )
            return deepcopy(self.messages[key])
        raise AssertionError(f"Unexpected SDK request {method} {path}")


def wire_config():
    config = ExampleDeviceConfig()
    values = {
        "repository": "getdoover/example-device",
        "dataset_slug": "counter-fixture",
        "dataset_revision": "a" * 40,
        "anchor_ms": ANCHOR,
    }
    return {
        **{
            getattr(config, key).to_dict()["x-name"]: value
            for key, value in values.items()
        },
        "APP_KEY": "example_device",
        "APP_ID": "202",
        "APP_DISPLAY_NAME": "Example",
    }


def payload(backend, kind="on_schedule", data=None):
    upgrade = {
        "agent_id": "101",
        "organisation_id": "303",
        "app_key": "example_device",
        "deployment_config": wire_config(),
        "ui_state": {},
        "ui_cmds": deepcopy(backend.aggregates["ui_cmds"]),
        "tag_values": deepcopy(backend.aggregates["tag_values"]),
        "connection_data": {},
        "token": "unit-test-upgraded-token",
    }
    event_data = {"schedule_id": "404", "organisation_id": "303", "upgrade": upgrade}
    if kind == "on_deployment":
        event_data.update(
            {
                "agent_id": "101",
                "app_id": "202",
                "app_install_id": "505",
                "app_key": "example_device",
                "app_display_name": "Example",
            }
        )
    if data:
        event_data.update(data)
    return {"op": kind, "d": event_data, "token": "unit-test-initial-token"}


def make_app(monkeypatch, backend, now=ANCHOR):
    app = application.ExampleDevice(serialization_verified=True)
    monkeypatch.setattr(app.api, "setup", AsyncMock())
    monkeypatch.setattr(app.api, "close", AsyncMock())
    monkeypatch.setattr(app.api, "_request", backend.request)
    monkeypatch.setattr(
        application, "fetch_dataset", AsyncMock(return_value=make_dataset())
    )
    monkeypatch.setattr(application, "time", SimpleNamespace(time=lambda: now / 1000))
    return app


def rpc_message(backend, *, value=45, marker=None):
    message_id = stable_message_id(ANCHOR + 1_000, "sdk-live-command")
    data = {
        "type": "rpc",
        "app_key": "counter",
        "method": "set_limit",
        "request": value,
        "status": {"code": "sent"},
        "response": {},
    }
    if marker is not None:
        data["_example_device"] = marker
    message = {
        "id": str(message_id),
        "author_id": "606",
        "channel": {"agent_id": "101", "name": "ui_cmds"},
        "data": data,
        "attachments": [],
    }
    backend.messages[("ui_cmds", message_id)] = deepcopy(message)
    return {"channel": message["channel"], "message": message}


@pytest.mark.asyncio
async def test_actual_sdk_deployment_then_schedule_populates_and_advances(monkeypatch):
    backend = SDKBackend()
    app = make_app(monkeypatch, backend)
    result, _ = await app._dispatch_invocation(payload(backend, "on_deployment"), None)
    assert result["phase"] == "active"
    assert app.failure is None
    assert backend.aggregates["tag_values"]["counter"]["value"] == 0
    assert backend.aggregates["tag_values"]["example_device"]["phase"] == "active"
    assert len(backend.messages) == 3
    app = make_app(monkeypatch, backend, ANCHOR + 1_800_000)
    result, _ = await app._dispatch_invocation(payload(backend), None)
    assert result["phase"] == "active"
    assert backend.aggregates["tag_values"]["counter"]["value"] == 10
    # Framework tag commits did not overwrite the runtime's fresh checkpoints.
    assert (
        backend.aggregates["tag_values"]["example_device"]["playback_state"]["cursor"]
        == 6
    )
    assert len(backend.messages) == 4


@pytest.mark.asyncio
async def test_imported_rpc_is_filtered_before_sdk_setup_or_rpc_dispatch(monkeypatch):
    backend = SDKBackend()
    app = make_app(monkeypatch, backend)
    rpc = rpc_message(backend, marker={"origin": "dataset", "record_id": "past-input"})
    with pytest.raises(ProcessorSkipped):
        await app._dispatch_invocation(payload(backend, "on_message_create", rpc), None)
    app.api.setup.assert_not_awaited()
    application.fetch_dataset.assert_not_awaited()
    assert backend.calls == []
    assert rpc["message"]["data"]["status"]["code"] == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,phase", [(0, "active"), (3_600_000, "exhausted")])
async def test_sdk_default_phase_does_not_overwrite_runtime_final_phase(
    monkeypatch, offset, phase
):
    backend = SDKBackend()
    app = make_app(monkeypatch, backend, ANCHOR + offset)
    await app._dispatch_invocation(payload(backend, "on_deployment"), None)
    own = backend.aggregates["tag_values"]["example_device"]
    assert own["phase"] == phase
    assert own["playback_state"]["phase"] == phase
    assert app.tag_manager._dirty == {}
    assert app.tag_manager._update_tags is False


@pytest.mark.asyncio
async def test_actual_sdk_live_rpc_updates_selection_without_sensor_handler(
    monkeypatch,
):
    backend = SDKBackend()
    await make_app(monkeypatch, backend)._dispatch_invocation(payload(backend), None)
    before = deepcopy(backend.aggregates["tag_values"]["counter"])
    rpc = rpc_message(backend)
    app = make_app(monkeypatch, backend, ANCHOR + 1_000)
    result, _ = await app._dispatch_invocation(
        payload(backend, "on_message_create", rpc), None
    )
    assert result["status"] == "acknowledged"
    assert backend.aggregates["ui_cmds"]["counter"]["set_limit"] == 45
    assert backend.aggregates["tag_values"]["counter"] == before
    message = backend.messages[("ui_cmds", int(rpc["message"]["id"]))]
    assert message["data"]["status"]["code"] == "success"
    assert message["data"]["response"]["telemetry_changed"] is False
    assert (
        sum(msg["data"].get("type") == "log" for msg in backend.messages.values()) == 1
    )


@pytest.mark.asyncio
async def test_expired_rpc_does_not_change_selected_value(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp((ANCHOR + 2_000) / 1_000, tz=timezone.utc)

    monkeypatch.setattr(sdk_rpc, "datetime", FrozenDatetime)
    backend = SDKBackend()
    await make_app(monkeypatch, backend)._dispatch_invocation(payload(backend), None)
    rpc = rpc_message(backend)
    rpc["message"]["data"]["expires_after"] = 1
    app = make_app(monkeypatch, backend, ANCHOR + 2_000)
    await app._dispatch_invocation(payload(backend, "on_message_create", rpc), None)
    assert backend.aggregates["ui_cmds"]["counter"]["set_limit"] == 25
    assert not any(
        msg["data"].get("type") == "log" for msg in backend.messages.values()
    )


@pytest.mark.asyncio
async def test_sdk_swallowed_handler_error_is_retained_for_entrypoint_retry(
    monkeypatch,
):
    backend = SDKBackend()
    backend.fail_batches = True
    app = make_app(monkeypatch, backend)
    # The real SDK catches on_schedule errors and returns. Our app retains
    # the failure so its public entrypoint can re-raise after SDK cleanup.
    result, _ = await app._dispatch_invocation(payload(backend), None)
    assert result is None
    assert isinstance(app.failure, OSError)
    state = backend.aggregates["tag_values"]["example_device"]["playback_state"]
    assert state["cursor"] == 0
    assert state["phase"] == "importing"


def test_public_entrypoint_rethrows_after_real_sdk_handles_failure(monkeypatch):
    backend = SDKBackend()
    backend.fail_batches = True
    app = make_app(monkeypatch, backend)
    monkeypatch.setattr(
        application, "verify_lambda_serialization", lambda context: None
    )
    monkeypatch.setattr(application, "ExampleDevice", lambda **kwargs: app)
    with pytest.raises(OSError, match="temporary storage failure"):
        application.invoke(payload(backend), None)


@pytest.mark.asyncio
async def test_sdk_presence_event_interpolates_without_dense_history(monkeypatch):
    backend = SDKBackend()
    await make_app(monkeypatch, backend)._dispatch_invocation(payload(backend), None)
    now = ANCHOR + 900_000
    presence = {"agent_open": {"unit-user": now}}
    backend.aggregates["dv-ui-sub"] = presence
    data = {
        "author_id": "606",
        "channel": {"agent_id": "101", "name": "dv-ui-sub"},
        "aggregate": {"data": presence},
        "request_data": {"data": presence},
    }
    app = make_app(monkeypatch, backend, now)
    await app._dispatch_invocation(payload(backend, "on_aggregate_update", data), None)
    assert backend.aggregates["tag_values"]["counter"]["value"] == 5
    assert len(backend.messages) == 3


@pytest.mark.parametrize(
    "presence",
    [
        {"agent_open": {"old": ANCHOR - 120_000}},
        {"agent_open": {"future": ANCHOR + 1}},
        {"group_open": {"list-only": ANCHOR}},
        {"agent_open": {"invalid": True}},
    ],
)
def test_only_fresh_page_presence_enables_viewing(presence):
    assert application.is_page_observed(presence, ANCHOR) is False

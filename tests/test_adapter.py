"""Exercise the installed SDK against an HTTP boundary, including retries."""

from copy import deepcopy

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from pydoover.processor.data_client import ProcessorDataClient

from example_device.adapter import DooverTransport
from example_device.runtime import HistoryWrite
from example_device.timeline import merge_data


@pytest.fixture
async def api_server():
    stored = {}
    aggregates = {
        "tag_values": {"processor": {"unrelated": 8}},
        "deployment_config": {"applications": {"meter": {"APP_ID": "new-install"}}},
    }
    requests = []

    async def handle(request):
        body = await request.json() if request.can_read_body else None
        requests.append((request.method, request.path, dict(request.query), body))
        if request.path == "/agents/messages":
            items = body["items"]
            for item in items:
                stored[(item["channel_name"], int(item["message_id"]))] = deepcopy(
                    item["data"]
                )
            return web.json_response(
                {
                    "items": [dict(item, success=True) for item in items],
                    "count": len(items),
                    "succeeded": len(items),
                    "failed": 0,
                }
            )
        pieces = request.path.split("/")
        channel = pieces[4]
        if pieces[5] == "aggregate":
            if request.method == "GET":
                if channel not in aggregates:
                    raise web.HTTPNotFound()
                return web.json_response(
                    {"data": aggregates[channel], "attachments": []}
                )
            current = deepcopy(aggregates.get(channel, {}))
            for path in request.query.getall("replace", []):
                keys = path.split(".")
                node = current
                for key in keys[:-1]:
                    node = node.setdefault(key, {})
                node.pop(keys[-1], None)
            aggregates[channel] = merge_data(current, body)
            return web.json_response({})
        message_id = int(pieces[6])
        key = channel, message_id
        if request.method == "GET" and key not in stored:
            raise web.HTTPNotFound()
        if request.method == "PATCH":
            stored[key] = merge_data(stored.get(key, {}), body["data"])
        return web.json_response(
            {
                "id": str(message_id),
                "author_id": "7",
                "channel": {"agent_id": "7", "name": channel},
                "data": stored[key],
                "attachments": [],
            }
        )

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    async with TestServer(app) as server:
        async with ProcessorDataClient(str(server.make_url("/"))) as api:
            api.agent_id = 7
            api.app_key = "processor"
            api.set_token("test-token")
            transport = DooverTransport(
                api,
                agent_id=7,
                app_key="processor",
                app_keys=["meter"],
                repository="sample/repo",
                device_lock_held=True,
            )
            yield transport, stored, aggregates, requests


async def test_backdated_batch_retry_and_collision(api_server):
    transport, stored, _, requests = api_server
    write = HistoryWrite(
        "tag_values",
        246415360000032,
        1735748350000,
        {"meter": {"value": 3}, "_example_device": {"origin": "dataset"}},
    )
    assert (await transport.publish_messages([write]))[0].success
    assert stored[(write.channel, write.message_id)] == write.data
    assert (await transport.publish_messages([write]))[0].success
    posts = [r for r in requests if r[0] == "POST"]
    assert len(posts) == 1
    assert posts[0][3]["items"][0]["ts"] == write.timestamp_ms
    assert posts[0][3]["items"][0]["message_id"] == str(write.message_id)
    stored[(write.channel, write.message_id)] = {"unrelated": "record"}
    with pytest.raises(ValueError, match="collision"):
        await transport.publish_messages([write])
    assert len([r for r in requests if r[0] == "POST"]) == 1


async def test_checkpoint_replaces_only_state_tag_without_history(api_server):
    transport, _, aggregates, requests = api_server
    value = {
        "version": 1,
        "anchor_ms": 1736000000000,
        "revision": "a" * 40,
        "phase": "importing",
        "old": True,
    }
    await transport.write_state(value)
    del value["old"]
    value["phase"] = "active"
    await transport.write_state(value)
    state = await transport.read_state()
    assert state["repository"] == "sample/repo"
    assert "old" not in state
    assert aggregates["tag_values"]["processor"]["unrelated"] == 8
    assert all("log_update" not in query for _, _, query, _ in requests)
    assert not any(method == "POST" for method, *_ in requests)


async def test_scope_and_installation_bindings(api_server):
    transport, _, aggregates, _ = api_server
    await transport.patch_aggregate("tag_values", {"meter": {"value": 3}})
    assert aggregates["tag_values"]["processor"] == {"unrelated": 8}
    with pytest.raises(ValueError, match="undeclared"):
        await transport.patch_aggregate("tag_values", {"processor": {"phase": "gone"}})
    with pytest.raises(ValueError, match="erase"):
        await transport.patch_aggregate(
            "ui_state", {"state": {"children": {"meter": {}}}}, ["state"]
        )
    await transport.patch_aggregate(
        "deployment_config", {"applications": {"meter": {"threshold": 4}}}
    )
    assert aggregates["deployment_config"]["applications"]["meter"] == {
        "APP_ID": "new-install",
        "threshold": 4,
    }
    with pytest.raises(ValueError, match="identity"):
        await transport.patch_aggregate(
            "deployment_config", {"applications": {"meter": {"APP_ID": "bad"}}}
        )


async def test_rpc_patch_uses_native_message_wrapper(api_server):
    transport, stored, _, requests = api_server
    await transport.update_rpc_response("ui_cmds", 123, {"status": {"code": "success"}})
    assert stored[("ui_cmds", 123)]["status"]["code"] == "success"
    assert requests[-1][3] == {"data": {"status": {"code": "success"}}}


async def test_device_lease_uses_real_sdk_aggregate_requests(api_server):
    from example_device.concurrency import DeviceLease

    transport, _, aggregates, requests = api_server
    first = DeviceLease(
        transport.api,
        agent_id=7,
        app_key="processor",
        owner="one",
        expires_at_ms=2000,
        clock=lambda: 1000,
    )
    second = DeviceLease(
        transport.api,
        agent_id=7,
        app_key="processor",
        owner="two",
        expires_at_ms=2000,
        clock=lambda: 1000,
    )
    assert await first.acquire()
    assert not await second.acquire()
    assert aggregates["tag_values"]["processor"]["collision_count"] == 1
    await first.release()
    assert await second.acquire()
    await second.release()
    own = aggregates["tag_values"]["processor"]
    assert own == {"unrelated": 8, "collision_count": 1, "last_collision_ms": 1000}
    assert all(
        "log_update" not in query
        for method, _, query, _ in requests
        if method == "PATCH"
    )

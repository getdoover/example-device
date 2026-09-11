from copy import deepcopy
from dataclasses import replace

import pytest
from test_runtime import ANCHOR, FakeTransport, make_dataset, make_runtime

from example_device.commands import CommandError, CommandRequest
from example_device.runtime import stable_message_id


def command(value=40, offset=1_000, method="set_limit"):
    timestamp = ANCHOR + offset
    return CommandRequest(
        stable_message_id(timestamp, f"request-{offset}"),
        timestamp,
        "counter",
        method,
        value,
    )


@pytest.mark.asyncio
async def test_command_changes_selection_and_response_but_no_telemetry():
    transport = FakeTransport()
    runtime = make_runtime(transport)
    await runtime.run(ANCHOR)
    tags = deepcopy(transport.aggregates["tag_values"])
    request = command()
    result = await runtime.acknowledge(request)
    assert result.status == "acknowledged"
    assert transport.aggregates["ui_cmds"]["counter"]["set_limit"] == 40
    assert transport.aggregates["tag_values"] == tags
    assert (
        transport.responses[("ui_cmds", request.message_id)]["status"]["code"]
        == "success"
    )
    logs = [
        message
        for message in transport.messages.values()
        if message.channel == "ui_cmds"
    ]
    assert len(logs) == 1
    assert logs[0].data["type"] == "log"
    assert logs[0].data["value"] == 40
    await runtime.run(ANCHOR + 1_800_000)
    assert transport.aggregates["ui_cmds"]["counter"]["set_limit"] == 40


@pytest.mark.asyncio
async def test_command_redelivery_and_lost_response_recover_once():
    transport = FakeTransport()
    runtime = make_runtime(transport)
    await runtime.run(ANCHOR)
    request = command()
    transport.lose_rpc_response_once = True
    with pytest.raises(OSError):
        await runtime.acknowledge(request)
    assert transport.state["commands"]["counter.set_limit"]["pending"] is not None
    # A schedule recovers the pending acknowledgement even if the RPC is never
    # redelivered; subsequent delivery can only repair its response.
    await make_runtime(transport).run(ANCHOR + 2_000)
    assert transport.state["commands"]["counter.set_limit"].get("pending") is None
    await make_runtime(transport).acknowledge(request)
    assert (
        sum(message.channel == "ui_cmds" for message in transport.messages.values())
        == 1
    )


@pytest.mark.asyncio
async def test_older_command_does_not_restore_stale_selected_value():
    transport = FakeTransport()
    runtime = make_runtime(transport)
    await runtime.run(ANCHOR)
    await runtime.acknowledge(command(75, offset=2_000))
    result = await runtime.acknowledge(command(10, offset=1_000))
    assert result.status == "superseded"
    assert transport.aggregates["ui_cmds"]["counter"]["set_limit"] == 75
    assert (
        sum(message.channel == "ui_cmds" for message in transport.messages.values())
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_request",
    [command(True), command(-1), command(float("nan")), command(method="unknown")],
)
async def test_invalid_commands_rejected_before_mutation(input_request):
    transport = FakeTransport()
    runtime = make_runtime(transport)
    await runtime.run(ANCHOR)
    old = deepcopy(transport.aggregates)
    with pytest.raises(CommandError):
        await runtime.acknowledge(input_request)
    assert transport.aggregates == old
    assert transport.responses == {}


@pytest.mark.asyncio
async def test_commands_rejected_until_installation_finishes():
    transport = FakeTransport()
    with pytest.raises(CommandError, match="preparing"):
        await make_runtime(transport).acknowledge(command())
    assert transport.state is None
    assert transport.messages == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value_type,value", [("null", None), ("object", {"nested": {"value": None}})]
)
async def test_pending_command_preserves_nulls_through_aggregate_storage(
    value_type, value
):
    transport = FakeTransport()
    dataset = make_dataset()
    control = replace(
        dataset.config.inputs[0], value_type=value_type, min=None, max=None
    )
    dataset = replace(dataset, config=replace(dataset.config, inputs=(control,)))
    runtime = make_runtime(transport, dataset)
    await runtime.run(ANCHOR)
    transport.lose_message_response_once = True
    with pytest.raises(OSError):
        await runtime.acknowledge(command(value))
    pending = transport.state["commands"]["counter.set_limit"]["pending"]
    assert isinstance(pending["value_json"], str)
    await make_runtime(transport, dataset).run(ANCHOR + 2_000)
    assert transport.state["commands"]["counter.set_limit"].get("pending") is None
    logs = [item for item in transport.messages.values() if item.channel == "ui_cmds"]
    assert len(logs) == 1
    assert logs[0].data["value"] == value

"""Exercise the real playback loop through transport failures and restarts."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from example_device.dataset import AttachmentFile, parse_dataset
from example_device.runtime import (
    DOOVER_EPOCH_MS,
    Runtime,
    WriteResult,
    stable_message_id,
)
from example_device.state import StateError
from example_device.timeline import merge_data

ANCHOR = DOOVER_EPOCH_MS + 20_000_000_000


def make_dataset(history_count=3, duration_ms=3_600_000):
    return parse_dataset(
        {
            "schema_version": 1,
            "slug": "counter-fixture",
            "name": "Counter fixture",
            "duration_ms": duration_ms,
            "apps": [
                {
                    "app_key": "counter",
                    "application_name": "counter",
                    "config": {},
                    "run": False,
                }
            ],
            "channels": ["tag_values", "ui_cmds"],
            "interpolation": [{"path": ["counter", "value"]}],
            "inputs": [
                {
                    "app_key": "counter",
                    "method": "set_limit",
                    "value_type": "number",
                    "min": 0,
                    "max": 100,
                }
            ],
        },
        {
            "tag_values": [
                {
                    "timestamp": -(history_count - index) * 1_000,
                    "kind": "message",
                    "id": f"history-{index}",
                    "data": {"counter": {"value": index}},
                    "apply_to_aggregate": True,
                }
                for index in range(history_count)
            ]
            + [
                {
                    "timestamp": 0,
                    "kind": "aggregate",
                    "mode": "merge",
                    "data": {
                        "counter": {"value": 0, "status": "ready", "enabled": True}
                    },
                },
                {
                    "timestamp": duration_ms // 2,
                    "kind": "message",
                    "id": "middle",
                    "data": {
                        "counter": {"value": 10, "status": "middle", "enabled": False}
                    },
                    "apply_to_aggregate": True,
                },
                {
                    "timestamp": duration_ms,
                    "kind": "message",
                    "id": "last",
                    "data": {"counter": {"value": 20}},
                    "apply_to_aggregate": True,
                },
            ],
            "ui_cmds": [
                {
                    "timestamp": 0,
                    "kind": "aggregate",
                    "mode": "merge",
                    "data": {"counter": {"set_limit": 25}},
                }
            ],
        },
    )


class FakeTransport:
    """A serial, durable fake that rejects overwrite collisions like the adapter."""

    def __init__(self):
        self.state = None
        self.messages = {}
        self.aggregates = {"tag_values": {"processor": {"unrelated": "preserved"}}}
        self.responses = {}
        self.batches = []
        self.aggregate_writes = []
        self.lock = asyncio.Lock()
        self.inside = False
        self.reject_serialization = False
        self.lose_checkpoint_once = False
        self.lose_message_response_once = False
        self.partial_fail_id = None
        self.lose_rpc_response_once = False

    @asynccontextmanager
    async def serialized(self):
        if self.reject_serialization:
            raise RuntimeError("Serialization is not verified")
        async with self.lock:
            self.inside = True
            try:
                yield
            finally:
                self.inside = False

    async def read_state(self):
        assert self.inside
        return deepcopy(self.state)

    async def write_state(self, value):
        assert self.inside
        if self.lose_checkpoint_once and self.messages:
            self.lose_checkpoint_once = False
            raise OSError("checkpoint response lost")
        # The adapter replaces its state branch, and Doover still removes null
        # object members within a replacement. Messages retain those nulls.
        self.state = merge_data({}, value)

    async def publish_messages(self, items):
        assert self.inside
        assert len(items) <= 50
        self.batches.append(deepcopy(items))
        results = []
        for item in items:
            if item.message_id == self.partial_fail_id:
                self.partial_fail_id = None
                results.append(WriteResult(item.message_id, False, "temporary failure"))
                continue
            key = (item.channel, item.message_id)
            if key in self.messages and self.messages[key] != item:
                raise RuntimeError("message identity collision")
            self.messages[key] = deepcopy(item)
            results.append(WriteResult(item.message_id, True))
        if self.lose_message_response_once:
            self.lose_message_response_once = False
            raise OSError("batch response lost after storage")
        return results

    async def patch_aggregate(self, channel, data, replace_paths=()):
        assert self.inside
        target = self.aggregates.setdefault(channel, {})
        replacement_values = {}
        for dotted in replace_paths:
            path = dotted.split(".")
            source, current = data, target
            for key in path[:-1]:
                source = source[key]
                current = current.setdefault(key, {})
            replacement_values[dotted] = deepcopy(source[path[-1]])
            current.pop(path[-1], None)
        self.aggregates[channel] = merge_data(target, data)
        self.aggregate_writes.append((channel, deepcopy(data), tuple(replace_paths)))

    async def update_rpc_response(self, channel, message_id, response):
        assert self.inside
        self.responses[(channel, message_id)] = deepcopy(response)
        if self.lose_rpc_response_once:
            self.lose_rpc_response_once = False
            raise OSError("RPC response lost")


def make_runtime(transport, dataset=None, **kwargs):
    return Runtime(
        dataset or make_dataset(),
        transport,
        anchor_ms=ANCHOR,
        revision="a" * 40,
        installation_id="generic-test-install",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_history_baseline_and_future_are_separate():
    transport = FakeTransport()
    runtime = make_runtime(transport)
    result = await runtime.run(ANCHOR)
    assert result.phase == "active"
    assert len(transport.messages) == 3
    assert all(message.timestamp_ms < ANCHOR for message in transport.messages.values())
    assert transport.aggregates["tag_values"] == {
        "processor": {"unrelated": "preserved"},
        "counter": {"value": 0, "status": "ready", "enabled": True},
    }
    for message in transport.messages.values():
        assert (message.message_id >> 22) + DOOVER_EPOCH_MS == message.timestamp_ms
        assert message.data["_example_device"]["origin"] == "dataset"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["lose_checkpoint_once", "lose_message_response_once"]
)
async def test_write_before_lost_checkpoint_resumes_without_duplicate_rows(failure):
    transport = FakeTransport()
    setattr(transport, failure, True)
    with pytest.raises(OSError):
        await make_runtime(transport).run(ANCHOR)
    ids_after_failure = set(transport.messages)
    result = await make_runtime(transport).run(ANCHOR)
    assert result.phase == "active"
    assert len(transport.messages) == 3
    assert set(transport.messages) == ids_after_failure
    assert transport.state["cursor"] == 5


@pytest.mark.asyncio
async def test_partial_batch_advances_only_contiguous_successes():
    transport = FakeTransport()
    dataset = make_dataset(history_count=105)
    runtime = make_runtime(transport, dataset, max_batches=1)
    transport.partial_fail_id = runtime._entry_ids[("tag_values", 2)]
    partial = await runtime.run(ANCHOR)
    assert partial.needs_continuation
    assert transport.state["cursor"] == 2
    while (
        result := await make_runtime(transport, dataset, max_batches=1).run(ANCHOR)
    ).needs_continuation:
        pass
    assert result.phase == "active"
    assert len(transport.messages) == 105
    assert all(len(batch) <= 50 for batch in transport.batches)
    assert len(str(transport.state)) < 600


@pytest.mark.asyncio
async def test_viewing_interpolates_aggregate_without_creating_history():
    transport = FakeTransport()
    runtime = make_runtime(transport)
    await runtime.run(ANCHOR)
    history_count = len(transport.messages)
    await runtime.run(ANCHOR + 900_000, observed=True)
    assert transport.aggregates["tag_values"]["counter"] == {
        "value": 5,
        "status": "ready",
        "enabled": True,
    }
    assert len(transport.messages) == history_count
    await runtime.run(ANCHOR + 1_800_000, observed=True)
    assert transport.aggregates["tag_values"]["counter"] == {
        "value": 10,
        "status": "middle",
        "enabled": False,
    }
    assert len(transport.messages) == history_count + 1


@pytest.mark.asyncio
async def test_idle_cadence_and_first_view_catches_up_immediately():
    transport = FakeTransport()
    runtime = make_runtime(transport)
    await runtime.run(ANCHOR)
    count = len(transport.aggregate_writes)
    result = await runtime.run(ANCHOR + 1_000)
    assert result.next_due_ms == ANCHOR + 1_800_000
    assert len(transport.aggregate_writes) == count
    await runtime.run(ANCHOR + 2_000, observed=True)
    assert transport.aggregates["tag_values"]["counter"]["value"] > 0


@pytest.mark.asyncio
async def test_exhaustion_stops_further_publication_and_initialization():
    transport = FakeTransport()
    runtime = make_runtime(transport)
    result = await runtime.run(ANCHOR + 3_600_000)
    assert result.phase == "exhausted"
    assert result.next_due_ms is None
    assert transport.aggregates["tag_values"]["counter"]["value"] == 20
    writes = len(transport.aggregate_writes)
    messages = len(transport.messages)
    await make_runtime(transport).run(ANCHOR + 20_000_000, observed=True)
    assert len(transport.aggregate_writes) == writes
    assert len(transport.messages) == messages


@pytest.mark.asyncio
async def test_missing_serialization_and_changed_revision_fail_before_channel_mutation():
    transport = FakeTransport()
    transport.reject_serialization = True
    with pytest.raises(RuntimeError, match="Serialization"):
        await make_runtime(transport).run(ANCHOR)
    assert transport.messages == {}
    assert transport.aggregate_writes == []
    transport.reject_serialization = False
    await make_runtime(transport).run(ANCHOR)
    previous = deepcopy(transport.aggregates)
    changed = Runtime(
        make_dataset(),
        transport,
        anchor_ms=ANCHOR,
        revision="b" * 40,
        installation_id="generic-test-install",
    )
    with pytest.raises(StateError, match="different dataset"):
        await changed.run(ANCHOR)
    assert transport.aggregates == previous


@pytest.mark.asyncio
async def test_serialized_concurrent_runs_share_fresh_progress():
    transport = FakeTransport()
    await asyncio.gather(
        make_runtime(transport).run(ANCHOR), make_runtime(transport).run(ANCHOR)
    )
    assert len(transport.messages) == 3
    assert len(transport.batches) == 1


def test_stable_ids_preserve_time_and_resolve_same_millisecond_collisions():
    used = set()
    first = stable_message_id(ANCHOR, "same", used)
    second = stable_message_id(ANCHOR, "same", used)
    assert first != second
    assert first == stable_message_id(ANCHOR, "same")
    assert (first >> 22) == (second >> 22)
    assert (first >> 4) & 15 == 2
    with pytest.raises(ValueError, match="snowflake range"):
        stable_message_id(DOOVER_EPOCH_MS - 1, "too-early")


@pytest.mark.asyncio
async def test_due_null_delta_removes_actual_stored_tag():
    transport = FakeTransport()
    dataset = make_dataset(duration_ms=2_000)
    entries = dataset.channels["tag_values"]
    deleted = replace(entries[-2], data={"counter": {"value": None}})
    dataset = replace(
        dataset,
        channels={
            **dataset.channels,
            "tag_values": (*entries[:-2], deleted, entries[-1]),
        },
    )
    runtime = make_runtime(transport, dataset)
    await runtime.run(ANCHOR)
    await runtime.run(ANCHOR + 1_000, observed=True)
    assert "value" not in transport.aggregates["tag_values"]["counter"]
    assert transport.aggregates["tag_values"]["processor"]["unrelated"] == "preserved"


@pytest.mark.asyncio
async def test_zero_message_initializes_aggregate_without_an_aggregate_record():
    transport = FakeTransport()
    dataset = make_dataset(history_count=0)
    zero = replace(
        dataset.channels["tag_values"][0],
        kind="message",
        id="zero",
        apply_to_aggregate=True,
        data={"counter": {"value": 7}},
    )
    dataset = replace(dataset, channels={**dataset.channels, "tag_values": (zero,)})
    result = await make_runtime(transport, dataset).run(ANCHOR)
    assert result.phase == "active"
    assert transport.aggregates["tag_values"]["counter"]["value"] == 7
    assert len(transport.messages) == 1


@pytest.mark.asyncio
async def test_zero_message_and_later_baseline_follow_authored_order():
    transport = FakeTransport()
    dataset = make_dataset(history_count=0)
    baseline = dataset.channels["tag_values"][0]
    zero = replace(
        baseline,
        kind="message",
        id="zero",
        index=0,
        apply_to_aggregate=True,
        data={"counter": {"value": 7}},
    )
    baseline = replace(baseline, index=1)
    dataset = replace(
        dataset, channels={**dataset.channels, "tag_values": (zero, baseline)}
    )
    await make_runtime(transport, dataset).run(ANCHOR)
    assert transport.aggregates["tag_values"]["counter"]["value"] == 0


@pytest.mark.asyncio
async def test_initial_scoped_replacement_erases_only_the_owned_branch():
    transport = FakeTransport()
    transport.aggregates["tag_values"]["counter"] = {"obsolete": True}
    dataset = make_dataset(history_count=0)
    initial, *remaining = dataset.channels["tag_values"]
    initial = replace(initial, mode="replace", scope=("counter",), data={"value": 0})
    dataset = replace(
        dataset, channels={**dataset.channels, "tag_values": (initial, *remaining)}
    )
    await make_runtime(transport, dataset).run(ANCHOR)
    assert transport.aggregates["tag_values"]["counter"] == {"value": 0}
    assert "processor" in transport.aggregates["tag_values"]


@pytest.mark.asyncio
async def test_late_installation_bounds_aggregate_catchup_across_invocations():
    transport = FakeTransport()
    dataset = make_dataset(history_count=0, duration_ms=120_000)
    initial, template, _ = dataset.channels["tag_values"]
    future = tuple(
        replace(
            template,
            index=index,
            timestamp=index * 1_000,
            id=f"sample-{index}",
            data={"counter": {"value": index}},
        )
        for index in range(1, 121)
    )
    dataset = replace(
        dataset, channels={**dataset.channels, "tag_values": (initial, *future)}
    )
    calls = 0
    while True:
        previous_writes = len(transport.aggregate_writes)
        result = await make_runtime(transport, dataset, max_batches=1).run(
            ANCHOR + 120_000
        )
        assert len(transport.aggregate_writes) - previous_writes <= 50
        calls += 1
        assert calls < 10
        if not result.needs_continuation:
            break
    assert calls > 3
    assert result.phase == "exhausted"
    assert len(transport.messages) == 120
    assert transport.aggregates["tag_values"]["counter"]["value"] == 120


def attachment_history_dataset():
    dataset = make_dataset(history_count=24)
    file = AttachmentFile(
        "attachments/frame.jpg", "frame.jpg", "image/jpeg", 10, "a" * 64
    )
    return replace(
        dataset,
        channels={
            **dataset.channels,
            "tag_values": tuple(
                replace(entry, attachments=(file,))
                if entry.kind == "message"
                else entry
                for entry in dataset.channels["tag_values"]
            ),
        },
    )


async def test_attachment_batches_checkpoint_at_most_five_captures():
    transport = FakeTransport()
    result = await make_runtime(
        transport, attachment_history_dataset(), max_batches=2
    ).run(ANCHOR)
    assert result.needs_continuation and result.cursor == 10
    assert [len(batch) for batch in transport.batches] == [5, 5]
    assert transport.state["cursor"] == 10
    while (
        result := await make_runtime(
            transport, attachment_history_dataset(), max_batches=2
        ).run(ANCHOR)
    ).needs_continuation:
        pass
    assert len(transport.messages) == 24 and result.phase == "active"


async def test_invocation_budget_yields_after_confirmed_attachment_batch(monkeypatch):
    from example_device import runtime

    clock = iter([100, 100, 281])
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    transport = FakeTransport()
    result = await make_runtime(transport, attachment_history_dataset()).run(ANCHOR)
    assert result.needs_continuation and result.cursor == 5
    assert transport.state["cursor"] == 5
    assert len(transport.messages) == 5

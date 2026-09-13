"""Resumable playback independent of the Doover transport."""

from __future__ import annotations

import hashlib
import time
from bisect import bisect_right
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, Sequence

from .dataset import AttachmentFile, DataPath, Dataset, Entry
from .state import PlaybackState, StateError
from .timeline import (
    ordered_entries,
    rebase_data,
    reconstruct_aggregates,
    set_data_path,
)

if TYPE_CHECKING:
    from .commands import CommandRequest, CommandResult

DOOVER_EPOCH_MS = 1_735_689_600_000
IMPORT_MARKER = "_example_device"
ATTACHMENT_MESSAGES_PER_BATCH = 5


@dataclass(frozen=True)
class HistoryWrite:
    channel: str
    message_id: int
    timestamp_ms: int
    data: dict[str, Any]
    attachments: tuple[AttachmentFile, ...] = ()
    attachment_paths: tuple[DataPath, ...] = ()


@dataclass(frozen=True)
class WriteResult:
    message_id: int
    success: bool
    error: str | None = None


class Transport(Protocol):
    """Implementations verify mutual exclusion and identity before mutations."""

    def serialized(self) -> AbstractAsyncContextManager[None]: ...

    async def read_state(self) -> dict[str, Any] | None: ...

    async def write_state(self, value: dict[str, Any]) -> None: ...

    async def publish_messages(
        self, items: Sequence[HistoryWrite]
    ) -> Sequence[WriteResult]:
        """Reject an existing ID with different content; report every outcome."""
        ...

    async def ensure_attachments(self, item: HistoryWrite) -> dict[str, str]:
        """Upload missing files to a stable message and return filename-to-URL bindings."""
        ...

    async def patch_aggregate(
        self, channel: str, data: dict[str, Any], replace_paths: Sequence[str] = ()
    ) -> None: ...

    async def update_rpc_response(
        self, channel: str, message_id: int, response: dict[str, Any]
    ) -> None: ...


@dataclass(frozen=True)
class RunResult:
    phase: str
    cursor: int
    published: int
    needs_continuation: bool
    next_due_ms: int | None


def stable_message_id(
    timestamp_ms: int, identity: str, used: set[int] | None = None
) -> int:
    """Allocate a deterministic suffix while retaining Doover's time/type bits.

    This is not a platform reservation. The transport must reject a collision
    with an unrelated stored record before attempting any write.
    """
    elapsed = timestamp_ms - DOOVER_EPOCH_MS
    if not 0 <= elapsed < (1 << 42):
        raise ValueError("Message timestamp is outside the Doover snowflake range")
    suffix = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:4], "big") % (
        1 << 18
    )
    for step in range(1 << 18):
        candidate = (suffix + step) % (1 << 18)
        lower_bits = ((candidate >> 4) << 8) | (2 << 4) | (candidate & 15)
        result = (elapsed << 22) | lower_bits
        if used is None or result not in used:
            if used is not None:
                used.add(result)
            return result
    raise ValueError("Too many example messages at one millisecond")


class Runtime:
    def __init__(
        self,
        dataset: Dataset,
        transport: Transport,
        *,
        anchor_ms: int,
        revision: str,
        installation_id: str,
        idle_interval_ms: int = 1_800_000,
        active_interval_ms: int = 60_000,
        max_batches: int = 4,
        invocation_budget_seconds: int = 180,
    ):
        if (
            idle_interval_ms <= 0
            or active_interval_ms <= 0
            or max_batches <= 0
            or invocation_budget_seconds <= 0
        ):
            raise ValueError("Runtime intervals and batch budget must be positive")
        self.dataset = dataset
        self.transport = transport
        self.anchor_ms = anchor_ms
        self.revision = revision
        self.installation_id = installation_id
        self.idle_interval_ms = idle_interval_ms
        self.active_interval_ms = active_interval_ms
        self.max_batches = max_batches
        self.invocation_budget_seconds = invocation_budget_seconds
        self.entries = ordered_entries(dataset)
        self.offsets = tuple(entry.timestamp for entry in self.entries)
        self.ids: dict[tuple[str, str], str] = {}
        self._entry_ids: dict[tuple[str, int], int] = {}
        self._messages = {
            (entry.channel, entry.id): entry
            for entry in self.entries
            if entry.kind == "message"
        }
        self._attachment_bindings: dict[tuple[str, int], dict[str, str]] = {}
        used: set[int] = set()
        for entry in self.entries:
            if entry.kind != "message":
                continue
            identity = "|".join(
                (
                    installation_id,
                    revision,
                    dataset.config.slug,
                    entry.channel,
                    entry.id or str(entry.index),
                )
            )
            message_id = stable_message_id(anchor_ms + entry.timestamp, identity, used)
            self._entry_ids[(entry.channel, entry.index)] = message_id
            if entry.id is not None:
                self.ids[(entry.channel, entry.id)] = str(message_id)

    async def _read_state(self) -> PlaybackState:
        raw = await self.transport.read_state()
        if raw is None:
            return PlaybackState(
                self.dataset.config.slug, self.revision, self.anchor_ms
            )
        state = PlaybackState.from_dict(raw)
        if (state.dataset_slug, state.revision, state.anchor_ms) != (
            self.dataset.config.slug,
            self.revision,
            self.anchor_ms,
        ):
            raise StateError(
                "Stored state belongs to a different dataset, revision or anchor"
            )
        if state.cursor > len(self.entries) or state.aggregate_cursor > len(
            self.entries
        ):
            raise StateError("Stored cursor exceeds the pinned dataset")
        input_keys = {
            f"{item.app_key}.{item.method}" for item in self.dataset.config.inputs
        }
        if not state.commands.keys() <= input_keys:
            raise StateError("Stored commands are outside the pinned input contract")
        return state

    def _base_write(self, entry: Entry) -> HistoryWrite:
        data = rebase_data(entry, self.anchor_ms, self.ids)
        data[IMPORT_MARKER] = {
            "origin": "dataset",
            "dataset": self.dataset.config.slug,
            "revision": self.revision,
            "record_id": entry.id or str(entry.index),
        }
        if entry.attachments:
            data[IMPORT_MARKER]["attachments"] = [
                {
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "size": file.size,
                    "sha256": file.sha256,
                }
                for file in entry.attachments
            ]
        return HistoryWrite(
            entry.channel,
            self._entry_ids[(entry.channel, entry.index)],
            self.anchor_ms + entry.timestamp,
            data,
            entry.attachments,
            tuple(field.path for field in entry.attachment_references),
        )

    async def _attachment_urls(self, entry: Entry) -> dict[str, str]:
        key = (entry.channel, entry.index)
        if key not in self._attachment_bindings:
            self._attachment_bindings[key] = await self.transport.ensure_attachments(
                self._base_write(entry)
            )
        return self._attachment_bindings[key]

    async def _resolve_attachments(self, entry: Entry, data: dict[str, Any]) -> None:
        for reference in entry.attachment_references:
            target = self._messages[(reference.channel, reference.id)]
            urls = await self._attachment_urls(target)
            set_data_path(data, reference.path, urls[reference.filename])

    async def _write(self, entry: Entry) -> HistoryWrite:
        item = self._base_write(entry)
        await self._resolve_attachments(entry, item.data)
        return item

    def _history_batch_end(self, start: int, eligible_end: int) -> int:
        """Checkpoint smaller groups when each record needs several network uploads."""
        end = min(start + 50, eligible_end)
        captures = 0
        for index in range(start, end):
            if self.entries[index].attachments:
                captures += 1
            if captures == ATTACHMENT_MESSAGES_PER_BATCH:
                return index + 1
        return end

    async def run(
        self, now_ms: int, observed: bool = False, force: bool = False
    ) -> RunResult:
        from .commands import resume_pending_commands

        if now_ms < self.anchor_ms:
            raise ValueError("Cannot initialize playback before its fixed anchor")
        deadline = time.monotonic() + self.invocation_budget_seconds
        async with self.transport.serialized():
            state = await self._read_state()
            await resume_pending_commands(self, state)
            interval = self.active_interval_ms if observed else self.idle_interval_ms
            if state.phase == "exhausted":
                return RunResult(state.phase, state.cursor, 0, False, None)
            newly_observed = observed and not state.last_observed
            observation_changed = observed != state.last_observed
            state.last_observed = observed
            if (
                state.phase == "active"
                and state.last_publication_ms is not None
                and not newly_observed
                and not force
            ):
                due_ms = state.last_publication_ms + interval
                if (
                    now_ms < due_ms
                    and now_ms < self.anchor_ms + self.dataset.duration_ms
                ):
                    if observation_changed:
                        await self.transport.write_state(state.to_dict())
                    return RunResult(state.phase, state.cursor, 0, False, due_ms)

            if state.phase == "initializing":
                # Save the installation identity before any external channel write.
                await self.transport.write_state(state.to_dict())
                for entry in self.entries[: bisect_right(self.offsets, 0)]:
                    if entry.kind == "aggregate" or (
                        entry.timestamp == 0 and entry.apply_to_aggregate
                    ):
                        await self._apply_aggregate_entry(entry)
                state.phase = "importing"
                state.aggregate_cursor = bisect_right(self.offsets, 0)
                await self.transport.write_state(state.to_dict())

            offset = min(now_ms - self.anchor_ms, self.dataset.duration_ms)
            eligible_end = bisect_right(self.offsets, offset)
            published = 0
            for _ in range(self.max_batches):
                if state.cursor >= eligible_end:
                    break
                # This is a between-batch budget, not a cancellation deadline for
                # requests already in progress. HTTP clients retain their timeouts.
                if time.monotonic() >= deadline:
                    return RunResult(state.phase, state.cursor, published, True, now_ms)
                batch_end = self._history_batch_end(state.cursor, eligible_end)
                entries = self.entries[state.cursor : batch_end]
                writes = [
                    await self._write(entry)
                    for entry in entries
                    if entry.kind == "message"
                ]
                results = (
                    await self.transport.publish_messages(writes) if writes else ()
                )
                outcomes = {result.message_id: result.success for result in results}
                if len(outcomes) != len(results) or set(outcomes) != {
                    item.message_id for item in writes
                }:
                    raise RuntimeError(
                        "Message transport returned an incomplete or duplicate result set"
                    )
                published += sum(result.success for result in results)
                start = state.cursor
                for entry in entries:
                    if (
                        entry.kind == "message"
                        and not outcomes[self._entry_ids[(entry.channel, entry.index)]]
                    ):
                        break
                    state.cursor += 1
                await self.transport.write_state(state.to_dict())
                if state.cursor != batch_end:
                    return RunResult(state.phase, state.cursor, published, True, now_ms)
                if state.cursor == start:
                    break

            if state.cursor < eligible_end:
                return RunResult(state.phase, state.cursor, published, True, now_ms)

            # Preserve deletion and scoped-replacement intent. A reconstructed
            # snapshot loses null tombstones, so merging that snapshot alone
            # would leave removed values in the service aggregate.
            for _ in range(self.max_batches):
                if state.aggregate_cursor >= eligible_end:
                    break
                if time.monotonic() >= deadline:
                    return RunResult(state.phase, state.cursor, published, True, now_ms)
                aggregate_end = min(state.aggregate_cursor + 50, eligible_end)
                for entry in self.entries[state.aggregate_cursor : aggregate_end]:
                    if entry.kind == "aggregate" or entry.apply_to_aggregate:
                        await self._apply_aggregate_entry(entry)
                state.aggregate_cursor = aggregate_end
                await self.transport.write_state(state.to_dict())
            if state.aggregate_cursor < eligible_end:
                return RunResult(state.phase, state.cursor, published, True, now_ms)
            if observed:
                aggregates = reconstruct_aggregates(
                    self.dataset,
                    offset,
                    anchor_ms=self.anchor_ms,
                    interpolate=True,
                    message_ids=self.ids,
                )
                patch = self._interpolated_patch(aggregates.get("tag_values", {}))
                if patch:
                    await self.transport.patch_aggregate("tag_values", patch)
            state.last_publication_ms = now_ms
            state.phase = (
                "exhausted" if offset >= self.dataset.duration_ms else "active"
            )
            await self.transport.write_state(state.to_dict())
            next_due = None if state.phase == "exhausted" else now_ms + interval
            return RunResult(state.phase, state.cursor, published, False, next_due)

    async def _apply_aggregate_entry(self, entry: Entry) -> None:
        data = rebase_data(entry, self.anchor_ms, self.ids)
        await self._resolve_attachments(entry, data)
        for key in reversed(entry.scope):
            data = {key: data}
        replace = (".".join(entry.scope),) if entry.mode == "replace" else ()
        await self.transport.patch_aggregate(entry.channel, data, replace)

    def _interpolated_patch(self, aggregate: dict[str, Any]) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        for rule in self.dataset.config.interpolation:
            value: Any = aggregate
            for key in rule.path:
                if not isinstance(value, dict) or key not in value:
                    value = None
                    break
                value = value[key]
            if type(value) not in (int, float):
                continue
            target = patch
            for key in rule.path[:-1]:
                target = target.setdefault(key, {})
            target[rule.path[-1]] = value
        return patch

    async def acknowledge(self, request: CommandRequest) -> CommandResult:
        from .commands import acknowledge

        return await acknowledge(self, request)

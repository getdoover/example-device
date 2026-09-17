"""Acknowledge declared example controls without changing telemetry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .dataset import Input
from .state import CommandProgress, PendingCommand, PlaybackState

if TYPE_CHECKING:
    from .runtime import Runtime


class CommandError(ValueError):
    """A live RPC is outside this example's declared input contract."""


@dataclass(frozen=True)
class CommandRequest:
    message_id: int
    timestamp_ms: int
    app_key: str
    method: str
    value: Any


@dataclass(frozen=True)
class CommandResult:
    status: str
    message_id: int


def validate_request(runtime: Runtime, request: CommandRequest) -> Input:
    if type(request.message_id) is not int or request.message_id <= 0:
        raise CommandError("Invalid command message ID")
    if (
        type(request.timestamp_ms) is not int
        or request.timestamp_ms < runtime.anchor_ms
    ):
        raise CommandError("Live command predates this installation")
    control = next(
        (
            item
            for item in runtime.dataset.config.inputs
            if item.app_key == request.app_key and item.method == request.method
        ),
        None,
    )
    if control is None:
        raise CommandError("Unknown example control")
    value = request.value
    valid = {
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": type(value) in (int, float) and math.isfinite(value),
        "string": isinstance(value, str),
        "null": value is None,
        "object": isinstance(value, dict),
    }.get(control.value_type, False)
    if not valid:
        raise CommandError(f"Control requires {control.value_type}")
    if control.choices is not None and value not in control.choices:
        raise CommandError("Value is outside the control choices")
    if type(value) in (int, float):
        if control.min is not None and value < control.min:
            raise CommandError("Value is below the control minimum")
        if control.max is not None and value > control.max:
            raise CommandError("Value is above the control maximum")
    return control


async def acknowledge(runtime: Runtime, request: CommandRequest) -> CommandResult:
    from .runtime import stable_message_id

    validate_request(runtime, request)
    async with runtime.transport.serialized():
        state = await runtime._read_state()
        if state.phase not in ("active", "exhausted"):
            raise CommandError("The example is still preparing its history")
        await resume_pending_commands(runtime, state)
        key = f"{request.app_key}.{request.method}"
        progress = state.commands.setdefault(key, CommandProgress())
        if request.message_id <= progress.last_request_id:
            # Delayed requests must not restore an older selected value. The
            # request's response is safe to repair without another input log.
            status = (
                "acknowledged"
                if request.message_id == progress.last_request_id
                else "superseded"
            )
            await runtime.transport.update_rpc_response(
                "ui_cmds", request.message_id, _response(status)
            )
            return CommandResult(status, request.message_id)

        log_id = stable_message_id(
            request.timestamp_ms,
            "|".join(
                (
                    runtime.installation_id,
                    runtime.revision,
                    "command-log",
                    str(request.message_id),
                )
            ),
            {request.message_id, *runtime._entry_ids.values()},
        )
        progress.pending = PendingCommand(
            request.message_id, request.timestamp_ms, request.value, log_id
        )
        # The pending request is durable before selected state, response or log
        # mutations. A later schedule can finish it without RPC redelivery.
        await runtime.transport.write_state(state.to_dict())
        await _finish_pending(runtime, state, key, progress)
        return CommandResult("acknowledged", request.message_id)


def _response(status: str) -> dict[str, Any]:
    return {
        "status": {"code": "success"},
        "response": {
            "status": status,
            "example_device": True,
            "telemetry_changed": False,
        },
    }


async def resume_pending_commands(runtime: Runtime, state: PlaybackState) -> None:
    """Caller must already hold the transport's local serialization context."""
    for key, progress in state.commands.items():
        if progress.pending is not None:
            await _finish_pending(runtime, state, key, progress)


async def _finish_pending(
    runtime: Runtime, state: PlaybackState, key: str, progress: CommandProgress
) -> None:
    from .runtime import IMPORT_MARKER, HistoryWrite

    pending = progress.pending
    if pending is None:
        return
    control = next(
        item
        for item in runtime.dataset.config.inputs
        if f"{item.app_key}.{item.method}" == key
    )
    await runtime.transport.patch_aggregate(
        "ui_cmds", {control.app_key: {control.method: pending.value}}
    )
    log = HistoryWrite(
        "ui_cmds",
        pending.log_id,
        pending.timestamp_ms,
        {
            "type": "log",
            "app_key": control.app_key,
            "key": control.method,
            "value": pending.value,
            IMPORT_MARKER: {
                "origin": "command_log",
                "request_id": str(pending.request_id),
            },
        },
    )
    results = await runtime.transport.publish_messages([log])
    if (
        len(results) != 1
        or results[0].message_id != pending.log_id
        or not results[0].success
    ):
        raise RuntimeError("Command input log was not confirmed")
    await runtime.transport.update_rpc_response(
        "ui_cmds", pending.request_id, _response("acknowledged")
    )
    progress.last_request_id = pending.request_id
    progress.pending = None
    await runtime.transport.write_state(state.to_dict())

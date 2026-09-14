"""Durable processor progress stored in one app-scoped device tag."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Phase = Literal["initializing", "importing", "active", "exhausted"]
READY_HISTORY_MESSAGES = 50


class StateError(ValueError):
    """Stored progress is invalid or belongs to another installation."""


@dataclass
class PendingCommand:
    request_id: int
    timestamp_ms: int
    value: Any
    log_id: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": str(self.request_id),
            "timestamp_ms": self.timestamp_ms,
            # Aggregate merge/replace removes object members whose value is
            # null. JSON text preserves a null command and nested object nulls.
            "value_json": json.dumps(
                self.value, allow_nan=False, separators=(",", ":")
            ),
            "log_id": str(self.log_id),
        }


@dataclass
class CommandProgress:
    last_request_id: int = 0
    pending: PendingCommand | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_request_id": str(self.last_request_id),
            "pending": self.pending.to_dict() if self.pending else None,
        }


@dataclass
class HistoryProgress:
    """Import [floor, end) backwards, independently of forward playback."""

    floor: int
    end: int
    cursor: int
    recent_count: int = 0

    @property
    def pending(self) -> bool:
        return self.cursor > self.floor

    @property
    def ready(self) -> bool:
        return self.recent_count >= READY_HISTORY_MESSAGES or not self.pending

    def to_dict(self) -> dict[str, int]:
        return {
            "floor": self.floor,
            "end": self.end,
            "cursor": self.cursor,
            "recent_count": self.recent_count,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HistoryProgress:
        floor = _integer(raw.get("floor"), "history floor", minimum=0)
        end = _integer(raw.get("end"), "history end", minimum=0)
        cursor = _integer(raw.get("cursor"), "history cursor", minimum=0)
        count = _integer(raw.get("recent_count"), "recent count", minimum=0)
        if not floor <= cursor <= end or count > min(
            READY_HISTORY_MESSAGES, end - cursor
        ):
            raise StateError("Invalid history progress")
        return cls(floor, end, cursor, count)


@dataclass
class PlaybackState:
    dataset_slug: str
    revision: str
    anchor_ms: int
    phase: Phase = "initializing"
    cursor: int = 0
    aggregate_cursor: int = 0
    last_publication_ms: int | None = None
    last_observed: bool = False
    commands: dict[str, CommandProgress] = field(default_factory=dict)
    history: HistoryProgress | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 2 if self.history is not None else 1,
            "dataset_slug": self.dataset_slug,
            "revision": self.revision,
            "anchor_ms": self.anchor_ms,
            "phase": self.phase,
            "cursor": self.cursor,
            "aggregate_cursor": self.aggregate_cursor,
            "last_publication_ms": self.last_publication_ms,
            "last_observed": self.last_observed,
            "commands": {key: item.to_dict() for key, item in self.commands.items()},
            "history": self.history.to_dict() if self.history is not None else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PlaybackState:
        """Parse the external tag value once at the storage boundary."""
        if raw.get("version") not in (1, 2):
            raise StateError("Unsupported playback state version")
        history = None
        if raw["version"] == 2:
            if not isinstance(raw.get("history"), dict):
                raise StateError("Playback state requires history progress")
            history = HistoryProgress.from_dict(raw["history"])
        phase = raw.get("phase")
        if phase not in ("initializing", "importing", "active", "exhausted"):
            raise StateError("Invalid playback phase")
        slug, revision = raw.get("dataset_slug"), raw.get("revision")
        if not isinstance(slug, str) or not isinstance(revision, str):
            raise StateError("Playback state requires dataset and revision")
        anchor = _integer(raw.get("anchor_ms"), "anchor_ms")
        cursor = _integer(raw.get("cursor"), "cursor", minimum=0)
        aggregate_cursor = _integer(
            raw.get("aggregate_cursor", 0), "aggregate_cursor", minimum=0
        )
        last_raw = raw.get("last_publication_ms")
        last = None if last_raw is None else _integer(last_raw, "last_publication_ms")
        observed = raw.get("last_observed", False)
        if type(observed) is not bool:
            raise StateError("last_observed must be boolean")
        commands_raw = raw.get("commands", {})
        if not isinstance(commands_raw, dict):
            raise StateError("commands must be an object")
        commands = {}
        for key, value in commands_raw.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise StateError("Invalid command progress")
            last_request_id = _identifier(
                value.get("last_request_id"), "last_request_id"
            )
            pending_raw = value.get("pending")
            pending = None
            if pending_raw is not None:
                if not isinstance(pending_raw, dict) or not isinstance(
                    pending_raw.get("value_json"), str
                ):
                    raise StateError("Invalid pending command")
                try:
                    pending_value = json.loads(pending_raw["value_json"])
                    json.dumps(pending_value, allow_nan=False)
                except (ValueError, TypeError) as error:
                    raise StateError(
                        "Pending command value is not valid JSON"
                    ) from error
                pending = PendingCommand(
                    _identifier(pending_raw.get("request_id"), "request_id"),
                    _integer(pending_raw.get("timestamp_ms"), "timestamp_ms"),
                    pending_value,
                    _identifier(pending_raw.get("log_id"), "log_id"),
                )
                if pending.request_id <= last_request_id:
                    raise StateError("Pending command precedes completed command")
            commands[key] = CommandProgress(last_request_id, pending)
        return cls(
            slug,
            revision,
            anchor,
            phase,
            cursor,
            aggregate_cursor,
            last,
            observed,
            commands,
            history,
        )


def _integer(value: Any, name: str, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise StateError(f"{name} must be an integer")
    return value


def _identifier(value: Any, name: str) -> int:
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    return _integer(value, name, minimum=0)

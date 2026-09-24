"""Replay a model from durable command checkpoints at their effective times."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

from .models import LoadedModel, json_object


@dataclass(frozen=True)
class ModelEvent:
    request_id: int
    offset_ms: int
    state: dict[str, Any]
    commands: dict[str, Any]

    def to_dict(self):
        return {
            "request_id": str(self.request_id),
            "offset_ms": self.offset_ms,
            "state": self.state,
            "commands": self.commands,
        }

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or set(raw) != {
            "request_id",
            "offset_ms",
            "state",
            "commands",
        }:
            raise ValueError("Invalid model command checkpoint")
        identifier, offset = raw["request_id"], raw["offset_ms"]
        if (
            not isinstance(identifier, str)
            or not identifier.isdecimal()
            or int(identifier) <= 0
        ):
            raise ValueError("Invalid model command ID")
        if type(offset) is not int or offset < 0:
            raise ValueError("Invalid model command time")
        return cls(
            int(identifier),
            offset,
            json_object(raw["state"], "Model checkpoint"),
            json_object(raw["commands"], "Model checkpoint commands"),
        )


def evaluate(model: LoadedModel, events: list[ModelEvent], offset_ms: int):
    index = bisect_right([event.offset_ms for event in events], offset_ms) - 1
    if index >= 0:
        event = events[index]
        state, commands, start = event.state, event.commands, event.offset_ms
    else:
        state, commands, start = (
            model.spec.initial_state,
            model.spec.initial_commands,
            0,
        )
    new_state, tags = model.step(state, commands, (offset_ms - start) / 1000)
    return new_state, commands, tags

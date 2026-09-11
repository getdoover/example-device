"""Pure state reconstruction and interpolation for an anchored replay."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .dataset import Dataset, Entry


def ordered_entries(
    dataset: Dataset, through_ms: int | None = None
) -> tuple[Entry, ...]:
    """Use timestamp, declared channel order, then source position for ties."""
    channel_order = {
        channel: index for index, channel in enumerate(dataset.config.channels)
    }
    return tuple(
        sorted(
            (
                entry
                for entries in dataset.channels.values()
                for entry in entries
                if through_ms is None or entry.timestamp <= through_ms
            ),
            key=lambda entry: (
                entry.timestamp,
                channel_order[entry.channel],
                entry.index,
            ),
        )
    )


def merge_data(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Match Doover merge-patch: null deletes object members; arrays replace."""
    result = deepcopy(target)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            previous = result.get(key)
            result[key] = merge_data(
                previous if isinstance(previous, dict) else {}, value
            )
        else:
            result[key] = deepcopy(value)
    return result


def _get(data: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _set(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = data
    for key in path[:-1]:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[path[-1]] = deepcopy(value)


def rebase_data(
    entry: Entry, anchor_ms: int, message_ids: dict[tuple[str, str], str] | None = None
) -> dict[str, Any]:
    """Translate explicitly declared timestamps and local message references."""
    data = deepcopy(entry.data)
    for field in entry.timestamp_fields:
        anchor = anchor_ms if field.unit == "ms" else anchor_ms / 1000
        _set(data, field.path, _get(data, field.path) + anchor)
    for field in entry.message_references:
        if message_ids is None:
            raise ValueError(
                "message_ids is required for entries with message references"
            )
        _set(data, field.path, message_ids[(field.channel, field.id)])
    return data


def apply_entry(
    current: dict[str, Any],
    entry: Entry,
    anchor_ms: int = 0,
    message_ids: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    """Apply one due aggregate operation without touching unrelated branches."""
    if entry.kind == "message" and not entry.apply_to_aggregate:
        return deepcopy(current)
    patch = rebase_data(entry, anchor_ms, message_ids)
    if not entry.scope:
        return merge_data(current, patch)
    result = deepcopy(current)
    previous = _get(current, entry.scope, {})
    value = (
        merge_data({}, patch)
        if entry.mode == "replace"
        else merge_data(previous if isinstance(previous, dict) else {}, patch)
    )
    _set(result, entry.scope, value)
    return result


def reconstruct_aggregates(
    dataset: Dataset,
    offset_ms: int,
    anchor_ms: int = 0,
    interpolate: bool = False,
    message_ids: dict[tuple[str, str], str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Replay due state changes; historical messages never replace the zero baseline."""
    aggregates: dict[str, dict[str, Any]] = {}
    for entry in ordered_entries(dataset, min(offset_ms, dataset.duration_ms)):
        if entry.kind == "message" and (
            not entry.apply_to_aggregate or entry.timestamp < 0
        ):
            continue
        aggregates[entry.channel] = apply_entry(
            aggregates.get(entry.channel, {}), entry, anchor_ms, message_ids
        )
    if interpolate and "tag_values" in aggregates:
        aggregates["tag_values"] = interpolate_tags(
            dataset, offset_ms, aggregates["tag_values"]
        )
    return aggregates


def interpolate_tags(
    dataset: Dataset, offset_ms: int, current: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Interpolate opted-in numeric leaves without publishing future samples."""
    if current is None:
        current = reconstruct_aggregates(dataset, offset_ms).get("tag_values", {})
    result = deepcopy(current)
    if offset_ms < 0 or offset_ms > dataset.duration_ms:
        return result
    missing = object()
    entries = dataset.channels.get("tag_values", ())
    for rule in dataset.config.interpolation:
        if type(_get(current, rule.path)) not in (int, float):
            continue
        points: dict[int, Any] = {}
        for entry in entries:
            if (
                entry.kind == "message"
                and entry.timestamp > 0
                and not entry.apply_to_aggregate
            ):
                continue
            if entry.scope and rule.path[: len(entry.scope)] != entry.scope:
                continue
            relative_path = rule.path[len(entry.scope) :]
            if not relative_path:
                continue
            value: Any = entry.data
            for part in relative_path:
                if not isinstance(value, dict):
                    value = None
                    break
                if part not in value:
                    value = missing
                    break
                value = value[part]
            if value is not missing:
                points[entry.timestamp] = value
            elif entry.mode == "replace" and entry.scope:
                points[entry.timestamp] = None
        before = [
            (timestamp, value)
            for timestamp, value in points.items()
            if timestamp <= offset_ms
        ]
        after = [
            (timestamp, value)
            for timestamp, value in points.items()
            if timestamp > offset_ms
        ]
        if not before:
            continue
        left_time, left = max(before, key=lambda pair: pair[0])
        if type(left) not in (int, float):
            continue
        if left_time == offset_ms:
            _set(result, rule.path, left)
            continue
        if not after:
            continue
        right_time, right = min(after, key=lambda pair: pair[0])
        if type(right) not in (int, float):
            continue
        if rule.max_gap_ms is not None and right_time - left_time > rule.max_gap_ms:
            continue
        fraction = (offset_ms - left_time) / (right_time - left_time)
        # A weighted sum avoids overflowing the difference of finite endpoints
        # with opposite signs, such as -1e308 and 1e308.
        value = left * (1 - fraction) + right * fraction
        _set(result, rule.path, value)
    return result

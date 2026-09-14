"""Parse portable example data before a processor mutates any channels."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal


class DatasetError(ValueError):
    """The dataset does not satisfy the portable replay contract."""


@dataclass(frozen=True)
class AppConfig:
    app_key: str
    application_name: str
    config: dict[str, Any]
    run: Literal[False] = False


@dataclass(frozen=True)
class ProcessorConfig:
    app_key: str
    application_name: str


@dataclass(frozen=True)
class Interpolation:
    path: tuple[str, ...]
    max_gap_ms: int | None = None


@dataclass(frozen=True)
class Input:
    app_key: str
    method: str
    value_type: str
    min: float | None = None
    max: float | None = None
    choices: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class TimestampField:
    path: tuple[str, ...]
    unit: Literal["ms", "s"]


@dataclass(frozen=True)
class MessageReference:
    path: tuple[str, ...]
    channel: str
    id: str


type DataPath = tuple[str | int, ...]


@dataclass(frozen=True)
class AttachmentFile:
    path: str
    filename: str
    content_type: str
    size: int
    sha256: str


@dataclass(frozen=True)
class AttachmentReference:
    path: DataPath
    channel: str
    id: str
    filename: str


@dataclass(frozen=True)
class Entry:
    channel: str
    index: int
    timestamp: int
    kind: Literal["aggregate", "message"]
    data: dict[str, Any]
    id: str | None = None
    mode: Literal["merge", "replace"] = "merge"
    scope: tuple[str, ...] = ()
    apply_to_aggregate: bool = False
    timestamp_fields: tuple[TimestampField, ...] = ()
    message_references: tuple[MessageReference, ...] = ()
    attachments: tuple[AttachmentFile, ...] = ()
    attachment_references: tuple[AttachmentReference, ...] = ()

    @property
    def timestamp_ms(self) -> int:
        return self.timestamp


@dataclass(frozen=True)
class DatasetConfig:
    schema_version: int
    slug: str
    name: str
    apps: tuple[AppConfig, ...]
    channels: tuple[str, ...]
    duration_ms: int
    interpolation: tuple[Interpolation, ...] = ()
    inputs: tuple[Input, ...] = ()
    processor: ProcessorConfig | None = None
    required_anchor_ms: int | None = None


@dataclass(frozen=True)
class Dataset:
    config: DatasetConfig
    channels: dict[str, tuple[Entry, ...]]

    @property
    def duration_ms(self) -> int:
        return self.config.duration_ms


_KEY = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,127}$")
_SLUG = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")
_FILENAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MIME = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_MESSAGE_ATTACHMENT_BYTES = 16 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 8
_RUNTIME_KEYS = frozenset(
    {
        "AGENT_ID",
        "ORGANISATION_ID",
        "ORGANIZATION_ID",
        "APP_ID",
        "APP_INSTALL_ID",
        "APP_KEY",
        "APP_INSTALL_KEY",
        "DEVICE_LIST",
        "DEVICE_MAP",
        "APPLICATION_ID",
        "APPLICATION_INSTALL_ID",
        "DEVICE_ID",
        "owner_id",
        "agent_id",
        "organisation_id",
        "organization_id",
        "device_id",
        "app_install_id",
        "application_id",
        "application_install_id",
        "app_id",
    }
)
_INPUT_TYPES = frozenset({"boolean", "number", "integer", "string", "null", "object"})


def _fail(where: str, message: str) -> None:
    raise DatasetError(f"{where}: {message}")


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail(where, "expected an object with string keys")
    return value


def _array(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(where, "expected an array")
    return value


def _fields(
    value: dict[str, Any], required: set[str], optional: set[str], where: str
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        _fail(where, f"missing fields: {', '.join(sorted(missing))}")
    if unknown:
        _fail(where, f"unknown fields: {', '.join(sorted(unknown))}")


def _string(value: Any, where: str, pattern: re.Pattern[str] | None = None) -> str:
    if (
        not isinstance(value, str)
        or not value
        or (pattern and not pattern.fullmatch(value))
    ):
        _fail(where, "expected a nonempty valid string")
    return value


def _integer(value: Any, where: str, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        _fail(
            where,
            f"expected an integer{' >= ' + str(minimum) if minimum is not None else ''}",
        )
    if abs(value) > 2**53 - 1:
        _fail(where, "integer exceeds exact JSON number range")
    return value


def _number(value: Any, where: str) -> int | float:
    if type(value) not in (int, float):
        _fail(where, "expected a finite number, not a boolean")
    if type(value) is int and abs(value) > 2**53 - 1:
        _fail(where, "integer exceeds exact JSON number range")
    if not math.isfinite(value):
        _fail(where, "expected a finite number, not a boolean")
    return value


def _json(value: Any, where: str) -> None:
    if value is None or type(value) in (str, bool):
        return
    if type(value) in (int, float):
        _number(value, where)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _json(child, f"{where}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in _object(value, where).items():
            if key == "_example_device":
                _fail(f"{where}.{key}", "reserved for processor import metadata")
            if key in _RUNTIME_KEYS:
                _fail(
                    f"{where}.{key}",
                    "installation identity must be bound at provisioning, not stored in a dataset",
                )
            _json(child, f"{where}.{key}")
        return
    _fail(where, "expected a JSON value")


def _path(value: Any, where: str) -> tuple[str, ...]:
    parts = tuple(_string(part, where) for part in _array(value, where))
    if not parts:
        _fail(where, "path must not be empty")
    return parts


def _at(data: dict[str, Any], path: tuple[str, ...], where: str) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict) or key not in value:
            _fail(where, f"path {'.'.join(path)} does not exist in data")
        value = value[key]
    return value


def _data_path(value: Any, where: str) -> DataPath:
    parts = []
    for part in _array(value, where):
        parts.append(
            _integer(part, where, 0) if type(part) is int else _string(part, where)
        )
    if not parts:
        _fail(where, "path must not be empty")
    return tuple(parts)


def _data_at(data: dict[str, Any], path: DataPath, where: str) -> Any:
    value: Any = data
    for key in path:
        if isinstance(value, dict) and isinstance(key, str) and key in value:
            value = value[key]
        elif isinstance(value, list) and type(key) is int and key < len(value):
            value = value[key]
        else:
            _fail(where, f"path {path!r} does not exist in data")
    return value


def _attachment(raw: Any, where: str) -> AttachmentFile:
    value = _object(raw, where)
    _fields(value, {"path", "filename", "content_type", "size", "sha256"}, set(), where)
    path = _string(value["path"], where)
    parts = path.split("/")
    if (
        len(parts) < 2
        or parts[0] != "attachments"
        or any(not _FILENAME.fullmatch(part) or part in (".", "..") for part in parts)
        or str(PurePosixPath(path)) != path
    ):
        _fail(
            where,
            "attachment path must stay under attachments/ with simple path components",
        )
    size = _integer(value["size"], where, 1)
    if size > MAX_ATTACHMENT_BYTES:
        _fail(where, "attachment exceeds the file size limit")
    return AttachmentFile(
        path,
        _string(value["filename"], where, _FILENAME),
        _string(value["content_type"], where, _MIME),
        size,
        _string(value["sha256"], where, _SHA256),
    )


def verify_attachment_bytes(attachment: AttachmentFile, raw: bytes) -> bytes:
    """Verify downloaded or local bytes against the pinned dataset manifest."""
    if (
        len(raw) != attachment.size
        or hashlib.sha256(raw).hexdigest() != attachment.sha256
    ):
        _fail(attachment.path, "attachment size or SHA-256 does not match its manifest")
    return raw


def read_local_attachment(directory: Path, attachment: AttachmentFile) -> bytes:
    root = directory.resolve()
    file = (root / attachment.path).resolve()
    if not file.is_relative_to(root / "attachments"):
        _fail(attachment.path, "attachment symlink escapes its directory")
    try:
        with file.open("rb") as stream:
            raw = stream.read(attachment.size + 1)
    except OSError as error:
        raise DatasetError(f"{attachment.path}: {error}") from error
    return verify_attachment_bytes(attachment, raw)


def _matches_input(value: Any, value_type: str) -> bool:
    return {
        "boolean": type(value) is bool,
        "number": type(value) in (int, float),
        "integer": type(value) is int,
        "string": type(value) is str,
        "null": value is None,
        "object": type(value) is dict,
    }[value_type]


def _config(raw: Any) -> DatasetConfig:
    raw = _object(raw, "config")
    _fields(
        raw,
        {"schema_version", "slug", "name", "apps", "channels", "duration_ms"},
        {"interpolation", "inputs", "processor", "required_anchor_ms"},
        "config",
    )
    if _integer(raw["schema_version"], "schema_version") != 1:
        _fail("schema_version", "only version 1 is supported")
    apps: list[AppConfig] = []
    for index, value in enumerate(_array(raw["apps"], "apps")):
        where = f"apps[{index}]"
        app = _object(value, where)
        _fields(app, {"app_key", "application_name", "config", "run"}, set(), where)
        key = _string(app["app_key"], f"{where}.app_key", _KEY)
        name = _string(app["application_name"], f"{where}.application_name", _KEY)
        if "host_configurator" in (key, name):
            _fail(where, "Host Configurator is excluded from example devices")
        if app["run"] is not False:
            _fail(
                where,
                "dataset apps must have run=false; the processor is installed separately",
            )
        config = _object(app["config"], f"{where}.config")
        _json(config, f"{where}.config")
        apps.append(AppConfig(key, name, deepcopy(config)))
    keys = {app.app_key for app in apps}
    if len(keys) != len(apps):
        _fail("apps", "app_key must be unique")
    processor = None
    if "processor" in raw:
        value = _object(raw["processor"], "processor")
        _fields(value, {"app_key", "application_name"}, set(), "processor")
        processor = ProcessorConfig(
            _string(value["app_key"], "processor.app_key", _KEY),
            _string(value["application_name"], "processor.application_name", _KEY),
        )
        if processor.app_key in keys:
            _fail("processor", "processor must not share a writable dataset app key")
        if "host_configurator" in (processor.app_key, processor.application_name):
            _fail("processor", "Host Configurator is excluded from example devices")
    channels = tuple(
        _string(value, "channels", _KEY)
        for value in _array(raw["channels"], "channels")
    )
    if not channels or len(channels) != len(set(channels)):
        _fail("channels", "expected unique channel names and at least one channel")
    if "dv-ui-sub" in channels:
        _fail("channels", "viewer presence is runtime state, not an authored channel")
    interpolation: list[Interpolation] = []
    for index, value in enumerate(
        _array(raw.get("interpolation", []), "interpolation")
    ):
        where = f"interpolation[{index}]"
        rule = _object(value, where)
        _fields(rule, {"path"}, {"max_gap_ms"}, where)
        path = _path(rule["path"], where)
        if len(path) < 2 or path[0] not in keys or "tag_values" not in channels:
            _fail(where, "interpolation requires a declared app's tag_values path")
        gap = _integer(rule["max_gap_ms"], where, 1) if "max_gap_ms" in rule else None
        interpolation.append(Interpolation(path, gap))
    if len({rule.path for rule in interpolation}) != len(interpolation):
        _fail("interpolation", "paths must be unique")
    inputs: list[Input] = []
    for index, value in enumerate(_array(raw.get("inputs", []), "inputs")):
        where = f"inputs[{index}]"
        control = _object(value, where)
        _fields(
            control,
            {"app_key", "method", "value_type"},
            {"min", "max", "choices"},
            where,
        )
        app_key = _string(control["app_key"], where, _KEY)
        method = _string(control["method"], where, _KEY)
        value_type = _string(control["value_type"], where)
        if app_key not in keys or "ui_cmds" not in channels:
            _fail(where, "inputs require a declared app and ui_cmds channel")
        if value_type not in _INPUT_TYPES:
            _fail(where, f"unsupported value_type {value_type}")
        minimum = _number(control["min"], where) if "min" in control else None
        maximum = _number(control["max"], where) if "max" in control else None
        if (minimum is not None or maximum is not None) and value_type not in {
            "number",
            "integer",
        }:
            _fail(where, "min and max apply only to numeric inputs")
        if minimum is not None and maximum is not None and minimum > maximum:
            _fail(where, "min must not exceed max")
        choices = None
        if "choices" in control:
            choices = tuple(deepcopy(_array(control["choices"], where)))
            if not choices:
                _fail(where, "choices must not be empty")
            for choice in choices:
                _json(choice, where)
                if not _matches_input(choice, value_type):
                    _fail(where, "choice does not match value_type")
                if (
                    minimum is not None
                    and choice < minimum
                    or maximum is not None
                    and choice > maximum
                ):
                    _fail(where, "choice falls outside min/max")
        inputs.append(Input(app_key, method, value_type, minimum, maximum, choices))
    if len({(control.app_key, control.method) for control in inputs}) != len(inputs):
        _fail("inputs", "app_key and method pairs must be unique")
    return DatasetConfig(
        1,
        _string(raw["slug"], "slug", _SLUG),
        _string(raw["name"], "name"),
        tuple(apps),
        channels,
        _integer(raw["duration_ms"], "duration_ms", 0),
        tuple(interpolation),
        tuple(inputs),
        processor,
        _integer(raw["required_anchor_ms"], "required_anchor_ms", 1735689600000)
        if "required_anchor_ms" in raw
        else None,
    )


def _ownership(
    channel: str,
    data: dict[str, Any],
    scope: tuple[str, ...],
    keys: set[str],
    where: str,
) -> None:
    if channel == "ui_overrides":
        if scope or set(data) != {"ops"} or not isinstance(data["ops"], list):
            _fail(where, "ui_overrides must contain an unscoped ops array")
        return
    prefixes = {
        "tag_values": (),
        "ui_cmds": (),
        "ui_state": ("state", "children"),
        "deployment_config": ("applications",),
    }
    if channel not in prefixes:
        return
    prefix = prefixes[channel]
    if scope:
        if (
            scope[: len(prefix)] != prefix
            or len(scope) <= len(prefix)
            or scope[len(prefix)] not in keys
        ):
            _fail(where, "scope must stay within a declared app's aggregate branch")
        return
    node = data
    for key in prefix:
        if set(node) != {key} or not isinstance(node[key], dict):
            _fail(where, f"aggregate must contain only {'.'.join(prefix)} app branches")
        node = node[key]
    if not set(node) <= keys or any(
        not isinstance(value, dict) for value in node.values()
    ):
        _fail(where, "aggregate can write only declared app objects")


def _entry(raw: Any, channel: str, index: int, config: DatasetConfig) -> Entry:
    where = f"{channel}[{index}]"
    raw = _object(raw, where)
    kind = raw.get("kind")
    common = {"timestamp", "kind", "data"}
    extra = {"timestamp_fields", "message_references", "attachment_references"}
    if kind == "aggregate":
        _fields(raw, common | {"mode"}, extra | {"scope"}, where)
    elif kind == "message":
        _fields(
            raw, common | {"id"}, extra | {"apply_to_aggregate", "attachments"}, where
        )
    else:
        _fail(where, "kind must be aggregate or message")
    timestamp = _integer(raw["timestamp"], f"{where}.timestamp")
    if timestamp > config.duration_ms:
        _fail(where, "timestamp exceeds duration_ms")
    if channel == "ui_cmds" and timestamp > 0:
        _fail(where, "future scripted inputs are not supported")
    data = _object(raw["data"], f"{where}.data")
    _json(data, f"{where}.data")
    scope = _path(raw["scope"], f"{where}.scope") if "scope" in raw else ()
    if any("." in part for part in scope):
        _fail(
            where,
            "scope segments cannot contain dots because the aggregate API uses dotted paths",
        )
    mode = raw.get("mode", "merge")
    if mode not in {"merge", "replace"}:
        _fail(where, "mode must be merge or replace")
    if mode == "replace" and not scope:
        _fail(where, "replace requires a nonempty scope to preserve unrelated state")
    if channel == "deployment_config" and mode == "replace":
        _fail(where, "deployment_config replacement would erase installation bindings")
    apply = raw.get("apply_to_aggregate", False)
    if type(apply) is not bool:
        _fail(where, "apply_to_aggregate must be boolean")
    if apply and channel == "ui_cmds":
        _fail(
            where,
            "RPC and input log messages must not be merged into selected-input state",
        )
    if kind == "aggregate" or apply:
        _ownership(channel, data, scope, {app.app_key for app in config.apps}, where)
    timestamps: list[TimestampField] = []
    for value in _array(raw.get("timestamp_fields", []), where):
        field = _object(value, where)
        _fields(field, {"path", "unit"}, set(), where)
        path = _path(field["path"], where)
        if field["unit"] not in {"ms", "s"}:
            _fail(where, "timestamp unit must be ms or s")
        value = _at(data, path, where)
        _integer(value, where) if field["unit"] == "ms" else _number(value, where)
        timestamps.append(TimestampField(path, field["unit"]))
    references: list[MessageReference] = []
    for value in _array(raw.get("message_references", []), where):
        field = _object(value, where)
        _fields(field, {"path", "channel", "id"}, set(), where)
        path = _path(field["path"], where)
        _at(data, path, where)
        references.append(
            MessageReference(
                path,
                _string(field["channel"], where, _KEY),
                _string(field["id"], where, _ID),
            )
        )
    attachments = tuple(
        _attachment(value, where) for value in _array(raw.get("attachments", []), where)
    )
    if (
        len(attachments) > MAX_ATTACHMENTS_PER_MESSAGE
        or sum(file.size for file in attachments) > MAX_MESSAGE_ATTACHMENT_BYTES
    ):
        _fail(where, "message attachments exceed the upload limit")
    if len({file.filename for file in attachments}) != len(attachments):
        _fail(where, "attachment filenames must be unique within a message")
    attachment_references = []
    for value in _array(raw.get("attachment_references", []), where):
        field = _object(value, where)
        _fields(field, {"path", "channel", "id", "filename"}, set(), where)
        path = _data_path(field["path"], where)
        if _data_at(data, path, where) is not None:
            _fail(where, "attachment reference placeholder must be null")
        attachment_references.append(
            AttachmentReference(
                path,
                _string(field["channel"], where, _KEY),
                _string(field["id"], where, _ID),
                _string(field["filename"], where, _FILENAME),
            )
        )
    paths = (
        [field.path for field in timestamps]
        + [field.path for field in references]
        + [field.path for field in attachment_references]
    )
    if any(
        left == right[: len(left)]
        for index, left in enumerate(paths)
        for other, right in enumerate(paths)
        if index != other
    ):
        _fail(
            where, "timestamp and reference paths must be distinct and must not overlap"
        )
    return Entry(
        channel,
        index,
        timestamp,
        kind,
        deepcopy(data),
        _string(raw["id"], f"{where}.id", _ID) if kind == "message" else None,
        mode,
        scope,
        apply,
        tuple(timestamps),
        tuple(references),
        attachments,
        tuple(attachment_references),
    )


def parse_dataset(config: Any, channels: Any) -> Dataset:
    """Validate all files and cross-file references as one transaction boundary."""
    parsed = _config(config)
    channels = _object(channels, "channels")
    if set(channels) != set(parsed.channels):
        _fail("channels", "files must match the config channel list exactly")
    result: dict[str, tuple[Entry, ...]] = {}
    identities: dict[tuple[str, str], Entry] = {}
    for channel in parsed.channels:
        entries = tuple(
            _entry(raw, channel, index, parsed)
            for index, raw in enumerate(_array(channels[channel], channel))
        )
        if any(
            left.timestamp > right.timestamp
            for left, right in zip(entries, entries[1:])
        ):
            _fail(
                channel, "entries must be ordered by timestamp; array order breaks ties"
            )
        for entry in entries:
            if entry.id is not None:
                key = (channel, entry.id)
                if key in identities:
                    _fail(channel, f"duplicate message id {entry.id}")
                identities[key] = entry
        result[channel] = entries
    channel_order = {channel: index for index, channel in enumerate(parsed.channels)}

    def order(entry: Entry) -> tuple[int, int, int]:
        return entry.timestamp, channel_order[entry.channel], entry.index

    for entries in result.values():
        for entry in entries:
            for reference in entry.attachment_references:
                target = identities.get((reference.channel, reference.id))
                if (
                    target is None
                    or order(target) > order(entry)
                    or reference.filename
                    not in {file.filename for file in target.attachments}
                ):
                    _fail(
                        entry.channel,
                        "attachment reference must name a file on this or an earlier message",
                    )
            for reference in entry.message_references:
                target = identities.get((reference.channel, reference.id))
                if target is None or order(target) >= order(entry):
                    _fail(
                        entry.channel,
                        "message reference must point to an earlier message in replay order",
                    )
            if entry.channel == "tag_values":
                timestamp_paths = {
                    entry.scope + field.path for field in entry.timestamp_fields
                } | {entry.scope + field.path for field in entry.attachment_references}
                if timestamp_paths & {rule.path for rule in parsed.interpolation}:
                    _fail(
                        "interpolation", "timestamp metadata must not be interpolated"
                    )
    return Dataset(parsed, result)


def _load_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _fail(str(path), f"duplicate JSON key {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DatasetError(f"{path}: {error}") from error


def load_directory(path: str | Path) -> Dataset:
    """Load exactly the declared channel files from a local dataset directory."""
    directory = Path(path)
    raw_config = _load_json(directory / "config.json")
    config = _config(raw_config)
    channel_directory = directory / "channels"
    files = {file.stem for file in channel_directory.glob("*.json")}
    if files != set(config.channels):
        _fail(
            str(channel_directory),
            "JSON files must match the config channel list exactly",
        )
    result = parse_dataset(
        raw_config,
        {
            channel: _load_json(channel_directory / f"{channel}.json")
            for channel in config.channels
        },
    )
    checked: set[AttachmentFile] = set()
    for entries in result.channels.values():
        for entry in entries:
            for attachment in entry.attachments:
                if attachment not in checked:
                    read_local_attachment(directory, attachment)
                    checked.add(attachment)
    return result

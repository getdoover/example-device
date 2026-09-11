import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from example_device.dataset import DatasetError, load_directory, parse_dataset


def config(channels=None):
    return {
        "schema_version": 1,
        "slug": "test-scenario",
        "name": "Test scenario",
        "apps": [
            {
                "app_key": "sensor",
                "application_name": "sensor_app",
                "config": {},
                "run": False,
            }
        ],
        "channels": channels or ["tag_values"],
        "duration_ms": 60000,
        "interpolation": [{"path": ["sensor", "level"], "max_gap_ms": 60000}],
    }


def baseline(data=None):
    return {
        "kind": "aggregate",
        "timestamp": 0,
        "mode": "merge",
        "data": data or {"sensor": {"level": 10}},
    }


def sample(timestamp=10000, **extra):
    return {
        "kind": "message",
        "timestamp": timestamp,
        "id": "record-a",
        "data": {"sensor": {"level": 20}},
        **extra,
    }


def test_parser_returns_independent_values_and_explicit_processor():
    raw = config()
    raw["processor"] = {"app_key": "replay", "application_name": "example_device"}
    channels = {"tag_values": [baseline(), sample()]}
    parsed = parse_dataset(raw, channels)
    channels["tag_values"][0]["data"]["sensor"]["level"] = 999
    assert parsed.channels["tag_values"][0].data["sensor"]["level"] == 10
    assert parsed.config.processor.app_key == "replay"
    assert parsed.duration_ms == 60000
    assert parsed.channels["tag_values"][1].timestamp_ms == 10000


@pytest.mark.parametrize("value", [True, False, 1.5, "0", None, 2**53])
def test_offsets_require_safe_integers(value):
    with pytest.raises(DatasetError, match="integer"):
        parse_dataset(config(), {"tag_values": [sample(value)]})


@pytest.mark.parametrize(
    "field,value",
    [("schema_version", 2), ("duration_ms", -1), ("slug", "../escape"), ("unknown", 1)],
)
def test_invalid_config_fields(field, value):
    raw = config()
    raw[field] = value
    with pytest.raises(DatasetError):
        parse_dataset(raw, {"tag_values": []})


@pytest.mark.parametrize(
    "identity",
    ["AGENT_ID", "APPLICATION_ID", "APP_INSTALL_ID", "device_id", "organisation_id"],
)
def test_installation_bindings_cannot_be_authored(identity):
    with pytest.raises(DatasetError, match="installation identity"):
        parse_dataset(
            config(),
            {"tag_values": [baseline({"sensor": {identity: "fictional-binding"}})]},
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**1000])
def test_payload_rejects_nonfinite_or_inexact_numbers(value):
    with pytest.raises(DatasetError):
        parse_dataset(
            config(), {"tag_values": [baseline({"sensor": {"level": value}})]}
        )


def test_channel_and_record_identity_checks():
    with pytest.raises(DatasetError, match="match"):
        parse_dataset(config(), {"other": []})
    with pytest.raises(DatasetError, match="duplicate message"):
        parse_dataset(config(), {"tag_values": [sample(), sample()]})
    with pytest.raises(DatasetError, match="ordered"):
        parse_dataset(config(), {"tag_values": [sample(), baseline()]})
    with pytest.raises(DatasetError, match="duration"):
        parse_dataset(config(), {"tag_values": [sample(60001)]})


def test_app_key_uniqueness_and_run_flags():
    raw = config()
    raw["apps"][0]["run"] = True
    with pytest.raises(DatasetError, match="run=false"):
        parse_dataset(raw, {"tag_values": []})
    raw = config()
    raw["apps"].append(deepcopy(raw["apps"][0]))
    with pytest.raises(DatasetError, match="unique"):
        parse_dataset(raw, {"tag_values": []})
    raw = config()
    raw["processor"] = {"app_key": "sensor", "application_name": "example_device"}
    with pytest.raises(DatasetError, match="writable"):
        parse_dataset(raw, {"tag_values": []})


def test_host_configurator_and_presence_channels_are_rejected():
    raw = config()
    raw["apps"][0]["application_name"] = "host_configurator"
    with pytest.raises(DatasetError, match="Host Configurator"):
        parse_dataset(raw, {"tag_values": []})
    raw = config(["dv-ui-sub"])
    raw["interpolation"] = []
    with pytest.raises(DatasetError, match="presence"):
        parse_dataset(raw, {"dv-ui-sub": []})


def test_import_metadata_is_reserved_for_runtime():
    for channel in ("tag_values", "custom"):
        raw = config([channel])
        raw["interpolation"] = []
        with pytest.raises(DatasetError, match="reserved"):
            parse_dataset(
                raw,
                {channel: [sample(data={"_example_device": {"origin": "dataset"}})]},
            )


def test_deployment_replacement_and_override_shape_fail_before_transport():
    raw = config(["deployment_config"])
    raw["interpolation"] = []
    entry = {
        "kind": "aggregate",
        "timestamp": 0,
        "mode": "replace",
        "scope": ["applications", "sensor"],
        "data": {"name": "Generic"},
    }
    with pytest.raises(DatasetError, match="installation bindings"):
        parse_dataset(raw, {"deployment_config": [entry]})
    raw["channels"] = ["ui_overrides"]
    with pytest.raises(DatasetError, match="ops array"):
        parse_dataset(raw, {"ui_overrides": [baseline({"other": []})]})
    valid = baseline({"ops": []})
    assert parse_dataset(raw, {"ui_overrides": [valid]}).channels["ui_overrides"][
        0
    ].data == {"ops": []}


@pytest.mark.parametrize(
    "channel,data",
    [
        ("tag_values", {"replay": {"cursor": 100}}),
        ("ui_cmds", {"undeclared": {"enabled": True}}),
        ("ui_state", {"state": {"children": {"undeclared": {}}}}),
        ("deployment_config", {"applications": {"undeclared": {}}}),
    ],
)
def test_aggregates_cannot_write_undeclared_app_namespaces(channel, data):
    raw = config([channel])
    raw["interpolation"] = []
    with pytest.raises(DatasetError, match="declared app"):
        parse_dataset(raw, {channel: [baseline(data)]})


def test_replace_requires_an_owned_scope():
    entry = baseline()
    entry["mode"] = "replace"
    with pytest.raises(DatasetError, match="scope"):
        parse_dataset(config(), {"tag_values": [entry]})
    entry["scope"] = ["replay"]
    with pytest.raises(DatasetError, match="scope"):
        parse_dataset(config(), {"tag_values": [entry]})
    entry["scope"] = ["sensor"]
    entry["data"] = {"level": 2}
    parsed = parse_dataset(config(), {"tag_values": [entry]})
    assert parsed.channels["tag_values"][0].scope == ("sensor",)
    entry["scope"] = ["sensor", "value.with.dot"]
    with pytest.raises(DatasetError, match="dots"):
        parse_dataset(config(), {"tag_values": [entry]})


def test_historical_rpc_is_separate_from_selected_state():
    raw = config(["ui_cmds"])
    raw["interpolation"] = []
    rpc = sample(
        -1000,
        data={"type": "rpc", "app_key": "sensor", "method": "enabled", "request": True},
    )
    parse_dataset(raw, {"ui_cmds": [rpc, baseline({"sensor": {"enabled": True}})]})
    rpc["apply_to_aggregate"] = True
    with pytest.raises(DatasetError, match="selected-input"):
        parse_dataset(raw, {"ui_cmds": [rpc]})
    rpc["apply_to_aggregate"] = False
    rpc["timestamp"] = 1
    with pytest.raises(DatasetError, match="future scripted"):
        parse_dataset(raw, {"ui_cmds": [rpc]})


def test_timestamp_fields_are_declared_present_numeric_and_not_interpolated():
    entry = baseline()
    entry["timestamp_fields"] = [{"path": ["sensor", "missing"], "unit": "ms"}]
    with pytest.raises(DatasetError, match="does not exist"):
        parse_dataset(config(), {"tag_values": [entry]})
    entry["timestamp_fields"][0]["path"] = ["sensor", "level"]
    with pytest.raises(DatasetError, match="metadata"):
        parse_dataset(config(), {"tag_values": [entry]})
    entry["timestamp_fields"][0]["unit"] = "minutes"
    with pytest.raises(DatasetError, match="unit"):
        parse_dataset(config(), {"tag_values": [entry]})


def test_message_reference_must_resolve_to_an_earlier_record():
    first = sample(0)
    second = sample(
        1000,
        id="record-b",
        data={"retry_of": None},
        message_references=[
            {"path": ["retry_of"], "channel": "tag_values", "id": "record-a"}
        ],
    )
    parse_dataset(config(), {"tag_values": [first, second]})
    second["message_references"][0]["id"] = "unknown"
    with pytest.raises(DatasetError, match="earlier message"):
        parse_dataset(config(), {"tag_values": [first, second]})
    first["message_references"] = [
        {"path": ["sensor", "level"], "channel": "tag_values", "id": "record-b"}
    ]
    with pytest.raises(DatasetError, match="earlier message"):
        parse_dataset(config(), {"tag_values": [first, second]})


def test_input_constraints_validate_types_and_bounds():
    raw = config(["tag_values", "ui_cmds"])
    raw["inputs"] = [
        {
            "app_key": "sensor",
            "method": "alarm",
            "value_type": "number",
            "min": 0,
            "max": 10,
            "choices": [1, 2],
        }
    ]
    assert parse_dataset(raw, {"tag_values": [], "ui_cmds": []}).config.inputs[
        0
    ].choices == (1, 2)
    raw["inputs"][0]["choices"] = [True]
    with pytest.raises(DatasetError, match="value_type"):
        parse_dataset(raw, {"tag_values": [], "ui_cmds": []})
    raw["inputs"][0]["choices"] = [11]
    with pytest.raises(DatasetError, match="outside"):
        parse_dataset(raw, {"tag_values": [], "ui_cmds": []})


def test_local_loader_checks_actual_files_and_duplicate_keys(tmp_path):
    (tmp_path / "channels").mkdir()
    (tmp_path / "config.json").write_text(json.dumps(config()))
    channel = tmp_path / "channels" / "tag_values.json"
    channel.write_text(json.dumps([baseline()]))
    assert load_directory(tmp_path).config.slug == "test-scenario"
    channel.write_text('[{"kind":"message","kind":"aggregate"}]')
    with pytest.raises(DatasetError, match="duplicate JSON key"):
        load_directory(tmp_path)
    channel.write_text("[]")
    (tmp_path / "channels" / "extra.json").write_text("[]")
    with pytest.raises(DatasetError, match="match"):
        load_directory(tmp_path)


def test_public_schemas_accept_parser_examples():
    root = Path(__file__).resolve().parents[1]
    for filename, instance in [
        ("device.schema.json", config()),
        ("channel.schema.json", [baseline(), sample()]),
    ]:
        schema = json.loads((root / "schemas" / filename).read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(instance)

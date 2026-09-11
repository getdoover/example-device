from copy import deepcopy

import pytest

from example_device.dataset import parse_dataset
from example_device.timeline import (
    apply_entry,
    interpolate_tags,
    merge_data,
    ordered_entries,
    rebase_data,
    reconstruct_aggregates,
)


def dataset(entries, *, interpolation=True, gap=None, channels=None):
    raw = {
        "schema_version": 1,
        "slug": "test",
        "name": "Test",
        "apps": [
            {
                "app_key": "sensor",
                "application_name": "sensor_app",
                "config": {},
                "run": False,
            }
        ],
        "channels": list(channels or {"tag_values": entries}),
        "duration_ms": 10000,
        "interpolation": [
            {"path": ["sensor", "level"], **({"max_gap_ms": gap} if gap else {})}
        ]
        if interpolation
        else [],
    }
    return parse_dataset(raw, channels or {"tag_values": entries})


def aggregate(timestamp=0, **tags):
    return {
        "timestamp": timestamp,
        "kind": "aggregate",
        "mode": "merge",
        "data": {"sensor": tags or {"level": 10}},
    }


def sample(timestamp=10000, apply=True, **tags):
    return {
        "timestamp": timestamp,
        "kind": "message",
        "id": f"sample-{timestamp}",
        "apply_to_aggregate": apply,
        "data": {"sensor": tags or {"level": 20}},
    }


def test_reconstruct_late_install_retains_baseline_and_never_publishes_future():
    data = dataset(
        [
            sample(-1000, level=999, historical=True),
            aggregate(level=10, status="normal"),
            sample(1000, level=12),
            sample(10000, level=100, status="future"),
        ]
    )
    assert reconstruct_aggregates(data, 3000) == {
        "tag_values": {"sensor": {"level": 12, "status": "normal"}}
    }
    assert reconstruct_aggregates(data, -1) == {}
    assert len(ordered_entries(data, 3000)) == 3


def test_interpolation_is_numeric_opt_in_and_leaves_history_sparse():
    data = dataset(
        [
            aggregate(level=10, status="normal", enabled=False, other=40),
            sample(10000, level=30, status="future", enabled=True, other=100),
        ]
    )
    before = deepcopy(data.channels)
    state = reconstruct_aggregates(data, 5000, interpolate=True)["tag_values"]
    assert state == {
        "sensor": {"level": 20, "status": "normal", "enabled": False, "other": 40}
    }
    assert data.channels == before
    assert len(ordered_entries(data, 5000)) == 1


def test_exact_endpoints_hold_sample_precision_and_no_extrapolation():
    data = dataset([aggregate(level=10), sample(10000, level=30)])
    assert interpolate_tags(data, 0)["sensor"]["level"] == 10
    assert type(interpolate_tags(data, 0)["sensor"]["level"]) is int
    assert interpolate_tags(data, 10000)["sensor"]["level"] == 30
    assert interpolate_tags(data, 10001)["sensor"]["level"] == 30
    assert interpolate_tags(data, -1) == {}


def test_finite_extreme_endpoints_do_not_overflow_intermediate_arithmetic():
    data = dataset([aggregate(level=-1e308), sample(10000, level=1e308)])
    assert interpolate_tags(data, 5000)["sensor"]["level"] == 0


@pytest.mark.parametrize("middle", [None, True, "offline", {"state": "offline"}])
def test_type_changes_break_interpolation(middle):
    data = dataset(
        [aggregate(level=10), sample(5000, level=middle), sample(10000, level=30)]
    )
    assert interpolate_tags(data, 2500)["sensor"]["level"] == 10
    assert interpolate_tags(data, 7500)["sensor"].get("level") == middle


def test_missing_fields_hold_state_and_do_not_create_a_fake_endpoint():
    data = dataset(
        [aggregate(level=10), sample(5000, status="normal"), sample(10000, level=30)]
    )
    assert interpolate_tags(data, 5000)["sensor"]["level"] == 20
    assert interpolate_tags(data, 5000)["sensor"]["status"] == "normal"


def test_max_gap_disables_interpolation_but_not_exact_sample():
    data = dataset([aggregate(level=10), sample(10000, level=30)], gap=5000)
    assert interpolate_tags(data, 5000)["sensor"]["level"] == 10
    assert interpolate_tags(data, 10000)["sensor"]["level"] == 30


def test_duplicate_times_use_last_file_entry():
    first, second = sample(10000, level=20), sample(10000, level=30)
    second["id"] = "same-time-second"
    data = dataset([aggregate(level=10), first, second])
    assert interpolate_tags(data, 5000)["sensor"]["level"] == 20
    assert reconstruct_aggregates(data, 10000)["tag_values"]["sensor"]["level"] == 30


def test_cross_channel_order_is_declared_order_not_alphabetic():
    data = dataset(
        [],
        interpolation=False,
        channels={"z_channel": [sample(0)], "a_channel": [sample(0)]},
    )
    assert [entry.channel for entry in ordered_entries(data)] == [
        "z_channel",
        "a_channel",
    ]


def test_nested_rebasing_preserves_durations_and_payload():
    entry = aggregate(level=10, updated=2000, event_started=-1.5, expires_after=30)
    entry["timestamp_fields"] = [
        {"path": ["sensor", "updated"], "unit": "ms"},
        {"path": ["sensor", "event_started"], "unit": "s"},
    ]
    parsed = dataset([entry]).channels["tag_values"][0]
    assert rebase_data(parsed, 100000)["sensor"] == {
        "level": 10,
        "updated": 102000,
        "event_started": 98.5,
        "expires_after": 30,
    }
    assert parsed.data["sensor"]["event_started"] == -1.5


def test_message_references_use_installed_ids():
    first = sample(0)
    second = sample(1, apply=False, retry_of="sample-0")
    second["message_references"] = [
        {"path": ["sensor", "retry_of"], "channel": "tag_values", "id": "sample-0"}
    ]
    parsed = dataset([first, second]).channels["tag_values"][1]
    assert (
        rebase_data(parsed, 0, {("tag_values", "sample-0"): "installed-message"})[
            "sensor"
        ]["retry_of"]
        == "installed-message"
    )
    with pytest.raises(ValueError, match="message_ids"):
        rebase_data(parsed, 0)


def test_scoped_replacement_preserves_other_app_and_processor_state():
    raw = {
        "timestamp": 0,
        "kind": "aggregate",
        "mode": "replace",
        "scope": ["sensor"],
        "data": {"level": 7},
    }
    entry = dataset([raw]).channels["tag_values"][0]
    current = {
        "sensor": {"level": 1, "obsolete": True},
        "other": {"value": 5},
        "processor": {"cursor": 12},
    }
    assert apply_entry(current, entry) == {
        "sensor": {"level": 7},
        "other": {"value": 5},
        "processor": {"cursor": 12},
    }
    assert current["sensor"]["obsolete"] is True


def test_scoped_replacement_removal_breaks_interpolation():
    replace = {
        "timestamp": 5000,
        "kind": "aggregate",
        "mode": "replace",
        "scope": ["sensor"],
        "data": {"status": "reset"},
    }
    data = dataset([aggregate(level=10), replace, sample(10000, level=30)])
    assert interpolate_tags(data, 2500)["sensor"]["level"] == 10
    assert "level" not in interpolate_tags(data, 7500)["sensor"]


def test_merge_matches_service_null_deletion_and_preserves_arrays():
    current = {
        "sensor": {"level": 1, "metadata": {"a": 1}, "points": [1, 2]},
        "processor": {"cursor": 3},
    }
    assert merge_data(
        current, {"sensor": {"level": None, "metadata": {"b": 2}, "points": [3]}}
    ) == {
        "sensor": {"metadata": {"a": 1, "b": 2}, "points": [3]},
        "processor": {"cursor": 3},
    }
    assert merge_data(
        {}, {"sensor": {"gone": None, "array": [None, {"keep": None}]}}
    ) == {"sensor": {"array": [None, {"keep": None}]}}


def test_historical_message_does_not_implicitly_change_aggregate():
    data = dataset([aggregate(level=10), sample(10000, apply=False, level=30)])
    assert reconstruct_aggregates(data, 10000)["tag_values"]["sensor"]["level"] == 10
    assert interpolate_tags(data, 5000)["sensor"]["level"] == 10
    assert interpolate_tags(data, 10000)["sensor"]["level"] == 10

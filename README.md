# Example devices

Datasets and a Doover processor that imports example-device history and publishes new data over time. The [water-storage example](devices/water-storage/config.json) contains synthetic telemetry for a 10 ML storage and a 12 V solar system.

## How it works

Organisation provisioning creates the device and installs the processor and display apps. Only the processor runs. Provisioning supplies the repository, dataset slug, full commit SHA, and `anchor_ms`: midnight on the organisation's creation day in its timezone. Device creation and app installation are handled outside this repository.

Dataset timestamps are millisecond offsets from that fixed anchor. Negative offsets become history; positive offsets become future data. The processor stores the anchor, pinned revision, and progress in device tags so interruptions resume automatically and repository edits do not change existing installations.

The processor initializes aggregates, imports history in batches, and catches up to the current time. A one-minute schedule checks for work. Publication normally happens every 30 minutes. While the device page is being viewed, one-minute updates interpolate declared numeric tags without adding extra history. Other values change at authored points.

Historical input events and their effects are precomputed. Live inputs update selected values, acknowledgements, and input logs without changing telemetry. Imported RPCs cannot execute as live commands. At the dataset's end, publication stops and the device shows `exhausted`; inputs can still be acknowledged.

## Data layout

Each `devices/<slug>/` contains `config.json` and `channels/<channel>.json`. Channel files are arrays of timestamped aggregate operations or messages. The [device schema](schemas/device.schema.json) and [channel schema](schemas/channel.schema.json) define the format.

| Channel | Contents |
| --- | --- |
| `ui_state` | Static app UI schemas. |
| `tag_values` | Telemetry history, zero-time baseline, and future samples. |
| `ui_cmds` | Historical RPCs, input logs, and initial selections. |
| `deployment_config` | Portable app settings, preserving installed identities. |
| `ui_overrides` | Optional presentation overrides. |

The water example covers 90 past days and 30 future days. Historical spacing is 30 minutes within 14 days, two hours from 14–45 days, and six hours from 45–90 days, with extra points around input events. Future samples are 30 minutes apart with no scripted inputs. Host Configurator and customer installation bindings are excluded.

## Local use

Requires Python 3.13 and uv. Validation and simulation make no cloud writes.

```sh
uv sync --frozen
uv run example-device validate devices/water-storage
uv run example-device simulate devices/water-storage --anchor-ms 1789084800000 --offset-ms 900000 --viewed
uv run python tools/generate_water_storage.py
uv run pytest -q
```

The generator is deterministic. With matplotlib installed, `--charts` writes previews under the ignored `build/water-storage/` directory.

## Cloud setup

Install the processor from `doover_config.json` with `repository`, `dataset_slug`, `dataset_revision`, and `anchor_ms`. The pinned dataset must be publicly accessible; downloads are anonymous.

Use one Lambda function for all example devices with reserved concurrency **1** and `lambda:GetFunctionConcurrency` permission on that function. The processor checks this before cloud writes. Defaults subscribe to `ui_cmds` and `dv-ui-sub`, with a `rate(1 minute)` schedule. All devices share that capacity.

Live deployment and organisation-provisioning integration still need verification in a dedicated example environment.

# Example devices

Datasets and a Doover processor that imports example-device history and publishes new data over time. The [water-storage example](devices/water-storage/config.json) contains synthetic telemetry for a 10 ML storage and a 12 V solar system. The [vehicle-tracker example](devices/vehicle-tracker/README.md) follows a Bunnings journey with 46 days of history, 30 future days, and a local route visualiser.

The [camera-device example](devices/camera-device/README.md) contains a Blender reconstruction of a Queen Victoria Building gallery and 3,552 compressed snapshots. Four pan-tilt views repeat hourly across seven days of history and 30 days after installation, with changing people and lighting. Playback publishes native camera attachments; a live stream remains separate work.

## How it works

Organisation provisioning creates the device and installs the processor and display apps. Only the processor runs. Provisioning supplies the repository, dataset slug, full commit SHA, and `anchor_ms`: midnight on the organisation's creation day in its timezone. Device creation and app installation are handled outside this repository.

Dataset timestamps are millisecond offsets from that fixed anchor. Negative offsets become history; positive offsets become future data. The processor stores the anchor, pinned revision, and progress in device tags so interruptions resume automatically and repository edits do not change existing installations.

The processor initializes aggregates, imports history in batches, and catches up to the current time. A one-minute schedule checks for work. Publication normally happens every 30 minutes. While the device page is being viewed, one-minute updates interpolate declared numeric tags without adding extra history. Other values change at authored points.

Successful playback checks refresh the device's `doover_connection` heartbeat, even when no telemetry is due. Doover shows the example as online and marks it offline after five minutes without a heartbeat. This reflects processor availability; exhausted telemetry remains a separate playback state.

Historical input events and their effects are precomputed. Live inputs update selected values, acknowledgements, and input logs without changing telemetry. Imported RPCs cannot execute as live commands. At the dataset's end, publication stops and the device shows `exhausted`; inputs can still be acknowledged.

## Data layout

Each `devices/<slug>/` contains `config.json` and `channels/<channel>.json`. Channel files are arrays of timestamped aggregate operations or messages. The [device schema](schemas/device.schema.json) and [channel schema](schemas/channel.schema.json) define the format.

| Channel | Contents |
| --- | --- |
| `ui_state` | Static app UI schemas. |
| `tag_values` | Telemetry history, zero-time baseline, and future samples. |
| `location` | Paired GPS history, zero-time position, and future tracking samples for the vehicle. |
| `ui_cmds` | Historical RPCs, input logs, and initial selections. |
| `deployment_config` | Portable app settings, preserving installed identities. |
| `ui_overrides` | Optional presentation overrides. |
| `doover_camera` | Hourly camera captures with four named JPEG attachments. |

The water example covers 90 past days and 30 future days. Historical spacing is 30 minutes within 14 days, two hours from 14–45 days, and six hours from 45–90 days, with extra points around input events. Future samples are 30 minutes apart with no scripted inputs. Host Configurator and customer installation bindings are excluded.

The vehicle example samples hourly before the past week and every 10 minutes from the past week through day +30. Arrival and departure samples preserve ignition changes and short trips. Odometer and engine hours integrate the full road route. Ferry movement adds neither. GPS and telemetry remain on the same recorded observation between samples.

Messages can declare `attachments` with a dataset-relative `path` under `attachments/`, `filename`, `content_type`, byte `size`, and `sha256`. The processor downloads files from the pinned GitHub revision only when their message is due, verifies their bytes, reserves a backdated message, and uploads missing native attachments. Retries inspect stored files before uploading again. Attachment data stays outside the Lambda package.

Attachment imports checkpoint after at most five capture messages per batch. A 180-second work budget is checked between batches; it does not cancel an in-progress network request. With the default four batches per invocation, the camera's initial 169 captures take nine scheduled invocations. Later hours add one capture with four files.

Optional `attachment_references` replace null fields in message or aggregate data with uploaded URLs. Each reference names a `channel`, message `id`, attachment `filename`, and `path` within the data. Path segments can be object keys or array indices. Native camera history uses attachment filenames directly and needs no URL references.

## Local use

Requires Python 3.13 and uv. Validation and simulation make no cloud writes.

```sh
uv sync --frozen
uv run example-device validate devices/water-storage
uv run example-device simulate devices/water-storage --anchor-ms 1789084800000 --offset-ms 900000 --viewed
uv run python tools/generate_water_storage.py
uv run example-device validate devices/camera-device
uv run python tools/generate_camera_device.py
uv run python tools/generate_vehicle_tracker.py
uv run example-device validate devices/vehicle-tracker
uv run pytest -q
```

The generator is deterministic. With matplotlib installed, `--charts` writes previews under the ignored `build/water-storage/` directory.

## Cloud setup

GitHub Actions uses `getdoover/workflows/.github/workflows/app.yml@main` to check, build, and publish the processor to production and staging. Pushes to `main` create releases; pull requests targeting `main` create alpha releases. The workflow can also be started manually. Doover authentication uses GitHub OIDC, with no API token stored in the repository. Both environments receive the same `package.zip`, built by `build.sh` from runtime dependencies and processor source only.

Install the processor from `doover_config.json` with `repository`, `dataset_slug`, `dataset_revision`, and `anchor_ms`. The pinned dataset must be publicly accessible; downloads are anonymous.

Use one Lambda function for all example devices with reserved concurrency **1** and `lambda:GetFunctionConcurrency` permission on that function. The processor checks this before cloud writes. Defaults subscribe to `ui_cmds` and `dv-ui-sub`, with a `rate(1 minute)` schedule. All devices share that capacity.

Staging playback has been verified on a dedicated example device. Organisation-provisioning integration remains separate.

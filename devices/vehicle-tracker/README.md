# Vehicle tracker example

This device visits all 334 active physical Bunnings sites in the captured Australian retail and trade directories. The full route takes 76 days. The exported dataset places zero exactly 46 elapsed days after departure, leaving 30 days of future telemetry.

| Period relative to zero | Tracking interval |
| --- | --- |
| Day -46 up to day -7 | 1 hour |
| Day -7 through zero | 10 minutes |
| Zero through day +30 | 10 minutes |

Extra samples at arrivals and departures preserve every store visit and ignition change. There are 7,007 tracking observations, each with one `location` message and one `tag_values` message. Both channels have a matching zero-time aggregate. Older history contains 1,427 observations, the past week contains 1,085, zero has one, and the future contains 4,494.

At zero, the vehicle is parked in Cairns with ignition off, an odometer of 11,748.651 km, and 166.805 engine hours. At the end, the odometer is 25,286.561 km and engine hours are 317.744167. Counters start at zero at the beginning of this synthetic journey. They integrate the full road steps, including driving between sparse historical observations.

The [raw visualiser](http://127.0.0.1:8765/visualiser.html) shows the itinerary and exported observations. Select **Go to zero** to inspect the starting state. Select **Show exported tracking samples** to display the authored GPS points and hold the vehicle at each observation until the next one. Blue samples are history and pink samples are future. The readout shows the latest observation's ignition, speed, odometer, and engine hours.

## Vehicle behaviour

Road travel follows 09:00 to 17:00 local time in the source itinerary. Each physical site receives a 30-minute visit. Ignition is on during road travel and off during visits, waits, and overnight stays. Engine hours accumulate only during road travel. The overnight Tasmania ferry has cabin accommodation with the vehicle engine off. GPS speed and position follow the moving ferry, while road odometer and engine hours stay fixed.

GPS positions follow Google's saved step polylines. Speed and distance use the same fraction of each step's duration. Step distances are normalized to Google's route total to reconcile rounding differences. Odometer is never calculated from straight lines between sparse samples. The original road-access snapping is preserved in the route geometry. Store and hotel map coordinates can differ slightly from those access points.

Location and telemetry are sampled together. Numeric tag interpolation is disabled so viewed updates cannot advance odometer or speed independently of the displayed GPS point and ignition state. The runtime publishes all authored messages when due; its normal 30-minute idle publication cycle can deliver several 10-minute observations together with their original timestamps.

Voltage, battery, signal strength, and temperature use deterministic simulator-style values. Analog input is unknown and altitude is omitted because the route data is two-dimensional.

The Maintenance Manager shows matching odometer and engine hours, trailing 14-day use, and service estimates. A synthetic service is recorded at the trip start, with a 10,000 km and six-month interval. No later service is invented, so overdue kilometres are negative. The source has no engine-hour service interval. Unbound remote widgets and controls that would change authored counters are omitted from the exported UI.

## Time and replay

The source calendar starts on 4 January 2027 at 09:00 in Tasmania. Zero corresponds to `2027-02-18T22:00:00Z`. Channel timestamps are millisecond offsets from zero. The runtime adds the installation's anchor to those offsets, including `device_time` and maintenance dates. The device-time UI uses a numeric timestamp so it follows the installed example date.

The export ends at exactly +30 days. The original final overnight has 90 more minutes because the journey ends in a different timezone. Those parked minutes remain in raw data. Every road leg, ferry leg, and store visit is included in the export. Road-hour checks apply to the source itinerary; replay rebases its timestamps to the installation anchor without rescheduling for a new calendar or timezone.

## Regenerate and verify

Run from the repository root. Sampling reads the saved full route and the device's existing app configuration and static UI. It requires no Google key, research files or network requests and leaves `raw/journey.json` unchanged.

```sh
uv run python tools/generate_vehicle_tracker.py
uv run python tools/export_vehicle_itinerary.py
uv run example-device validate devices/vehicle-tracker
uv run example-device simulate devices/vehicle-tracker --anchor-ms 1893456000000 --offset-ms 0 --viewed
uv run pytest tests/test_vehicle_dataset.py -q
```

`config.json` declares the inert display apps. `channels/` contains the portable UI, paired telemetry and location records, and deployment settings. Provisioning and cloud installation are separate from this local dataset. The original reference device is unchanged.

The [raw folder guide](raw/README.md) lists the versioned outputs and explains how to regenerate telemetry and CSV summaries without the local research files. [sampling-policy.json](raw/sampling-policy.json) records the exact window, counts, baseline, and final state. [tracking-samples.json](raw/tracking-samples.json) connects each exported observation to its raw event.

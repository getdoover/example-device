# Vehicle route and visualiser

This folder keeps the finished journey and the files needed to review it. The full route visits 334 Bunnings sites over 76 days. The device export uses 46 days of history and 30 future days.

| File | Contents |
| --- | --- |
| `journey.json` | Complete route geometry, navigation steps, durations, itinerary events, stores, accommodation and ferry terminals. |
| `itinerary.csv` | Every drive, store visit, wait, ferry crossing and overnight, with UTC and local times. |
| `daily-summary.csv` | Daily store counts, driving distance, hours and accommodation. |
| `sampling-policy.json` | Sample intervals, exact zero point, counter rules, sample counts and zero/final states. |
| `tracking-samples.json` | All 7,007 exported observations, linked to raw events, with paired GPS and vehicle telemetry. |
| `visualiser.html`, `visualiser.js`, `visualiser.css` | Local map, itinerary, route playback and tracking-sample controls. |

`journey.json` preserves all route points in Google's encoded polylines, both for the complete legs and their navigation steps. The visualiser decodes these points locally. The file also contains route distances and step durations, so sampling does not require the original Google API responses.

## Open the visualiser

Server Runner has a task named **Vehicle tracker route visualiser**, serving this folder at <http://127.0.0.1:8765/visualiser.html>. Start or restart that saved task. In another checkout, serve this folder with a local HTTP server. The map uses online Leaflet assets and OpenStreetMap tiles; the journey and telemetry are local and need no Google key.

Select a day or search for a store, town or overnight stay. The itinerary shows each event's local time. **Go to zero** selects the state 46 elapsed days into the trip. **Show exported tracking samples** displays historical observations in blue and future observations in pink. Playback holds at the latest exported observation so GPS, ignition, speed, odometer and engine hours stay together. Disable that checkbox for continuous playback along the original route geometry.

## Regenerate the outputs

Run from the repository root:

```sh
uv run python tools/generate_vehicle_tracker.py
uv run python tools/export_vehicle_itinerary.py
uv run example-device validate devices/vehicle-tracker
uv run pytest tests/test_vehicle_dataset.py -q
```

The sampler reads `journey.json` and preserves the apps and static UI from the existing `../config.json` and `../channels/ui_state.json`. It writes the device channels, sampling policy and tracking observations. `--output` can target a different folder; `--template` selects the existing device whose app settings and static UI to use. The CSV exporter reads the same full journey. Neither tool needs Google credentials, API caches, catalogue research or review reports.

The device channels contain one JSON record per line so the full history fits the runtime's 8 MiB per-file download limit. See [the vehicle guide](../README.md) for cadence, counters and replay behaviour.

## Route assumptions

Road travel is between 09:00 and 17:00 at the vehicle's location in the source itinerary, with a 30-minute visit at every physical Bunnings site. Store opening hours are not enforced. Static travel durations do not model future traffic or road closures.

The Tasmania transfer uses an overnight cabin, with a modelled 20:00 departure. The ferry's geometry and duration are preserved. Dated sailing and accommodation availability are not verified. The Mount Isa to Alice Springs section uses the Barkly Highway and an overnight at Barkly Homestead.

Google road-access points can differ from a store or hotel's map coordinate. The route retains those measured points without adding invented connectors. Odometer integrates road distances, not straight lines between sparse GPS observations. The ferry moves GPS while ignition is off and adds no road odometer or engine hours.

The exact 76-day export includes every journey movement and store visit. The final 90 minutes parked at the last hotel remain only in the complete raw itinerary.

## Local working files

`.gitignore` permits only the finished files listed above in this folder. Google responses in `api/`, catalogue captures, source-device research, accommodation reviews, audits, old journey versions and one-off route-building tools remain local. A fresh checkout can view, validate and resample the finished journey without them. To design a different route, retain those local caches or collect new source data.

Disposable replay dumps, credential-check reports and logs have been removed. Finder `.DS_Store` files are ignored throughout the repository.

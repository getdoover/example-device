#!/usr/bin/env python3
"""Export human-readable itinerary tables from the saved raw journey."""

import csv
import json
from collections import defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "devices/vehicle-tracker/raw"


def main():
    journey = json.loads((RAW / "journey.json").read_text())
    fields = [
        "day",
        "kind",
        "name",
        "start_local",
        "end_local",
        "timezone",
        "end_timezone",
        "start_utc",
        "end_utc",
        "duration_s",
        "distance_m",
        "from_id",
        "to_id",
        "place_id",
        "route_id",
        "notes",
        "purpose",
        "overnight_accommodation",
        "engine_on",
    ]
    with (RAW / "itinerary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(journey["events"])
    days = defaultdict(list)
    for event in journey["events"]:
        days[event["day"]].append(event)
    places = {
        p["id"]: p
        for p in journey["stores"]
        + journey["accommodations"]
        + journey["transport_places"]
    }
    rows = []
    for number, events in days.items():
        stays = [
            event
            for event in events
            if event["kind"] == "overnight"
            or event.get("overnight_accommodation") == "ferry_cabin"
        ]
        active = [event for event in events if event["kind"] in ("drive", "visit")]
        rows.append(
            {
                "day": number,
                "date": events[0]["start_local"][:10],
                "start": places[events[0]["from_id"]]["name"],
                "start_local": events[0]["start_local"],
                "finish_local": active[-1]["end_local"],
                "stores": sum(event["kind"] == "visit" for event in events),
                "drive_km": round(
                    sum(
                        event.get("distance_m", 0)
                        for event in events
                        if event["kind"] == "drive"
                    )
                    / 1000,
                    3,
                ),
                "drive_hours": round(
                    sum(
                        event["duration_s"]
                        for event in events
                        if event["kind"] == "drive"
                    )
                    / 3600,
                    3,
                ),
                "ferry_km": round(
                    sum(
                        event.get("distance_m", 0)
                        for event in events
                        if event["kind"] == "ferry"
                    )
                    / 1000,
                    3,
                ),
                "accommodation": (
                    "Spirit of Tasmania passenger cabin"
                    if stays[-1].get("overnight_accommodation") == "ferry_cabin"
                    else stays[-1]["name"]
                )
                if stays
                else "",
            }
        )
    with (RAW / "daily-summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Exported {len(journey['events'])} events and {len(rows)} days.")


if __name__ == "__main__":
    main()

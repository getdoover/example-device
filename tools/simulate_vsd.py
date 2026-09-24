#!/usr/bin/env python3
"""Exercise the VSD through real command and playback paths without cloud writes."""

import argparse
import asyncio
import json
from copy import deepcopy
from pathlib import Path

from example_device.commands import CommandRequest
from example_device.dataset import load_directory
from example_device.runtime import Runtime, stable_message_id
from example_device.simulator import MemoryTransport

ROOT = Path(__file__).resolve().parents[1]
ANCHOR = 1_789_084_800_000


async def simulate(directory):
    transport = MemoryTransport()
    rows = []

    def restarted():
        return Runtime(
            load_directory(directory),
            transport,
            anchor_ms=ANCHOR,
            revision="local-review",
            installation_id="vsd-demo",
            max_batches=100,
        )

    steps = [
        (0, "Initially stopped", None, None),
        (10, "Set 35 Hz while stopped", "frequency_setpoint", 35),
        (11, "Start", "start", None),
        (26, "Accelerating", None, None),
        (71, "Running at 35 Hz", None, None),
        (300, "Set 45 Hz", "frequency_setpoint", 45),
        (360, "Running at 45 Hz", None, None),
        (1200, "Stop", "stop", None),
        (1260, "Stopped, cooling", None, None),
        (1500, "Set 25 Hz while stopped", "frequency_setpoint", 25),
        (1800, "Restart", "start", None),
        (1860, "Running at 25 Hz", None, None),
        (3600, "Still running after restart", None, None),
    ]
    for seconds, label, method, value in steps:
        now = ANCHOR + seconds * 1000
        if method:
            await restarted().acknowledge(
                CommandRequest(
                    stable_message_id(now, f"demo-{seconds}"),
                    now,
                    "schneider_vsd",
                    method,
                    value if value is not None else now,
                )
            )
        else:
            while (
                await restarted().run(now, observed=True, force=True)
            ).needs_continuation:
                pass
        rows.append(
            {
                "seconds": seconds,
                "action": label,
                **deepcopy(transport.aggregates["tag_values"]["schneider_vsd"]),
            }
        )
    assert rows[1]["vsd_frequency"] == 0
    assert rows[3]["vsd_frequency"] == 15
    assert rows[4]["vsd_frequency"] == 35
    assert rows[6]["vsd_frequency"] == 45
    assert rows[8]["vsd_power"] == 0
    assert rows[9]["vsd_frequency"] == 0
    assert rows[-1]["vsd_frequency"] == 25
    return {
        "dataset": "vsd",
        "restarted_between_every_step": True,
        "observations": rows,
        "message_count": len(transport.messages),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "devices/vsd")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "build/vsd/command-demo.json"
    )
    args = parser.parse_args()
    result = asyncio.run(simulate(args.dataset))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"Verified {len(result['observations'])} VSD observations; report: {args.output}"
    )

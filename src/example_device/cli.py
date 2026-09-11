"""Validate and exercise local datasets without touching customer devices."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .dataset import load_directory
from .runtime import Runtime
from .simulator import MemoryTransport


async def simulate(path, anchor_ms, offset_ms, viewed):
    dataset = load_directory(path)
    transport = MemoryTransport()
    runtime = Runtime(
        dataset,
        transport,
        anchor_ms=anchor_ms,
        revision="local-review",
        installation_id="local-review",
        max_batches=20,
    )
    now_ms = anchor_ms + offset_ms
    while True:
        result = await runtime.run(now_ms, observed=viewed)
        if not result.needs_continuation:
            break
    return {
        "dataset": dataset.config.slug,
        "phase": result.phase,
        "message_count": len(transport.messages),
        "state": transport.state,
        "aggregates": transport.aggregates,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate or locally simulate a Doover dataset. No cloud writes are made.",
        epilog=(
            "Cloud execution requires one reserved concurrent Lambda invocation and "
            "lambda:GetFunctionConcurrency permission on that same function. "
            "Use one processor function for all installations; schedule it every minute, "
            "with a 30-minute idle publication interval. Enable cloud playback only after "
            "its dataset revision has been reviewed and published."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="Validate config and all channel files"
    )
    validate.add_argument("path", type=Path)
    playback = commands.add_parser(
        "simulate", help="Replay locally and print the resulting state"
    )
    playback.add_argument("path", type=Path)
    playback.add_argument("--anchor-ms", type=int, required=True)
    playback.add_argument("--offset-ms", type=int, default=0)
    playback.add_argument("--viewed", action="store_true")
    playback.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        dataset = load_directory(args.path)
        output = {
            "dataset": dataset.config.slug,
            "channels": {
                name: len(entries) for name, entries in dataset.channels.items()
            },
            "duration_ms": dataset.duration_ms,
        }
    else:
        output = asyncio.run(
            simulate(args.path, args.anchor_ms, args.offset_ms, args.viewed)
        )
    rendered = json.dumps(output, indent=2, allow_nan=False) + "\n"
    if getattr(args, "output", None):
        args.output.write_text(rendered)
    else:
        print(rendered, end="")

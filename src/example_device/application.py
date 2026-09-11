"""Doover event handlers with pinned public input and app-scoped state."""

from __future__ import annotations

import time
from dataclasses import asdict

from pydoover.models import AggregateUpdateEvent, MessageCreateEvent
from pydoover.processor import Application, ProcessorSkipped, run_app
from pydoover.rpc import command_is_expired
from pydoover.tags.manager import LogMode

from .adapter import STATE_TAG, DooverTransport
from .app_ui import ExampleTags, ExampleUI
from .commands import CommandError, CommandRequest
from .concurrency import verify_lambda_serialization
from .config import ExampleDeviceConfig
from .runtime import IMPORT_MARKER, Runtime
from .source import fetch_dataset, validate_source
from .state import PlaybackState


def is_page_observed(aggregate, now_ms):
    """Presence entries expire even if the server retains them in the aggregate."""
    if not isinstance(aggregate, dict) or not isinstance(
        aggregate.get("agent_open"), dict
    ):
        return False
    for value in aggregate["agent_open"].values():
        stamp = value.get("ts") if isinstance(value, dict) else value
        if type(stamp) in (int, float) and 0 <= now_ms - stamp < 120_000:
            return True
    return False


class ExampleDevice(Application):
    config_cls = ExampleDeviceConfig
    ui_cls = ExampleUI
    tags_cls = ExampleTags

    def __init__(self, *, serialization_verified=False):
        super().__init__()
        self.serialization_verified = serialization_verified
        self.failure = None

    async def _handle_event(self, event, subscription_id=None):
        # Subscriptions include response updates and our own imported/logged
        # messages. Reject them before the SDK lifecycle: its early-skip summary
        # needs an app_id that is only available after setup, and its dispatcher
        # does not handle message-update notifications.
        operation = event["op"]
        if operation == "on_message_create":
            payload = MessageCreateEvent.from_dict(event["d"])
        elif operation == "on_aggregate_update":
            payload = AggregateUpdateEvent.from_dict(event["d"])
        elif operation in ("on_deployment", "on_schedule"):
            return await super()._handle_event(event, subscription_id)
        else:
            return None
        if not await self.pre_hook_filter(payload):
            return None
        return await super()._handle_event(event, subscription_id)

    async def _dispatch_invocation(self, event, subscription_id):
        try:
            return await super()._dispatch_invocation(event, subscription_id)
        except ProcessorSkipped:
            raise
        except Exception as error:
            self.failure = error
            raise

    async def pre_hook_filter(self, event):
        if isinstance(event, MessageCreateEvent):
            data = event.message.data
            return (
                event.channel.name == "ui_cmds"
                and isinstance(data, dict)
                and IMPORT_MARKER not in data
                and data.get("type") == "rpc"
            )
        if isinstance(event, AggregateUpdateEvent):
            return event.channel.name == "dv-ui-sub"
        return True

    async def setup(self):
        # Runtime commits its own tags explicitly and never logs checkpoints.
        self.tag_manager.log_mode = LogMode.NEVER

    async def _runtime(self):
        # All invocations are globally serialized before framework initialization.
        # Read authoritative tags instead of trusting the event's older snapshot.
        from pydoover.api import NotFoundError

        try:
            tags = (await self.api.fetch_channel_aggregate("tag_values")).data
        except NotFoundError:
            tags = {}
        if not isinstance(tags, dict) or not isinstance(
            tags.get(self.app_key, {}), dict
        ):
            raise ValueError("Invalid processor tag namespace")
        own = tags.get(self.app_key, {})
        raw = own.get(STATE_TAG)
        if raw is not None:
            if not isinstance(raw, dict):
                raise ValueError("Invalid playback state")
            state = PlaybackState.from_dict(raw)
            slug, revision, anchor = state.dataset_slug, state.revision, state.anchor_ms
            repository = raw.get("repository")
            if not isinstance(repository, str):
                raise ValueError("Pinned state has no source repository")
        else:
            slug = self.config.dataset_slug.value
            revision = self.config.dataset_revision.value
            anchor = own.get("anchor_ms", self.config.anchor_ms.value)
            repository = self.config.repository.value
        if type(anchor) is not int or anchor < 1735689600000:
            raise ValueError(
                "anchor_ms must be an absolute millisecond timestamp after the Doover epoch"
            )
        validate_source(repository, revision, slug)
        dataset = await fetch_dataset(repository, revision, slug)
        if (
            dataset.config.processor
            and dataset.config.processor.app_key != self.app_key
        ):
            raise ValueError(
                "Installed processor app key differs from the dataset's processor binding"
            )
        transport = DooverTransport(
            self.api,
            agent_id=self.agent_id,
            app_key=self.app_key,
            app_keys=[app.app_key for app in dataset.config.apps],
            repository=repository,
            serialization_verified=self.serialization_verified,
        )
        runtime = Runtime(
            dataset,
            transport,
            anchor_ms=anchor,
            revision=revision,
            installation_id=f"{self.agent_id}:{self.app_key}",
            idle_interval_ms=self.config.idle_interval_seconds.value * 1000,
            active_interval_ms=self.config.active_interval_seconds.value * 1000,
            max_batches=self.config.max_batches.value,
        )
        return runtime

    async def _play(self, *, presence_event=False):
        try:
            runtime = await self._runtime()
            now_ms = int(time.time() * 1000)
            presence = await runtime.transport.aggregate("dv-ui-sub")
            observed = is_page_observed(presence, now_ms)
            result = await runtime.run(
                now_ms, observed=observed, force=presence_event and observed
            )
            # Liveness follows successful processor checks, independently of the
            # sparse telemetry cadence and the dataset's historical timestamps.
            heartbeat_ms = int(time.time() * 1000)
            await self.api.update_channel_aggregate(
                "doover_connection",
                {
                    "config": {
                        "connection_type": "Continuous",
                        "offline_after": 300,
                        "auto_sync_offline": True,
                    },
                    "status": {
                        "status": "ContinuousOnline",
                        "last_ping": heartbeat_ms,
                        "last_online": heartbeat_ms,
                        "user_agent": "example-device-manager",
                    },
                    "determination": "Online",
                },
                log_update=False,
                suppress_response=True,
            )
            return asdict(result)
        except Exception as error:
            self.failure = error
            raise

    async def on_deployment(self, event):
        return await self._play()

    async def on_schedule(self, event):
        return await self._play()

    async def on_aggregate_update(self, event):
        return await self._play(presence_event=True)

    async def on_message_create(self, event):
        try:
            if command_is_expired(event.message):
                return {"status": "expired"}
            runtime = await self._runtime()
            data = event.message.data
            request = CommandRequest(
                message_id=event.message.id,
                timestamp_ms=int(event.message.timestamp.timestamp() * 1000),
                app_key=data.get("app_key"),
                method=data.get("method"),
                value=data.get("request"),
            )
            # A late or imported command is never sent to a real app handler.
            try:
                result = await runtime.acknowledge(request)
            except CommandError as error:
                await runtime.transport.update_rpc_response(
                    "ui_cmds",
                    event.message.id,
                    {
                        "status": {
                            "code": "error",
                            "message": {"code": "EXAMPLE_INPUT", "message": str(error)},
                        }
                    },
                )
                return {"status": "rejected"}
            return asdict(result)
        except Exception as error:
            self.failure = error
            raise


def invoke(event, context):
    verify_lambda_serialization(context)
    app = ExampleDevice(serialization_verified=True)
    result = run_app(app, event, context)
    # The framework logs handler failures. Re-raise here so infrastructure can
    # retry, while durable tags and the periodic schedule also permit recovery.
    if app.failure is not None:
        raise app.failure
    return result

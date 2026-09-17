"""PyDoover channel operations for the coordinated playback runtime."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from pydoover.api import NotFoundError
from pydoover.models.data import BatchMutationItem, File

from .dataset import AttachmentFile, verify_attachment_bytes
from .runtime import WriteResult
from .timeline import set_data_path

STATE_TAG = "playback_state"
IMMUTABLE_FIELDS = frozenset(
    {
        "AGENT_ID",
        "ORGANISATION_ID",
        "APP_ID",
        "APP_INSTALL_ID",
        "APPLICATION_ID",
        "APP_KEY",
        "APP_INSTALL_KEY",
        "DEVICE_LIST",
        "DEVICE_MAP",
    }
)


class DooverTransport:
    """Only construct while the caller holds a best-effort device lease."""

    def __init__(
        self,
        api,
        *,
        agent_id,
        app_key,
        app_keys,
        repository,
        device_lock_held,
        attachment_loader: Callable[[AttachmentFile], Awaitable[bytes]] | None = None,
    ):
        if device_lock_held is not True:
            raise ValueError("Claim the device lease before constructing the transport")
        if app_key in app_keys:
            raise ValueError("Processor state namespace cannot also be a dataset app")
        self.api = api
        self.agent_id = agent_id
        self.app_key = app_key
        self.app_keys = frozenset(app_keys)
        self.repository = repository
        self.attachment_loader = attachment_loader
        self._attachment_messages = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def serialized(self):
        # The caller claims a device lease; this lock prevents local reentrancy.
        async with self._lock:
            yield

    async def aggregate(self, channel):
        try:
            result = await self.api.fetch_channel_aggregate(
                channel, agent_id=self.agent_id
            )
        except NotFoundError:
            return {}
        if not isinstance(result.data, dict):
            raise ValueError(f"Channel {channel} must contain an object aggregate")
        return result.data

    async def read_state(self):
        aggregate = await self.aggregate("tag_values")
        own = aggregate.get(self.app_key, {})
        if not isinstance(own, dict):
            raise ValueError("Processor tags must be an object")
        state = own.get(STATE_TAG)
        if state is not None and not isinstance(state, dict):
            raise ValueError("Playback state tag must be an object")
        return copy.deepcopy(state)

    async def write_state(self, value):
        state = {**value, "repository": self.repository}
        if len(json.dumps(state, allow_nan=False).encode()) > 128 * 1024:
            raise ValueError("Playback state exceeds the bounded tag size")
        await self.api.update_channel_aggregate(
            "tag_values",
            {
                self.app_key: {
                    STATE_TAG: state,
                    "anchor_ms": state["anchor_ms"],
                    "dataset_revision": state["revision"],
                    "phase": state["phase"],
                }
            },
            replace_keys=[f"{self.app_key}.{STATE_TAG}"],
            log_update=False,
            suppress_response=True,
            allow_invoking_channel=True,
            agent_id=self.agent_id,
        )

    async def publish_messages(self, items):
        """Reuse matching writes; reject an observed identity collision before POST."""
        outcomes = []
        pending = []
        for item in items:
            if item.attachments:
                await self.ensure_attachments(item)
                existing = self._attachment_messages[(item.channel, item.message_id)]
                if existing.data != item.data:
                    # The multipart upload has finished. Resolve its URL placeholders
                    # with a repeatable JSON-only write before advancing the cursor.
                    updated = await self.api.update_message(
                        item.channel,
                        item.message_id,
                        item.data,
                        replace_data=True,
                        allow_invoking_channel=True,
                        agent_id=self.agent_id,
                    )
                    if updated is None or updated.data != item.data:
                        raise ValueError(
                            "Attachment message finalization was not confirmed"
                        )
                    self._attachment_messages[(item.channel, item.message_id)] = updated
                outcomes.append(WriteResult(item.message_id, True))
                continue
            try:
                existing = await self.api.fetch_message(
                    item.channel, item.message_id, agent_id=self.agent_id
                )
            except NotFoundError:
                pending.append(item)
            else:
                if existing.data != item.data:
                    raise ValueError(
                        "Message identity collision; refusing to overwrite existing history"
                    )
                outcomes.append(WriteResult(item.message_id, True))
        if pending:
            response = await self.api.batch_create_messages(
                [
                    BatchMutationItem(
                        agent_id=self.agent_id,
                        channel_name=item.channel,
                        message_id=item.message_id,
                        timestamp=item.timestamp_ms,
                        data=item.data,
                    )
                    for item in pending
                ]
            )
            if len(response.items) != len(pending):
                raise ValueError("Incomplete batch response; keep progress unchanged")
            for item, result in zip(pending, response.items, strict=True):
                if (
                    result.agent_id != self.agent_id
                    or result.channel_name != item.channel
                ):
                    raise ValueError("Batch result targets a different channel")
                if result.message_id not in (None, item.message_id):
                    raise ValueError("Batch result has a different message identity")
                outcomes.append(
                    WriteResult(item.message_id, result.success, result.error)
                )
        by_id = {result.message_id: result for result in outcomes}
        return [by_id[item.message_id] for item in items]

    def _check_attachment_message(self, item, message):
        if (
            message.id != item.message_id
            or message.channel.agent_id != self.agent_id
            or message.channel.name != item.channel
        ):
            raise ValueError("Attachment response targets a different message")
        expected, actual = copy.deepcopy(item.data), copy.deepcopy(message.data)
        try:
            for path in item.attachment_paths:
                set_data_path(expected, path, None)
                set_data_path(actual, path, None)
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError(
                "Message identity collision in attachment placeholders"
            ) from error
        if actual != expected:
            raise ValueError(
                "Message identity collision; refusing to overwrite attachment history"
            )
        files = {file.filename: file for file in item.attachments}
        urls = {}
        for attachment in message.attachments:
            file = files.get(attachment.filename)
            if (
                file is None
                or (
                    attachment.size != file.size
                    or attachment.content_type != file.content_type
                )
                or not isinstance(attachment.url, str)
                or not attachment.url
            ):
                raise ValueError(
                    "Stored attachment metadata differs from the pinned manifest"
                )
            # Overlapping multipart retries can append the same pinned file.
            # Accept matching metadata and consistently reuse its first URL.
            urls.setdefault(attachment.filename, attachment.url)
        return urls

    async def ensure_attachments(self, item):
        """Resume native multipart uploads by inspecting the deterministic message."""
        if self.attachment_loader is None:
            raise ValueError("An attachment loader is required for this dataset")
        key = item.channel, item.message_id
        message = self._attachment_messages.get(key)
        if message is None:
            try:
                message = await self.api.fetch_message(
                    item.channel, item.message_id, agent_id=self.agent_id
                )
            except NotFoundError:
                # ProcessorDataClient.create_message does not expose message_id in
                # the pinned SDK. Reserve the historical ID with the batch API first.
                response = await self.api.batch_create_messages(
                    [
                        BatchMutationItem(
                            agent_id=self.agent_id,
                            channel_name=item.channel,
                            message_id=item.message_id,
                            timestamp=item.timestamp_ms,
                            data=item.data,
                        )
                    ]
                )
                if len(response.items) != 1:
                    raise ValueError("Attachment message reservation was not confirmed")
                result = response.items[0]
                if (
                    not result.success
                    or result.agent_id != self.agent_id
                    or result.channel_name != item.channel
                    or result.message_id not in (None, item.message_id)
                ):
                    raise ValueError("Attachment message reservation failed")
                message = await self.api.fetch_message(
                    item.channel, item.message_id, agent_id=self.agent_id
                )
        urls = self._check_attachment_message(item, message)
        missing = [file for file in item.attachments if file.filename not in urls]
        if missing:
            files = []
            for file in missing:
                raw = verify_attachment_bytes(file, await self.attachment_loader(file))
                files.append(File(file.filename, file.content_type, file.size, raw))
            # The SDK otherwise retries multipart PATCH blindly after a lost
            # response, which can append duplicate files. A later invocation must
            # GET the message before deciding whether another upload is necessary.
            retries = self.api.max_retries
            self.api.max_retries = 1
            self._attachment_messages.pop(key, None)
            try:
                message = await self.api.update_message(
                    item.channel,
                    item.message_id,
                    {},
                    files=files,
                    allow_invoking_channel=True,
                    agent_id=self.agent_id,
                )
            finally:
                self.api.max_retries = retries
            if message is None:
                raise ValueError(
                    "Attachment upload response was empty; keep progress unchanged"
                )
            urls = self._check_attachment_message(item, message)
        if set(urls) != {file.filename for file in item.attachments}:
            raise ValueError(
                "Attachment upload was incomplete; keep progress unchanged"
            )
        self._attachment_messages[key] = message
        return urls

    def _validate_scope(self, channel, data, replace_paths):
        if channel in ("tag_values", "ui_cmds"):
            keys = set(data)
            prefix = ""
        elif channel == "ui_state":
            if set(data) != {"state"} or set(data["state"]) != {"children"}:
                raise ValueError("UI initialization must be scoped to app children")
            keys = set(data["state"]["children"])
            prefix = "state.children."
        elif channel == "deployment_config":
            if set(data) != {"applications"}:
                raise ValueError(
                    "Deployment initialization must be scoped to applications"
                )
            keys = set(data["applications"])
            prefix = "applications."
        elif channel == "ui_overrides":
            if set(data) != {"ops"} or not isinstance(data["ops"], list):
                raise ValueError("UI overrides must contain an ops array")
            if any(path != "ops" for path in replace_paths):
                raise ValueError("Invalid override replacement scope")
            return
        else:
            # Generic channels have no platform-owned app namespaces.
            return
        if not keys <= self.app_keys:
            raise ValueError("Dataset operation targets an undeclared app namespace")
        for path in replace_paths:
            if not any(
                path == prefix + key or path.startswith(prefix + key + ".")
                for key in keys
            ):
                raise ValueError("Replacement would erase another app's state")

    async def patch_aggregate(self, channel, data, replace_paths=()):
        self._validate_scope(channel, data, replace_paths)
        if channel == "deployment_config":
            current = await self.aggregate(channel)
            installed = current.get("applications", {})
            for app_key, values in data["applications"].items():
                if not isinstance(installed.get(app_key), dict):
                    raise ValueError(
                        "Organisation provisioning must install each dataset app first"
                    )
                if any(key in values for key in IMMUTABLE_FIELDS):
                    raise ValueError("Dataset cannot provide installed identity fields")
            if replace_paths:
                raise ValueError(
                    "Deployment config replacement would erase installation bindings"
                )
        await self.api.update_channel_aggregate(
            channel,
            data,
            replace_keys=list(replace_paths) or None,
            log_update=False,
            suppress_response=True,
            allow_invoking_channel=True,
            agent_id=self.agent_id,
        )

    async def update_rpc_response(self, channel, message_id, response):
        await self.api.update_message(
            channel,
            message_id,
            response,
            allow_invoking_channel=True,
            agent_id=self.agent_id,
        )

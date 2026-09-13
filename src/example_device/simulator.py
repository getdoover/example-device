"""Local channel transport for reviewing a dataset without a cloud device."""

import asyncio
import copy
from contextlib import asynccontextmanager
from pathlib import Path

from .dataset import read_local_attachment
from .runtime import WriteResult
from .timeline import merge_data


class MemoryTransport:
    def __init__(self, attachment_directory: Path | None = None):
        self.state = None
        self.messages = {}
        self.aggregates = {}
        self.rpc_responses = {}
        self._lock = asyncio.Lock()
        self.attachment_directory = attachment_directory
        self.attachments = {}

    @asynccontextmanager
    async def serialized(self):
        async with self._lock:
            yield

    async def read_state(self):
        return copy.deepcopy(self.state)

    async def write_state(self, value):
        self.state = copy.deepcopy(value)

    async def publish_messages(self, items):
        outcomes = []
        for item in items:
            if item.attachments:
                await self.ensure_attachments(item)
            key = (item.channel, item.message_id)
            if key in self.messages and self.messages[key].data != item.data:
                raise ValueError("Message identity collision")
            self.messages[key] = copy.deepcopy(item)
            outcomes.append(WriteResult(item.message_id, True))
        return outcomes

    async def ensure_attachments(self, item):
        if self.attachment_directory is None:
            raise ValueError("Local attachment simulation requires a dataset directory")
        urls = {}
        for file in item.attachments:
            key = item.channel, item.message_id, file.filename
            if key not in self.attachments:
                self.attachments[key] = read_local_attachment(
                    self.attachment_directory, file
                )
            urls[file.filename] = (
                (self.attachment_directory / file.path).resolve().as_uri()
            )
        return urls

    async def patch_aggregate(self, channel, data, replace_paths=()):
        current = self.aggregates.get(channel, {})
        value = copy.deepcopy(current)
        for path in replace_paths:
            parts = path.split(".")
            node = value
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node.pop(parts[-1], None)
        self.aggregates[channel] = merge_data(value, data)

    async def update_rpc_response(self, channel, message_id, response):
        self.rpc_responses[(channel, message_id)] = copy.deepcopy(response)

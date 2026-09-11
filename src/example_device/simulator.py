"""Local channel transport for reviewing a dataset without a cloud device."""

import asyncio
import copy
from contextlib import asynccontextmanager

from .runtime import WriteResult
from .timeline import merge_data


class MemoryTransport:
    def __init__(self):
        self.state = None
        self.messages = {}
        self.aggregates = {}
        self.rpc_responses = {}
        self._lock = asyncio.Lock()

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
            key = (item.channel, item.message_id)
            if key in self.messages and self.messages[key].data != item.data:
                raise ValueError("Message identity collision")
            self.messages[key] = copy.deepcopy(item)
            outcomes.append(WriteResult(item.message_id, True))
        return outcomes

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

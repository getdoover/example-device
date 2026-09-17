"""Best-effort per-device coordination through ordinary Doover tags.

These read/write/read claims are deliberately not atomic locks. Two simultaneous
claimants can both proceed. Expiry and owner checks reduce damage, but cannot
provide mutual exclusion or an exact collision count.
"""

import time

from pydoover.api import NotFoundError


class DeviceBusy(RuntimeError):
    """A command must be retried after the current device update finishes."""


class DeviceLease:
    def __init__(self, api, *, agent_id, app_key, owner, expires_at_ms, clock=None):
        self.api = api
        self.agent_id = agent_id
        self.app_key = app_key
        self.owner = owner
        self.expires_at_ms = expires_at_ms
        self.clock = clock or (lambda: int(time.time() * 1000))

    async def _read(self):
        try:
            aggregate = await self.api.fetch_channel_aggregate(
                "tag_values", agent_id=self.agent_id
            )
        except NotFoundError:
            return {}
        if not isinstance(aggregate.data, dict):
            raise ValueError("Device tags must be an object")
        own = aggregate.data.get(self.app_key, {})
        if not isinstance(own, dict):
            raise ValueError("Processor tags must be an object")
        lock = own.get("update_lock")
        if lock is not None and (
            not isinstance(lock, dict)
            or not isinstance(lock.get("owner"), str)
            or type(lock.get("expires_at_ms")) is not int
        ):
            raise ValueError("Invalid device update lock")
        if type(own.get("collision_count", 0)) is not int:
            raise ValueError("Invalid device collision count")
        return own

    async def _write(self, values):
        await self.api.update_channel_aggregate(
            "tag_values",
            {self.app_key: values},
            agent_id=self.agent_id,
            log_update=False,
            suppress_response=True,
            allow_invoking_channel=True,
        )

    async def _collision(self, own):
        await self._write(
            {
                "collision_count": own.get("collision_count", 0) + 1,
                "last_collision_ms": self.clock(),
            }
        )
        return False

    async def acquire(self):
        own = await self._read()
        lock = own.get("update_lock")
        if lock and lock["expires_at_ms"] > self.clock():
            return await self._collision(own)
        await self._write(
            {
                "update_lock": {
                    "owner": self.owner,
                    "expires_at_ms": self.expires_at_ms,
                }
            }
        )
        own = await self._read()
        if (own.get("update_lock") or {}).get("owner") != self.owner:
            return await self._collision(own)
        return True

    async def release(self):
        own = await self._read()
        if (own.get("update_lock") or {}).get("owner") == self.owner:
            await self._write({"update_lock": None})

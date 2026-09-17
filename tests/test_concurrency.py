from copy import deepcopy
from types import SimpleNamespace

from pydoover.api import NotFoundError

from example_device.concurrency import DeviceLease
from example_device.timeline import merge_data


class TagAPI:
    def __init__(self):
        self.tags = {}

    async def fetch_channel_aggregate(self, channel, *, agent_id):
        if agent_id not in self.tags:
            raise NotFoundError("missing")
        return SimpleNamespace(data=deepcopy(self.tags[agent_id]))

    async def update_channel_aggregate(self, channel, data, *, agent_id, **kwargs):
        assert channel == "tag_values"
        assert kwargs["log_update"] is False
        self.tags[agent_id] = merge_data(self.tags.get(agent_id, {}), data)


def lease(api, device=1, owner="first", now=1000):
    return DeviceLease(
        api,
        agent_id=device,
        app_key="processor",
        owner=owner,
        expires_at_ms=2000,
        clock=lambda: now,
    )


async def test_same_device_skips_and_counts_but_other_device_can_run():
    api = TagAPI()
    first = lease(api)
    assert await first.acquire()
    assert not await lease(api, owner="second").acquire()
    assert not await lease(api, owner="third").acquire()
    assert api.tags[1]["processor"]["collision_count"] == 2
    assert await lease(api, device=2).acquire()
    await first.release()
    assert await lease(api, owner="fourth").acquire()


async def test_crash_expires_and_old_owner_does_not_release_successor():
    api = TagAPI()
    old = lease(api)
    assert await old.acquire()
    successor = lease(api, owner="new", now=2001)
    assert await successor.acquire()
    await old.release()
    assert api.tags[1]["processor"]["update_lock"]["owner"] == "new"


async def test_claim_readback_detects_overwritten_claim():
    api = TagAPI()
    original = api.update_channel_aggregate

    async def overwrite(channel, data, **kwargs):
        await original(channel, data, **kwargs)
        if data["processor"].get("update_lock"):
            api.tags[1]["processor"]["update_lock"]["owner"] = "racer"

    api.update_channel_aggregate = overwrite
    assert not await lease(api).acquire()
    assert api.tags[1]["processor"]["collision_count"] == 1
    assert api.tags[1]["processor"]["update_lock"]["owner"] == "racer"

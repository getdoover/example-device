import json
from urllib.parse import urlsplit

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from test_dataset import baseline, config

from example_device import source
from example_device.application import is_page_observed
from example_device.source import decode_json, validate_source


@pytest.mark.parametrize(
    "repository,revision,slug",
    [
        ("owner/repo", "main", "demo"),
        ("owner/../repo", "a" * 40, "demo"),
        ("owner/repo", "a" * 40, "../demo"),
        ("owner/repo?token=x", "a" * 40, "demo"),
    ],
)
def test_source_is_pinned_and_paths_cannot_escape(repository, revision, slug):
    with pytest.raises(ValueError):
        validate_source(repository, revision, slug)


def test_source_accepts_public_immutable_path():
    validate_source("sample/repo", "a" * 40, "demo")


@pytest.mark.parametrize(
    "payload", [b'{"a":1,"a":2}', b'{"value":NaN}', b'{"value":Infinity}']
)
def test_source_rejects_ambiguous_json(payload):
    with pytest.raises(ValueError):
        decode_json(payload)


@pytest.mark.parametrize(
    "stamp,expected",
    [
        (1_000, True),
        (120_999, True),
        (999, False),
        (121_001, False),
        (True, False),
        (None, False),
    ],
)
def test_viewer_presence_uses_age_not_retained_entries(stamp, expected):
    assert is_page_observed({"agent_open": {"viewer": stamp}}, 120_999) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "redirect", "oversized", "invalid"])
async def test_public_download_boundary(monkeypatch, failure):
    calls = []
    raw_config = json.dumps(config()).encode()
    raw_channel = json.dumps([baseline()]).encode()
    prefix = "/sample/repo/" + "a" * 40 + "/devices/test-scenario/"

    async def respond(request):
        assert "Authorization" not in request.headers
        calls.append(request.path)
        if request.path == prefix + "config.json":
            return web.Response(body=raw_config)
        assert request.path == prefix + "channels/tag_values.json"
        if failure == "redirect":
            raise web.HTTPFound("/unexpected")
        if failure == "oversized":
            return web.Response(body=b" " * 1025)
        if failure == "invalid":
            return web.Response(body=b'[{"kind":"message","timestamp":"tomorrow"}]')
        return web.Response(body=raw_channel)

    server_app = web.Application()
    server_app.router.add_route("GET", "/{tail:.*}", respond)
    real_session = aiohttp.ClientSession
    async with TestServer(server_app) as server:

        class RoutedSession:
            def __init__(self, **kwargs):
                assert kwargs["trust_env"] is False
                self.session = real_session(**kwargs)

            async def __aenter__(self):
                await self.session.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await self.session.__aexit__(*args)

            def get(self, url, **kwargs):
                parsed = urlsplit(url)
                assert parsed.scheme == "https"
                assert parsed.netloc == "raw.githubusercontent.com"
                assert kwargs["allow_redirects"] is False
                return self.session.get(server.make_url(parsed.path), **kwargs)

        monkeypatch.setattr(source.aiohttp, "ClientSession", RoutedSession)
        monkeypatch.setattr(source, "MAX_FILE_BYTES", 1024)
        if failure:
            with pytest.raises(ValueError):
                await source.fetch_dataset("sample/repo", "a" * 40, "test-scenario")
        else:
            dataset = await source.fetch_dataset(
                "sample/repo", "a" * 40, "test-scenario"
            )
            assert dataset.channels["tag_values"][0].data["sensor"]["level"] == 10
    assert calls == [prefix + "config.json", prefix + "channels/tag_values.json"]

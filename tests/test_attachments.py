"""Replay attachment bytes through the installed SDK's actual multipart HTTP path."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from jsonschema import Draft202012Validator
from pydoover.api import HTTPError
from pydoover.processor.data_client import ProcessorDataClient

from example_device.adapter import DooverTransport
from example_device.dataset import DatasetError, load_directory, parse_dataset
from example_device.runtime import Runtime
from example_device.timeline import merge_data

ANCHOR = 1_800_000_000_000
REVISION = "a" * 40


def camera_fixture():
    config = {
        "schema_version": 1,
        "slug": "test-camera",
        "name": "Test camera",
        "duration_ms": 7_200_000,
        "apps": [
            {
                "app_key": "camera",
                "application_name": "ptz_camera",
                "config": {},
                "run": False,
            }
        ],
        "channels": ["camera_images", "ui_state", "ui_overrides"],
    }
    messages = []
    blobs = {}
    for name, stamp in (("past", -3_600_000), ("initial", 0), ("future", 3_600_000)):
        raw = b"\xff\xd8\xff" + name.encode() + b"\x00\xff\xd9"
        path = f"attachments/{name}.jpg"
        blobs[path] = raw
        messages.append(
            {
                "kind": "message",
                "timestamp": stamp,
                "id": name,
                "data": {"position": 1, "url": None, "taken_at": stamp},
                "timestamp_fields": [{"path": ["taken_at"], "unit": "ms"}],
                "attachments": [
                    {
                        "path": path,
                        "filename": name + ".jpg",
                        "content_type": "image/jpeg",
                        "size": len(raw),
                        "sha256": sha256(raw).hexdigest(),
                    }
                ],
                "attachment_references": [
                    {
                        "path": ["url"],
                        "channel": "camera_images",
                        "id": name,
                        "filename": name + ".jpg",
                    }
                ],
            }
        )
    channels = {
        "camera_images": messages,
        "ui_state": [
            {
                "kind": "aggregate",
                "timestamp": 0,
                "mode": "merge",
                "data": {"state": {"children": {"camera": {"views": [{"url": None}]}}}},
                "attachment_references": [
                    {
                        "path": ["state", "children", "camera", "views", 0, "url"],
                        "channel": "camera_images",
                        "id": "initial",
                        "filename": "initial.jpg",
                    }
                ],
            }
        ],
        "ui_overrides": [
            {
                "kind": "aggregate",
                "timestamp": 3_600_000,
                "mode": "merge",
                "data": {
                    "ops": [
                        {"op": "replace", "path": "/camera/views/0/url", "value": None}
                    ]
                },
                "attachment_references": [
                    {
                        "path": ["ops", 0, "value"],
                        "channel": "camera_images",
                        "id": "future",
                        "filename": "future.jpg",
                    }
                ],
            }
        ],
    }
    return config, channels, blobs


def test_attachment_manifest_schema_and_parser_accept_real_contract():
    config, channels, _ = camera_fixture()
    parsed = parse_dataset(config, channels)
    assert parsed.channels["ui_state"][0].attachment_references[0].path[-2] == 0
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "schemas/channel.schema.json"
        ).read_text()
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for entries in channels.values():
        validator.validate(entries)


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "attachments/../secret",
        "/attachments/a.jpg",
        "https://example.com/a.jpg",
        "attachments/a%2fsecret.jpg",
        "attachments//a.jpg",
        "attachments/a\\b.jpg",
        "attachments/a.jpg?token=secret",
    ],
)
def test_attachment_paths_cannot_escape_pinned_dataset(path):
    config, channels, _ = camera_fixture()
    channels["camera_images"][0]["attachments"][0]["path"] = path
    with pytest.raises(DatasetError, match="attachment path"):
        parse_dataset(config, channels)


@pytest.mark.parametrize(
    "failure",
    [
        "hash",
        "size",
        "filename",
        "missing",
        "future",
        "placeholder",
        "index",
        "overlap",
    ],
)
def test_bad_attachment_contract_fails_before_any_upload(failure):
    config, channels, _ = camera_fixture()
    entry = channels["camera_images"][0]
    file = entry["attachments"][0]
    reference = entry["attachment_references"][0]
    if failure == "hash":
        file["sha256"] = "not-a-hash"
    elif failure == "size":
        file["size"] = 8 * 1024 * 1024 + 1
    elif failure == "filename":
        entry["attachments"].append(deepcopy(file))
    elif failure == "missing":
        reference["filename"] = "missing.jpg"
    elif failure == "future":
        reference.update(id="future", filename="future.jpg")
    elif failure == "placeholder":
        entry["data"]["url"] = "https://old-device/image.jpg"
    elif failure == "index":
        channels["ui_state"][0]["attachment_references"][0]["path"][-2] = -1
    elif failure == "overlap":
        entry["message_references"] = [
            {"path": ["url"], "channel": "camera_images", "id": "past"}
        ]
    with pytest.raises(DatasetError):
        parse_dataset(config, channels)


def test_local_validation_reads_hashes_and_rejects_symlink_escape(tmp_path):
    config, channels, blobs = camera_fixture()
    (tmp_path / "channels").mkdir()
    (tmp_path / "attachments").mkdir()
    (tmp_path / "config.json").write_text(json.dumps(config))
    for channel, entries in channels.items():
        (tmp_path / "channels" / f"{channel}.json").write_text(json.dumps(entries))
    for path, raw in blobs.items():
        (tmp_path / path).write_bytes(raw)
    assert load_directory(tmp_path).config.slug == "test-camera"
    file = tmp_path / "attachments/past.jpg"
    file.write_bytes(b"corrupted")
    with pytest.raises(DatasetError, match="SHA-256"):
        load_directory(tmp_path)
    file.unlink()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(blobs["attachments/past.jpg"])
    file.symlink_to(outside)
    with pytest.raises(DatasetError, match="symlink"):
        load_directory(tmp_path)


class AttachmentBackend:
    def __init__(self):
        self.messages = {}
        self.aggregates = {}
        self.calls = []
        self.uploads = []
        self.fail_upload_response = False
        self.fail_final_response = False
        self.partial_upload_count = None

    async def handle(self, request):
        files = []
        if request.content_type == "multipart/form-data":
            multipart = await request.multipart()
            body = None
            async for part in multipart:
                raw = bytes(await part.read())
                if part.name == "json_payload":
                    body = json.loads(raw)
                else:
                    assert part.name.startswith("attachment-")
                    files.append((part.filename, part.headers["Content-Type"], raw))
        else:
            body = await request.json() if request.can_read_body else None
        self.calls.append((request.method, request.path, deepcopy(body)))
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.path == "/agents/messages":
            for item in body["items"]:
                key = item["channel_name"], int(item["message_id"])
                assert key not in self.messages, "A retry must reuse the stored message"
                self.messages[key] = {
                    "id": item["message_id"],
                    "author_id": "7",
                    "channel": {"agent_id": "7", "name": item["channel_name"]},
                    "data": deepcopy(item["data"]),
                    "attachments": [],
                }
                assert (int(item["message_id"]) >> 22) + 1_735_689_600_000 == item["ts"]
            return web.json_response(
                {
                    "items": [dict(item, success=True) for item in body["items"]],
                    "count": len(body["items"]),
                    "succeeded": len(body["items"]),
                    "failed": 0,
                }
            )
        parts = request.path.split("/")
        channel = parts[4]
        if parts[5] == "aggregate":
            if request.method == "GET":
                if channel not in self.aggregates:
                    raise web.HTTPNotFound()
                return web.json_response(
                    {"data": self.aggregates[channel], "attachments": []}
                )
            current = deepcopy(self.aggregates.get(channel, {}))
            for dotted in request.query.getall("replace", []):
                keys = dotted.split(".")
                node = current
                for key in keys[:-1]:
                    node = node.setdefault(key, {})
                node.pop(keys[-1], None)
            self.aggregates[channel] = merge_data(current, body)
            return web.json_response({})
        key = channel, int(parts[6])
        if key not in self.messages:
            raise web.HTTPNotFound()
        message = self.messages[key]
        if files:
            assert request.method == "PATCH" and body == {"data": {}}
            if self.partial_upload_count is not None:
                files = files[: self.partial_upload_count]
                self.partial_upload_count = None
            for filename, content_type, raw in files:
                self.uploads.append((key, filename, content_type, raw))
                message["attachments"].append(
                    {
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(raw),
                        "url": f"https://api.example.test/agents/7/channels/{channel}/messages/{key[1]}/attachments/{filename}",
                    }
                )
            if self.fail_upload_response:
                self.fail_upload_response = False
                raise web.HTTPInternalServerError(
                    text="stored upload but response lost"
                )
        elif request.method == "PUT":
            message["data"] = deepcopy(body["data"])
            if self.fail_final_response:
                self.fail_final_response = False
                raise web.HTTPInternalServerError(
                    text="stored finalization but response lost"
                )
        elif request.method != "GET":
            raise AssertionError(f"Unexpected message operation {request.method}")
        return web.json_response(message)


@pytest.fixture
async def attachment_server():
    backend = AttachmentBackend()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", backend.handle)
    async with TestServer(app) as server:
        async with ProcessorDataClient(str(server.make_url("/"))) as api:
            api.agent_id = 7
            api.app_key = "processor"
            api.set_token("test-token")
            yield backend, api


def playback(api, blobs, loads, fixture=None):
    config, channels, _ = fixture or camera_fixture()

    async def loader(file):
        loads.append(file.path)
        return blobs[file.path]

    transport = DooverTransport(
        api,
        agent_id=7,
        app_key="processor",
        app_keys=["camera"],
        repository="sample/repo",
        serialization_verified=True,
        attachment_loader=loader,
    )
    return Runtime(
        parse_dataset(config, channels),
        transport,
        anchor_ms=ANCHOR,
        revision=REVISION,
        installation_id="7:processor",
        active_interval_ms=1,
        idle_interval_ms=1,
    )


async def test_native_multipart_uploads_historical_bytes_and_rewrites_message_and_ui(
    attachment_server,
):
    backend, api = attachment_server
    _, _, blobs = camera_fixture()
    loads = []
    result = await playback(api, blobs, loads).run(ANCHOR)
    assert result.phase == "active"
    assert len(backend.messages) == len(backend.uploads) == 2
    assert set(loads) == {"attachments/initial.jpg", "attachments/past.jpg"}
    for (channel, _), filename, content_type, raw in backend.uploads:
        assert channel == "camera_images" and content_type == "image/jpeg"
        assert raw == blobs["attachments/" + filename]
    for message in backend.messages.values():
        assert message["data"]["url"] == message["attachments"][0]["url"]
        assert message["data"]["taken_at"] <= ANCHOR
    initial = next(
        message
        for message in backend.messages.values()
        if message["data"]["taken_at"] == ANCHOR
    )
    assert (
        backend.aggregates["ui_state"]["state"]["children"]["camera"]["views"][0]["url"]
        == initial["attachments"][0]["url"]
    )
    await playback(api, blobs, loads).run(ANCHOR + 3_600_000)
    assert len(backend.messages) == len(backend.uploads) == 3
    assert loads.count("attachments/future.jpg") == 1
    future = next(
        message
        for message in backend.messages.values()
        if message["data"]["taken_at"] > ANCHOR
    )
    assert (
        backend.aggregates["ui_overrides"]["ops"][0]["value"]
        == future["attachments"][0]["url"]
    )


async def test_lost_multipart_response_reuses_uploaded_file_after_restart(
    attachment_server,
):
    backend, api = attachment_server
    _, _, blobs = camera_fixture()
    loads = []
    backend.fail_upload_response = True
    retries = api.max_retries
    with pytest.raises(HTTPError):
        await playback(api, blobs, loads).run(ANCHOR)
    assert api.max_retries == retries
    assert len(backend.uploads) == 1
    assert (
        backend.aggregates["tag_values"]["processor"]["playback_state"]["cursor"] == 0
    )
    result = await playback(api, blobs, loads).run(ANCHOR)
    assert result.phase == "active"
    assert len(backend.uploads) == len(backend.messages) == 2
    assert loads.count("attachments/initial.jpg") == 1
    assert all(
        len(message["attachments"]) == 1 for message in backend.messages.values()
    )
    assert all(message["data"]["url"] for message in backend.messages.values())


async def test_url_finalization_retry_changes_json_without_reuploading_files(
    attachment_server,
):
    backend, api = attachment_server
    _, _, blobs = camera_fixture()
    backend.fail_final_response = True
    result = await playback(api, blobs, []).run(ANCHOR)
    assert result.phase == "active"
    assert len(backend.uploads) == len(backend.messages) == 2
    assert len([call for call in backend.calls if call[0] == "PUT"]) == 3
    assert all(
        message["data"]["url"] == message["attachments"][0]["url"]
        for message in backend.messages.values()
    )


async def test_attachment_identity_collision_stops_before_download_or_overwrite(
    attachment_server,
):
    backend, api = attachment_server
    _, _, blobs = camera_fixture()
    loads = []
    await playback(api, blobs, loads).run(ANCHOR)
    backend.aggregates["tag_values"]["processor"]["playback_state"]["cursor"] = 0
    message = next(iter(backend.messages.values()))
    message["data"]["position"] = "unrelated record"
    writes = len([call for call in backend.calls if call[0] in ("POST", "PUT")])
    with pytest.raises(ValueError, match="collision"):
        await playback(api, blobs, loads).run(ANCHOR + 1)
    assert len(loads) == len(backend.uploads) == 2
    assert len([call for call in backend.calls if call[0] in ("POST", "PUT")]) == writes


async def test_corrupt_source_bytes_never_reach_multipart_upload(attachment_server):
    backend, api = attachment_server
    _, _, blobs = camera_fixture()
    blobs["attachments/initial.jpg"] = b"tampered"
    with pytest.raises(DatasetError, match="SHA-256"):
        await playback(api, blobs, []).run(ANCHOR)
    assert not backend.uploads
    assert "ui_state" not in backend.aggregates


def multi_camera_fixture():
    config, channels, _ = camera_fixture()
    config["channels"] = ["camera_images"]
    message = channels["camera_images"][0]
    message["data"] = {"camera_name": "Dahua PTZ", "media": [], "reason": "schedule"}
    message.pop("timestamp_fields")
    message.pop("attachment_references")
    message["attachments"] = []
    blobs = {}
    for name in ("Clock", "Cafe", "Shops", "Escalator"):
        filename = name + ".jpg"
        path = "attachments/hour-m0001/" + filename
        raw = b"\xff\xd8\xff" + name.encode() + b"\xff\xd9"
        blobs[path] = raw
        message["data"]["media"].append({"file": filename, "name": name})
        message["attachments"].append(
            {
                "path": path,
                "filename": filename,
                "content_type": "image/jpeg",
                "size": len(raw),
                "sha256": sha256(raw).hexdigest(),
            }
        )
    return config, {"camera_images": [message]}, blobs


@pytest.mark.parametrize("failure", ["lost_response", "partial"])
async def test_four_file_camera_message_retries_without_duplicate_attachments(
    attachment_server, failure
):
    backend, api = attachment_server
    fixture = multi_camera_fixture()
    _, channels, blobs = fixture
    loads = []
    if failure == "lost_response":
        backend.fail_upload_response = True
        expected_error = HTTPError
    else:
        backend.partial_upload_count = 2
        expected_error = ValueError
    with pytest.raises(expected_error):
        await playback(api, blobs, loads, fixture).run(ANCHOR)
    first_uploads = len(backend.uploads)
    assert first_uploads == (4 if failure == "lost_response" else 2)
    assert (
        backend.aggregates["tag_values"]["processor"]["playback_state"]["cursor"] == 0
    )
    result = await playback(api, blobs, loads, fixture).run(ANCHOR)
    assert result.phase == "active"
    assert len(backend.messages) == 1 and len(backend.uploads) == 4
    message = next(iter(backend.messages.values()))
    assert len({file["filename"] for file in message["attachments"]}) == 4
    actual_data = {
        key: value for key, value in message["data"].items() if key != "_example_device"
    }
    assert actual_data == channels["camera_images"][0]["data"]
    assert {file["file"] for file in message["data"]["media"]} == {
        file["filename"] for file in message["attachments"]
    }
    assert all(
        raw == blobs["attachments/hour-m0001/" + filename]
        for _, filename, _, raw in backend.uploads
    )
    assert len(loads) == (4 if failure == "lost_response" else 6)

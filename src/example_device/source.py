"""Load public datasets from an immutable GitHub revision."""

from __future__ import annotations

import json
import re
from typing import Any

import aiohttp

from .dataset import AttachmentFile, Dataset, parse_dataset, verify_attachment_bytes

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_REVISION = re.compile(r"[a-f0-9]{40}\Z")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_DATASET_BYTES = 32 * 1024 * 1024


def validate_source(repository: str, revision: str, slug: str) -> None:
    if not _REPOSITORY.fullmatch(repository) or any(
        part in (".", "..") for part in repository.split("/")
    ):
        raise ValueError("repository must be an owner/repository name")
    if not _REVISION.fullmatch(revision):
        raise ValueError("revision must be a full lowercase Git commit SHA")
    if not _COMPONENT.fullmatch(slug):
        raise ValueError("dataset slug must be a simple directory name")


def decode_json(raw: bytes) -> Any:
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        raw, parse_constant=reject_constant, object_pairs_hook=unique_pairs
    )


async def fetch_dataset(repository: str, revision: str, slug: str) -> Dataset:
    """Fetch config then its declared channels; no customer credentials are sent."""
    validate_source(repository, revision, slug)
    base = f"https://raw.githubusercontent.com/{repository}/{revision}/devices/{slug}"
    total = 0
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:

        async def read(path):
            nonlocal total
            async with session.get(f"{base}/{path}", allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError(
                        f"Dataset fetch failed for {path}: HTTP {response.status}"
                    )
                parts = []
                size = 0
                async for block in response.content.iter_chunked(64 * 1024):
                    size += len(block)
                    total += len(block)
                    if size > MAX_FILE_BYTES or total > MAX_DATASET_BYTES:
                        raise ValueError("Dataset exceeds the download size limit")
                    parts.append(block)
                return decode_json(b"".join(parts))

        config = await read("config.json")
        names = config.get("channels") if isinstance(config, dict) else None
        if not isinstance(names, list) or not 1 <= len(names) <= 32:
            raise ValueError("Dataset must declare 1 to 32 channels")
        if any(
            not isinstance(name, str) or not _COMPONENT.fullmatch(name)
            for name in names
        ):
            raise ValueError("Invalid channel filename")
        if len(names) != len(set(names)):
            raise ValueError("Duplicate channel names")
        channels = {}
        for name in names:
            channels[name] = await read(f"channels/{name}.json")
    result = parse_dataset(config, channels)
    if result.config.slug != slug:
        raise ValueError("Dataset slug does not match its requested directory")
    return result


async def fetch_attachment(
    repository: str, revision: str, slug: str, attachment: AttachmentFile
) -> bytes:
    """Download only a due file, without sharing the Doover client's credentials."""
    validate_source(repository, revision, slug)
    url = f"https://raw.githubusercontent.com/{repository}/{revision}/devices/{slug}/{attachment.path}"
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), trust_env=False
    ) as session:
        async with session.get(url, allow_redirects=False) as response:
            if response.status != 200:
                raise ValueError(
                    f"Attachment fetch failed for {attachment.path}: HTTP {response.status}"
                )
            if (
                response.content_length is not None
                and response.content_length != attachment.size
            ):
                raise ValueError("Attachment Content-Length differs from its manifest")
            raw = bytearray()
            async for block in response.content.iter_chunked(64 * 1024):
                raw.extend(block)
                if len(raw) > attachment.size:
                    raise ValueError("Attachment exceeds its declared download size")
    return verify_attachment_bytes(attachment, bytes(raw))

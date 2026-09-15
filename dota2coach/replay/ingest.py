"""Safe first-mile validation for untrusted Dota 2 replay files."""

import hashlib
import pathlib
from dataclasses import dataclass
from typing import Union

from .framing import (HEADER_SIZE, SOURCE2_MAGIC, DemoFormatError,
                      parse_demo_header)

DEFAULT_MAX_REPLAY_BYTES = 2 * 1024 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024


class ReplayInputError(ValueError):
    """The selected file cannot be accepted as a Source 2 replay."""


@dataclass(frozen=True)
class ReplayFileInfo:
    path: pathlib.Path
    size_bytes: int
    content_sha256: str
    file_info_offset: int
    spawn_groups_offset: int
    magic: str = "PBDEMS2"


def inspect_replay_file(path: Union[str, pathlib.Path],
                        max_bytes: int = DEFAULT_MAX_REPLAY_BYTES) -> ReplayFileInfo:
    """Validates and hashes a replay in bounded memory without modifying it."""
    candidate = pathlib.Path(path).expanduser().resolve()
    try:
        stat = candidate.stat()
    except OSError as exc:
        raise ReplayInputError(f"replay file is not readable: {candidate}") from exc
    if not candidate.is_file():
        raise ReplayInputError(f"replay path is not a regular file: {candidate}")
    if stat.st_size < HEADER_SIZE:
        raise ReplayInputError("file is too small to be a Dota 2 Source 2 replay")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if stat.st_size > max_bytes:
        raise ReplayInputError(
            f"replay is too large: {stat.st_size} bytes; limit is {max_bytes} bytes"
        )

    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as stream:
            fixed_header = stream.read(HEADER_SIZE)
            try:
                header = parse_demo_header(fixed_header, file_size=stat.st_size)
            except DemoFormatError as exc:
                raise ReplayInputError(str(exc)) from exc
            digest.update(fixed_header)
            while True:
                chunk = stream.read(HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except ReplayInputError:
        raise
    except OSError as exc:
        raise ReplayInputError(f"could not read replay: {candidate}") from exc

    return ReplayFileInfo(
        path=candidate,
        size_bytes=stat.st_size,
        content_sha256=digest.hexdigest(),
        file_info_offset=header.file_info_offset,
        spawn_groups_offset=header.spawn_groups_offset,
    )

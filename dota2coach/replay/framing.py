"""Strict streaming reader for the outer Source 2 ``PBDEMS2`` container.

This module deliberately stops at command framing. Protobuf payload decoding,
Snappy decompression and Dota entity semantics belong to decoder adapters. The
framing layer is ours: it validates untrusted input, records exact byte offsets
and builds the seek index used by every future adapter.
"""

import hashlib
import pathlib
import struct
from dataclasses import dataclass
from types import MappingProxyType
from typing import BinaryIO, Dict, Iterator, Mapping, Optional, Tuple, Union


SOURCE2_MAGIC = b"PBDEMS2\x00"
HEADER_SIZE = 16
COMPRESSED_FLAG = 0x40
DEFAULT_MAX_FRAME_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_COMMANDS = 10_000_000
SKIP_CHUNK_BYTES = 1024 * 1024

DEM_STOP = 0
DEM_FILE_INFO = 2
DEM_SYNC_TICK = 3
DEM_FULL_PACKET = 13
DEM_SPAWN_GROUPS = 15

COMMAND_NAMES = MappingProxyType({
    0: "DEM_Stop",
    1: "DEM_FileHeader",
    2: "DEM_FileInfo",
    3: "DEM_SyncTick",
    4: "DEM_SendTables",
    5: "DEM_ClassInfo",
    6: "DEM_StringTables",
    7: "DEM_Packet",
    8: "DEM_SignonPacket",
    9: "DEM_ConsoleCmd",
    10: "DEM_CustomData",
    11: "DEM_CustomDataCallbacks",
    12: "DEM_UserCmd",
    13: "DEM_FullPacket",
    14: "DEM_SaveGame",
    15: "DEM_SpawnGroups",
    16: "DEM_AnimationData",
    17: "DEM_AnimationHeader",
    18: "DEM_Recovery",
})


class DemoFormatError(ValueError):
    """The byte stream is not a safe, structurally valid PBDEMS2 container."""

    def __init__(self, message: str, offset: int):
        super().__init__(f"{message} at byte offset {offset}")
        self.offset = offset


@dataclass(frozen=True)
class DemoHeader:
    file_info_offset: int
    spawn_groups_offset: int


@dataclass(frozen=True)
class DemoCommand:
    """One outer command. ``body`` is absent during allocation-free scans."""

    offset: int
    raw_command: int
    command_id: int
    tick: int
    body_offset: int
    body_size: int
    compressed: bool
    body: Optional[bytes] = None

    @property
    def end_offset(self) -> int:
        return self.body_offset + self.body_size

    @property
    def command_name(self) -> str:
        return COMMAND_NAMES.get(self.command_id, f"UNKNOWN_{self.command_id}")


@dataclass(frozen=True)
class CommandPosition:
    offset: int
    tick: int


@dataclass(frozen=True)
class DemoIndex:
    """Header-only seek index; command bodies are never retained in memory."""

    path: pathlib.Path
    file_size: int
    content_sha256: str
    header: DemoHeader
    command_count: int
    compressed_command_count: int
    first_tick: Optional[int]
    last_tick: Optional[int]
    distinct_tick_count: int
    playback_offset: Optional[int]
    full_packets: Tuple[CommandPosition, ...]
    command_counts: Mapping[int, int]
    unknown_command_counts: Mapping[int, int]


def parse_demo_header(data: bytes, file_size: Optional[int] = None) -> DemoHeader:
    """Parses and range-checks the fixed 16-byte Source 2 demo header."""
    if len(data) < HEADER_SIZE:
        raise DemoFormatError("truncated PBDEMS2 header", len(data))
    if data[:8] != SOURCE2_MAGIC:
        raise DemoFormatError("unexpected replay magic; expected PBDEMS2", 0)
    file_info_offset, spawn_groups_offset = struct.unpack_from("<II", data, 8)
    if file_size is not None:
        for label, offset, field_offset in (
            ("DEM_FileInfo", file_info_offset, 8),
            ("DEM_SpawnGroups", spawn_groups_offset, 12),
        ):
            if offset and not HEADER_SIZE <= offset < file_size:
                raise DemoFormatError(
                    f"{label} header offset {offset} is outside the command stream",
                    field_offset,
                )
    return DemoHeader(file_info_offset, spawn_groups_offset)


class _Cursor:
    def __init__(self, stream: BinaryIO, digest=None):
        self._stream = stream
        self._digest = digest
        self.offset = 0

    def _track(self, data: bytes) -> bytes:
        self.offset += len(data)
        if self._digest is not None:
            self._digest.update(data)
        return data

    def read_exact(self, size: int, label: str) -> bytes:
        start = self.offset
        chunks = []
        remaining = size
        while remaining:
            chunk = self._track(self._stream.read(remaining))
            if not chunk:
                raise DemoFormatError(
                    f"truncated {label}: expected {size} bytes, got {size - remaining}",
                    start,
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return chunks[0] if len(chunks) == 1 else b"".join(chunks)

    def skip_exact(self, size: int, label: str) -> None:
        remaining = size
        start = self.offset
        while remaining:
            chunk = self._track(self._stream.read(min(remaining, SKIP_CHUNK_BYTES)))
            if not chunk:
                raise DemoFormatError(
                    f"truncated {label}: expected {size} bytes, got {size - remaining}", start
                )
            remaining -= len(chunk)

    def read_uvarint32(self, label: str, allow_clean_eof: bool = False) -> Optional[int]:
        start = self.offset
        value = 0
        for index in range(5):
            raw = self._track(self._stream.read(1))
            if not raw:
                if allow_clean_eof and index == 0:
                    return None
                raise DemoFormatError(f"truncated {label} varint", start)
            byte = raw[0]
            if index == 4 and byte > 0x0F:
                raise DemoFormatError(f"{label} varint overflows uint32", start)
            value |= (byte & 0x7F) << (7 * index)
            if byte < 0x80:
                return value
        raise DemoFormatError(f"unterminated {label} varint", start)


class DemoReader:
    """Single-pass streaming command reader with bounded allocations."""

    def __init__(self, stream: BinaryIO, *, file_size: Optional[int] = None,
                 max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES, digest=None):
        if max_frame_bytes <= 0:
            raise ValueError("max_frame_bytes must be positive")
        self._cursor = _Cursor(stream, digest=digest)
        self._max_frame_bytes = max_frame_bytes
        self._started = False
        self.header = parse_demo_header(
            self._cursor.read_exact(HEADER_SIZE, "PBDEMS2 header"), file_size=file_size
        )

    @property
    def offset(self) -> int:
        return self._cursor.offset

    def commands(self, *, read_bodies: bool = True) -> Iterator[DemoCommand]:
        if self._started:
            raise RuntimeError("DemoReader.commands() is a single-pass iterator")
        self._started = True
        while True:
            frame_offset = self.offset
            raw_command = self._cursor.read_uvarint32("command", allow_clean_eof=True)
            if raw_command is None:
                return
            raw_tick = self._cursor.read_uvarint32("tick")
            body_size = self._cursor.read_uvarint32("body size")
            assert raw_tick is not None and body_size is not None
            if body_size > self._max_frame_bytes:
                raise DemoFormatError(
                    f"command body size {body_size} exceeds limit {self._max_frame_bytes}",
                    frame_offset,
                )
            body_offset = self.offset
            if read_bodies:
                body = self._cursor.read_exact(body_size, "command body")
            else:
                self._cursor.skip_exact(body_size, "command body")
                body = None
            tick = raw_tick if raw_tick < 0x80000000 else raw_tick - 0x100000000
            yield DemoCommand(
                offset=frame_offset,
                raw_command=raw_command,
                command_id=raw_command & ~COMPRESSED_FLAG,
                tick=tick,
                body_offset=body_offset,
                body_size=body_size,
                compressed=bool(raw_command & COMPRESSED_FLAG),
                body=body,
            )


def scan_replay_file(path: Union[str, pathlib.Path], *,
                     max_file_bytes: int = 2 * 1024 * 1024 * 1024,
                     max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
                     max_commands: int = DEFAULT_MAX_COMMANDS) -> DemoIndex:
    """Builds a deterministic seek index without retaining command payloads."""
    candidate = pathlib.Path(path).expanduser().resolve()
    try:
        stat = candidate.stat()
    except OSError as exc:
        raise DemoFormatError(f"replay file is not readable: {candidate}", 0) from exc
    if not candidate.is_file():
        raise DemoFormatError(f"replay path is not a regular file: {candidate}", 0)
    if max_file_bytes <= 0 or max_commands <= 0:
        raise ValueError("scan limits must be positive")
    if stat.st_size > max_file_bytes:
        raise DemoFormatError(
            f"replay size {stat.st_size} exceeds limit {max_file_bytes}", 0
        )

    digest = hashlib.sha256()
    counts: Dict[int, int] = {}
    unknown: Dict[int, int] = {}
    full_packets = []
    first_tick = last_tick = None
    ticks = set()
    playback_offset = None
    compressed_count = 0
    command_count = 0
    file_info_target_seen = False
    spawn_groups_target_seen = False

    try:
        with candidate.open("rb") as stream:
            reader = DemoReader(stream, file_size=stat.st_size,
                                max_frame_bytes=max_frame_bytes, digest=digest)
            for command in reader.commands(read_bodies=False):
                command_count += 1
                if command_count > max_commands:
                    raise DemoFormatError(
                        f"command count exceeds limit {max_commands}", command.offset
                    )
                counts[command.command_id] = counts.get(command.command_id, 0) + 1
                if command.command_id not in COMMAND_NAMES:
                    unknown[command.command_id] = unknown.get(command.command_id, 0) + 1
                if command.compressed:
                    compressed_count += 1
                if command.tick >= 0:
                    first_tick = (command.tick if first_tick is None
                                  else min(first_tick, command.tick))
                    last_tick = (command.tick if last_tick is None
                                 else max(last_tick, command.tick))
                    ticks.add(command.tick)
                if playback_offset is None and command.command_id == DEM_SYNC_TICK:
                    playback_offset = command.end_offset
                if command.command_id == DEM_FULL_PACKET:
                    full_packets.append(CommandPosition(command.offset, command.tick))
                if command.offset == reader.header.file_info_offset:
                    file_info_target_seen = command.command_id == DEM_FILE_INFO
                if command.offset == reader.header.spawn_groups_offset:
                    spawn_groups_target_seen = command.command_id == DEM_SPAWN_GROUPS
            header = reader.header
    except DemoFormatError:
        raise
    except OSError as exc:
        raise DemoFormatError(f"could not read replay: {candidate}", 0) from exc

    if header.file_info_offset and not file_info_target_seen:
        raise DemoFormatError(
            "DEM_FileInfo header offset does not point to a DEM_FileInfo command",
            header.file_info_offset,
        )
    if header.spawn_groups_offset and not spawn_groups_target_seen:
        raise DemoFormatError(
            "DEM_SpawnGroups header offset does not point to a DEM_SpawnGroups command",
            header.spawn_groups_offset,
        )

    return DemoIndex(
        path=candidate,
        file_size=stat.st_size,
        content_sha256=digest.hexdigest(),
        header=header,
        command_count=command_count,
        compressed_command_count=compressed_count,
        first_tick=first_tick,
        last_tick=last_tick,
        distinct_tick_count=len(ticks),
        playback_offset=playback_offset,
        full_packets=tuple(full_packets),
        command_counts=MappingProxyType(dict(sorted(counts.items()))),
        unknown_command_counts=MappingProxyType(dict(sorted(unknown.items()))),
    )

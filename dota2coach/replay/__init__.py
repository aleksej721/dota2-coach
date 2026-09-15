"""Canonical Replay Intelligence contracts.

Low-level decoders are adapters into this package. Product code queries this
store and never depends on Manta, Clarity or raw protobuf names directly.
"""

from .contracts import (Checkpoint, Event, Provenance, ReplayManifest, ReplayQuery,
                        ReplaySlice, StateDelta, TruthLevel)
from .ingest import ReplayFileInfo, ReplayInputError, inspect_replay_file
from .framing import (COMMAND_NAMES, COMPRESSED_FLAG, DemoCommand, DemoFormatError,
                      DemoHeader, DemoIndex, DemoReader, scan_replay_file)
from .store import CanonicalReplayStore

__all__ = [
    "CanonicalReplayStore",
    "COMMAND_NAMES",
    "COMPRESSED_FLAG",
    "Checkpoint",
    "Event",
    "DemoCommand",
    "DemoFormatError",
    "DemoHeader",
    "DemoIndex",
    "DemoReader",
    "Provenance",
    "ReplayManifest",
    "ReplayFileInfo",
    "ReplayInputError",
    "ReplayQuery",
    "ReplaySlice",
    "StateDelta",
    "TruthLevel",
    "inspect_replay_file",
    "scan_replay_file",
]

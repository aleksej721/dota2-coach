"""Canonical Replay Intelligence contracts.

Low-level decoders are adapters into this package. Product code queries this
store and never depends on Manta, Clarity or raw protobuf names directly.
"""

from .contracts import (Checkpoint, Event, Provenance, ReplayManifest, ReplayQuery,
                        ReplaySlice, StateDelta, TruthLevel)
from .store import CanonicalReplayStore

__all__ = [
    "CanonicalReplayStore",
    "Checkpoint",
    "Event",
    "Provenance",
    "ReplayManifest",
    "ReplayQuery",
    "ReplaySlice",
    "StateDelta",
    "TruthLevel",
]

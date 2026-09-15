"""Versioned, decoder-independent contracts for precise replay facts.

Every timestamp is an integer number of milliseconds on the Dota game clock.
It may be negative during pre-game. Ticks are retained as source coordinates;
game time is the user-facing coordinate and must be pause-aware in the decoder.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Mapping, Optional


REPLAY_SCHEMA_VERSION = 1


class TruthLevel(str, Enum):
    """How directly a fact is supported by the replay."""

    OBSERVED = "observed"
    DERIVED = "derived"
    INFERRED = "inferred"


@dataclass(frozen=True)
class Provenance:
    """Exact origin of a canonical fact for debugging and evidence links."""

    decoder: str
    source_kind: str
    source_tick: int
    source_field: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.decoder.strip() or not self.source_kind.strip():
            raise ValueError("decoder and source_kind must be non-empty")
        if self.source_tick < 0:
            raise ValueError("source_tick must be non-negative")


@dataclass(frozen=True)
class ReplayManifest:
    """Identity and compatibility metadata for one ingested replay."""

    content_sha256: str
    file_size: int
    decoder: str
    decoder_version: str
    game_build: int
    tick_rate: float
    first_tick: int
    last_tick: int
    match_id: Optional[int] = None
    schema_version: int = REPLAY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        digest = self.content_sha256.lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("content_sha256 must be a 64-character hex digest")
        if self.file_size < 0 or self.tick_rate <= 0:
            raise ValueError("file_size must be non-negative and tick_rate must be positive")
        if self.first_tick < 0 or self.last_tick < self.first_tick:
            raise ValueError("invalid tick range")
        if self.schema_version != REPLAY_SCHEMA_VERSION:
            raise ValueError("unsupported replay schema version")


@dataclass(frozen=True)
class StateDelta:
    """Changed fields for one entity at one source tick."""

    tick: int
    game_time_ms: int
    entity_id: int
    fields: Mapping[str, Any] = field(default_factory=dict)
    deleted: bool = False
    truth: TruthLevel = TruthLevel.OBSERVED
    provenance: Optional[Provenance] = None

    def __post_init__(self) -> None:
        if self.tick < 0 or self.entity_id < 0:
            raise ValueError("tick and entity_id must be non-negative")
        if not self.deleted and not self.fields:
            raise ValueError("an upsert delta must contain at least one field")


@dataclass(frozen=True)
class Event:
    """Discrete replay event such as cast, damage, death, order or purchase."""

    event_id: str
    tick: int
    game_time_ms: int
    kind: str
    actor_id: Optional[int] = None
    target_id: Optional[int] = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    truth: TruthLevel = TruthLevel.OBSERVED
    provenance: Optional[Provenance] = None

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.kind.strip():
            raise ValueError("event_id and kind must be non-empty")
        if self.tick < 0:
            raise ValueError("tick must be non-negative")
        if self.actor_id is not None and self.actor_id < 0:
            raise ValueError("actor_id must be non-negative")
        if self.target_id is not None and self.target_id < 0:
            raise ValueError("target_id must be non-negative")


@dataclass(frozen=True)
class Checkpoint:
    """Materialized entity state used to bound random-access reconstruction."""

    tick: int
    game_time_ms: int
    entities: Mapping[int, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ValueError("tick must be non-negative")
        if any(entity_id < 0 for entity_id in self.entities):
            raise ValueError("entity ids must be non-negative")


@dataclass(frozen=True)
class ReplayQuery:
    """A bounded query; empty filters mean all kinds/entities/fields."""

    start_ms: int
    end_ms: int
    event_kinds: FrozenSet[str] = frozenset()
    entity_ids: FrozenSet[int] = frozenset()
    fields: FrozenSet[str] = frozenset()
    include_events: bool = True
    include_deltas: bool = True

    def __post_init__(self) -> None:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be greater than or equal to start_ms")
        if any(entity_id < 0 for entity_id in self.entity_ids):
            raise ValueError("entity ids must be non-negative")


@dataclass(frozen=True)
class ReplaySlice:
    """Deterministic answer returned by a time-range query."""

    schema_version: int
    start_ms: int
    end_ms: int
    state_at_start: Mapping[int, Mapping[str, Any]]
    deltas: List[StateDelta]
    events: List[Event]


def to_wire(value: Any) -> Any:
    """Recursively converts contracts to a JSON-serializable representation."""
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return to_wire(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_wire(item) for item in value]
    return value

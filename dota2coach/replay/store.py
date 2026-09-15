"""Indexed in-memory reference implementation of the canonical replay store.

This is the correctness oracle for decoder experiments, not the final large-file
encoding. It already provides logarithmic time-window lookup and bounded state
reconstruction from checkpoints. A later binary/columnar backend must preserve
the same observable query behaviour.
"""

import copy
from bisect import bisect_left, bisect_right
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .contracts import (REPLAY_SCHEMA_VERSION, Checkpoint, Event, ReplayManifest,
                        ReplayQuery, ReplaySlice, StateDelta)


SortKey = Tuple[int, int]


class CanonicalReplayStore:
    """Append-only replay facts with deterministic time-range queries."""

    def __init__(self, manifest: ReplayManifest):
        self.manifest = manifest
        self._deltas: List[StateDelta] = []
        self._delta_keys: List[SortKey] = []
        self._events: List[Event] = []
        self._event_keys: List[SortKey] = []
        self._checkpoints: List[Checkpoint] = []
        self._checkpoint_keys: List[SortKey] = []
        self._event_ids = set()

    @staticmethod
    def _key(game_time_ms: int, tick: int) -> SortKey:
        return game_time_ms, tick

    @staticmethod
    def _append_monotonic(keys: List[SortKey], key: SortKey, label: str) -> None:
        if keys and key < keys[-1]:
            raise ValueError(f"{label} must be appended in game-time/tick order")
        keys.append(key)

    def _validate_tick(self, tick: int) -> None:
        if tick < self.manifest.first_tick or tick > self.manifest.last_tick:
            raise ValueError(
                f"tick {tick} is outside manifest range "
                f"[{self.manifest.first_tick}, {self.manifest.last_tick}]"
            )

    def append_delta(self, delta: StateDelta) -> None:
        self._validate_tick(delta.tick)
        key = self._key(delta.game_time_ms, delta.tick)
        self._append_monotonic(self._delta_keys, key, "state deltas")
        self._deltas.append(delta)

    def append_event(self, event: Event) -> None:
        self._validate_tick(event.tick)
        if event.event_id in self._event_ids:
            raise ValueError(f"duplicate event_id: {event.event_id}")
        key = self._key(event.game_time_ms, event.tick)
        self._append_monotonic(self._event_keys, key, "events")
        self._events.append(event)
        self._event_ids.add(event.event_id)

    def append_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._validate_tick(checkpoint.tick)
        key = self._key(checkpoint.game_time_ms, checkpoint.tick)
        self._append_monotonic(self._checkpoint_keys, key, "checkpoints")
        self._checkpoints.append(checkpoint)

    def extend_deltas(self, deltas: Iterable[StateDelta]) -> None:
        for delta in deltas:
            self.append_delta(delta)

    def extend_events(self, events: Iterable[Event]) -> None:
        for event in events:
            self.append_event(event)

    def _checkpoint_before(self, game_time_ms: int) -> Optional[Checkpoint]:
        at = bisect_right(self._checkpoint_keys, (game_time_ms, self.manifest.last_tick)) - 1
        return self._checkpoints[at] if at >= 0 else None

    def state_at(self, game_time_ms: int,
                 entity_ids: Iterable[int] = ()) -> Dict[int, Dict[str, Any]]:
        """Reconstructs state after all deltas at or before ``game_time_ms``."""
        selected = frozenset(entity_ids)
        checkpoint = self._checkpoint_before(game_time_ms)
        if checkpoint is None:
            state: Dict[int, Dict[str, Any]] = {}
            lower = 0
            checkpoint_key = None
        else:
            state = {
                int(entity_id): copy.deepcopy(dict(fields))
                for entity_id, fields in checkpoint.entities.items()
                if not selected or int(entity_id) in selected
            }
            checkpoint_key = self._key(checkpoint.game_time_ms, checkpoint.tick)
            lower = bisect_left(self._delta_keys, (checkpoint.game_time_ms, 0))

        upper = bisect_right(self._delta_keys, (game_time_ms, self.manifest.last_tick))
        for delta in self._deltas[lower:upper]:
            if checkpoint_key is not None and self._key(delta.game_time_ms, delta.tick) <= checkpoint_key:
                continue
            if selected and delta.entity_id not in selected:
                continue
            if delta.deleted:
                state.pop(delta.entity_id, None)
                continue
            entity = state.setdefault(delta.entity_id, {})
            entity.update(copy.deepcopy(dict(delta.fields)))
        return state

    def query(self, query: ReplayQuery) -> ReplaySlice:
        """Returns facts in a closed ``[start_ms, end_ms]`` interval."""
        state = self.state_at(query.start_ms, query.entity_ids)
        deltas: List[StateDelta] = []
        events: List[Event] = []

        if query.include_deltas:
            start = bisect_left(self._delta_keys, (query.start_ms, 0))
            end = bisect_right(self._delta_keys, (query.end_ms, self.manifest.last_tick))
            for delta in self._deltas[start:end]:
                if query.entity_ids and delta.entity_id not in query.entity_ids:
                    continue
                if query.fields and not delta.deleted:
                    fields = {key: value for key, value in delta.fields.items() if key in query.fields}
                    if not fields:
                        continue
                    delta = StateDelta(
                        tick=delta.tick,
                        game_time_ms=delta.game_time_ms,
                        entity_id=delta.entity_id,
                        fields=fields,
                        deleted=False,
                        truth=delta.truth,
                        provenance=delta.provenance,
                    )
                deltas.append(delta)

        if query.include_events:
            start = bisect_left(self._event_keys, (query.start_ms, 0))
            end = bisect_right(self._event_keys, (query.end_ms, self.manifest.last_tick))
            for event in self._events[start:end]:
                if query.event_kinds and event.kind not in query.event_kinds:
                    continue
                if query.entity_ids and not ({event.actor_id, event.target_id} & query.entity_ids):
                    continue
                events.append(event)

        if query.fields:
            state = {
                entity_id: {key: value for key, value in fields.items() if key in query.fields}
                for entity_id, fields in state.items()
            }

        return ReplaySlice(
            schema_version=REPLAY_SCHEMA_VERSION,
            start_ms=query.start_ms,
            end_ms=query.end_ms,
            state_at_start=state,
            deltas=deltas,
            events=events,
        )

    def counts(self) -> Mapping[str, int]:
        return {
            "deltas": len(self._deltas),
            "events": len(self._events),
            "checkpoints": len(self._checkpoints),
        }

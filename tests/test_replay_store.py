import unittest

from dota2coach.replay import (CanonicalReplayStore, Checkpoint, Event, Provenance,
                               ReplayManifest, ReplayQuery, StateDelta, TruthLevel)
from dota2coach.replay.contracts import to_wire


def manifest():
    return ReplayManifest(
        content_sha256="a" * 64,
        file_size=1024,
        decoder="fixture",
        decoder_version="1",
        game_build=9999,
        tick_rate=30.0,
        first_tick=100,
        last_tick=1000,
        match_id=42,
    )


class ReplayStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = CanonicalReplayStore(manifest())
        provenance = Provenance("fixture", "packet_entities", 100, "position")
        self.store.append_checkpoint(Checkpoint(
            tick=100,
            game_time_ms=0,
            entities={1: {"hero": "faceless_void", "x": 100.0, "hp": 700},
                      2: {"hero": "templar_assassin", "x": 500.0, "hp": 900}},
        ))
        self.store.extend_deltas([
            StateDelta(130, 1000, 1, {"x": 140.0}, provenance=provenance),
            StateDelta(160, 2000, 2, {"x": 350.0, "hp": 760}, provenance=provenance),
            StateDelta(190, 3000, 1, {"ability.chronosphere.cooldown_ms": 0},
                       truth=TruthLevel.DERIVED),
            StateDelta(220, 4000, 2, {}, deleted=True),
        ])
        self.store.extend_events([
            Event("cast-1", 191, 3010, "ability_cast", actor_id=1,
                  payload={"ability": "chronosphere", "x": 145.0}),
            Event("damage-1", 200, 3500, "damage", actor_id=2, target_id=1,
                  payload={"amount": 220}),
        ])

    def test_state_reconstruction_uses_checkpoint_and_deltas(self):
        state = self.store.state_at(2500)
        self.assertEqual(140.0, state[1]["x"])
        self.assertEqual(350.0, state[2]["x"])
        self.assertEqual(760, state[2]["hp"])
        self.assertNotIn("ability.chronosphere.cooldown_ms", state[1])
        self.assertNotIn(2, self.store.state_at(4500))

    def test_query_filters_time_entities_kinds_and_fields(self):
        result = self.store.query(ReplayQuery(
            start_ms=1500,
            end_ms=3600,
            event_kinds=frozenset({"ability_cast"}),
            entity_ids=frozenset({1}),
            fields=frozenset({"x", "ability.chronosphere.cooldown_ms"}),
        ))
        self.assertEqual({1}, set(result.state_at_start))
        self.assertEqual({"x": 140.0}, result.state_at_start[1])
        self.assertEqual(["ability.chronosphere.cooldown_ms"],
                         list(result.deltas[0].fields))
        self.assertEqual(["cast-1"], [event.event_id for event in result.events])

    def test_contracts_are_json_ready_and_truth_is_explicit(self):
        result = self.store.query(ReplayQuery(3000, 3100))
        wire = to_wire(result)
        self.assertEqual(1, wire["schema_version"])
        self.assertEqual("derived", wire["deltas"][0]["truth"])

    def test_rejects_non_monotonic_and_duplicate_input(self):
        with self.assertRaises(ValueError):
            self.store.append_delta(StateDelta(1, -100, 1, {"x": 0}))
        with self.assertRaises(ValueError):
            self.store.append_event(Event("cast-1", 300, 5000, "ability_cast"))


if __name__ == "__main__":
    unittest.main()

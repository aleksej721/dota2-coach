"""Фазы пиков рангового All Pick: кого игрок видел в момент выбора.

Запуск: python -m unittest tests/test_draft_phases.py
"""

import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dota2coach.features import FeatureExtractor  # noqa: E402


def picks(sequence):
    """«RDDRRDDRDR» → пики в порядке подтверждения, герой = сторона + номер."""
    return [{"order": i, "is_pick": True, "side": "Radiant" if c == "R" else "Dire",
             "hero": f"{c}{i}"} for i, c in enumerate(sequence)]


def me(hero, radiant):
    return SimpleNamespace(hero_name=hero, is_radiant=radiant)


class DraftPhasesTest(unittest.TestCase):
    def phased(self, sequence):
        rows = picks(sequence)
        self.assertTrue(FeatureExtractor._assign_phases(rows))
        return rows

    def test_phases_are_blocks_of_four_four_two(self):
        rows = self.phased("RDDRDRRDDR")   # матч 9019547886
        self.assertEqual([r["phase"] for r in rows], [1, 1, 1, 1, 2, 2, 2, 2, 3, 3])

    def test_second_phase_sees_only_first_phase_enemies(self):
        rows = self.phased("RDDRDRRDDR")
        # Dire D7 выбирал во второй фазе: видел R0 и R3, R5/R6 выбирались вслепую
        # одновременно с ним, R9 — ласт-пик, уже видевший его.
        my = FeatureExtractor._my_pick(None, rows, me("D7", radiant=False), phased=True)
        self.assertEqual(my["phase"], 2)
        self.assertEqual(my["team_order"], 4)
        self.assertEqual(my["enemies_visible"], ["R0", "R3"])
        self.assertEqual(my["enemies_blind"], ["R5", "R6"])
        self.assertEqual(my["enemies_after"], ["R9"])
        self.assertEqual(my["allies_before"], ["D1", "D2", "D4"])

    def test_first_phase_is_blind_and_last_pick_sees_four(self):
        rows = self.phased("RDDRDRRDDR")
        first = FeatureExtractor._my_pick(None, rows, me("R0", radiant=True), phased=True)
        self.assertEqual(first["enemies_visible"], [])
        last = FeatureExtractor._my_pick(None, rows, me("R9", radiant=True), phased=True)
        self.assertEqual(last["phase"], 3)
        self.assertEqual(len(last["enemies_visible"]), 4)
        self.assertEqual(last["enemies_blind"], ["D8"])
        self.assertEqual(last["enemies_after"], [])

    def test_no_phases_when_blocks_do_not_fit(self):
        self.assertFalse(FeatureExtractor._assign_phases(picks("RRRRDDDDRD")))
        self.assertFalse(FeatureExtractor._assign_phases(picks("RDRRDRRDDRD")))  # 11 пиков

    def test_strict_queue_without_phases(self):
        rows = picks("RDRDRDRDRD")
        my = FeatureExtractor._my_pick(None, rows, me("D3", radiant=False), phased=False)
        self.assertEqual(my["enemies_before"], ["R0", "R2"])
        self.assertEqual(my["enemies_after"], ["R4", "R6", "R8"])


if __name__ == "__main__":
    unittest.main()

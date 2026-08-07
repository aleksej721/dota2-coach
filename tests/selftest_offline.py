"""Офлайн-проверка расширенного конвейера БЕЗ сети.

Синтетический «сырой» ответ OpenDota (с новыми полями: benchmarks, abilities,
combat-счётчики, lane_efficiency, teamfights, permanent_buffs) прогоняем через
normalize -> FeatureExtractor -> BundleBuilder и печатаем итоговый промпт.

Запуск из корня проекта:  python tests/selftest_offline.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dota2coach import normalize
from dota2coach.bundle import BundleBuilder
from dota2coach.constants import Constants  # заглушка: fallback-имена, без сети
from dota2coach.features import FeatureExtractor


def _bench(raw, pct):
    return {"raw": raw, "pct": pct}


def player(slot, hero_id, lane_role, nw, **extra):
    base = {
        "player_slot": slot, "hero_id": hero_id, "lane_role": lane_role, "is_roaming": False,
        "level": 25, "kills": 8, "deaths": 3, "assists": 6, "last_hits": 206, "denies": 12,
        "gold_per_min": 640, "xp_per_min": 700, "net_worth": nw, "hero_damage": 25000,
        "tower_damage": 8000, "hero_healing": 0, "damage_taken": {"a": 12000, "b": 8000},
        "gold_t": [0, 300, 700, 1200, 1700, 2300, 2900, 3600, 4300, 5100, nw],
        "xp_t": [0, 250, 600, 1100, 1600, 2200, 2800, 3500, 4300, 5200, 6100],
        "lh_t": [0, 4, 10, 18, 27, 36, 45, 55, 66, 78, 90],
        "dn_t": [0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11],
        "purchase_log": [{"time": 356, "key": "phase_boots"}, {"time": 805, "key": "echo_sabre"}],
        "ability_upgrades_arr": [5001, 5002, 5001, 5003, 5001, 5004],
        "permanent_buffs": [], "kills_log": [], "kill_streaks": {"3": 1}, "multi_kills": {"2": 1},
        "stuns": 12.5, "max_hero_hit": {"value": 848, "key": "npc_dota_hero_lion"},
        "damage": {"npc_dota_hero_lion": 9000, "npc_dota_hero_axe": 4000},
        "camps_stacked": 2, "creeps_stacked": 5, "rune_pickups": 6, "obs_placed": 0,
        "sen_placed": 0, "buyback_count": 1, "pings": 14, "actions_per_min": 320,
        "life_state": {"0": 1955, "1": 38, "2": 180}, "neutral_kills": 40, "ancient_kills": 6,
        "tower_kills": 3, "roshan_kills": 1, "courier_kills": 0, "observer_kills": 1,
        "sentry_kills": 2, "lane_efficiency_pct": 88,
        "benchmarks": {
            "gold_per_min": _bench(640, 0.91), "xp_per_min": _bench(700, 0.88),
            "last_hits_per_min": _bench(6.4, 0.79), "hero_damage_per_min": _bench(600, 0.72),
            "tower_damage": _bench(8000, 0.85),
        },
    }
    base.update(extra)
    return base


def fake_raw():
    me = player(0, 5, 2, 6000, kills=8, deaths=3, assists=6,
                kills_log=[{"time": 210, "key": "npc_dota_hero_lion"},
                           {"time": 540, "key": "npc_dota_hero_axe"}])
    ally = player(1, 1, 1, 4000, kills=2, deaths=5, assists=9, obs_placed=12, sen_placed=8,
                  permanent_buffs=[{"permanent_buff": 5, "stack_count": 24}])
    enemy = player(128, 2, 3, 3500, kills=4, deaths=4, assists=3,
                   kills_log=[{"time": 330, "key": "npc_dota_hero_5"}])  # «убил меня»
    return {
        "match_id": 8927853552, "duration": 2491, "game_mode": 22, "lobby_type": 7,
        "patch": 57, "version": 22, "region": 3, "radiant_win": True,
        "radiant_gold_adv": [0, 100, 250, 500, 400, 700, 900, 1200, 1500, 1800, 2200],
        "radiant_xp_adv": [0, 80, 200, 350, 300, 600, 800, 1000, 1300, 1600, 2000],
        "picks_bans": [],  # All Pick — стадий драфта нет (проверяем honest-ветку)
        "objectives": [
            {"type": "CHAT_MESSAGE_FIRSTBLOOD", "time": 92},
            {"type": "building_kill", "time": 640, "key": "npc_dota_badguys_tower1_mid"},
            {"type": "CHAT_MESSAGE_ROSHAN_KILL", "time": 1180, "team": 2},
        ],
        "teamfights": [
            {"start": 520, "end": 560, "deaths": 3,
             "players": [{"gold_delta": 400, "xp_delta": 300, "deaths": 0, "damage": 1500, "healing": 0},
                         {"gold_delta": -150, "xp_delta": -100, "deaths": 1, "damage": 200, "healing": 0},
                         {"gold_delta": -100, "xp_delta": -80, "deaths": 1, "damage": 500, "healing": 0}]},
        ],
        "players": [me, ally, enemy],
    }


def main():
    constants = Constants()  # имена станут hero_5, ability_5001 и т.п. — это ок для теста
    match = normalize.from_opendota(fake_raw(), constants)

    assert match.parsed is True
    me = next(p for p in match.players if p.player_slot == 0)
    assert "mid" in me.position_label
    assert me.win is True
    assert me.lane_efficiency_pct == 88
    assert me.seconds_dead == 180

    features = FeatureExtractor(constants).extract(match, me, depth="deep")
    assert features.meta["result"] == "ПОБЕДА"
    assert len(features.scoreboard) == 3
    assert len(features.laning["cs_by_min"]) == 10
    assert len(features.objectives) == 3
    assert any(b["buffs"] for b in features.buffs)  # у союзника есть стак

    text = BundleBuilder().build(features, depth="deep")
    for marker in ["## СКОРБОРД", "## БЕНЧМАРКИ", "## НЕТВОРТ", "## РАСКАЧКА",
                   "## ЛАЙНИНГ", "## ТИМФАЙТЫ", "## ПОСТОЯННЫЕ БАФФЫ"]:
        assert marker in text, f"нет секции {marker}"

    print("OK: расширенный офлайн-конвейер отработал. Промпт (--depth deep):\n")
    print(text)


if __name__ == "__main__":
    main()

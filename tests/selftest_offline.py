"""Офлайн-проверка расширенного конвейера БЕЗ сети.

Синтетический «сырой» ответ OpenDota (с новыми полями: benchmarks, abilities,
combat-счётчики, lane_efficiency, teamfights, permanent_buffs) прогоняем через
normalize -> FeatureExtractor -> BundleBuilder и печатаем итоговый промпт.

Запуск из корня проекта:  python tests/selftest_offline.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dota2coach import i18n, normalize
from dota2coach.bundle import BundleBuilder
from dota2coach.constants import Constants, strip_loc_tokens  # заглушка: без сети
from dota2coach.features import FeatureExtractor
from dota2coach.policy import FOCUSES, ROLES, ROLE_FOCUSES, Policy
from dota2coach.render import resolve_depth


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
        "purchase_log": [{"time": 356, "key": "phase_boots"},
                         {"time": 805, "key": "echo_sabre"},
                         {"time": 1200, "key": "glimmer_cape"}],
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
                   # stack_count = 0 — это «есть аганим/шард», такие записи фильтруем
                   permanent_buffs=[{"permanent_buff": 12, "stack_count": 0}],
                   kills_log=[{"time": 330, "key": "npc_dota_hero_5"},
                              {"time": 2450, "key": "npc_dota_hero_5"}])  # включая late death
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


def check_loc_tokens():
    """Токены локализации талантов должны срезаться, а живой текст — уцелеть."""
    cases = {
        "+{s:bonus_rot_slow}% Rot Slow": "Rot Slow",
        "-{s:bonus_AbilityCooldown}s Meat Hook Cooldown": "Meat Hook Cooldown",
        "{s:bonus_radius_explosion} AoE Laser": "AoE Laser",
        "+8% Spell Lifesteal": "+8% Spell Lifesteal",   # значение есть — не трогаем
        "+175 Health": "+175 Health",
    }
    for raw, expected in cases.items():
        got = strip_loc_tokens(raw)
        assert got == expected, f"{raw!r} -> {got!r}, ожидалось {expected!r}"
    # Слово, начинающееся на 's', не должно потерять первую букву.
    assert strip_loc_tokens("+{s:bonus_x} slow duration") == "slow duration"


def check_draft_grouping(match):
    """All Pick: если пики и баны сгруппированы, честно это признаём."""
    assert match.draft_is_chronological is False, "пустой драфт не хронологичен"


class ItemAwareConstants(Constants):
    """Минимальный справочник предметов — чтобы проверить поглощение компонентов."""

    _ITEMS = {
        "boots":        {"cost": 500, "components": [], "consumable": False},
        "gloves":       {"cost": 450, "components": [], "consumable": False},
        "belt":         {"cost": 450, "components": [], "consumable": False},
        "power_treads": {"cost": 1400, "components": ["boots", "gloves", "belt"],
                         "consumable": False},
        "tango":        {"cost": 90, "components": [], "consumable": True},
    }

    def item_cost(self, key):
        return self._ITEMS.get(key, {}).get("cost", 0)

    def item_components(self, key):
        return list(self._ITEMS.get(key, {}).get("components", []))

    def item_is_consumable(self, key):
        return self._ITEMS.get(key, {}).get("consumable", False)


class OfflineConstants(Constants):
    """Заглушка с обратимым npc-именем героя для проверки таймингов смертей."""

    def hero_npc(self, hero_id):
        return f"npc_dota_hero_{hero_id}" if hero_id else None


def check_item_absorption():
    """Компоненты, ушедшие в сборку, и расходники не должны попадать в тайминги."""
    from dota2coach.model import Player

    p = Player(account_id=None, player_slot=0, is_radiant=True, win=True,
               hero_id=1, hero_name="test")
    p.purchase_log = [
        {"time": 0, "key": "tango"}, {"time": 60, "key": "boots"},
        {"time": 120, "key": "gloves"}, {"time": 180, "key": "belt"},
        {"time": 240, "key": "power_treads"}, {"time": 300, "key": "recipe_nothing"},
    ]
    rows = FeatureExtractor(ItemAwareConstants())._assembled_purchases(p, min_cost=1000)
    assert [r["item"] for r in rows] == ["power_treads"], rows
    assert rows[0]["time"] == "4:00", rows


def check_scaffold(match, me, extractor, builder, quick_text):
    """Заметка игрока: свой блок, приоритет в правилах, раздел 0 в формате ответа."""
    noted = Policy(depth="quick", focus="full", note="  почему я слил лайн?  ",
                   mmr="Legend 3500")
    assert noted.note == "почему я слил лайн?", "заметка должна обрезаться по краям"
    text = builder.build(extractor.extract(match, me, noted), noted)

    assert "## ГЛАВНЫЙ ЗАПРОС ИГРОКА" in text
    assert text.index("## ГЛАВНЫЙ ЗАПРОС ИГРОКА") < text.index("## ФОРМАТ ОТВЕТА")
    assert "### 0. Ответ на главный запрос" in text
    assert "главный приоритет" in text
    assert "Legend 3500" in text, "уровень игрока не доехал до калибровки"
    assert "ВАЖНО:" in text.split("## МЕТА")[0], "нет указателя в шапке"
    # Заметка не должна стоять в одном ряду с генеричными вопросами.
    assert "1. почему я слил лайн?" not in text

    # Guardrails и структура ответа обязаны быть в промпте всегда.
    for marker in ["## КАК ГОТОВИТЬ РАЗБОР", "ЗАПРЕЩЕНЫ общие советы",
                   "### 1. Вердикт", "### 3. Главный leak", "### 6. Куда копать дальше"]:
        assert marker in quick_text, f"нет блока {marker}"
    assert "### 0." not in quick_text, "без заметки раздела 0 быть не должно"

    # Пустая заметка = отсутствие заметки, поведение не меняется.
    blank = Policy(depth="quick", focus="full", note="   ")
    assert blank.has_note is False
    assert builder.build(extractor.extract(match, me, blank), blank) == quick_text


def check_models(match, me, extractor, builder):
    """Упаковка меняется, содержание — нет."""
    md = Policy(depth="quick", model="chatgpt")
    xml = Policy(depth="quick", model="claude")
    md_text = builder.build(extractor.extract(match, me, md), md)
    xml_text = builder.build(extractor.extract(match, me, xml), xml)

    for tag in ["<role>", "</role>", "<match_data>", "</match_data>",
                "<method>", "<output_format>", "<data_limitations>"]:
        assert tag in xml_text, f"нет тега {tag}"
    assert "<role>" not in md_text, "markdown-версия не должна содержать теги"
    # Данные внутри тегов те же: сверяем строку скорборда.
    row = [ln for ln in md_text.splitlines() if ln.startswith("  ★ ")][0]
    assert row in xml_text, "данные разъехались между упаковками"

    assert resolve_depth(None, "claude") == "deep"
    assert resolve_depth(None, "chatgpt") == "quick"
    assert resolve_depth("quick", "claude") == "quick", "явный --depth должен побеждать"


def check_languages(match, me, extractor, builder):
    """Язык переключает весь промпт, а не только инструкцию."""
    assert i18n.missing_keys() == {}, "переводы разъехались, см. i18n.missing_keys()"

    for lang, marker, answer in (("ru", "## МЕТА", "Отвечай на русском языке."),
                                 ("en", "## META", "Answer in English."),
                                 ("uk", "## МЕТА", "Відповідай українській мовою.")):
        p = Policy(depth="quick", lang=lang)
        text = builder.build(extractor.extract(match, me, p), p)
        assert marker in text, f"{lang}: нет секции {marker}"
        assert answer in text, f"{lang}: нет инструкции про язык ответа"
        assert "[" + "sec.meta" + "?]" not in text, f"{lang}: непереведённый ключ"

    en = Policy(depth="deep", lang="en")
    en_text = builder.build(extractor.extract(match, me, en), en)
    for russian in ["Матч ", "погибли", "нейтралы", "поз. 1 — carry"]:
        assert russian not in en_text, f"в английский промпт утекло: {russian}"


def check_roles_and_focuses(match, me, extractor, builder):
    """Роль меняет и доказательства, и методику, не мутируя Match."""
    assert ROLES == ("1", "2", "3", "4", "5")
    assert {"vision", "tempo", "initiation", "enable"} <= set(FOCUSES)
    assert "farm" not in ROLE_FOCUSES["4"] and "farm" not in ROLE_FOCUSES["5"]

    original_position = me.position_key
    carry = Policy(depth="quick", focus="full", role="1")
    support = Policy(depth="quick", focus="enable", role="5")
    carry_features = extractor.extract(match, me, carry)
    support_features = extractor.extract(match, me, support)
    carry_text = builder.build(carry_features, carry)
    support_text = builder.build(support_features, support)

    assert me.position_key == original_position == "2", "override не должен мутировать Match"
    assert carry_features.meta["position_key"] == "1"
    assert support_features.meta["position_key"] == "5"

    carry_metrics = {x["key"] for x in carry_features.role_impact["metrics"]}
    support_metrics = {x["key"] for x in support_features.role_impact["metrics"]}
    assert {"cs10", "gpm", "networth"} <= carry_metrics
    assert not {"cs10", "gpm", "networth"} & support_metrics
    assert {"wards", "assists", "camps_stacked", "healing"} <= support_metrics

    assert "Оценивай игрока как Pos 1 Carry" in carry_text
    assert "Смерти после 40:00" in carry_text and "40:50" in carry_text
    assert "Оценивай игрока как Pos 5 Hard Support" in support_text
    assert "Фарм нерелевантен" in support_text
    assert "CS@10 ≥" not in support_text
    assert "Glimmer Cape" in support_text or "glimmer_cape" in support_text
    assert "не даёт надёжного счётчика сейвов" in support_text

    # У ★ support-бенчмарки не поднимают last hits/GPM как критерий успеха.
    own_bench = {x["metric"] for x in support_features.benchmarks[0]["rows"]}
    assert "last_hits_per_min" not in own_bench and "gold_per_min" not in own_bench

    auto = Policy().resolve_role("2")
    assert auto.role == "2" and auto.role_source == "heuristic"
    selected = Policy(role="5").resolve_role("2")
    assert selected.role == "5" and selected.role_source == "selected"

    for focus in ("vision", "tempo", "initiation", "enable"):
        p = Policy(depth="quick", focus=focus, role="4")
        text = builder.build(extractor.extract(match, me, p), p)
        assert f"focus={focus}" in text

    for lang, marker in (("ru", "Pos 3 Offlane"), ("en", "Evaluate the player as Pos 3"),
                         ("uk", "Оцінюй гравця як Pos 3")):
        p = Policy(depth="quick", role="3", lang=lang)
        text = builder.build(extractor.extract(match, me, p), p)
        assert marker in text, f"{lang}: role scaffold не локализован"


def main():
    constants = OfflineConstants()  # имена станут hero_5, ability_5001 и т.п. — это ок
    match = normalize.from_opendota(fake_raw(), constants)

    assert match.parsed is True
    me = next(p for p in match.players if p.player_slot == 0)
    assert (me.position_key, me.lane_key) == ("2", "mid")
    assert me.win is True
    assert me.lane_efficiency_pct == 88
    assert me.seconds_dead == 180

    check_loc_tokens()
    check_draft_grouping(match)
    check_item_absorption()

    extractor = FeatureExtractor(constants)
    builder = BundleBuilder()

    # quick: только S-тир — тяжёлые секции не должны появиться.
    quick = Policy(depth="quick", focus="full")
    quick_text = builder.build(extractor.extract(match, me, quick), quick)
    assert "## УРОН ПО ГЕРОЯМ" not in quick_text
    assert "## ПОСТОЯННЫЕ БАФФЫ" not in quick_text

    # focus=fights поднимает тимфайты и урон даже в quick и меняет акцент методики.
    fights = Policy(depth="quick", focus="fights")
    fights_text = builder.build(extractor.extract(match, me, fights), fights)
    assert "## УРОН ПО ГЕРОЯМ" in fights_text
    assert "замес" in fights_text

    check_scaffold(match, me, extractor, builder, quick_text)
    check_models(match, me, extractor, builder)
    check_languages(match, me, extractor, builder)
    check_roles_and_focuses(match, me, extractor, builder)

    deep = Policy(depth="deep", focus="full")
    features = extractor.extract(match, me, deep)
    assert features.meta["win"] is True
    assert len(features.scoreboard) == 3
    assert len(features.laning["cs_by_min"]) == 10
    assert len(features.objectives) == 3
    assert any(b["buffs"] for b in features.buffs)  # у союзника есть стак 24
    assert all(x["stacks"] for b in features.buffs for x in b["buffs"])  # нулевых нет

    text = builder.build(features, deep)
    for marker in ["## СКОРБОРД", "## БЕНЧМАРКИ", "## ЭКОНОМИКА", "## РАСКАЧКА",
                   "## ЛАЙНИНГ", "## ТИМФАЙТЫ", "## ПОСТОЯННЫЕ БАФФЫ"]:
        assert marker in text, f"нет секции {marker}"
    assert "{s:" not in text, "в промпт утёк токен локализации"
    # Заглушка Constants не знает имён баффов (buff#5), но фильтр по стакам работает:
    # нулевой buff#12 у врага в промпт не попал.
    assert "×24" in text and "buff#12" not in text

    assert len(quick_text) < len(text), "quick должен быть компактнее deep"

    print(f"OK: офлайн-конвейер отработал. quick={len(quick_text)} симв., "
          f"deep={len(text)} симв.\n")
    print(text)


if __name__ == "__main__":
    main()

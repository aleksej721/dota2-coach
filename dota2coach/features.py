"""FeatureExtractor — из нормализованного Match собирает ОТОБРАННЫЕ факты.

Здесь живёт главный принцип проекта: сигнал > объём. Из OpenDota мы достаём
максимум, но наружу отдаём то, что реально помогает разобрать игру:

  * поминутные ряды прореживаем и дополняем точками перелома;
  * из лога покупок оставляем собранные предметы, поглощая их компоненты;
  * тимфайты сворачиваем до «кто выиграл + мой вклад», если не просили деталей.

Глубину каждой секции диктует Policy — сам экстрактор ничего не решает и не
считает того, что не попадёт в промпт. Оценки «хорошо/плохо» не выносим: это
работа внешней LLM, наше дело — факты и их контекст (перцентили, бенчмарки).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .anomalies import Anomaly, AnomalyDetector
from .constants import Constants
from .model import Match, Player
from .policy import EXPANDED, FULL_LOG, ROLES, Policy

LANE_WINDOW_SEC = 600      # окно лайнинга 0..10 мин
TIMELINE_STEP_MIN = 5      # шаг прореживания поминутных рядов
MAX_SWINGS = 8             # сколько переломов баланса показываем максимум

# Пороги «значимости» покупки (золото). Компоненты и расходники отсекаются
# отдельно, до порога, поэтому здесь речь только о собранных предметах.
KEY_ITEM_COST = 1000       # мои ключевые предметы
MAJOR_ITEM_COST = 2000     # крупные предметы остальных игроков
ALWAYS_KEY_ITEMS = {"aghanims_shard"}  # дешевле порога, но всегда меняет игру

# Метрики бенчмарков OpenDota в порядке вывода. Подписи берутся из i18n
# по ключу bench.<метрика> — здесь только выбор и порядок.
_BENCH_METRICS = (
    "gold_per_min", "xp_per_min", "kills_per_min", "last_hits_per_min",
    "hero_damage_per_min", "hero_healing_per_min", "tower_damage", "stuns_per_min",
)

# Один и тот же percentile имеет разный смысл для разных обязанностей. Здесь
# задаём не оценку, а порядок и состав доказательств, доступных модели.
_ROLE_BENCH_METRICS = {
    "1": ("gold_per_min", "last_hits_per_min", "hero_damage_per_min",
          "tower_damage", "xp_per_min"),
    "2": ("xp_per_min", "kills_per_min", "hero_damage_per_min",
          "gold_per_min", "stuns_per_min"),
    "3": ("stuns_per_min", "hero_damage_per_min", "tower_damage",
          "xp_per_min", "hero_healing_per_min"),
    "4": ("kills_per_min", "stuns_per_min", "hero_healing_per_min",
          "xp_per_min", "hero_damage_per_min"),
    "5": ("hero_healing_per_min", "stuns_per_min", "kills_per_min",
          "xp_per_min", "hero_damage_per_min"),
}

# Purchase log не содержит семантических тегов. Маленький явный набор позволяет
# поднять именно командные/защитные тайминги, не называя любой дорогой предмет
# «utility». Счётчики поставленных вардов идут отдельно и сюда не попадают.
_UTILITY_ITEMS = {
    "arcane_boots", "tranquil_boots", "mekansm", "guardian_greaves",
    "force_staff", "glimmer_cape", "ghost", "euls", "cyclone",
    "lotus_orb", "pipe", "crimson_guard", "holy_locket", "solar_crest",
    "pavise", "drum_of_endurance", "boots_of_bearing", "urn_of_shadows",
    "spirit_vessel", "aether_lens", "blink", "aeon_disk", "rod_of_atos",
    "sheepstick", "orchid", "bloodthorn",
}


@dataclass
class Features:
    meta: Dict[str, Any] = field(default_factory=dict)
    draft: Dict[str, Any] = field(default_factory=dict)
    scoreboard: List[Dict[str, Any]] = field(default_factory=list)
    networth: Dict[str, Any] = field(default_factory=dict)
    items: List[Dict[str, Any]] = field(default_factory=list)
    abilities: List[Dict[str, Any]] = field(default_factory=list)
    benchmarks: List[Dict[str, Any]] = field(default_factory=list)
    laning: Dict[str, Any] = field(default_factory=dict)
    combat: List[Dict[str, Any]] = field(default_factory=list)
    buffs: List[Dict[str, Any]] = field(default_factory=list)
    teamfights: List[Dict[str, Any]] = field(default_factory=list)
    objectives: List[Dict[str, Any]] = field(default_factory=list)
    damage: List[Dict[str, Any]] = field(default_factory=list)
    # Выбранный игроком промежуток под лупой. Пусто, если окно не задано.
    window: Dict[str, Any] = field(default_factory=dict)
    role_impact: Dict[str, Any] = field(default_factory=dict)
    # Картина матча, посчитанная заранее: командный контекст, пары по ролям,
    # источники золота, смерти и тип полученного урона. См. _key_facts.
    facts: Dict[str, Any] = field(default_factory=dict)
    # Статистические отклонения — сырьё для гипотез модели, см. anomalies.py.
    anomalies: List[Anomaly] = field(default_factory=list)
    # Оговорки, которые зависят от того, что мы отфильтровали или чего нет в
    # источнике. Хранятся как (ключ i18n, параметры) — текст соберёт bundle
    # на языке промпта. Печатаются в секции «ОГРАНИЧЕНИЯ ДАННЫХ».
    caveats: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)


def mmss(seconds: Optional[int]) -> str:
    if seconds is None:
        return "?"
    sign = "-" if seconds < 0 else ""
    seconds = abs(int(seconds))
    return f"{sign}{seconds // 60}:{seconds % 60:02d}"


def _at(arr: List[int], idx: int) -> Optional[int]:
    return arr[idx] if 0 <= idx < len(arr) else None


class FeatureExtractor:
    def __init__(self, constants: Constants):
        self._c = constants
        self._anomalies = AnomalyDetector(constants)

    def extract(self, match: Match, me: Player, policy: Policy) -> Features:
        f = Features()
        f.meta = self._meta(match, me, policy)
        f.scoreboard = [self._score_row(p, me) for p in match.players]
        if policy.shows("facts"):
            f.facts = (self._game_facts(match, me, policy) if policy.whole_game
                       else self._key_facts(match, me, policy))

        if policy.shows("anomalies"):
            # min_cost=0: детектору нужна вся сборка, иначе накопленная
            # стоимость поедет и «ожидаемый» тайминг станет фикцией.
            f.anomalies = self._anomalies.detect(
                match, me, self.assembled_purchases(me, min_cost=0))

        if policy.shows("role_impact"):
            f.role_impact = self._role_impact(match, me, policy)
            if policy.role in ("4", "5"):
                f.caveats.append(("caveat.saves_unavailable", {}))

        if policy.shows("draft"):
            f.draft = self._draft(match, me, policy, f.caveats)
        if policy.shows("benchmarks"):
            f.benchmarks = self._benchmarks(match, me, policy)
        if policy.shows("networth"):
            f.networth = self._networth(match, me, policy)
        if policy.shows("items"):
            f.items = self._items(match, me, policy, f.caveats)
        if policy.shows("abilities"):
            f.abilities = self._abilities(match, me, policy, f.caveats)
        if policy.shows("laning"):
            f.laning = self._laning(match, me, policy)
        if policy.shows("combat"):
            f.combat = self._combat(match, me, policy)
        if policy.shows("buffs"):
            f.buffs = self._buffs(match, me)
        if policy.shows("teamfights"):
            f.teamfights = self._teamfights(match, me, policy)
        if policy.shows("objectives"):
            f.objectives = self._objectives(match, policy)
        if policy.shows("damage"):
            f.damage = [self._damage_row(p, me) for p in self._audience(match, me, policy, "damage")]
        if policy.shows("window"):
            f.window = self._window(match, me, policy)
            f.caveats.append(("caveat.window_compressed",
                              {"start": policy.window[0], "end": policy.window[1]}))
        return f

    # --- общие помощники ------------------------------------------------------

    def _tag(self, p: Player, me: Player) -> str:
        # Маркер без букв: метка «я» не должна переводиться вместе с языком промпта,
        # иначе она разъедется с легендой в шапке.
        who = "★ " if p is me else ""
        side = "R" if p.is_radiant else "D"
        return f"{who}[{side}] {p.hero_name}"

    def _short_tag(self, p: Player, me: Player) -> str:
        """Компактная метка для перечислений внутри строки."""
        side = "R" if p.is_radiant else "D"
        return f"{p.hero_name}[{side}]" + ("★" if p is me else "")

    def _audience(self, match: Match, me: Player, policy: Policy, section: str) -> List[Player]:
        """Кого показываем в секции: только меня (сводка) или всех (развёрнуто)."""
        if policy.at_least(section, EXPANDED):
            return list(match.players)
        return [me]

    @staticmethod
    def _effective_role(me: Player, policy: Policy) -> str:
        return policy.role if policy.role in ROLES else me.position_key

    def _position_key(self, p: Player, me: Player, policy: Policy) -> str:
        """Явный --role относится только к ★, не меняя модель матча."""
        return self._effective_role(me, policy) if p is me else p.position_key

    # --- META -----------------------------------------------------------------

    def _meta(self, match: Match, me: Player, policy: Policy) -> Dict[str, Any]:
        return {
            "match_id": match.match_id,
            "patch": match.patch,
            "date": (datetime.fromtimestamp(match.start_time, timezone.utc).strftime("%Y-%m-%d")
                     if match.start_time else None),
            "mode": match.game_mode,
            "lobby": match.lobby_type,
            "duration": mmss(match.duration),
            "win": me.win,
            "my_side": "Radiant" if me.is_radiant else "Dire",
            "winner": "Radiant" if match.radiant_win else "Dire",
            "hero": me.hero_name,
            "position_key": self._effective_role(me, policy),
            "role_source": policy.role_source,
            "lane_key": me.lane_key,
            "level": me.level,
            "kills": me.kills,
            "deaths": me.deaths,
            "assists": me.assists,
            "parsed": match.parsed,
        }

    # --- КАРТИНА МАТЧА (посчитано заранее) -------------------------------------

    # Коды причин изменения золота Valve (EDOTA_ModifyGold_Reason). Отдельно
    # показываем только то, что объясняет «откуда деньги»; остальное — прочее.
    _GOLD_SOURCES = (("13", "creeps"), ("14", "neutrals"), ("12", "heroes"),
                     ("11", "buildings"), ("15", "roshan"), ("17", "runes"))
    _FACT_MINUTES = (10, 20, 30)

    def _key_facts(self, match: Match, me: Player, policy: Policy) -> Dict[str, Any]:
        """Выводы, которые модель раньше угадывала, а теперь получает готовыми.

        Каждый блок закрывает конкретный класс ошибок разбора:
          * пары по ролям и доля в нетворте — «кор перегружен» или «отстал сам»;
          * источники золота — «гонка фарма» по GPM, где смешаны крипы и убийства;
          * смерти и тип полученного урона — советы по BKB вслепую.
        Блок симметричен по командам там, где это возможно, — на нём же строится
        режим разбора игры целиком, без привязки к одному игроку.
        """
        mine = [p for p in match.players if p.is_radiant == me.is_radiant]
        theirs = [p for p in match.players if p.is_radiant != me.is_radiant]
        team_nw = sum(p.net_worth_final for p in mine) or 1
        team_dmg = sum(p.hero_damage for p in mine) or 1
        fights = [(tf.get("start") or 0, tf.get("end") or 0) for tf in match.teamfights]

        def by_position(team: List[Player]) -> Dict[str, Player]:
            out: Dict[str, Player] = {}
            for p in team:
                key = self._position_key(p, me, policy)
                if key in ROLES and key not in out:
                    out[key] = p
            return out

        my_roles, their_roles = by_position(mine), by_position(theirs)
        pairs = []
        for role in ROLES:
            a, b = my_roles.get(role), their_roles.get(role)
            if not a or not b:
                continue
            pairs.append({
                "role": role,
                "mine": self._short_tag(a, me), "theirs": self._short_tag(b, me),
                "earned": [{"m": m, "mine": _at(a.gold_t, m), "theirs": _at(b.gold_t, m)}
                           for m in self._FACT_MINUTES if _at(a.gold_t, m) is not None],
                "nw": [a.net_worth_final, b.net_worth_final],
            })

        my_counterpart = their_roles.get(self._position_key(me, me, policy))
        gold = [self._gold_sources(me, me)]
        if my_counterpart:
            gold.append(self._gold_sources(my_counterpart, me))

        deaths = []
        for d in me.deaths_log:
            when = d.get("time") or 0
            deaths.append({
                "time": mmss(when),
                "killer": self._c.npc_to_hero(d.get("key")) if d.get("key") else None,
                "in_fight": any(lo - 15 <= when <= hi + 15 for lo, hi in fights),
                "dead_for": d.get("time_dead"),
            })

        return {
            "rank": me.rank_tier,
            "party": me.party_size,
            "kills": [sum(p.kills for p in mine), sum(p.kills for p in theirs)],
            "my_deaths": me.deaths,
            "team_deaths": sum(p.deaths for p in mine),
            "nw_share": round(100 * me.net_worth_final / team_nw),
            "dmg_share": round(100 * me.hero_damage / team_dmg),
            "pairs": pairs,
            "gold": gold,
            "deaths": deaths,
            "damage_taken": self._damage_taken(me),
        }

    @staticmethod
    def _took_part(fp: Dict[str, Any]) -> bool:
        """Был ли игрок в драке: урон по героям, смерть или убийство героя.

        gold_delta и healing не годятся: золото набегает и у того, кто фармил на
        другом конце карты, а healing включает обычную регенерацию.
        """
        return bool(fp.get("deaths") or fp.get("damage") or any(
            v for k, v in (fp.get("killed") or {}).items()
            if str(k).startswith("npc_dota_hero_")))

    def _game_facts(self, match: Match, me: Player, policy: Policy) -> Dict[str, Any]:
        """Картина матча без привязки к игроку: по каждому из десяти героев.

        Цель — чтобы «кто решал игру» читалось не по урону и KDA, а по тому, на
        что игрок влиял: в скольких драках был, когда умирал, откуда брал золото
        (строения и Рошан — давление на карту, герои — драки, крипы — фарм).
        """
        fights = [(tf.get("start") or 0, tf.get("end") or 0) for tf in match.teamfights]
        presence = [0] * len(match.players)
        for tf in match.teamfights:
            for idx, fp in enumerate(tf.get("players") or []):
                if idx < len(presence) and self._took_part(fp):
                    presence[idx] += 1

        teams: Dict[str, List[Player]] = {"radiant": match.radiant_players(),
                                          "dire": match.dire_players()}
        totals = {side: {"nw": sum(p.net_worth_final for p in ps),
                         "dmg": sum(p.hero_damage for p in ps) or 1,
                         "kills": sum(p.kills for p in ps)}
                  for side, ps in teams.items()}

        players = []
        for idx, p in enumerate(match.players):
            side = "radiant" if p.is_radiant else "dire"
            deaths_in_fights = sum(
                1 for d in p.deaths_log
                if any(lo - 15 <= (d.get("time") or 0) <= hi + 15 for lo, hi in fights))
            players.append({
                "who": self._short_tag(p, me).replace("★", ""),
                "position": self._position_key(p, None, policy),
                "nw": p.net_worth_final,
                "nw_share": round(100 * p.net_worth_final / (totals[side]["nw"] or 1)),
                "dmg_share": round(100 * p.hero_damage / totals[side]["dmg"]),
                "tower_damage": p.tower_damage,
                "deaths": p.deaths, "deaths_in_fights": deaths_in_fights,
                "fights": presence[idx], "gold": self._gold_sources(p, me)["rows"],
            })

        radiant_roles = {p.position_key: p for p in teams["radiant"] if p.position_key in ROLES}
        dire_roles = {p.position_key: p for p in teams["dire"] if p.position_key in ROLES}
        pairs = []
        for role in ROLES:
            a, b = radiant_roles.get(role), dire_roles.get(role)
            if a and b:
                pairs.append({"role": role, "mine": a.hero_name, "theirs": b.hero_name,
                              "earned": [{"m": m, "mine": _at(a.gold_t, m), "theirs": _at(b.gold_t, m)}
                                         for m in self._FACT_MINUTES if _at(a.gold_t, m) is not None],
                              "nw": [a.net_worth_final, b.net_worth_final]})

        return {"whole_game": True, "fights_total": len(match.teamfights),
                "kills": [totals["radiant"]["kills"], totals["dire"]["kills"]],
                "nw": [totals["radiant"]["nw"], totals["dire"]["nw"]],
                "pairs": pairs, "players": players}

    def _gold_sources(self, p: Player, me: Player) -> Dict[str, Any]:
        income = {k: v for k, v in p.gold_reasons.items() if v > 0 and k not in ("1", "6")}
        total = sum(income.values()) or 1
        rows = [{"key": name, "gold": income.get(code, 0),
                 "pct": round(100 * income.get(code, 0) / total)}
                for code, name in self._GOLD_SOURCES]
        known = {code for code, _ in self._GOLD_SOURCES}
        other = sum(v for k, v in income.items() if k not in known)
        rows.append({"key": "other", "gold": other, "pct": round(100 * other / total)})
        return {"who": self._short_tag(p, me), "total": sum(income.values()),
                "rows": [r for r in rows if r["gold"]]}

    def _damage_taken(self, p: Player, top: int = 5) -> Dict[str, Any]:
        """Полученный урон за матч: доли по типу и что BKB не остановил бы."""
        total = sum(v for v in p.damage_received_by.values() if v > 0)
        if not total:
            return {}
        by_type: Dict[str, int] = {}
        through_bkb = blocked_by_bkb = 0
        sources = []
        for key, value in sorted(p.damage_received_by.items(), key=lambda kv: -kv[1]):
            if value <= 0:
                continue
            info = self._c.damage_source(key)
            kind = info["type"] or ("item" if info["item"] else "unknown")
            by_type[kind] = by_type.get(kind, 0) + value
            if info["through_bkb"] is True:
                through_bkb += value
            elif info["through_bkb"] is False:
                blocked_by_bkb += value
            if len(sources) < top:
                sources.append({"key": key, "name": info["name"], "type": kind,
                                "through_bkb": info["through_bkb"],
                                "attack": bool(info.get("attack")), "value": value})

        def pct(value: int) -> int:
            return round(100 * value / total)

        return {"total": total,
                "by_type": {k: pct(v) for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])},
                "through_bkb": pct(through_bkb), "blocked_by_bkb": pct(blocked_by_bkb),
                "sources": sources}

    # --- DRAFT ----------------------------------------------------------------

    def _draft(self, match: Match, me: Player, policy: Policy,
               caveats: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
        ordered = sorted(match.picks_bans, key=lambda x: x.order)
        rows = [{"order": pb.order, "is_pick": pb.is_pick,
                 "side": pb.side, "hero": pb.hero_name} for pb in ordered]

        chronological = match.draft_is_chronological
        if rows and not chronological:
            caveats.append(("caveat.draft_grouped", {"mode": match.game_mode}))

        picks = [r for r in rows if r["is_pick"]]
        phased = not chronological and self._assign_phases(picks)
        return {
            "mode": match.game_mode,
            "chronological": chronological,
            "rows": rows,
            "picks": picks,
            "bans": [r for r in rows if not r["is_pick"]],
            "phased": phased,
            "my_pick": None if policy.whole_game else self._my_pick(picks, me, phased),
            "lanes": self._lanes(match, me),
            "radiant": [self._roster_row(p, me, policy) for p in match.radiant_players()],
            "dire": [self._roster_row(p, me, policy) for p in match.dire_players()],
        }

    def _my_pick(self, picks: List[Dict[str, Any]], me: Player,
                 phased: bool) -> Optional[Dict[str, Any]]:
        """Место моего героя в драфте и то, что было видно в момент выбора.

        Главный факт драфта для разбора: пик оценивается по той информации,
        которая была на экране, а не по исходу матча.

        В ранговом All Pick (phased=True) пики идут тремя фазами: 2+2, 2+2, 1+1.
        Внутри фазы команды выбирают одновременно и выбор соперника не видят —
        он открывается, когда фаза закончилась. Союзники видны сразу. Поэтому
        важны три разных списка: кого из соперников я видел (прошлые фазы), кто
        выбирал вслепую вместе со мной (моя фаза) и кто выбирал, УЖЕ видя моего
        героя (следующие фазы, — это и есть возможный контрпик).

        Без фаз (Captains Mode и нестандартные драфты) порядок трактуется как
        строгая очередь: всё, что выше моего пика, было видно.
        """
        my_side = "Radiant" if me.is_radiant else "Dire"
        at = next((i for i, r in enumerate(picks)
                   if r["hero"] == me.hero_name and r["side"] == my_side), None)
        if at is None:
            return None

        def heroes(rows: List[Dict[str, Any]], mine: bool) -> List[str]:
            return [r["hero"] for r in rows if (r["side"] == my_side) is mine]

        if phased:
            phase = picks[at]["phase"]
            return {
                "phased": True,
                "phase": phase,
                "team_order": len(heroes(picks[:at], True)) + 1,
                "enemies_visible": [r["hero"] for r in picks
                                    if r["side"] != my_side and r["phase"] < phase],
                "allies_before": heroes(picks[:at], True),
                "enemies_blind": [r["hero"] for r in picks
                                  if r["side"] != my_side and r["phase"] == phase],
                "enemies_after": [r["hero"] for r in picks
                                  if r["side"] != my_side and r["phase"] > phase],
            }

        before, after = picks[:at], picks[at + 1:]
        return {
            "phased": False,
            "order": at + 1,
            "total": len(picks),
            "tag": "first" if at == 0 else "last" if at == len(picks) - 1 else "mid",
            "enemies_before": heroes(before, False),
            "allies_before": heroes(before, True),
            "enemies_after": heroes(after, False),
        }

    @staticmethod
    def _assign_phases(picks: List[Dict[str, Any]]) -> bool:
        """Раскладывает пики рангового All Pick по трём фазам, если данные сходятся.

        OpenDota отдаёт пики All Pick в порядке подтверждения, и он ложится на
        фазы ровно блоками: первые четыре — фаза 1 (по два от команды), следующие
        четыре — фаза 2, последние два — ласт-пики. Проверено на реальных матчах.
        Если блоки не сходятся (перепик, рандом, 11 записей) — фаз не выдумываем.
        """
        blocks = ((0, 4, 1), (4, 8, 2), (8, 10, 3))
        if len(picks) != 10:
            return False
        for lo, hi, _ in blocks:
            sides = [r["side"] for r in picks[lo:hi]]
            if sides.count("Radiant") != sides.count("Dire"):
                return False
        for lo, hi, phase in blocks:
            for r in picks[lo:hi]:
                r["phase"] = phase
        return True

    @staticmethod
    def _lanes(match: Match, me: Player) -> List[Dict[str, Any]]:
        """Кто против кого стоял на линиях: низ, центр, верх.

        Физическая линия OpenDota: 1 — низ (лёгкая Radiant), 2 — центр, 3 — верх
        (лёгкая Dire). Роумеры и лесники в линию не попадают — это тоже факт.
        """
        out = []
        for lane in (1, 2, 3):
            row = {"lane": lane, "radiant": [], "dire": []}
            for p in match.players:
                if p.lane == lane:
                    tag = p.hero_name + ("★" if p is me else "")
                    row["radiant" if p.is_radiant else "dire"].append(tag)
            out.append(row)
        return out

    def _roster_row(self, p: Player, me: Player, policy: Policy) -> Dict[str, Any]:
        return {"hero": p.hero_name, "position_key": self._position_key(p, me, policy),
                "lane_key": p.lane_key}

    # --- SCOREBOARD -----------------------------------------------------------

    def _score_row(self, p: Player, me: Player) -> Dict[str, Any]:
        return {
            "who": self._tag(p, me),
            "lvl": p.level,
            "kda": f"{p.kills}/{p.deaths}/{p.assists}",
            "lh_dn": f"{p.last_hits}/{p.denies}",
            "gpm_xpm": f"{p.gpm}/{p.xpm}",
            "nw": p.net_worth,
            "hd": p.hero_damage,
            "td": p.tower_damage,
            "heal": p.hero_healing,
            "dt": p.damage_taken_total,
        }

    # --- BENCHMARKS -----------------------------------------------------------

    def _benchmarks(self, match: Match, me: Player, policy: Policy) -> List[Dict[str, Any]]:
        out = []
        metrics = _ROLE_BENCH_METRICS.get(self._effective_role(me, policy), _BENCH_METRICS)
        for p in self._audience(match, me, policy, "benchmarks"):
            rows = []
            # Ролевой фильтр относится только к ★. В deep профили остальных
            # остаются универсальными, иначе выбранная роль исказила бы их данные.
            selected = metrics if p is me else _BENCH_METRICS
            for metric in selected:
                b = p.benchmarks.get(metric)
                if isinstance(b, dict) and b.get("raw") is not None:
                    pct = b.get("pct")
                    rows.append({"metric": metric, "raw": round(b["raw"], 1),
                                 "pct": round(pct * 100) if pct is not None else None})
            out.append({"who": self._tag(p, me), "rows": rows})
        return out

    # --- NET WORTH TIMELINE ---------------------------------------------------

    def _team_adv_series(self, match: Match, me: Player) -> Tuple[List[int], List[int]]:
        """Перевес МОЕЙ команды по золоту и опыту, поминутно.

        Основной источник — radiant_gold_adv/radiant_xp_adv. Если их нет
        (нераспарсенный матч), золото восстанавливаем суммированием gold_t.
        """
        sign = 1 if me.is_radiant else -1
        gold = [sign * v for v in match.radiant_gold_adv]
        xp = [sign * v for v in match.radiant_xp_adv]
        if not gold:
            minutes = max((len(p.gold_t) for p in match.players), default=0)
            rad, dire = match.radiant_players(), match.dire_players()
            gold = [sign * (sum(_at(p.gold_t, m) or 0 for p in rad)
                            - sum(_at(p.gold_t, m) or 0 for p in dire))
                    for m in range(minutes)]
        return gold, xp

    @staticmethod
    def _swings(gold_adv: List[int]) -> List[Dict[str, Any]]:
        """Минуты, где перевес по золоту менял знак, — это и есть сюжет матча."""
        swings: List[Dict[str, Any]] = []
        prev_sign = 0
        for m, v in enumerate(gold_adv):
            cur = (v > 0) - (v < 0)
            if cur and prev_sign and cur != prev_sign:
                swings.append({"m": m, "gold": v,
                               "key": "nw.swing_ahead" if cur > 0 else "nw.swing_behind"})
            if cur:
                prev_sign = cur
        return swings

    def _networth(self, match: Match, me: Player, policy: Policy) -> Dict[str, Any]:
        gold_adv, xp_adv = self._team_adv_series(match, me)
        minutes = max(len(gold_adv), max((len(p.gold_t) for p in match.players), default=0))
        idxs = sorted(set(list(range(0, minutes, TIMELINE_STEP_MIN))
                          + ([minutes - 1] if minutes else [])))

        team = [{"m": m, "gold": _at(gold_adv, m), "xp": _at(xp_adv, m)} for m in idxs]
        swings: List[Dict[str, Any]] = self._swings(gold_adv)
        if len(swings) > MAX_SWINGS:  # оставляем самые крупные перевороты
            swings = sorted(sorted(swings, key=lambda s: abs(s["gold"]),
                                   reverse=True)[:MAX_SWINGS], key=lambda s: s["m"])

        peak: Dict[str, Any] = {}
        if gold_adv:
            best_m = max(range(len(gold_adv)), key=lambda m: gold_adv[m])
            worst_m = min(range(len(gold_adv)), key=lambda m: gold_adv[m])
            peak = {"best": {"m": best_m, "gold": gold_adv[best_m]},
                    "worst": {"m": worst_m, "gold": gold_adv[worst_m]}}

        # Кривые нетворта: в сводке — я и вражеские коры (кто именно меня обгонял),
        # в развёрнутом виде — все десять.
        if policy.at_least("networth", EXPANDED):
            shown = list(match.players)
        else:
            shown = [me] + [p for p in match.enemies_of(me) if p.is_core]
        curves = [{"who": self._tag(p, me),
                   "series": [{"m": m, "nw": _at(p.gold_t, m)} for m in idxs]}
                  for p in shown]

        return {"step": TIMELINE_STEP_MIN, "team": team, "swings": swings,
                "peak": peak, "curves": curves}

    # --- ITEMS ----------------------------------------------------------------

    def assembled_purchases(self, p: Player, min_cost: int) -> List[Dict[str, Any]]:
        """Оставляет только реально собранные предметы дороже порога.

        Идём по логу покупок; когда встречаем собранный предмет, помечаем его
        компоненты среди более ранних непоглощённых покупок как «съеденные».
        Так Iron Branch и Boots of Speed исчезают, а Manta Style и Power Treads
        остаются — с их настоящим таймингом.
        """
        log = [(e.get("time"), (e.get("key") or "").replace("item_", ""))
               for e in p.purchase_log]
        absorbed = [False] * len(log)

        for i, (_, key) in enumerate(log):
            need = list(self._c.item_components(key))
            if not need:
                continue
            for j in range(i - 1, -1, -1):
                if not need:
                    break
                if absorbed[j]:
                    continue
                if log[j][1] in need:
                    need.remove(log[j][1])
                    absorbed[j] = True

        out = []
        for i, (t, key) in enumerate(log):
            if absorbed[i] or key.startswith("recipe_") or self._c.item_is_consumable(key):
                continue
            if key not in ALWAYS_KEY_ITEMS and self._c.item_cost(key) < min_cost:
                continue
            # `t` и `key` нужны детектору аномалий: он считает темп сборки в
            # секундах и берёт стоимость по ключу. Печать использует `time`/`item`.
            out.append({"time": mmss(t), "t": t, "key": key,
                        "item": self._c.item_name(key)})
        return out

    def _full_purchases(self, p: Player) -> List[Dict[str, Any]]:
        return [{"time": mmss(e.get("time")), "item": self._c.item_name(e.get("key"))}
                for e in p.purchase_log]

    def _items(self, match: Match, me: Player, policy: Policy,
               caveats: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        full_log = policy.at_least("items", FULL_LOG)
        # Единственная секция, где состав участников не зависит от уровня. Билд
        # оценивается в контексте, а не в вакууме: Manta на 13:13 значит разное
        # против Ursa с Blink и против Ursa без него, а BKB «поздно» или «вовремя»
        # — это вопрос о том, когда у соперника появился контроль. Поэтому
        # крупные предметы остальных девяти печатаются всегда, а уровень
        # управляет подробностью МОЕЙ сборки: ключевые -> полный лог покупок.
        # Цена решения — десяток коротких строк; сигнала в них несоизмеримо больше.

        out = []
        for p in match.players:
            if full_log and p is me:
                timings, kind = self._full_purchases(p), "full"
            elif p is me and not policy.whole_game:
                timings, kind = self.assembled_purchases(p, KEY_ITEM_COST), "key"
            else:
                timings, kind = self.assembled_purchases(p, MAJOR_ITEM_COST), "major"
            out.append({"who": self._tag(p, me), "kind": kind, "timings": timings})

        if not full_log:
            caveats.append(("caveat.items_filtered",
                            {"mine": KEY_ITEM_COST, "others": MAJOR_ITEM_COST}))
        return out

    # --- ABILITY BUILD --------------------------------------------------------

    def _ability_row(self, p: Player, me: Player) -> Dict[str, Any]:
        build = [{"n": i + 1, "name": self._c.ability_name(aid),
                  "talent": self._c.is_talent(aid)}
                 for i, aid in enumerate(p.ability_upgrades)]
        return {"who": self._tag(p, me), "build": build}

    def _abilities(self, match: Match, me: Player, policy: Policy,
                   caveats: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if policy.at_least("abilities", EXPANDED):
            shown = list(match.players)
        else:
            shown = [me] + match.lane_opponents_of(me)

        caveats.append(("caveat.abilities_order", {}))
        return [self._ability_row(p, me) for p in shown]

    # --- LANING 0..10 ---------------------------------------------------------

    def _laning(self, match: Match, me: Player, policy: Policy) -> Dict[str, Any]:
        cs = [{"min": m, "lh": _at(me.lh_t, m), "dn": _at(me.dn_t, m)} for m in range(1, 11)]

        my_kills = [{"time": mmss(e.get("time")), "victim": self._c.npc_to_hero(e.get("key"))}
                    for e in me.kills_log if (e.get("time") or 0) <= LANE_WINDOW_SEC]

        my_npc = self._c.hero_npc(me.hero_id)
        my_deaths = []
        if my_npc:
            for opp in match.players:
                if opp is me:
                    continue
                for e in opp.kills_log:
                    if e.get("key") == my_npc and (e.get("time") or 0) <= LANE_WINDOW_SEC:
                        my_deaths.append({"time": mmss(e.get("time")), "killer": opp.hero_name})
            my_deaths.sort(key=lambda d: d["time"])

        opponents = [{"who": self._tag(p, me), "position_key": p.position_key,
                      "lane_key": p.lane_key, "eff_pct": p.lane_efficiency_pct,
                      "cs_by_min": [{"min": m, "lh": _at(p.lh_t, m), "dn": _at(p.dn_t, m)}
                                    for m in range(1, 11)]}
                     for p in match.lane_opponents_of(me)]

        detailed = policy.at_least("laning", EXPANDED)
        gold_xp = ([{"min": m, "gold": _at(me.gold_t, m), "xp": _at(me.xp_t, m)}
                    for m in range(1, 11)] if detailed else [])

        return {
            "position_key": self._effective_role(me, policy),
            "lane_key": me.lane_key,
            "me_eff_pct": me.lane_efficiency_pct,
            "cs_by_min": cs,
            "my_gold_xp": gold_xp,
            "my_kills": my_kills,
            "my_deaths": my_deaths,
            "opponents": opponents,
            "detailed": detailed,
            "lane_efficiency_all": [{"who": self._tag(p, me), "eff_pct": p.lane_efficiency_pct}
                                    for p in match.players if p.lane_efficiency_pct is not None],
        }

    # --- ROLE IMPACT ---------------------------------------------------------

    def _utility_purchases(self, p: Player) -> List[Dict[str, Any]]:
        """Тайминги командных предметов без расходников и компонентов."""
        seen = set()
        out = []
        for event in p.purchase_log:
            key = event.get("key")
            if key not in _UTILITY_ITEMS or key in seen:
                continue
            seen.add(key)
            out.append({"time": mmss(event.get("time")), "item": self._c.item_name(key)})
        return out

    def _death_times(self, match: Match, me: Player) -> List[int]:
        my_npc = self._c.hero_npc(me.hero_id)
        if not my_npc:
            return []
        times = [
            int(event.get("time") or 0)
            for opponent in match.enemies_of(me)
            for event in opponent.kills_log
            if event.get("key") == my_npc
        ]
        return sorted(t for t in times if t >= 0)

    @staticmethod
    def _fight_context(match: Match, me: Player) -> Tuple[int, int]:
        idx = match.players.index(me)
        involved = deaths = 0
        for fight in match.teamfights:
            players = fight.get("players") or []
            mine = players[idx] if idx < len(players) else {}
            mine_deaths = mine.get("deaths") or 0
            if mine_deaths or mine.get("damage") or mine.get("healing"):
                involved += 1
            deaths += mine_deaths
        return involved, deaths

    def _role_impact(self, match: Match, me: Player, policy: Policy) -> Dict[str, Any]:
        role = self._effective_role(me, policy)
        team = match.radiant_players() if me.is_radiant else match.dire_players()
        team_kills = sum(p.kills for p in team)
        # В неполностью распарсенных/синтетических данных K+A иногда расходится
        # с суммой team kills. Процент не должен становиться физически невозможным.
        participation = min(
            100,
            round(100 * (me.kills + me.assists) / team_kills) if team_kills else 0,
        )
        death_times = self._death_times(match, me)
        involved, fight_deaths = self._fight_context(match, me)
        early_kills = sorted(
            int(e.get("time") or 0) for e in me.kills_log
            if 0 <= int(e.get("time") or 0) <= 15 * 60
        )

        common = {
            "role": role,
            "role_source": policy.role_source,
            "kill_participation": participation,
            "assists": me.assists,
            "deaths": me.deaths,
            "fight_involvement": involved,
            "fight_deaths": fight_deaths,
        }
        metrics_by_role = {
            "1": [
                ("cs10", _at(me.lh_t, 10)), ("gpm", me.gpm),
                ("networth", me.net_worth), ("hero_damage", me.hero_damage),
                ("kill_participation", participation),
            ],
            "2": [
                ("xpm", me.xpm), ("runes", me.rune_pickups),
                ("early_kills", len(early_kills)), ("kill_participation", participation),
                ("hero_damage", me.hero_damage),
            ],
            "3": [
                ("damage_taken", me.damage_taken_total), ("stuns", round(me.stuns, 1)),
                ("kill_participation", participation), ("fight_involvement", involved),
                ("fight_deaths", fight_deaths),
            ],
            "4": [
                ("assists", me.assists), ("kill_participation", participation),
                ("camps_stacked", me.camps_stacked), ("creeps_stacked", me.creeps_stacked),
                ("runes", me.rune_pickups), ("wards", f"{me.obs_placed}/{me.sen_placed}"),
                ("dewards", me.observer_kills + me.sentry_kills), ("stuns", round(me.stuns, 1)),
            ],
            "5": [
                ("assists", me.assists), ("kill_participation", participation),
                ("wards", f"{me.obs_placed}/{me.sen_placed}"),
                ("dewards", me.observer_kills + me.sentry_kills),
                ("camps_stacked", me.camps_stacked), ("creeps_stacked", me.creeps_stacked),
                ("healing", me.hero_healing), ("stuns", round(me.stuns, 1)),
                ("fight_deaths", fight_deaths),
            ],
        }
        common.update({
            "metrics": [{"key": key, "value": value}
                        for key, value in metrics_by_role.get(role, [])],
            "early_kill_times": [mmss(t) for t in early_kills],
            "late_death_times": [mmss(t) for t in death_times if t >= 40 * 60],
            "key_items": self.assembled_purchases(me, KEY_ITEM_COST)
                         if role in ("1", "2") else [],
            "utility_items": self._utility_purchases(me)
                             if role in ("3", "4", "5") else [],
        })
        return common

    # --- COMBAT / ECON --------------------------------------------------------

    def _combat_row(self, p: Player, me: Player, with_b_tier: bool) -> Dict[str, Any]:
        row = {
            "who": self._tag(p, me),
            "best_streak": max((int(k) for k in p.kill_streaks), default=0),
            "best_multikill": max((int(k) for k in p.multi_kills), default=0),
            "stuns_sec": round(p.stuns, 1),
            "camps_stacked": p.camps_stacked,
            "runes": p.rune_pickups,
            "obs": p.obs_placed,
            "sen": p.sen_placed,
            "buybacks": p.buyback_count,
            "time_dead": mmss(p.seconds_dead),
            # Ключи канонические — подписи подставит i18n по kills.<ключ>.
            "kills_by_type": {
                "neutrals": p.neutral_kills, "ancients": p.ancient_kills,
                "towers": p.tower_kills, "roshan": p.roshan_kills,
                "courier": p.courier_kills, "observers": p.observer_kills,
                "sentries": p.sentry_kills,
            },
            "extra": {},
        }
        if with_b_tier:
            mh = p.max_hero_hit
            row["extra"] = {
                "apm": p.actions_per_min,
                "pings": p.pings,
                "max_hero_hit": (f"{mh['value']} по {self._c.npc_to_hero(mh.get('key'))}"
                                 if mh.get("value") else None),
            }
        return row

    def _combat(self, match: Match, me: Player, policy: Policy) -> List[Dict[str, Any]]:
        with_b_tier = policy.at_least("combat", EXPANDED)
        return [self._combat_row(p, me, with_b_tier)
                for p in self._audience(match, me, policy, "combat")]

    # --- PERMANENT BUFFS ------------------------------------------------------

    def _buffs(self, match: Match, me: Player) -> List[Dict[str, Any]]:
        """Только реально накопленные стаки.

        Записи со stack_count = 0 — это «у игрока есть Aghanim's Scepter/Shard»;
        их тайминг и так виден в секции предметов, поэтому здесь они лишний шум.
        """
        out = []
        for p in match.players:
            buffs = [{"name": self._c.permanent_buff_name(b.get("permanent_buff")),
                      "stacks": b.get("stack_count"),
                      "since": mmss(b.get("grant_time")) if b.get("grant_time") else None}
                     for b in p.permanent_buffs if (b.get("stack_count") or 0) > 0]
            if buffs:
                out.append({"who": self._tag(p, me), "buffs": buffs})
        return out

    # --- TEAMFIGHTS -----------------------------------------------------------

    def _fight_row(self, match: Match, me: Player, tf: Dict[str, Any],
                   detailed: bool) -> Dict[str, Any]:
        """Один тимфайт. Вынесен отдельно: та же раскладка нужна секции окна,
        где детализация максимальная независимо от глубины остального промпта."""
        my_idx = match.players.index(me)
        tf_players = tf.get("players") or []
        rad_deaths = dire_deaths = 0
        fallen: List[str] = []
        participants = []
        # Кто был в бою, а кого не было — по обеим сторонам и на ЛЮБОЙ глубине.
        # «Проиграли 3 на 5» и «проиграли 5 на 5» — разные бои с разными
        # выводами, а без этой строки модель видит только счёт потерь.
        present = {"mine": [], "theirs": []}
        absent = {"mine": [], "theirs": []}

        for idx, p in enumerate(match.players):
            if idx >= len(tf_players):
                continue
            fp = tf_players[idx]
            deaths = fp.get("deaths") or 0
            if deaths:
                # Время смерти — из журнала смертей игрока: «керри умер первым»
                # и «керри умер последним» — разные выводы о драке.
                lo, hi = (tf.get("start") or 0) - 5, (tf.get("end") or 0) + 5
                when = next((e.get("time") for e in p.deaths_log
                             if lo <= (e.get("time") or -1) <= hi), None)
                fallen.append((when if when is not None else 10 ** 9,
                               self._short_tag(p, me) + (f" {mmss(when)}" if when is not None else "")))
                if p.is_radiant:
                    rad_deaths += deaths
                else:
                    dire_deaths += deaths
            # Игрок «участвовал», если умер, нанёс урон по героям или кого-то
            # убил. По gold_delta и healing участие НЕ определяем: золото набегает
            # и у того, кто фармил на другом конце карты, а healing в данных боя
            # включает обычную регенерацию — у керри, стоявшего в лесу, его сотни.
            took_part = self._took_part(fp)
            team = "mine" if p.is_radiant == me.is_radiant else "theirs"
            (present if took_part else absent)[team].append(self._short_tag(p, me))
            if detailed and (deaths or fp.get("damage")):
                participants.append({
                    "who": self._tag(p, me),
                    "gold_delta": fp.get("gold_delta"),
                    "xp_delta": fp.get("xp_delta"),
                    "deaths": deaths,
                    "damage": fp.get("damage"),
                    "healing": fp.get("healing"),
                })

        my_losses, enemy_losses = ((dire_deaths, rad_deaths) if not me.is_radiant
                                   else (rad_deaths, dire_deaths))
        if my_losses < enemy_losses:
            verdict = "tf.win"
        elif my_losses > enemy_losses:
            verdict = "tf.lose"
        else:
            verdict = "tf.even"

        mine = tf_players[my_idx] if my_idx < len(tf_players) else {}
        killed = [self._c.npc_to_hero(k) for k, v in (mine.get("killed") or {}).items()
                  if str(k).startswith("npc_dota_hero_") and v]

        return {
            "start": mmss(tf.get("start")),
            "end": mmss(tf.get("end")),
            "deaths": tf.get("deaths"),
            "my_losses": my_losses,
            "enemy_losses": enemy_losses,
            "verdict": verdict,
            # По порядку гибели, а не по номеру слота.
            "fallen": [tag for _, tag in sorted(fallen)],
            "me": {
                "damage": mine.get("damage") or 0,
                "deaths": mine.get("deaths") or 0,
                "gold_delta": mine.get("gold_delta") or 0,
                "xp_delta": mine.get("xp_delta") or 0,
                "killed": killed,
            },
            "participants": participants,
            "presence": {"mine": len(present["mine"]), "theirs": len(present["theirs"]),
                         "absent_mine": absent["mine"], "absent_theirs": absent["theirs"]},
            "in_lane": (tf.get("start") or 0) <= LANE_WINDOW_SEC,
        }

    def _teamfights(self, match: Match, me: Player, policy: Policy) -> List[Dict[str, Any]]:
        detailed = policy.at_least("teamfights", EXPANDED)
        fights = match.teamfights
        if policy.focus == "laning":
            # Разбираем линию — поздние замесы к вопросу отношения не имеют.
            fights = [tf for tf in fights if (tf.get("start") or 0) <= LANE_WINDOW_SEC]
        return [self._fight_row(match, me, tf, detailed) for tf in fights]

    # --- ОКНО (максимальная детализация выбранного промежутка) -----------------

    def _window(self, match: Match, me: Player, policy: Policy) -> Dict[str, Any]:
        """Всё, что происходило в промежутке, по всем героям и без прореживания.

        Единственное место в проекте, где мы сознательно не экономим: игрок сам
        попросил рассмотреть отрезок под лупой, и порог «сигнал > объём» здесь
        оплачен тем, что весь остальной матч ужат до сводки (см. Policy.level).
        """
        start_min, end_min = policy.window
        lo, hi = start_min * 60, end_min * 60
        minutes = list(range(start_min, end_min + 1))

        gold_adv, xp_adv = self._team_adv_series(match, me)
        team = [{"m": m, "gold": _at(gold_adv, m), "xp": _at(xp_adv, m)} for m in minutes]

        series = [{"who": self._tag(p, me),
                   "rows": [{"m": m, "nw": _at(p.gold_t, m), "xp": _at(p.xp_t, m),
                             "lh": _at(p.lh_t, m), "dn": _at(p.dn_t, m)}
                            for m in minutes]}
                  for p in match.players]

        kills = []
        for p in match.players:
            for e in p.kills_log:
                t = e.get("time")
                if t is None or not (lo <= t <= hi):
                    continue
                kills.append({"t": t, "time": mmss(t), "killer": self._short_tag(p, me),
                              "victim": self._c.npc_to_hero(e.get("key"))})
        kills.sort(key=lambda k: k["t"])

        # Порог стоимости здесь не применяем: в узком окне важна каждая покупка,
        # включая расходники — по ним видно, кто готовился к бою, а кто фармил.
        purchases = []
        for p in match.players:
            for e in p.purchase_log:
                t, key = e.get("time"), (e.get("key") or "")
                if t is None or not (lo <= t <= hi) or key.startswith("recipe_"):
                    continue
                purchases.append({"t": t, "time": mmss(t), "who": self._short_tag(p, me),
                                  "item": self._c.item_name(key)})
        purchases.sort(key=lambda x: x["t"])

        fights = [self._fight_row(match, me, tf, detailed=True)
                  for tf in match.teamfights
                  if (tf.get("end") or 0) >= lo and (tf.get("start") or 0) <= hi]

        objectives = [{"time": mmss(o.time), "kind": o.kind, "params": o.params,
                       "minor": o.minor}
                      for o in match.objectives if lo <= o.time <= hi]

        return {"start": start_min, "end": end_min, "team": team, "series": series,
                "kills": kills, "purchases": purchases, "fights": fights,
                "objectives": objectives,
                "empty": not (kills or purchases or fights or objectives)}

    # --- OBJECTIVES -----------------------------------------------------------

    def _objectives(self, match: Match, policy: Policy) -> List[Dict[str, Any]]:
        rows = [{"time": mmss(o.time), "kind": o.kind, "params": o.params, "minor": o.minor}
                for o in match.objectives]
        if policy.at_least("objectives", EXPANDED):
            return rows
        return [r for r in rows if not r["minor"]]

    # --- DAMAGE (по героям) ---------------------------------------------------

    def _damage_row(self, p: Player, me: Player) -> Dict[str, Any]:
        top = sorted(p.damage_by_hero.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {"who": self._tag(p, me),
                "targets": [{"hero": self._c.npc_to_hero(k), "dmg": v} for k, v in top]}

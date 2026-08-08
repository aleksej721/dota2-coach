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
    role_impact: Dict[str, Any] = field(default_factory=dict)
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

        if policy.shows("anomalies"):
            # min_cost=0: детектору нужна вся сборка, иначе накопленная
            # стоимость поедет и «ожидаемый» тайминг станет фикцией.
            f.anomalies = self._anomalies.detect(
                match, me, self._assembled_purchases(me, min_cost=0))

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

    # --- DRAFT ----------------------------------------------------------------

    def _draft(self, match: Match, me: Player, policy: Policy,
               caveats: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
        ordered = sorted(match.picks_bans, key=lambda x: x.order)
        rows = [{"order": pb.order, "is_pick": pb.is_pick,
                 "side": pb.side, "hero": pb.hero_name} for pb in ordered]

        chronological = match.draft_is_chronological
        if rows and not chronological:
            caveats.append(("caveat.draft_grouped", {"mode": match.game_mode}))

        return {
            "mode": match.game_mode,
            "chronological": chronological,
            "rows": rows,
            "picks": [r for r in rows if r["is_pick"]],
            "bans": [r for r in rows if not r["is_pick"]],
            "radiant": [self._roster_row(p, me, policy) for p in match.radiant_players()],
            "dire": [self._roster_row(p, me, policy) for p in match.dire_players()],
        }

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

    def _assembled_purchases(self, p: Player, min_cost: int) -> List[Dict[str, Any]]:
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
        audience = self._audience(match, me, policy, "items")

        out = []
        for p in audience:
            if full_log and p is me:
                timings, kind = self._full_purchases(p), "full"
            elif p is me:
                timings, kind = self._assembled_purchases(p, KEY_ITEM_COST), "key"
            else:
                timings, kind = self._assembled_purchases(p, MAJOR_ITEM_COST), "major"
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
            "key_items": self._assembled_purchases(me, KEY_ITEM_COST)
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

    def _teamfights(self, match: Match, me: Player, policy: Policy) -> List[Dict[str, Any]]:
        detailed = policy.at_least("teamfights", EXPANDED)
        my_idx = match.players.index(me)
        out = []

        fights = match.teamfights
        if policy.focus == "laning":
            # Разбираем линию — поздние замесы к вопросу отношения не имеют.
            fights = [tf for tf in fights if (tf.get("start") or 0) <= LANE_WINDOW_SEC]

        for tf in fights:
            tf_players = tf.get("players") or []
            rad_deaths = dire_deaths = 0
            fallen: List[str] = []
            participants = []

            for idx, p in enumerate(match.players):
                if idx >= len(tf_players):
                    continue
                fp = tf_players[idx]
                deaths = fp.get("deaths") or 0
                if deaths:
                    fallen.append(self._short_tag(p, me))
                    if p.is_radiant:
                        rad_deaths += deaths
                    else:
                        dire_deaths += deaths
                # Игрок «участвовал», если умер или нанёс урон. Ненулевой gold_delta
                # набегает и у того, кто в это время спокойно фармил на другой карте.
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

            out.append({
                "start": mmss(tf.get("start")),
                "end": mmss(tf.get("end")),
                "deaths": tf.get("deaths"),
                "my_losses": my_losses,
                "enemy_losses": enemy_losses,
                "verdict": verdict,
                "fallen": fallen,
                "me": {
                    "damage": mine.get("damage") or 0,
                    "deaths": mine.get("deaths") or 0,
                    "gold_delta": mine.get("gold_delta") or 0,
                    "xp_delta": mine.get("xp_delta") or 0,
                    "killed": killed,
                },
                "participants": participants,
                "in_lane": (tf.get("start") or 0) <= LANE_WINDOW_SEC,
            })
        return out

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

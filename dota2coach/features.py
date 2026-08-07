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

from .constants import Constants
from .model import Match, Player
from .policy import EXPANDED, FULL_LOG, Policy

LANE_WINDOW_SEC = 600      # окно лайнинга 0..10 мин
TIMELINE_STEP_MIN = 5      # шаг прореживания поминутных рядов
MAX_SWINGS = 8             # сколько переломов баланса показываем максимум

# Пороги «значимости» покупки (золото). Компоненты и расходники отсекаются
# отдельно, до порога, поэтому здесь речь только о собранных предметах.
KEY_ITEM_COST = 1000       # мои ключевые предметы
MAJOR_ITEM_COST = 2000     # крупные предметы остальных игроков
ALWAYS_KEY_ITEMS = {"aghanims_shard"}  # дешевле порога, но всегда меняет игру

# Метрики бенчмарков OpenDota -> человекочитаемая подпись.
_BENCH_LABELS = {
    "gold_per_min": "GPM",
    "xp_per_min": "XPM",
    "kills_per_min": "киллы/мин",
    "last_hits_per_min": "добивания/мин",
    "hero_damage_per_min": "урон по героям/мин",
    "hero_healing_per_min": "лечение/мин",
    "tower_damage": "урон по строениям",
    "stuns_per_min": "стан/мин",
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
    # Оговорки, которые зависят от того, что мы отфильтровали или чего нет в
    # источнике. Собираются по ходу извлечения и печатаются в «ОГРАНИЧЕНИЯ ДАННЫХ».
    caveats: List[str] = field(default_factory=list)


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

    def extract(self, match: Match, me: Player, policy: Policy) -> Features:
        f = Features()
        f.meta = self._meta(match, me)
        f.scoreboard = [self._score_row(p, me) for p in match.players]

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
        who = "★Я " if p is me else ""
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

    # --- META -----------------------------------------------------------------

    def _meta(self, match: Match, me: Player) -> Dict[str, Any]:
        return {
            "match_id": match.match_id,
            "patch": match.patch,
            "mode": match.game_mode,
            "lobby": match.lobby_type,
            "duration": mmss(match.duration),
            "result": "ПОБЕДА" if me.win else "ПОРАЖЕНИЕ",
            "my_side": "Radiant" if me.is_radiant else "Dire",
            "winner": "Radiant" if match.radiant_win else "Dire",
            "me": f"{me.hero_name} | {me.position_label} | ур.{me.level} | "
                  f"KDA {me.kills}/{me.deaths}/{me.assists}",
            "parsed": match.parsed,
        }

    # --- DRAFT ----------------------------------------------------------------

    def _draft(self, match: Match, me: Player, policy: Policy,
               caveats: List[str]) -> Dict[str, Any]:
        ordered = sorted(match.picks_bans, key=lambda x: x.order)
        rows = [{"order": pb.order, "kind": "пик" if pb.is_pick else "БАН",
                 "side": pb.side, "hero": pb.hero_name} for pb in ordered]

        chronological = match.draft_is_chronological
        if rows and not chronological:
            caveats.append(
                "- Режим «{mode}»: OpenDota отдаёт пики и баны отдельными группами, "
                "а не в истинном порядке драфта. В секции ДРАФТ они так и показаны — "
                "не делай выводов о том, что за чем шло.".format(mode=match.game_mode)
            )

        return {
            "mode": match.game_mode,
            "chronological": chronological,
            "rows": rows,
            "picks": [r for r in rows if r["kind"] == "пик"],
            "bans": [r for r in rows if r["kind"] == "БАН"],
            "radiant": [{"hero": p.hero_name, "pos": p.position_label}
                        for p in match.radiant_players()],
            "dire": [{"hero": p.hero_name, "pos": p.position_label}
                     for p in match.dire_players()],
        }

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
        for p in self._audience(match, me, policy, "benchmarks"):
            rows = []
            for key, label in _BENCH_LABELS.items():
                b = p.benchmarks.get(key)
                if isinstance(b, dict) and b.get("raw") is not None:
                    pct = b.get("pct")
                    pct_txt = f"перцентиль {round(pct * 100)}" if pct is not None else "?"
                    rows.append({"metric": label, "raw": round(b["raw"], 1), "pct": pct_txt})
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
                swings.append({
                    "m": m, "gold": v,
                    "text": "моя команда вышла вперёд" if cur > 0 else "перевес ушёл к соперникам",
                })
            if cur:
                prev_sign = cur
        return swings

    def _networth(self, match: Match, me: Player, policy: Policy) -> Dict[str, Any]:
        gold_adv, xp_adv = self._team_adv_series(match, me)
        minutes = max(len(gold_adv), max((len(p.gold_t) for p in match.players), default=0))
        idxs = sorted(set(list(range(0, minutes, TIMELINE_STEP_MIN))
                          + ([minutes - 1] if minutes else [])))

        team = [{"m": m, "gold": _at(gold_adv, m), "xp": _at(xp_adv, m)} for m in idxs]
        swings = self._swings(gold_adv)
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

        return {
            "step": TIMELINE_STEP_MIN,
            "team": team,
            "swings": swings,
            "peak": peak,
            "curves": curves,
            "note": f"Точки — каждые {TIMELINE_STEP_MIN} мин плюс последняя минута; "
                    "переломы перечислены отдельно. Гранулярность источника — "
                    "1 точка/мин (максимум OpenDota).",
        }

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
            out.append({"time": mmss(t), "item": self._c.item_name(key)})
        return out

    def _full_purchases(self, p: Player) -> List[Dict[str, Any]]:
        return [{"time": mmss(e.get("time")), "item": self._c.item_name(e.get("key"))}
                for e in p.purchase_log]

    def _items(self, match: Match, me: Player, policy: Policy,
               caveats: List[str]) -> List[Dict[str, Any]]:
        full_log = policy.at_least("items", FULL_LOG)
        audience = self._audience(match, me, policy, "items")

        out = []
        for p in audience:
            if full_log and p is me:
                timings, kind = self._full_purchases(p), "полный лог покупок"
            elif p is me:
                timings, kind = self._assembled_purchases(p, KEY_ITEM_COST), "ключевые"
            else:
                timings, kind = self._assembled_purchases(p, MAJOR_ITEM_COST), "крупные"
            out.append({"who": self._tag(p, me), "kind": kind, "timings": timings})

        if not full_log:
            caveats.append(
                f"- Предметы: только собранные (мои — от {KEY_ITEM_COST} золота, чужие — "
                f"от {MAJOR_ITEM_COST}); компоненты, расходники и варды скрыты."
            )
        return out

    # --- ABILITY BUILD --------------------------------------------------------

    def _ability_row(self, p: Player, me: Player) -> Dict[str, Any]:
        build = []
        for i, aid in enumerate(p.ability_upgrades):
            name = self._c.ability_name(aid)
            build.append({"n": i + 1,
                          "ability": f"талант: {name}" if self._c.is_talent(aid) else name})
        return {"who": self._tag(p, me), "build": build}

    def _abilities(self, match: Match, me: Player, policy: Policy,
                   caveats: List[str]) -> List[Dict[str, Any]]:
        if policy.at_least("abilities", EXPANDED):
            shown = list(match.players)
        else:
            shown = [me] + match.lane_opponents_of(me)

        caveats.append(
            "- Раскачка: #N — это порядок прокачки, а НЕ уровень героя (времени "
            "источник не даёт). Числовых значений талантов в OpenDota нет — только названия."
        )
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

        opponents = [{"who": self._tag(p, me), "pos": p.position_label,
                      "eff_pct": p.lane_efficiency_pct,
                      "cs_by_min": [{"min": m, "lh": _at(p.lh_t, m), "dn": _at(p.dn_t, m)}
                                    for m in range(1, 11)]}
                     for p in match.lane_opponents_of(me)]

        detailed = policy.at_least("laning", EXPANDED)
        gold_xp = ([{"min": m, "gold": _at(me.gold_t, m), "xp": _at(me.xp_t, m)}
                    for m in range(1, 11)] if detailed else [])

        return {
            "me_lane": me.position_label,
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
            "kills_by_type": {
                "нейтралы": p.neutral_kills, "древние": p.ancient_kills,
                "башни": p.tower_kills, "рошан": p.roshan_kills,
                "курьер": p.courier_kills, "обсы": p.observer_kills, "сентри": p.sentry_kills,
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
                verdict = "выиграла моя команда"
            elif my_losses > enemy_losses:
                verdict = "выиграли соперники"
            else:
                verdict = "равный размен"

            mine = tf_players[my_idx] if my_idx < len(tf_players) else {}
            killed = [self._c.npc_to_hero(k) for k, v in (mine.get("killed") or {}).items()
                      if str(k).startswith("npc_dota_hero_") and v]

            out.append({
                "start": mmss(tf.get("start")),
                "end": mmss(tf.get("end")),
                "deaths": tf.get("deaths"),
                "score": f"потери: мы {my_losses} / они {enemy_losses}",
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
        rows = [{"time": mmss(o.time), "event": o.label, "minor": o.minor}
                for o in match.objectives]
        if policy.at_least("objectives", EXPANDED):
            return rows
        return [r for r in rows if not r["minor"]]

    # --- DAMAGE (по героям) ---------------------------------------------------

    def _damage_row(self, p: Player, me: Player) -> Dict[str, Any]:
        top = sorted(p.damage_by_hero.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {"who": self._tag(p, me),
                "targets": [{"hero": self._c.npc_to_hero(k), "dmg": v} for k, v in top]}

"""FeatureExtractor — из нормализованного Match собирает факты по секциям.

Только ФАКТЫ и простые производные (снапшоты, тайминги, суммы, окна). Оценки
«хорошо/плохо» оставляем внешней LLM. Секции покрывают ВСЕХ 10 игроков там, где
это осмысленно (нетворт, скорборд, билды), потому что для разбора важен весь
контекст матча, а не только мои цифры.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .constants import Constants
from .model import Match, Player

LANE_WINDOW_SEC = 600  # окно лайнинга 0..10 мин

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

    def extract(self, match: Match, me: Player, depth: str) -> Features:
        step = 1 if depth == "deep" else 5
        return Features(
            meta=self._meta(match, me),
            draft=self._draft(match, me),
            scoreboard=[self._score_row(p, me) for p in match.players],
            networth=self._networth(match, me, step),
            items=[self._items_row(p, me) for p in match.players],
            abilities=[self._ability_row(p, me) for p in match.players],
            benchmarks=[self._bench_row(p, me) for p in match.players],
            laning=self._laning(match, me),
            combat=[self._combat_row(p, me) for p in match.players],
            buffs=[b for b in (self._buffs_row(p, me) for p in match.players) if b],
            teamfights=self._teamfights(match, me),
            objectives=[{"time": mmss(o.time), "event": o.label} for o in match.objectives],
            damage=[self._damage_row(p, me) for p in match.players],
        )

    # --- helpers по игроку ----------------------------------------------------

    def _tag(self, p: Player, me: Player) -> str:
        who = "★Я " if p is me else ""
        side = "R" if p.is_radiant else "D"
        return f"{who}[{side}] {p.hero_name}"

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

    def _draft(self, match: Match, me: Player) -> Dict[str, Any]:
        picks_bans = [
            {"order": pb.order, "kind": "пик" if pb.is_pick else "БАН",
             "side": pb.side, "hero": pb.hero_name}
            for pb in sorted(match.picks_bans, key=lambda x: x.order)
        ]
        rad = [{"hero": p.hero_name, "pos": p.position_label} for p in match.radiant_players()]
        dire = [{"hero": p.hero_name, "pos": p.position_label} for p in match.dire_players()]
        return {"picks_bans": picks_bans, "radiant": rad, "dire": dire}

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

    # --- NET WORTH TIMELINE ---------------------------------------------------

    def _networth(self, match: Match, me: Player, step: int) -> Dict[str, Any]:
        minutes = max((len(p.gold_t) for p in match.players), default=0)
        idxs = sorted(set(list(range(0, minutes, step)) + ([minutes - 1] if minutes else [])))

        per_player = []
        for p in match.players:
            per_player.append({
                "who": self._tag(p, me),
                "series": [{"m": m, "nw": _at(p.gold_t, m)} for m in idxs],
            })

        # Командные суммы по минутам + преимущество моей команды.
        rad = match.radiant_players()
        dire = match.dire_players()
        team_series = []
        sign = 1 if me.is_radiant else -1
        for m in idxs:
            r = sum(_at(p.gold_t, m) or 0 for p in rad)
            d = sum(_at(p.gold_t, m) or 0 for p in dire)
            adv = _at(match.radiant_gold_adv, m)
            team_series.append({
                "m": m, "radiant": r, "dire": d,
                "my_adv": (sign * adv) if adv is not None else (sign * (r - d)),
            })
        return {"minutes": minutes, "per_player": per_player, "team": team_series,
                "note": "Частота нетворта = 1 точка/мин (это максимальная гранулярность "
                        "OpenDota; секундная точность — только через свой парсер, Тир 3)."}

    # --- ITEMS ----------------------------------------------------------------

    def _items_row(self, p: Player, me: Player) -> Dict[str, Any]:
        timings = [{"time": mmss(e.get("time")), "item": self._c.item_name(e.get("key"))}
                   for e in p.purchase_log]
        return {"who": self._tag(p, me), "timings": timings}

    # --- ABILITY BUILD --------------------------------------------------------

    def _ability_row(self, p: Player, me: Player) -> Dict[str, Any]:
        build = [{"lvl": i + 1, "ability": self._c.ability_name(aid)}
                 for i, aid in enumerate(p.ability_upgrades)]
        return {"who": self._tag(p, me), "build": build}

    # --- BENCHMARKS -----------------------------------------------------------

    def _bench_row(self, p: Player, me: Player) -> Dict[str, Any]:
        rows = []
        for key, label in _BENCH_LABELS.items():
            b = p.benchmarks.get(key)
            if isinstance(b, dict) and b.get("raw") is not None:
                pct = b.get("pct")
                pct_txt = f"перцентиль {round(pct * 100)}" if pct is not None else "?"
                rows.append({"metric": label, "raw": round(b["raw"], 1), "pct": pct_txt})
        return {"who": self._tag(p, me), "rows": rows}

    # --- LANING 0..10 ---------------------------------------------------------

    def _laning(self, match: Match, me: Player) -> Dict[str, Any]:
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

        # Лайн-эффективность всех игроков (для сравнения линий).
        eff = [{"who": self._tag(p, me), "eff_pct": p.lane_efficiency_pct}
               for p in match.players if p.lane_efficiency_pct is not None]

        return {
            "me_lane": me.position_label,
            "me_eff_pct": me.lane_efficiency_pct,
            "cs_by_min": cs,
            "my_kills": my_kills,
            "my_deaths": my_deaths,
            "lane_efficiency_all": eff,
        }

    # --- COMBAT / ECON --------------------------------------------------------

    def _combat_row(self, p: Player, me: Player) -> Dict[str, Any]:
        best_streak = max((int(k) for k in p.kill_streaks), default=0)
        best_multi = max((int(k) for k in p.multi_kills), default=0)
        mh = p.max_hero_hit
        max_hit = None
        if mh.get("value"):
            max_hit = f"{mh['value']} по {self._c.npc_to_hero(mh.get('key'))}"
        return {
            "who": self._tag(p, me),
            "best_streak": best_streak,
            "best_multikill": best_multi,
            "stuns_sec": round(p.stuns, 1),
            "camps_stacked": p.camps_stacked,
            "creeps_stacked": p.creeps_stacked,
            "runes": p.rune_pickups,
            "obs": p.obs_placed,
            "sen": p.sen_placed,
            "buybacks": p.buyback_count,
            "pings": p.pings,
            "apm": p.actions_per_min,
            "time_dead": mmss(p.seconds_dead),
            "max_hit": max_hit,
            "kills_by_type": {
                "нейтралы": p.neutral_kills, "древние": p.ancient_kills,
                "башни": p.tower_kills, "рошан": p.roshan_kills,
                "курьер": p.courier_kills, "обсы": p.observer_kills, "сентри": p.sentry_kills,
            },
        }

    # --- PERMANENT BUFFS ------------------------------------------------------

    def _buffs_row(self, p: Player, me: Player) -> Optional[Dict[str, Any]]:
        if not p.permanent_buffs:
            return None
        buffs = [{"buff_id": b.get("permanent_buff"), "stacks": b.get("stack_count")}
                 for b in p.permanent_buffs]
        return {"who": self._tag(p, me), "buffs": buffs}

    # --- TEAMFIGHTS -----------------------------------------------------------

    def _teamfights(self, match: Match, me: Player) -> List[Dict[str, Any]]:
        out = []
        for tf in match.teamfights:
            tf_players = tf.get("players") or []
            participants = []
            for idx, p in enumerate(match.players):
                if idx >= len(tf_players):
                    continue
                fp = tf_players[idx]
                # Участник, если были смерти/убийства/значимый обмен золотом.
                if (fp.get("deaths") or fp.get("gold_delta") or fp.get("damage")):
                    participants.append({
                        "who": self._tag(p, me),
                        "gold_delta": fp.get("gold_delta"),
                        "xp_delta": fp.get("xp_delta"),
                        "deaths": fp.get("deaths"),
                        "damage": fp.get("damage"),
                        "healing": fp.get("healing"),
                    })
            out.append({
                "start": mmss(tf.get("start")), "end": mmss(tf.get("end")),
                "deaths": tf.get("deaths"), "participants": participants,
                "in_lane": (tf.get("start") or 0) <= LANE_WINDOW_SEC,
            })
        return out

    # --- DAMAGE (по героям) ---------------------------------------------------

    def _damage_row(self, p: Player, me: Player) -> Dict[str, Any]:
        top = sorted(p.damage_by_hero.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {"who": self._tag(p, me),
                "targets": [{"hero": self._c.npc_to_hero(k), "dmg": v} for k, v in top]}

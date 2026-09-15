"""Компактный data-contract интерактивного обзора матча.

`Match` остаётся внутренним языком анализа, а browser не должен разбирать
готовый текст prompt. Этот модуль строит JSON-ready проекцию с рядами,
скорбордом и событиями, достаточную для OpenDota Match Explorer.

Здесь нет тренерских вердиктов. Даже низкий percentile — только сигнал для
проверки: причинность и agency по одной цифре не устанавливаются.
"""

from typing import Any, Dict, List, Optional

from .model import Match, Player


OVERVIEW_SCHEMA_VERSION = 2


def _ints(values) -> List[int]:
    return [int(value or 0) for value in (values or [])]


def _timeline(values) -> List[Dict[str, int]]:
    """Индекс ряда OpenDota — минута матча."""
    return [{"minute": minute, "value": int(value or 0)}
            for minute, value in enumerate(values or [])]


def _turning_points(values) -> List[Dict[str, int]]:
    """Минуты смены стороны перевеса; нули не создают ложный перелом."""
    points: List[Dict[str, int]] = []
    previous_sign = 0
    for minute, raw in enumerate(values or []):
        value = int(raw or 0)
        sign = 1 if value > 0 else (-1 if value < 0 else 0)
        if sign and previous_sign and sign != previous_sign:
            points.append({"minute": minute, "value": value})
        if sign:
            previous_sign = sign
    return points


def _benchmark_signals(me: Player) -> List[Dict[str, Any]]:
    """Самый высокий и низкий hero benchmark без причинного ярлыка."""
    available = []
    for metric, data in (me.benchmarks or {}).items():
        if not isinstance(data, dict) or data.get("pct") is None:
            continue
        try:
            percentile = round(float(data["pct"]) * 100)
        except (TypeError, ValueError):
            continue
        available.append((percentile, metric, data.get("raw")))

    if not available:
        return []

    available.sort(key=lambda item: item[0])
    low, high = available[0], available[-1]
    signals: List[Dict[str, Any]] = []
    if high[0] >= 60:
        signals.append({
            "kind": "strength",
            "metric": high[1],
            "raw": high[2],
            "percentile": high[0],
            "basis": "hero_benchmark",
        })
    if low[0] <= 40 and low[1] != high[1]:
        signals.append({
            "kind": "inspect",
            "metric": low[1],
            "raw": low[2],
            "percentile": low[0],
            "basis": "hero_benchmark",
        })
    return signals


def _player(player: Player, me: Player,
            items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "player_slot": player.player_slot,
        "hero_id": player.hero_id,
        "hero": player.hero_name,
        "is_radiant": player.is_radiant,
        "is_me": player.player_slot == me.player_slot,
        "role": player.position_key,
        "lane": player.lane_key,
        "level": player.level,
        "kills": player.kills,
        "deaths": player.deaths,
        "assists": player.assists,
        "last_hits": player.last_hits,
        "denies": player.denies,
        "gpm": player.gpm,
        "xpm": player.xpm,
        "net_worth": player.net_worth,
        "hero_damage": player.hero_damage,
        "tower_damage": player.tower_damage,
        "hero_healing": player.hero_healing,
        "damage_taken": player.damage_taken_total,
        "lane_efficiency_pct": player.lane_efficiency_pct,
        "series": {
            "net_worth": _ints(player.gold_t),
            "xp": _ints(player.xp_t),
            "last_hits": _ints(player.lh_t),
            "denies": _ints(player.dn_t),
        },
        "items": [
            {
                "time": int(item.get("t", 0) or 0),
                "key": str(item.get("key") or ""),
                "name": str(item.get("item") or item.get("key") or ""),
            }
            for item in (items or []) if item.get("key")
        ],
    }


def _teamfights(match: Match, me: Player) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    me_index: Optional[int] = next(
        (index for index, player in enumerate(match.players)
         if player.player_slot == me.player_slot), None)

    for index, fight in enumerate(match.teamfights or []):
        players = fight.get("players") or []
        radiant_gold = dire_gold = radiant_xp = dire_xp = 0
        for player, entry in zip(match.players, players):
            gold = int(entry.get("gold_delta", 0) or 0)
            xp = int(entry.get("xp_delta", 0) or 0)
            if player.is_radiant:
                radiant_gold += gold
                radiant_xp += xp
            else:
                dire_gold += gold
                dire_xp += xp

        mine = players[me_index] if me_index is not None and me_index < len(players) else {}
        deaths = fight.get("deaths", 0)
        if isinstance(deaths, list):
            deaths = len(deaths)
        result.append({
            "index": index + 1,
            "start": int(fight.get("start", 0) or 0),
            "end": int(fight.get("end", fight.get("last_death", 0)) or 0),
            "deaths": int(deaths or 0),
            "radiant_gold_delta": radiant_gold,
            "dire_gold_delta": dire_gold,
            "radiant_xp_delta": radiant_xp,
            "dire_xp_delta": dire_xp,
            "me": {
                "gold_delta": int(mine.get("gold_delta", 0) or 0),
                "xp_delta": int(mine.get("xp_delta", 0) or 0),
                "damage": int(mine.get("damage", 0) or 0),
                "healing": int(mine.get("healing", 0) or 0),
                "deaths": int(mine.get("deaths", 0) or 0),
            },
        })
    return result


def build_match_overview(match: Match, me: Player,
                         item_timings: Optional[Dict[int, List[Dict[str, Any]]]] = None
                         ) -> Dict[str, Any]:
    """Возвращает versioned JSON-ready обзор без UI-строк и AI-выводов."""
    radiant = match.radiant_players()
    dire = match.dire_players()
    my_team = radiant if me.is_radiant else dire
    gold = _ints(match.radiant_gold_adv)
    xp = _ints(match.radiant_xp_adv)

    return {
        "schema_version": OVERVIEW_SCHEMA_VERSION,
        "quality": {
            "source": "opendota",
            "parsed": match.parsed,
            "timeline_granularity": "minute",
            "has_positions": False,
            "has_tick_data": False,
        },
        "match": {
            "match_id": match.match_id,
            "duration": match.duration,
            "patch": match.patch,
            "game_mode": match.game_mode,
            "lobby_type": match.lobby_type,
            "radiant_win": match.radiant_win,
            "radiant_kills": sum(player.kills for player in radiant),
            "dire_kills": sum(player.kills for player in dire),
        },
        "perspective": {
            "player_slot": me.player_slot,
            "hero_id": me.hero_id,
            "hero": me.hero_name,
            "role": me.position_key,
            "side": "radiant" if me.is_radiant else "dire",
            "win": me.win,
            "team_kills": sum(player.kills for player in my_team),
            "kill_participation_pct": min(100, round(
                100 * (me.kills + me.assists) /
                max(1, sum(player.kills for player in my_team))
            )),
        },
        "signals": _benchmark_signals(me),
        "players": [
            _player(player, me, (item_timings or {}).get(player.player_slot))
            for player in match.players
        ],
        "economy": {
            "radiant_gold_adv": gold,
            "radiant_xp_adv": xp,
            "gold_points": _timeline(gold),
            "xp_points": _timeline(xp),
            "gold_turning_points": _turning_points(gold),
            "xp_turning_points": _turning_points(xp),
        },
        "draft": {
            # Captains Mode хранит настоящую хронологию. All Draft обычно
            # группирует сначала пики, затем баны; UI обязан показать их двумя
            # честными группами, а не выдумывать последовательность действий.
            "chronological": match.draft_is_chronological,
            "picks": [
                {"order": pick.order, "hero": pick.hero_name,
                 "side": pick.side.lower()}
                for pick in sorted(match.picks_bans, key=lambda item: item.order)
                if pick.is_pick
            ],
            "bans": [
                {"order": pick.order, "hero": pick.hero_name,
                 "side": pick.side.lower()}
                for pick in sorted(match.picks_bans, key=lambda item: item.order)
                if not pick.is_pick
            ],
        },
        "objectives": [
            {
                "time": objective.time,
                "kind": objective.kind,
                "type": objective.type,
                "team": objective.team,
                "minor": objective.minor,
                "params": objective.params,
            }
            for objective in match.objectives
        ],
        "teamfights": _teamfights(match, me),
    }

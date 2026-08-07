"""Нормализация: сырой JSON OpenDota -> внутренняя модель Match.

Здесь и только здесь живёт знание о формате OpenDota. Если завтра поменяется API
или появится другой источник — правим/добавляем нормализатор, остальное не трогаем.

Всё через .get с дефолтами: если матч распарсен не полностью, недостающие поля
просто станут пустыми/нулевыми, а не уронят программу.
"""

from typing import Any, Dict, List, Optional

from .constants import Constants
from .model import Match, Objective, PickBan, Player

_LANE_NAMES = {1: "safe lane", 2: "mid", 3: "off lane", 4: "jungle"}


def from_opendota(raw: Dict[str, Any], constants: Constants) -> Match:
    radiant_win = bool(raw.get("radiant_win"))
    players: List[Player] = [_player(p, radiant_win, constants) for p in raw.get("players", [])]

    _assign_positions([p for p in players if p.is_radiant])
    _assign_positions([p for p in players if not p.is_radiant])

    objectives = [o for o in (_objective(o, constants) for o in (raw.get("objectives") or [])) if o]
    picks_bans = [_pick_ban(pb, constants) for pb in (raw.get("picks_bans") or [])]

    return Match(
        match_id=raw.get("match_id"),
        duration=raw.get("duration") or 0,
        game_mode=constants.game_mode_name(raw.get("game_mode")),
        lobby_type=constants.lobby_type_name(raw.get("lobby_type")),
        patch=constants.patch_name(raw.get("patch")),
        radiant_win=radiant_win,
        parsed=raw.get("version") is not None,
        region=raw.get("region"),
        players=players,
        picks_bans=picks_bans,
        objectives=objectives,
        teamfights=raw.get("teamfights") or [],
        radiant_gold_adv=raw.get("radiant_gold_adv") or [],
        radiant_xp_adv=raw.get("radiant_xp_adv") or [],
    )


def _player(p: Dict[str, Any], radiant_win: bool, constants: Constants) -> Player:
    slot = p.get("player_slot", 0)
    is_radiant = slot < 128
    hero_id = p.get("hero_id", 0)
    life_state = p.get("life_state") or {}

    # damage: {npc_name -> урон}. Оставляем только урон по героям.
    damage = p.get("damage") or {}
    damage_by_hero = {k: v for k, v in damage.items() if str(k).startswith("npc_dota_hero_")}

    return Player(
        account_id=p.get("account_id"),
        player_slot=slot,
        is_radiant=is_radiant,
        win=(is_radiant == radiant_win),
        hero_id=hero_id,
        hero_name=constants.hero_name(hero_id),
        personaname=p.get("personaname"),
        lane_role=p.get("lane_role"),
        is_roaming=bool(p.get("is_roaming")),
        lane_efficiency_pct=p.get("lane_efficiency_pct"),
        lane_pos=p.get("lane_pos") or {},
        level=p.get("level", 0),
        kills=p.get("kills", 0),
        deaths=p.get("deaths", 0),
        assists=p.get("assists", 0),
        last_hits=p.get("last_hits", 0),
        denies=p.get("denies", 0),
        gpm=p.get("gold_per_min", 0),
        xpm=p.get("xp_per_min", 0),
        net_worth_final=p.get("net_worth", 0) or p.get("total_gold", 0),
        hero_damage=p.get("hero_damage", 0),
        tower_damage=p.get("tower_damage", 0),
        hero_healing=p.get("hero_healing", 0),
        damage_taken_total=sum((p.get("damage_taken") or {}).values()),
        gold_t=p.get("gold_t") or [],
        xp_t=p.get("xp_t") or [],
        lh_t=p.get("lh_t") or [],
        dn_t=p.get("dn_t") or [],
        purchase_log=p.get("purchase_log") or [],
        ability_upgrades=p.get("ability_upgrades_arr") or [],
        permanent_buffs=p.get("permanent_buffs") or [],
        kills_log=p.get("kills_log") or [],
        kill_streaks=p.get("kill_streaks") or {},
        multi_kills=p.get("multi_kills") or {},
        stuns=p.get("stuns") or 0.0,
        max_hero_hit=p.get("max_hero_hit") or {},
        damage_by_hero=damage_by_hero,
        camps_stacked=p.get("camps_stacked", 0) or 0,
        creeps_stacked=p.get("creeps_stacked", 0) or 0,
        rune_pickups=p.get("rune_pickups", 0) or 0,
        obs_placed=p.get("obs_placed", 0) or 0,
        sen_placed=p.get("sen_placed", 0) or 0,
        buyback_count=p.get("buyback_count", 0) or 0,
        pings=p.get("pings", 0) or 0,
        actions_per_min=p.get("actions_per_min", 0) or 0,
        seconds_dead=int(life_state.get("2", 0)),
        neutral_kills=p.get("neutral_kills", 0) or 0,
        ancient_kills=p.get("ancient_kills", 0) or 0,
        tower_kills=p.get("tower_kills", 0) or 0,
        roshan_kills=p.get("roshan_kills", 0) or 0,
        courier_kills=p.get("courier_kills", 0) or 0,
        observer_kills=p.get("observer_kills", 0) or 0,
        sentry_kills=p.get("sentry_kills", 0) or 0,
        benchmarks=p.get("benchmarks") or {},
    )


def _lane_name(p: Player) -> str:
    if p.is_roaming:
        return "roaming"
    return _LANE_NAMES.get(p.lane_role, "unknown")


def _assign_positions(team: List[Player]) -> None:
    """Грубая эвристика позиций 1..5 (линия + ранг по нетворту)."""
    lanes: Dict[str, List[Player]] = {}
    for p in team:
        lanes.setdefault(_lane_name(p), []).append(p)
    for lane_name, ps in lanes.items():
        ps.sort(key=lambda pl: pl.net_worth, reverse=True)
        for i, p in enumerate(ps):
            is_core = (lane_name == "mid") or (i == 0 and lane_name in ("safe lane", "off lane"))
            p.position_label = _format_position(lane_name, is_core)


def _format_position(lane_name: str, is_core: bool) -> str:
    pos_map = {
        ("mid", True): "поз. 2 — mid",
        ("safe lane", True): "поз. 1 — carry (safe lane)",
        ("safe lane", False): "поз. 5 — hard support (safe lane)",
        ("off lane", True): "поз. 3 — offlane",
        ("off lane", False): "поз. 4 — support (off lane)",
    }
    if (lane_name, is_core) in pos_map:
        return pos_map[(lane_name, is_core)]
    role = "core" if is_core else "support"
    return f"{role} ({lane_name})"


def _pick_ban(pb: Dict[str, Any], constants: Constants) -> PickBan:
    return PickBan(
        order=pb.get("order", 0),
        is_pick=bool(pb.get("is_pick")),
        hero_name=constants.hero_name(pb.get("hero_id")),
        side="Radiant" if pb.get("team") == 0 else "Dire",
    )


def _objective(o: Dict[str, Any], constants: Constants) -> Optional[Objective]:
    t = o.get("type", "")
    time = o.get("time", 0)

    if t == "CHAT_MESSAGE_FIRSTBLOOD":
        return Objective(time=time, type=t, label="первая кровь")
    if t == "building_kill":
        key = o.get("key", "") or ""
        owner = "Dire" if "badguys" in key else ("Radiant" if "goodguys" in key else "?")
        short = key.replace("npc_dota_", "").replace("goodguys_", "").replace("badguys_", "")
        kind = "казарма" if ("rax" in key or "melee" in key or "range" in key) else "вышка"
        return Objective(time=time, type=t, label=f"{owner}: снесена {kind} ({short})")
    if t == "CHAT_MESSAGE_ROSHAN_KILL":
        team = o.get("team")
        who = "Radiant" if team == 2 else ("Dire" if team == 3 else "?")
        return Objective(time=time, type=t, label=f"{who} убил Рошана", team=team)
    if t == "CHAT_MESSAGE_AEGIS":
        return Objective(time=time, type=t, label="подобран Aegis")
    return None

"""Внутренняя нормализованная модель матча.

Это «общий язык» приложения. Любой источник данных (сейчас OpenDota, позже —
собственный парсер реплеев) обязан отдать именно эти объекты. Всё, что идёт
после источника (FeatureExtractor, BundleBuilder), знает только про эту модель
и не догадывается, откуда данные пришли. В этом и смысл Data Source Adapter.

v0.2: модель расширена под «выжимаем из OpenDota максимум» — детальный
скорборд, бенчмарки-перцентили, билд предметов и способностей, лайн-метрики,
боевые/экономические счётчики, тимфайты.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Objective:
    """Событие-объектив: башня, Рошан, первая кровь и т.п."""
    time: int
    type: str
    label: str
    team: Optional[int] = None      # 2 = Radiant, 3 = Dire (где применимо)
    minor: bool = False             # рутина (t1-вышки, курьер) — прячем в сводке


@dataclass
class PickBan:
    """Один пик или бан из фазы драфта (есть только в Captains Mode)."""
    order: int
    is_pick: bool
    hero_name: str
    side: str                       # "Radiant" / "Dire"


@dataclass
class Player:
    # --- идентификация ---
    account_id: Optional[int]
    player_slot: int
    is_radiant: bool
    win: bool
    hero_id: int
    hero_name: str
    personaname: Optional[str] = None

    # --- позиция / линия ---
    lane_role: Optional[int] = None
    lane: Optional[int] = None          # физическая линия (1/2/3) — для поиска оппонентов
    is_roaming: bool = False
    position_label: str = ""
    is_core: bool = False               # кор или саппорт (эвристика по линии + нетворту)
    lane_efficiency_pct: Optional[int] = None
    lane_pos: Dict[str, Any] = field(default_factory=dict)

    # --- итоговый скорборд ---
    level: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    denies: int = 0
    gpm: int = 0
    xpm: int = 0
    net_worth_final: int = 0
    hero_damage: int = 0
    tower_damage: int = 0
    hero_healing: int = 0
    damage_taken_total: int = 0

    # --- поминутные ряды (индекс = минута) ---
    gold_t: List[int] = field(default_factory=list)    # кумулятивный нетворт
    xp_t: List[int] = field(default_factory=list)
    lh_t: List[int] = field(default_factory=list)
    dn_t: List[int] = field(default_factory=list)

    # --- билды ---
    purchase_log: List[Dict[str, Any]] = field(default_factory=list)   # [{time, key}]
    ability_upgrades: List[int] = field(default_factory=list)          # id по уровням
    permanent_buffs: List[Dict[str, Any]] = field(default_factory=list)

    # --- бой / логи ---
    kills_log: List[Dict[str, Any]] = field(default_factory=list)
    kill_streaks: Dict[str, int] = field(default_factory=dict)
    multi_kills: Dict[str, int] = field(default_factory=dict)
    stuns: float = 0.0
    max_hero_hit: Dict[str, Any] = field(default_factory=dict)
    damage_by_hero: Dict[str, int] = field(default_factory=dict)       # npc -> урон

    # --- экономика / карта ---
    camps_stacked: int = 0
    creeps_stacked: int = 0
    rune_pickups: int = 0
    obs_placed: int = 0
    sen_placed: int = 0
    buyback_count: int = 0
    pings: int = 0
    actions_per_min: int = 0
    seconds_dead: int = 0
    neutral_kills: int = 0
    ancient_kills: int = 0
    tower_kills: int = 0
    roshan_kills: int = 0
    courier_kills: int = 0
    observer_kills: int = 0
    sentry_kills: int = 0

    # --- бенчмарки OpenDota: {metric: {"raw": x, "pct": 0..1}} ---
    benchmarks: Dict[str, Any] = field(default_factory=dict)

    @property
    def net_worth(self) -> int:
        if self.net_worth_final:
            return self.net_worth_final
        return self.gold_t[-1] if self.gold_t else 0


@dataclass
class Match:
    match_id: int
    duration: int
    game_mode: str
    lobby_type: str
    patch: str
    radiant_win: bool
    parsed: bool
    region: Optional[int] = None
    players: List[Player] = field(default_factory=list)
    picks_bans: List[PickBan] = field(default_factory=list)
    objectives: List[Objective] = field(default_factory=list)
    teamfights: List[Dict[str, Any]] = field(default_factory=list)
    radiant_gold_adv: List[int] = field(default_factory=list)
    radiant_xp_adv: List[int] = field(default_factory=list)

    def radiant_players(self) -> List[Player]:
        return [p for p in self.players if p.is_radiant]

    def dire_players(self) -> List[Player]:
        return [p for p in self.players if not p.is_radiant]

    def enemies_of(self, me: Player) -> List[Player]:
        return [p for p in self.players if p.is_radiant != me.is_radiant]

    def lane_opponents_of(self, me: Player) -> List[Player]:
        """Соперники по линии: та же физическая линия, другая сторона."""
        if me.lane is None:
            return []
        return [p for p in self.enemies_of(me) if p.lane == me.lane]

    @property
    def draft_is_chronological(self) -> bool:
        """True, если picks_bans идут в реальном порядке драфта (пики и баны вперемешку).

        В Captains Mode `order` — настоящая хронология. В all draft / all pick
        OpenDota отдаёт сначала все пики, потом все баны, и восстановить истинный
        порядок невозможно — врать об этом мы не будем.
        """
        kinds = [pb.is_pick for pb in sorted(self.picks_bans, key=lambda x: x.order)]
        if not kinds:
            return False
        # Признак «сгруппировано»: сначала подряд все пики, потом подряд все баны.
        grouped = (True in kinds) and (False in kinds) and kinds == sorted(kinds, reverse=True)
        return not grouped

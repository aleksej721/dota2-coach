"""Аномалии — статистически необычное в данных матча.

Зачем отдельный модуль. Можно было бы вписать в промпт правило «всегда проверяй
тайминг BKB» — но такой список пришлось бы вести руками, и он всё равно отстал бы
от патча и от матчапа. Вместо этого мы ищем ОТКЛОНЕНИЯ в самих данных: предмет,
выбивающийся из темпа собственной сборки; перцентиль на краю распределения; провал
в кривой золота; кластер смертей. «Поздний BKB» всплывает как следствие, а не как
захардкоженный вопрос — и ровно так же всплывёт любой другой предмет.

Оценок здесь нет: как и везде в проекте, наружу идёт факт и его контекст. Что это
значило, решает внешняя модель — аномалии для неё сырьё, из которого она строит
гипотезы (см. scaffold.py, раздел «Гипотезы о причине исхода»).

Каждое отклонение помечено ОСЬЮ (draft/build/farm/fights/position/lane): это
подсказка, к какой гипотезе его цеплять, а не вердикт.
"""

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .constants import Constants
from .model import Match, Player

# Сколько отклонений максимум уходит в промпт. Больше — и секция сама
# превращается в шум, от которого мы уходили.
MAX_ANOMALIES = 7

# Перцентиль считаем необычным, если он у края распределения.
PCT_LOW, PCT_HIGH = 20, 80
# Разброс между лучшей и худшей метрикой — сигнал «одно есть, другого нет».
PCT_SPREAD = 45

# Предмет «опаздывает», если он отстал от собственного темпа сборки. Базовый
# сдвиг (расходники, варды, выкупы) вычитается медианой по всей сборке, поэтому
# порог здесь — про отклонение ОТ СЕБЯ, а не про абсолютный тайминг.
ITEM_MIN_COST = 1000
ITEM_LAG_MIN_MINUTES = 3.0
ITEM_LAG_FACTOR = 1.15
MAX_ITEM_LAGS = 2

# Провал в фарме: участок, где мой доход просел относительно личного среднего.
STALL_MIN_LENGTH = 4
STALL_RATIO = 0.6
STALL_NOT_BEFORE_MIN = 8

# Смерти, сбитые в кучу, — почти всегда один эпизод, а не разрозненные ошибки.
CLUSTER_SPAN_SEC = 300
CLUSTER_MIN_DEATHS = 3

# Доля времени мёртвым против медианы остальных игроков матча.
DEAD_SHARE_MIN = 0.10
DEAD_SHARE_FACTOR = 1.5

LANE_GAP_MIN = 15
KP_LOW, KP_HIGH = 40, 85

# Обвал перевеса: сколько золота команда теряет за окно, чтобы это был сюжет.
COLLAPSE_WINDOW_MIN = 5
COLLAPSE_GOLD_MIN = 5000

# Сколько перцентилей у краёв показываем. Низких — до трёх: провал почти всегда
# диагностичен. Высоких — один, самый крайний: пять строк «верх распределения»
# подряд говорят ровно то же, что одна, и вытесняют более полезные отклонения.
MAX_LOW_PERCENTILES = 3
MAX_HIGH_PERCENTILES = 1

# Метрика бенчмарка -> ось гипотезы. Один и тот же перцентиль ведёт к разным
# версиям: провал по добиваниям — это про фарм, провал по урону — про бои.
#
# Заодно это белый список: OpenDota отдаёт метрик больше, чем у нас есть подписей
# в bench.*, и без фильтра в промпт утекал бы маркер несуществующего перевода.
_METRIC_AXIS = {
    "gold_per_min": "farm",
    "xp_per_min": "farm",
    "last_hits_per_min": "farm",
    "hero_damage_per_min": "fights",
    "hero_healing_per_min": "fights",
    "kills_per_min": "fights",
    "stuns_per_min": "fights",
    "tower_damage": "fights",
}


@dataclass(frozen=True)
class Anomaly:
    """Одно отклонение: ключ текста, ось гипотезы, параметры для подстановки.

    Готовой фразы здесь нет — её соберёт bundle на языке промпта, как и всё
    остальное в проекте.
    """

    key: str
    axis: str
    params: Dict[str, Any] = field(default_factory=dict)
    # 0..1 — только для отбора топа. В промпт не печатается: точность такой
    # оценки мнимая, а игрок начал бы читать её как «важность».
    severity: float = 0.0


def _mmss(seconds: Optional[float]) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class AnomalyDetector:
    """Набор независимых детекторов поверх нормализованного Match.

    Каждый детектор молча возвращает пустой список, если нужных данных нет:
    нераспарсенный матч не должен ронять разбор, он просто даёт меньше сигнала.
    """

    def __init__(self, constants: Constants):
        self._c = constants

    def detect(self, match: Match, me: Player,
               build: Sequence[Dict[str, Any]]) -> List[Anomaly]:
        """`build` — собранная сборка ★ из FeatureExtractor (без компонентов).

        Приходит снаружи намеренно: алгоритм поглощения компонентов живёт в
        features.py, и дублировать его здесь ради одной проверки незачем.
        """
        found: List[Anomaly] = []
        found += self._item_lag(me, build)
        found += self._bench_edges(me)
        found += self._bench_spread(me)
        found += self._farm_stall(me)
        found += self._death_cluster(match, me)
        found += self._dead_share(match, me)
        found += self._lane_gap(match, me)
        found += self._kill_participation(match, me)
        found += self._gold_collapse(match, me)

        found.sort(key=lambda a: a.severity, reverse=True)
        return found[:MAX_ANOMALIES]

    # --- сборка ---------------------------------------------------------------

    def _item_lag(self, me: Player,
                  build: Sequence[Dict[str, Any]]) -> List[Anomaly]:
        """Предметы, отставшие от темпа СОБСТВЕННОЙ сборки.

        Ожидаемая минута предмета = накопленная стоимость сборки / GPM. Это
        систематически оптимистично (расходники, варды и выкупы в стоимость не
        входят), поэтому абсолютное отставание ни о чём не говорит: у саппорта
        оно велико у каждого предмета. Значимо только превышение над МЕДИАНОЙ
        отставания по всей сборке — то есть «этот предмет опоздал даже по твоим
        собственным меркам».
        """
        if not me.gpm or not build:
            return []

        rows: List[Tuple[Dict[str, Any], float, float]] = []
        cumulative = 0
        for item in build:
            cost = self._c.item_cost(item.get("key"))
            if cost <= 0 or item.get("t") is None:
                continue
            cumulative += cost
            actual = item["t"] / 60.0
            expected = cumulative / me.gpm
            rows.append((item, actual, expected))

        if len(rows) < 3:  # на двух точках медиана отставания ничего не значит
            return []

        baseline = median(actual - expected for _, actual, expected in rows)

        out: List[Anomaly] = []
        for item, actual, expected in rows:
            if self._c.item_cost(item.get("key")) < ITEM_MIN_COST:
                continue
            excess = (actual - expected) - baseline
            if excess < ITEM_LAG_MIN_MINUTES or actual < expected * ITEM_LAG_FACTOR:
                continue
            out.append(Anomaly(
                key="anom.item_lag", axis="build",
                params={"item": item["item"], "at": item["time"],
                        "excess": round(excess), "gpm": me.gpm,
                        "expected": _mmss((expected + baseline) * 60)},
                severity=_clamp(excess / 12.0),
            ))

        out.sort(key=lambda a: a.severity, reverse=True)
        return out[:MAX_ITEM_LAGS]

    # --- бенчмарки ------------------------------------------------------------

    @staticmethod
    def _percentiles(me: Player) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for metric, b in (me.benchmarks or {}).items():
            if metric not in _METRIC_AXIS:
                continue
            if isinstance(b, dict) and b.get("pct") is not None:
                out[metric] = round(b["pct"] * 100)
        return out

    def _bench_edges(self, me: Player) -> List[Anomaly]:
        lows: List[Anomaly] = []
        highs: List[Anomaly] = []
        for metric, pct in self._percentiles(me).items():
            axis = _METRIC_AXIS[metric]
            params = {"metric_key": metric, "pct": pct}
            if pct <= PCT_LOW:
                lows.append(Anomaly(key="anom.bench_low", axis=axis, params=params,
                                    severity=_clamp(0.45 + (PCT_LOW - pct) / 30.0)))
            elif pct >= PCT_HIGH:
                highs.append(Anomaly(key="anom.bench_high", axis=axis, params=params,
                                     severity=_clamp(0.25 + (pct - PCT_HIGH) / 60.0)))

        lows.sort(key=lambda a: a.severity, reverse=True)
        highs.sort(key=lambda a: a.severity, reverse=True)
        return lows[:MAX_LOW_PERCENTILES] + highs[:MAX_HIGH_PERCENTILES]

    def _bench_spread(self, me: Player) -> List[Anomaly]:
        """Разрыв между лучшей и худшей метрикой — «одно вытянул, другое нет»."""
        pcts = self._percentiles(me)
        if len(pcts) < 2:
            return []
        best = max(pcts, key=lambda m: pcts[m])
        worst = min(pcts, key=lambda m: pcts[m])
        spread = pcts[best] - pcts[worst]
        if spread < PCT_SPREAD:
            return []
        return [Anomaly(
            key="anom.bench_spread", axis="fights",
            params={"high_key": best, "high": pcts[best],
                    "low_key": worst, "low": pcts[worst]},
            severity=_clamp(0.3 + (spread - PCT_SPREAD) / 50.0),
        )]

    # --- фарм -----------------------------------------------------------------

    def _farm_stall(self, me: Player) -> List[Anomaly]:
        """Самый длинный участок, где мой доход просел против личного среднего."""
        gold = me.gold_t
        if len(gold) < STALL_NOT_BEFORE_MIN + STALL_MIN_LENGTH + 1:
            return []

        deltas = [gold[m] - gold[m - 1] for m in range(1, len(gold))]
        average = sum(deltas) / len(deltas)
        if average <= 0:
            return []

        threshold = average * STALL_RATIO
        best: Optional[Tuple[int, int]] = None
        start: Optional[int] = None
        for i, delta in enumerate(deltas):
            minute = i + 1
            if delta < threshold and minute >= STALL_NOT_BEFORE_MIN:
                start = minute if start is None else start
                if best is None or (minute - start) > (best[1] - best[0]):
                    best = (start, minute)
            else:
                start = None

        if best is None or (best[1] - best[0] + 1) < STALL_MIN_LENGTH:
            return []

        span = gold[best[1]] - gold[best[0] - 1]
        rate = round(span / (best[1] - best[0] + 1))
        return [Anomaly(
            key="anom.farm_stall", axis="farm",
            params={"start": best[0], "end": best[1], "rate": rate,
                    "average": round(average)},
            severity=_clamp(0.3 + (best[1] - best[0]) / 12.0),
        )]

    # --- смерти и позиционирование --------------------------------------------

    def _death_times(self, match: Match, me: Player) -> List[int]:
        npc = self._c.hero_npc(me.hero_id)
        if not npc:
            return []
        times = [int(e.get("time") or 0)
                 for enemy in match.enemies_of(me)
                 for e in enemy.kills_log if e.get("key") == npc]
        return sorted(t for t in times if t >= 0)

    def _death_cluster(self, match: Match, me: Player) -> List[Anomaly]:
        times = self._death_times(match, me)
        if len(times) < CLUSTER_MIN_DEATHS:
            return []

        best: Tuple[int, int, int] = (0, 0, 0)  # (сколько, начало, конец)
        left = 0
        for right in range(len(times)):
            while times[right] - times[left] > CLUSTER_SPAN_SEC:
                left += 1
            count = right - left + 1
            if count > best[0]:
                best = (count, times[left], times[right])

        if best[0] < CLUSTER_MIN_DEATHS:
            return []
        return [Anomaly(
            key="anom.death_cluster", axis="position",
            params={"count": best[0], "start": _mmss(best[1]), "end": _mmss(best[2]),
                    "total": len(times)},
            severity=_clamp(0.35 + (best[0] - CLUSTER_MIN_DEATHS) / 5.0),
        )]

    @staticmethod
    def _dead_share(match: Match, me: Player) -> List[Anomaly]:
        others = [p.seconds_dead for p in match.players if p is not me and p.seconds_dead]
        if not match.duration or not me.seconds_dead or not others:
            return []

        share = me.seconds_dead / match.duration
        typical = median(others)
        if share < DEAD_SHARE_MIN or me.seconds_dead < typical * DEAD_SHARE_FACTOR:
            return []
        return [Anomaly(
            key="anom.dead_share", axis="position",
            params={"dead": _mmss(me.seconds_dead), "pct": round(share * 100),
                    "typical": _mmss(typical)},
            severity=_clamp(0.3 + share),
        )]

    # --- линия и бои ----------------------------------------------------------

    @staticmethod
    def _lane_gap(match: Match, me: Player) -> List[Anomaly]:
        opponents = [p for p in match.lane_opponents_of(me)
                     if p.lane_efficiency_pct is not None]
        if me.lane_efficiency_pct is None or not opponents:
            return []

        theirs = round(median(p.lane_efficiency_pct for p in opponents))
        gap = me.lane_efficiency_pct - theirs
        if abs(gap) < LANE_GAP_MIN:
            return []
        return [Anomaly(
            key="anom.lane_gap_ahead" if gap > 0 else "anom.lane_gap_behind",
            axis="lane",
            params={"mine": me.lane_efficiency_pct, "theirs": theirs, "gap": abs(gap)},
            severity=_clamp(0.3 + abs(gap) / 60.0),
        )]

    @staticmethod
    def _kill_participation(match: Match, me: Player) -> List[Anomaly]:
        team = match.radiant_players() if me.is_radiant else match.dire_players()
        team_kills = sum(p.kills for p in team)
        if not team_kills:
            return []

        pct = min(100, round(100 * (me.kills + me.assists) / team_kills))
        if KP_LOW < pct < KP_HIGH:
            return []
        return [Anomaly(
            key="anom.kp_low" if pct <= KP_LOW else "anom.kp_high", axis="fights",
            params={"pct": pct, "kills": me.kills, "assists": me.assists,
                    "team_kills": team_kills},
            severity=_clamp(0.3 + abs(pct - 60) / 60.0),
        )]

    @staticmethod
    def _gold_collapse(match: Match, me: Player) -> List[Anomaly]:
        """Окно, где перевес моей команды по золоту менялся быстрее всего.

        Именно там обычно и «поехала» игра, а по кривым это видно не сразу.
        """
        sign = 1 if me.is_radiant else -1
        adv = [sign * v for v in match.radiant_gold_adv]
        if len(adv) <= COLLAPSE_WINDOW_MIN:
            return []

        worst = (0, 0, 0)  # (изменение, начало, конец)
        for start in range(len(adv) - COLLAPSE_WINDOW_MIN):
            end = start + COLLAPSE_WINDOW_MIN
            change = adv[end] - adv[start]
            if change < worst[0]:
                worst = (change, start, end)

        if -worst[0] < COLLAPSE_GOLD_MIN:
            return []
        return [Anomaly(
            key="anom.gold_collapse", axis="fights",
            params={"start": worst[1], "end": worst[2], "gold": -worst[0]},
            severity=_clamp(0.35 + (-worst[0]) / 20000.0),
        )]

"""Профиль игрока: кросс-матчевая агрегация без БД.

Один матч отвечает на вопрос «что случилось». Десяток матчей отвечает на другой,
более полезный: «что у меня повторяется». Второй вопрос требует не больше данных,
а других данных — поэтому это отдельный агрегатор, а не десять обычных промптов
подряд.

Здесь принцип «сигнал > объём» работает жёстче, чем где-либо ещё. Полные данные
десяти матчей — это сотни килобайт, в которых утонет любая модель, и заодно
кончится контекст. Наружу уходит только:

  * средние и разброс по ключевым метрикам;
  * тренд перцентилей (растёт/падает), а не перцентиль каждого матча;
  * ПОВТОРЯЮЩИЕСЯ аномалии — те, что встретились в существенной доле матчей;
  * профиль по стадиям игры: на каких минутах перевес систематически уходит;
  * по ОДНОЙ строке итога на матч.

Само определение «повторяющегося» переиспользует anomalies.py: паттерн — это
отклонение, случившееся не однажды. Отдельного списка «типичных ошибок» нет и
здесь: он так же устарел бы, как и список важных предметов.

Состояние не хранится: агрегация живёт в памяти на время запроса.
"""

from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .anomalies import Anomaly, AnomalyDetector
from .features import mmss
from .model import Match, Player
from .policy import ROLES

# Сколько матчей вообще имеет смысл просить. Меньше двух — это не профиль,
# а один матч; больше двадцати — минуты ожидания на лимите 1 запрос/сек и
# усреднение по разным патчам, где выводы уже сомнительны.
MIN_MATCHES, MAX_MATCHES, DEFAULT_MATCHES = 2, 20, 10

# Отклонение становится «паттерном», если встретилось хотя бы в этой доле
# матчей и минимум дважды. Один раз — случайность, дважды из трёх — уже привычка.
PATTERN_SHARE = 0.4
PATTERN_MIN_COUNT = 2

# Стадии игры для профиля перевеса. Шаг в 5 минут — компромисс: мельче даёт шум
# на выборке из десяти матчей, крупнее смазывает переход «мид-гейм → лейт».
STAGE_STEP_MIN = 5
STAGE_LAST = 45          # всё после этой минуты сваливаем в одну корзину
MAX_WEAK_STAGES = 2

# Поминутные ряды есть только у распарсенных матчей, поэтому стадии часто
# опираются на меньшую выборку, чем весь профиль. Ниже этого числа матчей слово
# «систематически» — вымысел: один матч не бывает системой.
STAGE_MIN_SAMPLES = 2

# Метрики, по которым считаем тренд перцентилей. Порядок — порядок вывода.
TREND_METRICS = ("gold_per_min", "xp_per_min", "last_hits_per_min",
                 "hero_damage_per_min", "hero_healing_per_min", "stuns_per_min")

# Тренд объявляем только при заметной разнице между первой и второй половиной
# выборки: на десяти матчах ±5 перцентилей — это шум, а не динамика.
TREND_MIN_DELTA = 8

# lane_role в OpenDota: 1 safe / 2 mid / 3 off. Позиции 4 и 5 отдельного
# lane_role не имеют, поэтому фильтр по ним отдаём как линию их пары.
ROLE_TO_LANE_ROLE = {"1": 1, "2": 2, "3": 3, "4": 3, "5": 1}


@dataclass
class MatchDigest:
    """Один матч — одна строка. Всё, что не влезло, здесь и не нужно."""

    match_id: int
    hero: str
    role: str
    win: bool
    duration: str
    kda: str
    gpm: int
    xpm: int
    cs10: Optional[int]
    net_worth: int
    kill_participation: int
    lane_eff: Optional[int]
    parsed: bool
    # Оси аномалий этого матча — чтобы в сводке было видно, где он «сломался».
    axes: List[str] = field(default_factory=list)


@dataclass
class ProfileFeatures:
    account_id: int = 0
    requested: int = 0
    hero_filter: Optional[str] = None
    role_filter: Optional[str] = None
    digests: List[MatchDigest] = field(default_factory=list)
    averages: Dict[str, Any] = field(default_factory=dict)
    trends: List[Dict[str, Any]] = field(default_factory=list)
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    stages: Dict[str, Any] = field(default_factory=dict)
    heroes: List[Dict[str, Any]] = field(default_factory=list)
    caveats: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)

    @property
    def analyzed(self) -> int:
        return len(self.digests)


def _avg(values: Sequence[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return mean(clean) if clean else None


def _round(value: Optional[float], digits: int = 0) -> Optional[Any]:
    if value is None:
        return None
    return round(value) if digits == 0 else round(value, digits)


class ProfileAggregator:
    """Match + «кто из игроков я» -> кросс-матчевая выжимка.

    Матчи приходят уже загруженными: качать их — дело источника, а сводить —
    это здесь. Разделение то же, что между DataSource и FeatureExtractor.
    """

    def __init__(self, detector: AnomalyDetector, extractor):
        self._detector = detector
        # Экстрактор нужен ровно за одним: собрать сборку предметов тем же
        # алгоритмом поглощения компонентов, что и в разборе одного матча.
        self._extractor = extractor

    def aggregate(self, account_id: int, pairs: Sequence[Tuple[Match, Player]],
                 requested: int, hero_filter: Optional[str] = None,
                 role_filter: Optional[str] = None) -> ProfileFeatures:
        out = ProfileFeatures(account_id=account_id, requested=requested,
                              hero_filter=hero_filter, role_filter=role_filter)

        anomalies_by_match: List[List[Anomaly]] = []
        for match, me in pairs:
            found = self._detector.detect(
                match, me, self._extractor._assembled_purchases(me, min_cost=0))
            anomalies_by_match.append(found)
            out.digests.append(self._digest(match, me, found))

        if not out.digests:
            return out

        out.averages = self._averages(pairs, out.digests)
        out.trends = self._trends(pairs)
        out.patterns = self._patterns(anomalies_by_match)
        out.stages = self._stages(pairs)
        out.heroes = self._heroes(out.digests)
        out.caveats = self._caveats(out, pairs)
        return out

    # --- по одному матчу ------------------------------------------------------

    @staticmethod
    def _kill_participation(match: Match, me: Player) -> int:
        team = match.radiant_players() if me.is_radiant else match.dire_players()
        team_kills = sum(p.kills for p in team)
        if not team_kills:
            return 0
        return min(100, round(100 * (me.kills + me.assists) / team_kills))

    def _digest(self, match: Match, me: Player, found: Sequence[Anomaly]) -> MatchDigest:
        return MatchDigest(
            match_id=match.match_id,
            hero=me.hero_name,
            role=me.position_key,
            win=me.win,
            duration=mmss(match.duration),
            kda=f"{me.kills}/{me.deaths}/{me.assists}",
            gpm=me.gpm,
            xpm=me.xpm,
            cs10=me.lh_t[10] if len(me.lh_t) > 10 else None,
            net_worth=me.net_worth,
            kill_participation=self._kill_participation(match, me),
            lane_eff=me.lane_efficiency_pct,
            parsed=match.parsed,
            # Дубли осей не нужны: важно, ЧТО сломалось, а не сколько раз.
            axes=sorted({a.axis for a in found}),
        )

    # --- средние --------------------------------------------------------------

    def _averages(self, pairs: Sequence[Tuple[Match, Player]],
                  digests: Sequence[MatchDigest]) -> Dict[str, Any]:
        wins = sum(1 for d in digests if d.win)
        deaths = [p.deaths for _, p in pairs]
        return {
            "matches": len(digests),
            "wins": wins,
            "losses": len(digests) - wins,
            "winrate": round(100 * wins / len(digests)),
            "gpm": _round(_avg([d.gpm for d in digests])),
            "xpm": _round(_avg([d.xpm for d in digests])),
            "cs10": _round(_avg([d.cs10 for d in digests])),
            "kills": _round(_avg([p.kills for _, p in pairs]), 1),
            "deaths": _round(_avg(deaths), 1),
            "assists": _round(_avg([p.assists for _, p in pairs]), 1),
            # Худший матч по смертям — контекст к среднему: одна катастрофа
            # тянет среднее вверх, и без этого числа вывод был бы искажён.
            "deaths_max": max(deaths) if deaths else None,
            "kill_participation": _round(_avg([d.kill_participation for d in digests])),
            "lane_eff": _round(_avg([d.lane_eff for d in digests])),
            "duration": mmss(round(mean(m.duration for m, _ in pairs))),
            "net_worth": _round(_avg([d.net_worth for d in digests])),
        }

    # --- тренды перцентилей ---------------------------------------------------

    def _trends(self, pairs: Sequence[Tuple[Match, Player]]) -> List[Dict[str, Any]]:
        """Средний перцентиль и направление, а не перцентиль каждого матча.

        Матчи приходят свежими первыми, поэтому «первая половина выборки» — это
        последние игры. Направление считаем как разницу свежей половины и старой.
        """
        out = []
        for metric in TREND_METRICS:
            series = []
            for _, me in pairs:
                bench = (me.benchmarks or {}).get(metric)
                if isinstance(bench, dict) and bench.get("pct") is not None:
                    series.append(round(bench["pct"] * 100))
            if len(series) < MIN_MATCHES:
                continue

            half = max(1, len(series) // 2)
            recent, older = mean(series[:half]), mean(series[half:])
            delta = recent - older
            if len(series) < 4 or abs(delta) < TREND_MIN_DELTA:
                direction = "flat"
            else:
                direction = "up" if delta > 0 else "down"

            out.append({"metric": metric, "avg": round(mean(series)),
                        "low": min(series), "high": max(series),
                        "direction": direction, "delta": round(abs(delta)),
                        "samples": len(series)})
        return out

    # --- повторяющиеся паттерны ----------------------------------------------

    def _patterns(self, per_match: Sequence[Sequence[Anomaly]]) -> List[Dict[str, Any]]:
        """Отклонение, встретившееся не однажды, — это уже привычка.

        Считаем по ключу аномалии, а не по её тексту: параметры (какой именно
        предмет опоздал, на какой минуте просел фарм) в разных матчах разные,
        а вопрос один и тот же.
        """
        total = len(per_match)
        if total < MIN_MATCHES:
            return []

        counts: Dict[str, int] = {}
        axes: Dict[str, str] = {}
        samples: Dict[str, List[Dict[str, Any]]] = {}
        for found in per_match:
            for key in {a.key for a in found}:   # один матч считается один раз
                counts[key] = counts.get(key, 0) + 1
            for a in found:
                axes[a.key] = a.axis
                samples.setdefault(a.key, []).append(a.params)

        threshold = max(PATTERN_MIN_COUNT, round(PATTERN_SHARE * total))
        out = []
        for key, count in counts.items():
            if count < threshold:
                continue
            out.append({"key": key, "axis": axes[key], "count": count, "total": total,
                        "share": round(100 * count / total),
                        # Два примера с числами: без них паттерн звучит как ярлык.
                        "examples": samples[key][:2]})
        out.sort(key=lambda p: p["count"], reverse=True)
        return out

    # --- профиль по стадиям игры ---------------------------------------------

    def _stages(self, pairs: Sequence[Tuple[Match, Player]]) -> Dict[str, Any]:
        """На каких минутах перевес систематически уходит.

        Именно это отвечает на «стабильно проседаю на 25–35 мин»: для каждой
        пятиминутки берём ИЗМЕНЕНИЕ перевеса моей команды по золоту и усредняем
        по всем матчам. Уровень перевеса не годится — он тянется из предыдущих
        стадий, и провал в мид-гейме выглядел бы как провал во всём лейте.
        """
        buckets: Dict[int, List[int]] = {}
        for match, me in pairs:
            sign = 1 if me.is_radiant else -1
            adv = [sign * v for v in match.radiant_gold_adv]
            if len(adv) < 2:
                continue
            for start in range(0, min(len(adv) - 1, STAGE_LAST), STAGE_STEP_MIN):
                end = min(start + STAGE_STEP_MIN, len(adv) - 1)
                if end <= start:
                    continue
                buckets.setdefault(start, []).append(adv[end] - adv[start])

        rows = [{"start": start, "end": min(start + STAGE_STEP_MIN, STAGE_LAST),
                 "change": round(mean(values)), "samples": len(values)}
                for start, values in sorted(buckets.items())]
        if not rows:
            return {}

        # Сколько матчей реально дали поминутные ряды. Если их меньше двух, о
        # систематике говорить нельзя — печатаем таблицу и честную оговорку,
        # а выводы «стабильно проседаешь тут» не делаем вовсе.
        coverage = max(r["samples"] for r in rows)
        if coverage < STAGE_MIN_SAMPLES:
            return {"step": STAGE_STEP_MIN, "rows": rows, "coverage": coverage,
                    "thin": True, "weak": [], "strong": None}

        # Стадию считаем сравнимой с остальными, только если она измерена хотя бы
        # на половине доступных матчей: у долгих игр поздние корзины пустуют.
        floor = max(STAGE_MIN_SAMPLES, round(coverage / 2))
        comparable = [r for r in rows if r["samples"] >= floor]

        # Слабые стадии — те, где среднее изменение отрицательное. Если таких нет,
        # честно возвращаем пустой список, а не «худшие из хороших».
        weak = sorted([r for r in comparable if r["change"] < 0],
                      key=lambda r: r["change"])
        strong = max(comparable, key=lambda r: r["change"]) if comparable else None
        return {"step": STAGE_STEP_MIN, "rows": rows, "coverage": coverage,
                "thin": False, "weak": weak[:MAX_WEAK_STAGES],
                "strong": strong if strong and strong["change"] > 0 else None}

    # --- герои ----------------------------------------------------------------

    @staticmethod
    def _heroes(digests: Sequence[MatchDigest]) -> List[Dict[str, Any]]:
        """Состав выборки по героям: без него средние нельзя читать честно."""
        rows: Dict[str, Dict[str, Any]] = {}
        for d in digests:
            row = rows.setdefault(d.hero, {"hero": d.hero, "games": 0, "wins": 0})
            row["games"] += 1
            row["wins"] += int(d.win)
        return sorted(rows.values(), key=lambda r: r["games"], reverse=True)

    # --- оговорки -------------------------------------------------------------

    def _caveats(self, out: ProfileFeatures,
                 pairs: Sequence[Tuple[Match, Player]]) -> List[Tuple[str, Dict[str, Any]]]:
        caveats: List[Tuple[str, Dict[str, Any]]] = [
            ("caveat.profile_aggregated", {"analyzed": out.analyzed}),
        ]
        if out.analyzed < out.requested:
            caveats.append(("caveat.profile_short",
                            {"requested": out.requested, "analyzed": out.analyzed}))

        unparsed = sum(1 for d in out.digests if not d.parsed)
        if unparsed:
            caveats.append(("caveat.profile_unparsed", {"count": unparsed}))

        roles = {d.role for d in out.digests if d.role in ROLES}
        if not out.role_filter and len(roles) > 1:
            caveats.append(("caveat.profile_mixed_roles", {"count": len(roles)}))

        patches = {m.patch for m, _ in pairs if m.patch}
        if len(patches) > 1:
            caveats.append(("caveat.profile_patches",
                            {"patches": ", ".join(sorted(patches))}))
        return caveats

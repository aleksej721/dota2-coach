"""Pipeline — связывает стадии в один поток.

DataSource -> (нормализация внутри источника) -> FeatureExtractor -> BundleBuilder.
Стадии соединены типами (Match, Features, str), поэтому любую из них можно заменить,
не трогая соседние.

Сборка текста и запись файла разведены намеренно: `build()` нужен и CLI, и
веб-обёртке, а писать в output/ должен только CLI — веб отдаёт файл браузеру.
"""

import pathlib
from typing import Callable, List, Optional, Tuple

from .bundle import BundleBuilder, ProfileBundleBuilder
from .constants import Constants
from .features import FeatureExtractor
from .model import Match, Player
from .policy import Policy
from .profile import (MAX_MATCHES, MIN_MATCHES, ROLE_TO_LANE_ROLE, ProfileAggregator,
                      ProfileFeatures)
from .sources.base import (KIND_HERO_UNKNOWN, KIND_NO_MATCHES, KIND_PLAYER_NOT_FOUND,
                           DataSource, DataSourceError)

# Сколько матчей максимум разрешаем СКАЧАТЬ на один профиль. С фильтром по
# позиции часть скачанных матчей отбрасывается (позиция — эвристика, серверный
# фильтр по линии неточен), и без потолка запрос мог бы тянуться минутами.
FETCH_BUDGET_FACTOR = 2

# Прогресс выборки: (номер, всего, match_id). Нужен веб-интерфейсу и CLI, чтобы
# показывать, что процесс идёт, — на десяти матчах это десятки секунд.
ProgressFn = Callable[[int, int, int], None]


class Pipeline:
    def __init__(self, source: DataSource, extractor: FeatureExtractor,
                 builder: BundleBuilder, constants: Constants,
                 aggregator: ProfileAggregator, profile_builder: ProfileBundleBuilder,
                 out_dir: str = "output"):
        self._source = source
        self._extractor = extractor
        self._builder = builder
        self._constants = constants
        self._aggregator = aggregator
        self._profile_builder = profile_builder
        self._out_dir = pathlib.Path(out_dir)

    def build(self, match_id: int, account_id: Optional[int], hero: Optional[str],
              policy: Policy) -> Tuple[str, Match, Player]:
        """Собирает текст промпта. Ничего не пишет на диск.

        Вместе с текстом возвращает Match и найденного игрока: вызывающему коду
        бывает нужен статус матча (распарсен ли он) и сторона игрока — например,
        веб-интерфейс окрашивает результат в цвета его фракции.
        """
        match = self._source.fetch_match(match_id)
        me = self._find_me(match, account_id, hero)
        # Роль пользователя переопределяет эвристику только для его профиля.
        # Match не мутируем: позиции остальных игроков остаются фактами
        # нормализации и не «заражаются» пользовательским выбором.
        effective_policy = policy.resolve_role(me.position_key)
        features = self._extractor.extract(match, me, effective_policy)
        return self._builder.build(features, effective_policy), match, me

    def run(self, match_id: int, account_id: Optional[int], hero: Optional[str],
            policy: Policy) -> Tuple[pathlib.Path, str]:
        """Как build(), но ещё и кладёт результат в output/<match_id>.txt."""
        text, _, _ = self.build(match_id, account_id, hero, policy)
        self._out_dir.mkdir(exist_ok=True)
        path = self._out_dir / f"{match_id}.txt"
        path.write_text(text, encoding="utf-8")
        return path, text

    def warm(self) -> None:
        """Прогревает справочники. Сеть трогает, данные матчей — нет."""
        self._constants.warm()

    # --- профиль (кросс-матчевый разбор) --------------------------------------

    def build_profile(self, account_id: int, count: int, hero: Optional[str] = None,
                      role: Optional[str] = None, policy: Optional[Policy] = None,
                      progress: Optional[ProgressFn] = None
                      ) -> Tuple[str, ProfileFeatures]:
        """account_id -> текст мульти-матчевого промпта. На диск не пишет.

        Матчи тянутся по одному через общий rate-limiter (вежливость к OpenDota),
        парсинг нераспарсенных НЕ заказывается: десять ожиданий по три минуты
        превратили бы запрос в получасовой. Недоступный матч пропускается, а не
        рушит профиль — сколько матчей реально вошло, видно в оговорках промпта.
        """
        policy = policy or Policy()
        count = max(MIN_MATCHES, min(MAX_MATCHES, count))

        hero_id = None
        if (hero or "").strip():
            hero_id = self._constants.hero_id_by_name(hero)
            if hero_id is None:
                raise DataSourceError(
                    f"Не удалось однозначно опознать героя «{hero}». Напиши имя полнее — "
                    f"например, «Phantom Lancer» вместо «Phantom».", KIND_HERO_UNKNOWN)

        # Позиция игрока — наша эвристика, серверный фильтр OpenDota знает только
        # линию. Поэтому линию используем как подсказку, а точную позицию
        # проверяем сами и просим с запасом, чтобы добрать нужное число матчей.
        lane_role = ROLE_TO_LANE_ROLE.get(role) if role else None
        wanted = count * FETCH_BUDGET_FACTOR if role else count
        ids = self._source.fetch_player_matches(account_id, min(wanted, MAX_MATCHES * 2),
                                                hero_id, lane_role)

        pairs: List[Tuple[Match, Player]] = []
        attempted = 0
        for match_id in ids:
            if len(pairs) >= count or attempted >= count * FETCH_BUDGET_FACTOR:
                break
            attempted += 1
            if progress:
                progress(len(pairs) + 1, count, match_id)
            try:
                match = self._source.fetch_match(match_id, allow_parse=False)
            except DataSourceError:
                continue  # один недоступный матч не должен ронять весь профиль
            me = next((p for p in match.players if p.account_id == account_id), None)
            if me is None:
                continue
            if role and me.position_key != role:
                continue
            pairs.append((match, me))

        if not pairs:
            raise DataSourceError(
                f"Ни один из матчей игрока {account_id} не удалось разобрать под заданные "
                f"фильтры. Попробуй без фильтра по позиции — она определяется эвристикой "
                f"и может не совпасть с твоим представлением о роли.", KIND_NO_MATCHES)

        features = self._aggregator.aggregate(account_id, pairs, requested=count,
                                              hero_filter=hero, role_filter=role)
        return self._profile_builder.build(features, policy), features

    @staticmethod
    def _find_me(match: Match, account_id: Optional[int], hero: Optional[str]) -> Player:
        if account_id is not None:
            for p in match.players:
                if p.account_id == account_id:
                    return p
        if hero:
            needle = hero.lower()
            for p in match.players:
                if needle in p.hero_name.lower():
                    return p

        # Не нашли — помогаем пользователю: показываем, из кого выбирать.
        roster = ", ".join(
            f"{p.hero_name}"
            + (f" (id={p.account_id})" if p.account_id else " (анонимный)")
            for p in match.players
        )
        raise DataSourceError(
            "Не удалось определить, кто из игроков — ты. Проверь account_id или имя героя.\n"
            f"Игроки матча: {roster}",
            KIND_PLAYER_NOT_FOUND,
        )

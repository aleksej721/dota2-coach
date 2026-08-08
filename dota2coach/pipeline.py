"""Pipeline — связывает стадии в один поток.

DataSource -> (нормализация внутри источника) -> FeatureExtractor -> BundleBuilder.
Стадии соединены типами (Match, Features, str), поэтому любую из них можно заменить,
не трогая соседние.

Сборка текста и запись файла разведены намеренно: `build()` нужен и CLI, и
веб-обёртке, а писать в output/ должен только CLI — веб отдаёт файл браузеру.
"""

import pathlib
from typing import Optional, Tuple

from .bundle import BundleBuilder
from .features import FeatureExtractor
from .model import Match, Player
from .policy import Policy
from .sources.base import KIND_PLAYER_NOT_FOUND, DataSource, DataSourceError


class Pipeline:
    def __init__(self, source: DataSource, extractor: FeatureExtractor,
                 builder: BundleBuilder, out_dir: str = "output"):
        self._source = source
        self._extractor = extractor
        self._builder = builder
        self._out_dir = pathlib.Path(out_dir)

    def build(self, match_id: int, account_id: Optional[int], hero: Optional[str],
              policy: Policy) -> Tuple[str, Match]:
        """Собирает текст промпта. Ничего не пишет на диск.

        Вместе с текстом возвращает Match: вызывающему коду бывает нужен его
        статус (например, распарсен ли матч), чтобы предупредить пользователя.
        """
        match = self._source.fetch_match(match_id)
        me = self._find_me(match, account_id, hero)
        # Роль пользователя переопределяет эвристику только для его профиля.
        # Match не мутируем: позиции остальных игроков остаются фактами
        # нормализации и не «заражаются» пользовательским выбором.
        effective_policy = policy.resolve_role(me.position_key)
        features = self._extractor.extract(match, me, effective_policy)
        return self._builder.build(features, effective_policy), match

    def run(self, match_id: int, account_id: Optional[int], hero: Optional[str],
            policy: Policy) -> Tuple[pathlib.Path, str]:
        """Как build(), но ещё и кладёт результат в output/<match_id>.txt."""
        text, _ = self.build(match_id, account_id, hero, policy)
        self._out_dir.mkdir(exist_ok=True)
        path = self._out_dir / f"{match_id}.txt"
        path.write_text(text, encoding="utf-8")
        return path, text

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

"""Pipeline — связывает стадии в один поток и пишет результат в файл.

DataSource -> (нормализация внутри источника) -> FeatureExtractor -> BundleBuilder -> файл.
Стадии соединены типами (Match, Features, str), поэтому любую из них можно заменить,
не трогая соседние.
"""

import pathlib
from typing import Optional, Tuple

from .bundle import BundleBuilder
from .features import FeatureExtractor
from .model import Match, Player
from .sources.base import DataSource, DataSourceError


class Pipeline:
    def __init__(self, source: DataSource, extractor: FeatureExtractor,
                 builder: BundleBuilder, out_dir: str = "output"):
        self._source = source
        self._extractor = extractor
        self._builder = builder
        self._out_dir = pathlib.Path(out_dir)

    def run(self, match_id: int, account_id: Optional[int], hero: Optional[str],
            depth: str) -> Tuple[pathlib.Path, str]:
        match = self._source.fetch_match(match_id)
        me = self._find_me(match, account_id, hero)

        features = self._extractor.extract(match, me, depth)
        text = self._builder.build(features, depth)

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
            "Не удалось определить, кто из игроков — ты. Проверь --me/--hero.\n"
            f"Игроки матча: {roster}"
        )

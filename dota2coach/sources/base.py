"""Интерфейс источника данных (Data Source Adapter).

Ключевая абстракция проекта. Контракт один: «дай мне match_id — получи Match».
Как именно источник добывает данные (HTTP к OpenDota / парсинг .dem-файла) —
его личное дело. Остальное приложение зависит ТОЛЬКО от этого интерфейса.

Так на шаге Тир 3 мы добавим ReplayParserSource(DataSource), который вернёт тот
же Match из локального реплея, и ни FeatureExtractor, ни BundleBuilder, ни CLI
менять не придётся.
"""

from abc import ABC, abstractmethod

from ..model import Match


class DataSourceError(Exception):
    """Ожидаемая проблема источника (нет матча, сеть, лимиты). С понятным текстом."""


class DataSource(ABC):
    @abstractmethod
    def fetch_match(self, match_id: int) -> Match:
        """Возвращает нормализованный Match или бросает DataSourceError."""
        raise NotImplementedError

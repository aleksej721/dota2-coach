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

# Виды сбоев. Нужны обёрткам, которым мало текста: веб по ним выбирает HTTP-код,
# не разбирая сообщение регулярками.
KIND_NOT_FOUND = "not_found"          # матча нет в OpenDota
KIND_PLAYER_NOT_FOUND = "player_not_found"  # матч есть, но не понять, кто из игроков — ты
KIND_RATE_LIMITED = "rate_limited"    # 429
KIND_NETWORK = "network"              # сеть не отвечает
KIND_UNAVAILABLE = "unavailable"      # 5xx или мусор вместо JSON
KIND_UNKNOWN = "unknown"


class DataSourceError(Exception):
    """Ожидаемая проблема источника (нет матча, сеть, лимиты). С понятным текстом."""

    def __init__(self, message: str, kind: str = KIND_UNKNOWN):
        super().__init__(message)
        self.kind = kind


class DataSource(ABC):
    @abstractmethod
    def fetch_match(self, match_id: int) -> Match:
        """Возвращает нормализованный Match или бросает DataSourceError."""
        raise NotImplementedError

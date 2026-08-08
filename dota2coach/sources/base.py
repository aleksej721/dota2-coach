"""Интерфейс источника данных (Data Source Adapter).

Ключевая абстракция проекта. Контракт один: «дай мне match_id — получи Match».
Как именно источник добывает данные (HTTP к OpenDota / парсинг .dem-файла) —
его личное дело. Остальное приложение зависит ТОЛЬКО от этого интерфейса.

Так на шаге Тир 3 мы добавим ReplayParserSource(DataSource), который вернёт тот
же Match из локального реплея, и ни FeatureExtractor, ни BundleBuilder, ни CLI
менять не придётся.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from ..model import Match

# Виды сбоев. Нужны обёрткам, которым мало текста: веб по ним выбирает HTTP-код,
# не разбирая сообщение регулярками.
KIND_NOT_FOUND = "not_found"          # матча нет в OpenDota
KIND_PLAYER_NOT_FOUND = "player_not_found"  # матч есть, но не понять, кто из игроков — ты
KIND_RATE_LIMITED = "rate_limited"    # 429
KIND_NETWORK = "network"              # сеть не отвечает
KIND_UNAVAILABLE = "unavailable"      # 5xx или мусор вместо JSON
KIND_NO_MATCHES = "no_matches"        # у игрока нет матчей под заданные фильтры
KIND_HERO_UNKNOWN = "hero_unknown"    # имя героя не опознано или неоднозначно
KIND_UNKNOWN = "unknown"


class DataSourceError(Exception):
    """Ожидаемая проблема источника (нет матча, сеть, лимиты). С понятным текстом."""

    def __init__(self, message: str, kind: str = KIND_UNKNOWN):
        super().__init__(message)
        self.kind = kind


class DataSource(ABC):
    @abstractmethod
    def fetch_match(self, match_id: int, allow_parse: bool = True) -> Match:
        """Возвращает нормализованный Match или бросает DataSourceError.

        allow_parse=False запрещает заказывать парсинг нераспарсенного матча.
        Нужен режиму профиля: там матчей десяток, и ожидание парсинга каждого
        превратило бы запрос из минутного в получасовой. Лучше собрать профиль
        по тому, что готово, и честно сказать, сколько матчей оказалось неполными.
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_player_matches(self, account_id: int, limit: int,
                             hero_id: Optional[int] = None,
                             lane_role: Optional[int] = None) -> List[int]:
        """ID последних матчей игрока под заданными фильтрами, свежие первыми."""
        raise NotImplementedError

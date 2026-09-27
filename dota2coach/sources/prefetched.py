"""PrefetchedSource — матчи, которые браузер пользователя уже скачал сам.

Зачем это вообще нужно. OpenDota считает лимит запросов по IP-адресу (60 в
минуту, около 3000 в сутки), а бесплатные контейнеры хостинга выходят в сеть
через общие адреса, одни на множество чужих сервисов. Их суточный лимит
выбирают другие, и сервер получал 429 на первом же запросе — сайт был мёртв,
хотя код исправен. OpenDota при этом разрешает CORS, поэтому страница забирает
матч сама, со своего IP и в пределах своего лимита, и присылает сырой ответ.

Источник живёт ровно один запрос и оборачивает серверный: всё, чего браузер не
прислал, по-прежнему тянется обычным путём. Присланным данным сервер доверяет
только внутри этого запроса — в общий кэш они не пишутся, иначе один
пользователь мог бы подложить подправленный матч всем остальным.
"""

from typing import Any, Dict, Iterable, List, Optional

from ..model import Match
from .base import DataSource
from .opendota import OpenDotaSource

# Потолок на число присланных матчей: профиль берёт не больше 20 матчей с
# двукратным запасом под фильтр позиции. Всё сверх — мусор или злоупотребление.
MAX_PREFETCHED = 40


def valid_raw(raw: Any, match_id: Optional[int] = None) -> bool:
    """Похоже ли это на ответ OpenDota /matches/{id}, и тот ли это матч."""
    if not isinstance(raw, dict):
        return False
    try:
        rid = int(raw.get("match_id"))
    except (TypeError, ValueError):
        return False
    if match_id is not None and rid != match_id:
        return False
    players = raw.get("players")
    return isinstance(players, list) and 0 < len(players) <= 10 \
        and all(isinstance(p, dict) for p in players)


class PrefetchedSource(DataSource):
    def __init__(self, fallback: OpenDotaSource, matches: Iterable[Any] = (),
                 match_ids: Optional[List[int]] = None):
        self._fallback = fallback
        self._raws: Dict[int, Dict[str, Any]] = {}
        for raw in list(matches)[:MAX_PREFETCHED]:
            if valid_raw(raw):
                self._raws[int(raw["match_id"])] = raw
        # None — «список не прислан, спроси сервер»; пустой список — честный ответ
        # OpenDota «матчей нет», и перезапрашивать его через забитый IP незачем.
        self._match_ids = ([int(m) for m in match_ids if int(m) > 0]
                           if match_ids is not None else None)

    @property
    def count(self) -> int:
        return len(self._raws)

    def fetch_match(self, match_id: int, allow_parse: bool = True) -> Match:
        # Распарсенная копия в серверном кэше пришла от OpenDota напрямую и
        # полнее всего остального — она в приоритете.
        cached = self._fallback.cached_parsed(match_id)
        if cached is not None:
            return self._fallback.from_raw(cached)
        raw = self._raws.get(match_id)
        if raw is not None:
            return self._fallback.from_raw(raw)
        return self._fallback.fetch_match(match_id, allow_parse=allow_parse)

    def fetch_player_matches(self, account_id: int, limit: int,
                             hero_id: Optional[int] = None,
                             lane_role: Optional[int] = None) -> List[int]:
        if self._match_ids is not None:
            return self._match_ids[:limit]
        return self._fallback.fetch_player_matches(account_id, limit, hero_id, lane_role)

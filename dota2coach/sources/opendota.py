"""OpenDotaSource — реализация DataSource поверх публичного OpenDota API.

Логика:
  1. GET /matches/{id}.
  2. Если матч не распарсен (нет поминутных данных) — POST /request/{id},
     дождаться завершения задачи (поллинг), затем повторный GET.
  3. Отдать нормализованный Match.
"""

import json
import pathlib
import time
from typing import Any, Dict, List, Optional

import requests

from .. import config, normalize
from ..constants import Constants
from ..model import Match
from .base import (KIND_NETWORK, KIND_NO_MATCHES, KIND_NOT_FOUND, KIND_RATE_LIMITED,
                   KIND_UNAVAILABLE, DataSource, DataSourceError, drop_key, key_rejected)


class OpenDotaSource(DataSource):
    BASE = "https://api.opendota.com/api"

    def __init__(self, session: requests.Session, constants: Constants, rate_limiter,
                 parse_timeout: Optional[float] = None, poll_interval: float = 6.0,
                 use_cache: bool = True, cache_dir: Optional[str] = None,
                 retry_attempts: int = 2, retry_backoff: float = 0.6):
        # Ключ API сюда не передаётся: он лежит на сессии (см. core.build_pipeline),
        # и requests добавляет его к каждому запросу сам.
        self._session = session
        self._constants = constants
        self._rate = rate_limiter
        # За обратным прокси хостинга трёхминутное ожидание не переживёт таймаут
        # соединения, поэтому значение приходит из окружения (см. config).
        self._parse_timeout = (parse_timeout if parse_timeout is not None
                               else config.parse_timeout_sec())
        self._poll_interval = poll_interval
        self._use_cache = use_cache
        self._cache_dir = pathlib.Path(cache_dir or config.cache_dir())
        self._retry_attempts = max(0, retry_attempts)
        self._retry_backoff = max(0.0, retry_backoff)

    # --- низкоуровневые HTTP-хелперы -----------------------------------------

    @staticmethod
    def _snippet(resp: requests.Response, limit: int = 200) -> str:
        """Начало тела ответа — единственная зацепка, когда сбой не воспроизводится.

        «HTTP 403» сам по себе не отличает исчерпанный лимит от блокировки
        клиента, а страж вроде Cloudflare вообще отдаёт HTML-заглушку вместо
        JSON — по одному коду этого не видно. Тело обрезаем: в лог нужен
        признак, а не дамп страницы.
        """
        try:
            body = " ".join((resp.text or "").split())
        except Exception:        # noqa: BLE001 — диагностика не должна ронять разбор
            return ""
        if not body:
            return ""
        ctype = resp.headers.get("Content-Type", "?")
        return f" [{ctype}] {body[:limit]}"

    def _get(self, path: str, query: Optional[Dict[str, Any]] = None) -> Any:
        # Короткий bounded retry сглаживает рестарт API и единичный 502, но не
        # превращает запрос страницы в бесконечное ожидание. Rate limiter
        # применяется к КАЖДОЙ попытке: повтор — тоже внешний запрос.
        key_retry_available = True
        last_network_error = None
        for attempt in range(self._retry_attempts + 1):
            self._rate.acquire()
            try:
                resp = self._session.get(f"{self.BASE}{path}", params=query or {}, timeout=30)
            except requests.RequestException as e:
                last_network_error = e
                if attempt < self._retry_attempts:
                    self._retry_delay(attempt)
                    continue
                raise DataSourceError(f"Сетевая ошибка при GET {path}: {e}", KIND_NETWORK)

            # Отвергнутый необязательный ключ пробуем без ключа. Этот повтор не
            # съедает весь retry budget: проблема авторизации и сбой API — разные
            # причины, и после drop_key ещё может понадобиться обычный retry.
            if key_retry_available and key_rejected(self._session, resp):
                drop_key(self._session)
                key_retry_available = False
                return self._get(path, query)

            if resp.status_code == 404:
                raise DataSourceError(f"OpenDota: ресурс не найден (404) для {path}.",
                                      KIND_NOT_FOUND)
            if resp.status_code == 429:
                if attempt < self._retry_attempts:
                    self._retry_delay(attempt, resp)
                    continue
                raise DataSourceError(
                    "OpenDota: превышен лимит запросов (429). Подожди минуту или задай "
                    "OPENDOTA_API_KEY для более высоких лимитов.", KIND_RATE_LIMITED)
            if resp.status_code >= 500:
                if attempt < self._retry_attempts:
                    self._retry_delay(attempt, resp)
                    continue
                raise DataSourceError(f"OpenDota временно недоступна (HTTP {resp.status_code}) "
                                      f"на GET {path}.{self._snippet(resp)}", KIND_UNAVAILABLE)
            if resp.status_code != 200:
                raise DataSourceError(f"OpenDota вернула HTTP {resp.status_code} на GET "
                                      f"{path}.{self._snippet(resp)}", KIND_UNAVAILABLE)
            try:
                return resp.json()
            except ValueError:
                raise DataSourceError(f"OpenDota вернула не-JSON ответ на GET {path} "
                                      f"(HTTP {resp.status_code}).{self._snippet(resp)}",
                                      KIND_UNAVAILABLE)

        # Недостижимо, но явно сохраняет тип ошибки при изменении цикла.
        raise DataSourceError(f"Сетевая ошибка при GET {path}: {last_network_error}", KIND_NETWORK)

    def _retry_delay(self, attempt: int, resp: Optional[requests.Response] = None) -> None:
        """Backoff с ограничением; Retry-After у OpenDota имеет приоритет."""
        delay = self._retry_backoff * (2 ** attempt)
        if resp is not None:
            try:
                delay = max(delay, float(resp.headers.get("Retry-After", 0) or 0))
            except (TypeError, ValueError):
                pass
        if delay:
            time.sleep(min(delay, 3.0))

    def _post(self, path: str) -> Any:
        self._rate.acquire()
        try:
            resp = self._session.post(f"{self.BASE}{path}", timeout=30)
        except requests.RequestException as e:
            raise DataSourceError(f"Сетевая ошибка при POST {path}: {e}", KIND_NETWORK)
        if key_rejected(self._session, resp):
            drop_key(self._session)
            return self._post(path)
        if resp.status_code not in (200, 201):
            raise DataSourceError(f"OpenDota вернула HTTP {resp.status_code} на POST "
                                  f"{path}.{self._snippet(resp)}", KIND_UNAVAILABLE)
        try:
            return resp.json()
        except ValueError:
            return None

    # --- кэш сырого ответа ----------------------------------------------------

    def _cache_path(self, match_id: int) -> pathlib.Path:
        return self._cache_dir / f"match_{match_id}.json"

    def _cached_match(self, match_id: int, require_parsed: bool = True) -> Optional[Dict[str, Any]]:
        """Читает сохранённый ответ, обычно требуя завершённый parse.

        Это экономит запросы к API при повторных прогонах с другими --depth/--focus.
        Неполную копию в штатном пути перезапрашиваем, но держим как fallback на
        случай, когда OpenDota временно перестала отвечать.
        """
        if not self._use_cache:
            return None
        path = self._cache_path(match_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("match_id") is None:
            return None
        return raw if not require_parsed or self._is_parsed(raw) else None

    def _store_match(self, match_id: int, raw: Dict[str, Any]) -> None:
        if not self._use_cache or not isinstance(raw, dict) or raw.get("match_id") is None:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_path(match_id)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(raw), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            pass  # кэш — оптимизация, его отсутствие не должно ломать разбор

    # --- публичный контракт ---------------------------------------------------

    def fetch_player_matches(self, account_id: int, limit: int,
                             hero_id: Optional[int] = None,
                             lane_role: Optional[int] = None) -> List[int]:
        """Один запрос к /players/{id}/matches — фильтры отдаём серверу.

        Фильтровать на своей стороне было бы дороже: пришлось бы тянуть длинную
        историю и выбрасывать почти всё, а лимит запросов у OpenDota общий.
        """
        query: Dict[str, Any] = {"limit": limit, "project": "hero_id"}
        if hero_id is not None:
            query["hero_id"] = hero_id
        if lane_role is not None:
            query["lane_role"] = lane_role

        try:
            rows = self._get(f"/players/{account_id}/matches", query)
        except DataSourceError as e:
            if e.kind == KIND_NOT_FOUND:
                raise DataSourceError(
                    f"Игрок {account_id} не найден в OpenDota. Проверь account_id "
                    f"(Steam32) — он виден в адресе профиля на Dotabuff или OpenDota.",
                    KIND_NOT_FOUND)
            raise

        ids = [r.get("match_id") for r in (rows or []) if isinstance(r, dict)]
        ids = [int(m) for m in ids if m]
        if not ids:
            raise DataSourceError(
                f"У игрока {account_id} не нашлось матчей под заданные фильтры. "
                f"Ослабь фильтр по герою или позиции — или проверь, что матчи игрока "
                f"открыты в настройках Dota 2 («Раскрывать данные о матчах»).",
                KIND_NO_MATCHES)
        return ids

    def fetch_match(self, match_id: int, allow_parse: bool = True) -> Match:
        cached = self._cached_match(match_id)
        if cached is not None:
            print(f"      Беру матч {match_id} из локального кэша (.cache). "
                  f"Свежие данные: --no-cache")
            return normalize.from_opendota(cached, self._constants)

        not_found = DataSourceError(
            f"Матч {match_id} не найден в OpenDota. Проверь ID — он должен быть "
            f"из истории матчей, а не ID лобби или профиля.", KIND_NOT_FOUND)
        stale = self._cached_match(match_id, require_parsed=False)
        try:
            raw = self._get(f"/matches/{match_id}")
        except DataSourceError as e:
            # У _get сообщение техническое («ресурс не найден для /matches/1»),
            # а пользователю нужно понятное — путь к эндпоинту ему ни о чём не говорит.
            if stale is not None and e.kind in (KIND_NETWORK, KIND_RATE_LIMITED, KIND_UNAVAILABLE):
                print(f"      OpenDota недоступна; использую сохранённую базовую копию "
                      f"матча {match_id}.", flush=True)
                return normalize.from_opendota(stale, self._constants)
            raise not_found if e.kind == KIND_NOT_FOUND else e
        if raw is None or raw.get("match_id") is None:
            raise not_found

        if not self._is_parsed(raw) and allow_parse:
            print(f"      Матч ещё не распарсен OpenDota — запрашиваю парсинг "
                  f"(это может занять до {int(self._parse_timeout)} c)...")
            # Базовый ответ уже полезен: сохраняем его ДО запроса парсинга. Если
            # request endpoint или следующий GET упадёт, не теряем скорборд.
            self._store_match(match_id, raw)
            try:
                self._request_parse_and_wait(match_id)
                refreshed = self._get(f"/matches/{match_id}")
                if isinstance(refreshed, dict) and refreshed.get("match_id") is not None:
                    raw = refreshed
            except DataSourceError as e:
                if e.kind not in (KIND_NETWORK, KIND_RATE_LIMITED, KIND_UNAVAILABLE):
                    raise
                print(f"      Детальный парсинг OpenDota недоступен ({e.kind}); "
                      f"продолжаю с базовыми данными.", flush=True)
            if not self._is_parsed(raw):
                print("      Внимание: парсинг не успел завершиться. Продолжаю с тем, "
                      "что есть (Тир 1/2 могут быть неполными).")

        self._store_match(match_id, raw)
        return normalize.from_opendota(raw, self._constants)

    # --- парсинг-задача -------------------------------------------------------

    @staticmethod
    def _is_parsed(raw: Dict[str, Any]) -> bool:
        # OpenDota проставляет 'version', когда матч прошёл детальный парсинг.
        return raw.get("version") is not None

    def _request_parse_and_wait(self, match_id: int) -> None:
        job = self._post(f"/request/{match_id}")
        job_id = None
        if isinstance(job, dict):
            job_id = (job.get("job") or {}).get("jobId")

        deadline = time.monotonic() + self._parse_timeout
        while time.monotonic() < deadline:
            time.sleep(self._poll_interval)
            if job_id is None:
                # Нет id задачи — просто ждём и полагаемся на повторный GET.
                return
            status = self._get(f"/request/{job_id}")
            # Пока задача жива — приходит объект; когда готово — приходит null.
            if not status:
                return
        # Таймаут не критичен: вызывающий код перепроверит _is_parsed.

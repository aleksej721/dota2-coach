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
from typing import Any, Dict, Optional

import requests

from .. import normalize
from ..constants import Constants
from ..model import Match
from .base import DataSource, DataSourceError


class OpenDotaSource(DataSource):
    BASE = "https://api.opendota.com/api"

    def __init__(self, session: requests.Session, constants: Constants, rate_limiter,
                 api_key: Optional[str] = None,
                 parse_timeout: float = 180.0, poll_interval: float = 6.0,
                 use_cache: bool = True, cache_dir: str = ".cache"):
        self._session = session
        self._constants = constants
        self._rate = rate_limiter
        self._api_key = api_key
        self._parse_timeout = parse_timeout
        self._poll_interval = poll_interval
        self._use_cache = use_cache
        self._cache_dir = pathlib.Path(cache_dir)

    # --- низкоуровневые HTTP-хелперы -----------------------------------------

    def _params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = dict(extra or {})
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def _get(self, path: str) -> Any:
        self._rate.acquire()  # вежливость к API перед каждым запросом
        try:
            resp = self._session.get(f"{self.BASE}{path}", params=self._params(), timeout=30)
        except requests.RequestException as e:
            raise DataSourceError(f"Сетевая ошибка при GET {path}: {e}")

        if resp.status_code == 404:
            raise DataSourceError(f"OpenDota: ресурс не найден (404) для {path}.")
        if resp.status_code == 429:
            raise DataSourceError(
                "OpenDota: превышен лимит запросов (429). Подожди минуту или задай "
                "OPENDOTA_API_KEY для более высоких лимитов.")
        if resp.status_code >= 500:
            raise DataSourceError(f"OpenDota временно недоступна (HTTP {resp.status_code}). "
                                  f"Попробуй ещё раз чуть позже.")
        if resp.status_code != 200:
            raise DataSourceError(f"OpenDota вернула HTTP {resp.status_code} для {path}.")
        try:
            return resp.json()
        except ValueError:
            raise DataSourceError(f"OpenDota вернула не-JSON ответ для {path}.")

    def _post(self, path: str) -> Any:
        self._rate.acquire()
        try:
            resp = self._session.post(f"{self.BASE}{path}", params=self._params(), timeout=30)
        except requests.RequestException as e:
            raise DataSourceError(f"Сетевая ошибка при POST {path}: {e}")
        if resp.status_code not in (200, 201):
            raise DataSourceError(f"OpenDota вернула HTTP {resp.status_code} для POST {path}.")
        try:
            return resp.json()
        except ValueError:
            return None

    # --- кэш сырого ответа ----------------------------------------------------

    def _cache_path(self, match_id: int) -> pathlib.Path:
        return self._cache_dir / f"match_{match_id}.json"

    def _cached_match(self, match_id: int) -> Optional[Dict[str, Any]]:
        """Сыгранный матч неизменен, поэтому распарсенный ответ кэшируем навсегда.

        Это экономит запросы к API при повторных прогонах с другими --depth/--focus.
        Нераспарсенные ответы не кэшируем — их ещё имеет смысл перезапросить.
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
        return raw if self._is_parsed(raw) else None

    def _store_match(self, match_id: int, raw: Dict[str, Any]) -> None:
        if not self._use_cache or not self._is_parsed(raw):
            return
        try:
            self._cache_dir.mkdir(exist_ok=True)
            self._cache_path(match_id).write_text(json.dumps(raw), encoding="utf-8")
        except OSError:
            pass  # кэш — оптимизация, его отсутствие не должно ломать разбор

    # --- публичный контракт ---------------------------------------------------

    def fetch_match(self, match_id: int) -> Match:
        cached = self._cached_match(match_id)
        if cached is not None:
            print(f"      Беру матч {match_id} из локального кэша (.cache). "
                  f"Свежие данные: --no-cache")
            return normalize.from_opendota(cached, self._constants)

        raw = self._get(f"/matches/{match_id}")
        if raw is None or raw.get("match_id") is None:
            raise DataSourceError(f"Матч {match_id} не найден в OpenDota.")

        if not self._is_parsed(raw):
            print(f"      Матч ещё не распарсен OpenDota — запрашиваю парсинг "
                  f"(это может занять до {int(self._parse_timeout)} c)...")
            self._request_parse_and_wait(match_id)
            raw = self._get(f"/matches/{match_id}")  # перезабираем уже с деталями
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

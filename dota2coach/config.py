"""Конфигурация: всё, что приходит из переменных окружения.

Единственное место, где приложение читает окружение. Ничего секретного в
репозитории нет и быть не должно — ключи, пути и адреса задаются только здесь.
Полный список переменных с пояснениями лежит в .env.example.

Значения по умолчанию рассчитаны на ЛОКАЛЬНЫЙ запуск: личный инструмент не
должен без спроса торчать в сеть и писать куда попало. Хостинг переопределяет
их своими переменными.
"""

import os
from dataclasses import dataclass
from typing import Optional, Tuple

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_CACHE_DIR = ".cache"
DEFAULT_PARSE_TIMEOUT_SEC = 180.0


def _env(name: str) -> Optional[str]:
    value = (os.environ.get(name) or "").strip()
    return value or None


@dataclass
class Config:
    # Ключ НЕОБЯЗАТЕЛЕН: OpenDota работает и без него, но с ключом лимиты выше.
    api_key: Optional[str]

    @staticmethod
    def load() -> "Config":
        # Читаем из переменной окружения — ключ не хардкодим и не коммитим.
        return Config(api_key=_env("OPENDOTA_API_KEY"))


def server_binding() -> Tuple[str, int]:
    """Куда биндиться серверу: (host, port).

    Наличие PORT — признак того, что нас запустил хостинг (Render, Heroku и им
    подобные). Тогда слушать надо 0.0.0.0, иначе снаружи до контейнера не
    достучаться. Без PORT остаёмся на 127.0.0.1: локальный запуск не должен
    открывать инструмент в сеть по умолчанию.

    HOST задаётся отдельно, если нужно переопределить это правило вручную.
    """
    raw = _env("PORT")
    port = int(raw) if raw and raw.isdigit() else DEFAULT_PORT
    host = _env("HOST") or ("0.0.0.0" if raw and raw.isdigit() else DEFAULT_HOST)
    return host, port


def cache_dir() -> str:
    """Каталог кэша сырых ответов и справочников.

    На хостинге с эфемерной файловой системой кэш живёт до перезапуска — это
    нормально, он всего лишь оптимизация. Важно другое: код не должен ПАДАТЬ,
    если каталог недоступен для записи, см. ConstantsRepo._load.
    """
    return _env("DOTA2COACH_CACHE_DIR") or DEFAULT_CACHE_DIR


def parse_timeout_sec() -> float:
    """Сколько ждать, пока OpenDota распарсит матч.

    Локально не жалко ждать три минуты. За обратным прокси хостинга столько
    ждать нельзя: соединение оборвут раньше, чем мы ответим, и пользователь
    увидит пустую ошибку вместо объяснения. Поэтому значение вынесено в env.
    """
    raw = _env("PARSE_TIMEOUT_SEC")
    try:
        return max(0.0, float(raw)) if raw else DEFAULT_PARSE_TIMEOUT_SEC
    except ValueError:
        return DEFAULT_PARSE_TIMEOUT_SEC

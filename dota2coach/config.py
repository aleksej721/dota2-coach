"""Конфигурация приложения. Пока хранит только опциональный ключ OpenDota."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    # Ключ НЕОБЯЗАТЕЛЕН: OpenDota работает и без него, но с ключом лимиты выше.
    api_key: Optional[str]

    @staticmethod
    def load() -> "Config":
        # Читаем из переменной окружения — ключ не хардкодим и не коммитим.
        key = os.environ.get("OPENDOTA_API_KEY")
        return Config(api_key=key.strip() if key else None)

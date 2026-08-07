"""Простой ограничитель частоты запросов (вежливость к API)."""

import time


class RateLimiter:
    """Гарантирует минимальный интервал между вызовами acquire().

    OpenDota free-tier — ~60 запросов/мин. Мы делаем их единицы, но всё равно
    держим паузу, чтобы не долбить сервис пачками (особенно при поллинге парсинга).
    Класс однопоточный — усложнять локами незачем.
    """

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0

    def acquire(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()

"""Простой ограничитель частоты запросов (вежливость к API)."""

import threading
import time


class RateLimiter:
    """Гарантирует минимальный интервал между вызовами acquire().

    OpenDota free-tier — ~60 запросов/мин, и лимит общий на всех пользователей
    развёрнутого сервиса, а не на каждого. Поэтому лимитер один на процесс, и
    все запросы — и разбор матча, и справочники, и прогрев — идут через него.

    Потокобезопасен намеренно: на сервере в фоне греются справочники, пока
    основной поток обслуживает запрос, и без лока оба увидели бы одно и то же
    `_last`, разом ушли в сеть и выдали пачку запросов вместо очереди.
    """

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        # Спим ВНУТРИ лока: иначе два потока вычислят паузу от одного и того же
        # `_last`, проснутся одновременно и лимит окажется вдвое превышен.
        with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.monotonic()

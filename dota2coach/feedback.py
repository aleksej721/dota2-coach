"""Сбор отзывов о качестве разбора.

Зачем отдельный модуль. Инструмент отдаёт промпт, но насколько полезным вышел
РАЗБОР — из данных не видно никак. Единственный источник этого сигнала — сам
игрок, и его надо забрать в один клик, пока результат перед глазами.

Хранилище плагинное, потому что площадка развёртывания диктует разные ответы:

  * stdout — ВСЕГДА. На хостинге с эфемерной файловой системой это
    единственный канал, который переживает перезапуск: отзыв остаётся в логах
    сервиса, даже когда контейнер пересоздан;
  * JSONL-файл — локально это удобный архив, на хостинге живёт до перезапуска.
    Отсутствие прав на запись не должно ломать отправку;
  * вебхук — если задан FEEDBACK_WEBHOOK_URL, отзыв дополнительно уходит POST-ом
    во внешнее хранилище (Google Apps Script, Formspree, свой эндпоинт). Это
    единственный способ хранить отзывы по-настоящему, не поднимая базу, и он
    включается переменной окружения, без правок кода.

Персональных данных не собираем: account_id в отзыв НЕ кладётся. Он опознаёт
человека, а для оценки качества разбора не нужен — достаточно того, какой режим
и какие настройки дали такой результат.
"""

import json
import os
import pathlib
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DEFAULT_FEEDBACK_FILE = "feedback.jsonl"

# Вебхук не должен задерживать ответ пользователю: он уже нажал «палец вверх»
# и ждёт «спасибо», а не сетевого раунда до чужого сервиса.
WEBHOOK_TIMEOUT_SEC = 5.0

# Эндпоинт публичный. Потолок на процесс защищает и логи от потопа, и внешний
# вебхук от лишних запросов. Порог заведомо выше живого пользования.
MAX_PER_MINUTE = 60


@dataclass(frozen=True)
class Feedback:
    """Одна оценка. Поля контекста — только про настройки разбора."""

    rating: int                       # +1 / -1
    mode: str                         # "match" | "profile"
    lang: str
    model: str
    created_at: str                   # ISO-8601, UTC
    comment: Optional[str] = None
    match_id: Optional[int] = None
    role: Optional[str] = None
    depth: Optional[str] = None
    focus: Optional[str] = None
    window: Optional[str] = None
    matches: Optional[int] = None     # размер выборки в режиме профиля
    prompt_bytes: Optional[int] = None
    # True — это дослан комментарий к УЖЕ отправленной оценке. Нужно, чтобы при
    # подсчёте не удвоить голоса: считать оценки надо по записям с followup=false.
    followup: bool = False

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FeedbackStore(ABC):
    @abstractmethod
    def save(self, feedback: Feedback) -> None:
        """Сохраняет отзыв. Исключения наружу не выпускает."""
        raise NotImplementedError


class StdoutStore(FeedbackStore):
    """Печатает отзыв в лог одной строкой JSON.

    Основной канал на хостинге: файловая система эфемерная, а логи — нет.
    Префикс FEEDBACK позволяет выцепить отзывы грепом среди прочего вывода.
    """

    def save(self, feedback: Feedback) -> None:
        print("FEEDBACK " + json.dumps(feedback.as_dict(), ensure_ascii=False),
              flush=True)


class JsonlStore(FeedbackStore):
    """Дописывает отзыв строкой в JSONL-файл."""

    def __init__(self, path: Optional[str] = None):
        self._path = pathlib.Path(path or DEFAULT_FEEDBACK_FILE)
        self._lock = threading.Lock()

    def save(self, feedback: Feedback) -> None:
        line = json.dumps(feedback.as_dict(), ensure_ascii=False)
        try:
            # Лок нужен: uvicorn обслуживает запросы в нескольких потоках, и без
            # него две записи могут перемешаться внутри одной строки.
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError as e:
            # Нет прав на запись — не повод терять отзыв: он уже ушёл в stdout.
            print(f"FEEDBACK: не удалось записать в {self._path} ({e})", flush=True)


class WebhookStore(FeedbackStore):
    """POST-ит отзыв во внешний сервис."""

    def __init__(self, url: str, timeout: float = WEBHOOK_TIMEOUT_SEC):
        self._url = url
        self._timeout = timeout

    def save(self, feedback: Feedback) -> None:
        # Импорт внутри метода: без заданного вебхука requests здесь не нужен.
        import requests

        try:
            requests.post(self._url, json=feedback.as_dict(), timeout=self._timeout)
        except Exception as e:
            # Чужой сервис лежит — это его проблема, а не пользователя: отзыв
            # уже сохранён локально, и ломать ему «спасибо» мы не будем.
            print(f"FEEDBACK: вебхук не принял отзыв ({e})", flush=True)


class MultiStore(FeedbackStore):
    """Пишет во все хранилища. Сбой одного не мешает остальным."""

    def __init__(self, stores: List[FeedbackStore]):
        self._stores = stores

    def save(self, feedback: Feedback) -> None:
        for store in self._stores:
            try:
                store.save(feedback)
            except Exception as e:
                print(f"FEEDBACK: хранилище {type(store).__name__} упало ({e})",
                      flush=True)


class RateLimitedStore(FeedbackStore):
    """Отбрасывает отзывы сверх потолка в минуту.

    Эндпоинт открыт всему интернету, а за ним — логи и чужой вебхук. Простого
    счётчика на процесс достаточно: сервис однопроцессный, а порог заведомо
    выше того, что способен нажать живой человек.
    """

    def __init__(self, inner: FeedbackStore, max_per_minute: int = MAX_PER_MINUTE):
        self._inner = inner
        self._max = max_per_minute
        self._lock = threading.Lock()
        self._window_started = 0.0
        self._count = 0

    def save(self, feedback: Feedback) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._window_started >= 60.0:
                self._window_started, self._count = now, 0
            self._count += 1
            if self._count > self._max:
                print("FEEDBACK: превышен потолок отзывов в минуту, запись отброшена",
                      flush=True)
                return
        self._inner.save(feedback)


def build_store() -> FeedbackStore:
    """Собирает хранилище по переменным окружения.

    stdout и файл — всегда, вебхук — если задан URL. Порядок важен: stdout
    первым, чтобы отзыв попал в лог даже если всё остальное откажет.
    """
    stores: List[FeedbackStore] = [
        StdoutStore(),
        JsonlStore((os.environ.get("FEEDBACK_FILE") or "").strip() or None),
    ]
    webhook = (os.environ.get("FEEDBACK_WEBHOOK_URL") or "").strip()
    if webhook:
        stores.append(WebhookStore(webhook))
    return RateLimitedStore(MultiStore(stores))

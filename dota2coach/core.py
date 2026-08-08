"""core — вызываемое ядро: собрать конвейер и получить текст промпта.

Единственное место, где конкретные реализации связываются друг с другом.
И CLI, и веб-обёртка ходят сюда, а не собирают конвейер каждая по-своему —
иначе они бы разъехались по поведению при первой же правке.

Логика генерации живёт в Pipeline/FeatureExtractor/BundleBuilder и здесь не
дублируется: этот модуль только про проводку зависимостей.
"""

from dataclasses import dataclass
from typing import Optional

import requests

from .bundle import BundleBuilder
from .config import Config
from .constants import ConstantsRepo
from .features import FeatureExtractor
from .pipeline import Pipeline
from .policy import Policy
from .ratelimit import RateLimiter
from .sources.opendota import OpenDotaSource

USER_AGENT = "dota2coach/0.1 (personal use)"
OPENDOTA_MIN_INTERVAL_SEC = 1.0


@dataclass(frozen=True)
class PromptResult:
    """Текст промпта плюс то, что о нём стоит знать вызывающей стороне."""

    text: str
    match_id: int
    policy: Policy
    parsed: bool          # False — OpenDota не распарсила матч, детальные секции неполные

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8"))

    @property
    def filename(self) -> str:
        return f"{self.match_id}.txt"


def build_pipeline(api_key: Optional[str] = None, use_cache: bool = True,
                   out_dir: str = "output") -> Pipeline:
    """Собирает конвейер поверх OpenDota.

    Одна HTTP-сессия и один общий rate-limiter на все запросы (~1 req/sec):
    и матч, и справочники ходят через них.
    """
    if api_key is None:
        api_key = Config.load().api_key

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    rate = RateLimiter(min_interval=OPENDOTA_MIN_INTERVAL_SEC)

    constants = ConstantsRepo(session, rate, api_key=api_key)
    source = OpenDotaSource(session, constants, rate, api_key=api_key, use_cache=use_cache)
    return Pipeline(source, FeatureExtractor(constants), BundleBuilder(), out_dir=out_dir)


def generate_prompt(match_id: int, account_id: Optional[int] = None,
                    hero: Optional[str] = None, policy: Optional[Policy] = None,
                    pipeline: Optional[Pipeline] = None) -> PromptResult:
    """match_id -> готовый текст промпта. Ничего не пишет на диск.

    Готовый `pipeline` можно передать снаружи, чтобы переиспользовать прогретые
    справочники и общий rate-limiter между вызовами (так делает веб-сервер).
    Бросает DataSourceError с заполненным `kind`.
    """
    policy = policy or Policy()
    pipeline = pipeline or build_pipeline()
    text, match = pipeline.build(match_id, account_id, hero, policy)
    return PromptResult(text=text, match_id=match_id, policy=policy, parsed=match.parsed)

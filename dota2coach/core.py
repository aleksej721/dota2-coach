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

from .anomalies import AnomalyDetector
from .bundle import BundleBuilder, ProfileBundleBuilder
from .config import Config
from .constants import ConstantsRepo
from .features import FeatureExtractor
from .pipeline import Pipeline, ProgressFn
from .policy import Policy
from .profile import ProfileAggregator, ProfileFeatures
from .ratelimit import RateLimiter
from .sources.opendota import OpenDotaSource

USER_AGENT = "dota2coach/0.1 (personal use)"
OPENDOTA_MIN_INTERVAL_SEC = 1.0


@dataclass(frozen=True)
class ProfileResult:
    """Промпт по профилю плюс то, что о выборке стоит знать вызывающей стороне."""

    text: str
    account_id: int
    policy: Policy
    analyzed: int          # сколько матчей реально вошло в выборку
    requested: int
    unparsed: int          # из них без полного парсинга — данные неполные
    winrate: int

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8"))

    @property
    def filename(self) -> str:
        return f"profile_{self.account_id}_{self.analyzed}.txt"


@dataclass(frozen=True)
class PromptResult:
    """Текст промпта плюс то, что о нём стоит знать вызывающей стороне."""

    text: str
    match_id: int
    policy: Policy
    parsed: bool          # False — OpenDota не распарсила матч, детальные секции неполные
    side: str             # "radiant" | "dire" — сторона игрока
    win: bool

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
    extractor = FeatureExtractor(constants)
    aggregator = ProfileAggregator(AnomalyDetector(constants), extractor)
    return Pipeline(source, extractor, BundleBuilder(), constants, aggregator,
                    ProfileBundleBuilder(), out_dir=out_dir)


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
    text, match, me = pipeline.build(match_id, account_id, hero, policy)
    return PromptResult(text=text, match_id=match_id, policy=policy, parsed=match.parsed,
                        side="radiant" if me.is_radiant else "dire", win=me.win)


def generate_profile_prompt(account_id: int, count: int, hero: Optional[str] = None,
                            role: Optional[str] = None, policy: Optional[Policy] = None,
                            pipeline: Optional[Pipeline] = None,
                            progress: Optional[ProgressFn] = None) -> ProfileResult:
    """account_id -> мульти-матчевый промпт. Ничего не пишет на диск.

    Вторая точка входа рядом с generate_prompt(), с тем же контрактом: и CLI, и
    веб зовут её, а не собирают конвейер сами.
    """
    policy = policy or Policy()
    pipeline = pipeline or build_pipeline()
    text, features = pipeline.build_profile(account_id, count, hero, role, policy,
                                            progress=progress)
    return ProfileResult(
        text=text, account_id=account_id, policy=policy,
        analyzed=features.analyzed, requested=features.requested,
        unparsed=sum(1 for d in features.digests if not d.parsed),
        winrate=features.averages.get("winrate", 0),
    )

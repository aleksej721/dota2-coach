"""CLI: `python -m dota2coach analyze <match_id> --me <account_id> [--depth quick|deep]`.

Здесь собирается («провязывается») весь конвейер из конкретных реализаций.
Меняешь источник данных — правишь одну строку сборки, остальное не трогаешь.
"""

import argparse
import sys
from typing import Optional, Sequence

import requests

from .bundle import BundleBuilder
from .config import Config
from .constants import ConstantsRepo
from .features import FeatureExtractor
from .pipeline import Pipeline
from .ratelimit import RateLimiter
from .sources.base import DataSourceError
from .sources.opendota import OpenDotaSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dota2coach",
        description="Собирает промпт-разбор матча Dota 2 из данных OpenDota.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="проанализировать один матч")
    a.add_argument("match_id", type=int, help="ID матча Dota 2")
    a.add_argument("--me", type=int, default=None, help="твой account_id (Steam32)")
    a.add_argument("--hero", type=str, default=None,
                   help="или имя твоего героя в матче (если не знаешь account_id)")
    a.add_argument("--depth", choices=["quick", "deep"], default="quick",
                   help="объём промпта: quick (по умолчанию) или deep")
    return parser


def run_analyze(args: argparse.Namespace) -> int:
    if args.me is None and not args.hero:
        print("Ошибка: укажи --me <account_id> ИЛИ --hero <имя героя>.", file=sys.stderr)
        return 2

    config = Config.load()

    # Общая HTTP-сессия и один общий rate-limiter на все запросы (~1 req/sec).
    session = requests.Session()
    session.headers.update({"User-Agent": "dota2coach/0.1 (personal use)"})
    rate = RateLimiter(min_interval=1.0)

    constants = ConstantsRepo(session, rate, api_key=config.api_key)
    source = OpenDotaSource(session, constants, rate, api_key=config.api_key)
    extractor = FeatureExtractor(constants)
    builder = BundleBuilder()
    pipeline = Pipeline(source, extractor, builder, out_dir="output")

    try:
        path, text = pipeline.run(args.match_id, args.me, args.hero, args.depth)
    except DataSourceError as e:
        print(f"Не удалось: {e}", file=sys.stderr)
        return 1

    print(f"\nГотово: промпт сохранён в {path}")
    print("--- предпросмотр (первые строки) ---")
    print("\n".join(text.splitlines()[:12]))
    print("...\nСкопируй весь файл и вставь в ChatGPT/Claude.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "analyze":
        return run_analyze(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

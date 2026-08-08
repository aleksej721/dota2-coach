"""CLI: `python -m dota2coach analyze <match_id> --me <account_id> [--depth] [--focus]`.

Тонкая обёртка над core: разбор аргументов и печать. Конвейер собирается в
core.build_pipeline() — там же, откуда его берёт веб-интерфейс.
"""

import argparse
import sys
from typing import Optional, Sequence, Tuple

from .core import build_pipeline
from .i18n import DEFAULT_LANG, LANGUAGES
from .policy import DEPTHS, FOCUSES, ROLES, Policy
from .render import DEFAULT_MODEL, MODELS, resolve_depth
from .sources.base import DataSourceError


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
    a.add_argument("--depth", choices=list(DEPTHS), default=None,
                   help="объём промпта: quick (только S-тир) или deep; "
                        "по умолчанию — то, что подходит выбранной --model")
    a.add_argument("--focus", choices=list(FOCUSES), default="full",
                   help="под какой вопрос затачивать разбор (по умолчанию full)")
    a.add_argument("--role", choices=list(ROLES), default=None,
                   help="твоя позиция 1–5; переопределяет эвристику роли для тебя")
    a.add_argument("--model", choices=list(MODELS), default=DEFAULT_MODEL,
                   help="под какую LLM упаковать промпт (по умолчанию chatgpt): "
                        "claude получает XML-теги, остальные — markdown")
    a.add_argument("--lang", choices=list(LANGUAGES), default=DEFAULT_LANG,
                   help="язык промпта, включая инструкцию модели отвечать на нём")
    a.add_argument("--mmr", metavar="УРОВЕНЬ", default=None,
                   help="твой MMR или бракет (напр. 3500 или Legend) — модель "
                        "откалибрует советы под этот уровень")
    a.add_argument("--note", "--ask", dest="note", metavar="ТЕКСТ", default=None,
                   help="твой конкретный вопрос к разбору — он станет главным приоритетом "
                        "(напр. --note \"почему я слил лайн против Pudge?\")")
    a.add_argument("--window", metavar="НАЧАЛО-КОНЕЦ", default=None,
                   help="игровой промежуток в минутах (напр. 30-40) — он будет "
                        "показан с максимальной детализацией по всем героям, "
                        "а остальной матч сжат до сводки")
    a.add_argument("--no-cache", action="store_true",
                   help="не брать сырой ответ матча из .cache — сходить в API заново")

    s = sub.add_parser("serve", help="поднять локальный веб-интерфейс")
    s.add_argument("--host", default="127.0.0.1", help="по умолчанию 127.0.0.1")
    s.add_argument("--port", type=int, default=8000, help="по умолчанию 8000")
    s.add_argument("--reload", action="store_true", help="автоперезапуск при правках (dev)")
    return parser


def parse_window(raw: Optional[str]) -> Optional[Tuple[int, int]]:
    """«30-40» -> (30, 40). Валидацию границ делает Policy, здесь только разбор."""
    if not raw:
        return None
    parts = raw.replace("–", "-").split("-")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise ValueError(f"--window ожидает вид НАЧАЛО-КОНЕЦ в минутах, получено {raw!r}")
    return int(parts[0]), int(parts[1])


def run_analyze(args: argparse.Namespace) -> int:
    if args.me is None and not args.hero:
        print("Ошибка: укажи --me <account_id> ИЛИ --hero <имя героя>.", file=sys.stderr)
        return 2

    try:
        window = parse_window(args.window)
    except ValueError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2

    pipeline = build_pipeline(use_cache=not args.no_cache, out_dir="output")
    try:
        policy = Policy(depth=resolve_depth(args.depth, args.model), focus=args.focus,
                        note=args.note, model=args.model, lang=args.lang, mmr=args.mmr,
                        role=args.role, window=window)
    except ValueError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2

    try:
        path, text = pipeline.run(args.match_id, args.me, args.hero, policy)
    except DataSourceError as e:
        print(f"Не удалось: {e}", file=sys.stderr)
        return 1

    size_kb = len(text.encode("utf-8")) / 1024
    print(f"\nГотово: промпт сохранён в {path} ({size_kb:.1f} КБ, depth={policy.depth}, "
          f"focus={policy.focus}, model={policy.model}, lang={policy.lang})")
    if policy.mmr:
        print(f"Уровень для калибровки советов: {policy.mmr}")
    if policy.role:
        print(f"Роль для оценки: позиция {policy.role}")
    if policy.has_window:
        print(f"Окно с максимальной детализацией: {policy.window[0]}–{policy.window[1]} мин "
              f"(остальной матч сжат до сводки)")
    if policy.has_note:
        print(f"Главный запрос игрока: «{policy.note_inline}»")
    elif args.note is not None:
        print("Заметка пустая — промпт собран как обычно.", file=sys.stderr)
    print("--- предпросмотр (первые строки) ---")
    print("\n".join(text.splitlines()[:12]))
    print("...\nСкопируй весь файл и вставь в ChatGPT/Claude.")
    return 0


def run_serve(args: argparse.Namespace) -> int:
    # Импорт внутри функции: без веб-зависимостей CLI обязан работать как раньше.
    try:
        from .web import serve
    except ImportError:
        print("Веб-интерфейсу нужны fastapi и uvicorn:\n"
              "    pip install -r requirements.txt", file=sys.stderr)
        return 1
    serve(host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "analyze":
        return run_analyze(args)
    if args.command == "serve":
        return run_serve(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

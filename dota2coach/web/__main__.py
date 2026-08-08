"""Точка входа для `python -m dota2coach.web`."""

import argparse

from . import serve

if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="dota2coach.web",
                                description="Локальный веб-интерфейс dota2coach.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    args = p.parse_args()
    serve(host=args.host, port=args.port, reload=args.reload)

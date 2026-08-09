"""Веб-обёртка. `serve()` вынесен сюда, чтобы CLI не тянул uvicorn на импорте."""

from typing import Optional


def serve(host: Optional[str] = None, port: Optional[int] = None,
          reload: bool = False) -> None:
    """Поднимает сервер. Без явных host/port берёт их из окружения.

    На хостинге порт диктует переменная PORT, и слушать надо 0.0.0.0 —
    подробности и обоснование в config.server_binding().
    """
    import uvicorn

    from .. import config

    env_host, env_port = config.server_binding()
    host = host or env_host
    port = port or env_port

    print(f"dota2coach: http://{host}:{port}  (Ctrl+C — остановить)")
    # Строкой, а не объектом app: иначе не заработает --reload.
    uvicorn.run("dota2coach.web.app:app", host=host, port=port, reload=reload)

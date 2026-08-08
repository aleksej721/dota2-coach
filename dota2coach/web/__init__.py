"""Веб-обёртка. `serve()` вынесен сюда, чтобы CLI не тянул uvicorn на импорте."""


def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn

    print(f"dota2coach: http://{host}:{port}  (Ctrl+C — остановить)")
    # Строкой, а не объектом app: иначе не заработает --reload.
    uvicorn.run("dota2coach.web.app:app", host=host, port=port, reload=reload)

"""Локальный веб-интерфейс поверх core.generate_prompt().

Вторая обёртка над тем же ядром, что и CLI: сервер ничего не генерирует сам,
он только принимает форму, зовёт core и отдаёт текст. Ни БД, ни истории, ни
авторизации — инструмент личный и живёт на localhost.
"""

import asyncio
import json
import pathlib
import threading
from typing import Literal, Optional, get_args

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import i18n
from ..core import build_pipeline, generate_prompt
from ..policy import DEPTHS, FOCUSES, ROLES, ROLE_FOCUSES, Policy
from ..render import MODELS, PROFILES, resolve_depth
from ..sources.base import (KIND_NETWORK, KIND_NOT_FOUND, KIND_PLAYER_NOT_FOUND,
                            KIND_RATE_LIMITED, KIND_UNAVAILABLE, DataSourceError)

STATIC_DIR = pathlib.Path(__file__).parent / "static"

# OpenDota парсит матч до ~3 минут; держим запас и отвечаем понятным 504,
# а не рвём соединение молча.
REQUEST_TIMEOUT_SEC = 240.0

Depth = Literal["quick", "deep"]
Focus = Literal[
    "full", "laning", "fights", "farm", "draft",
    "vision", "tempo", "initiation", "enable",
]
Role = Literal["1", "2", "3", "4", "5"]
Model = Literal["chatgpt", "claude", "gemini"]
Lang = Literal["ru", "en", "uk"]

# Значения продублированы ради автодокументации и валидации pydantic — страхуемся,
# чтобы они не разъехались с policy.py, render.py и i18n.
assert set(get_args(Depth)) == set(DEPTHS)
assert set(get_args(Focus)) == set(FOCUSES)
assert set(get_args(Role)) == set(ROLES)
assert set(get_args(Model)) == set(MODELS)
assert set(get_args(Lang)) == set(i18n.LANGUAGES)

# Вид сбоя источника -> HTTP-код. Без этой таблицы пришлось бы разбирать
# текст исключения регулярками.
STATUS_BY_KIND = {
    KIND_NOT_FOUND: 404,
    KIND_PLAYER_NOT_FOUND: 400,
    KIND_RATE_LIMITED: 429,
    KIND_NETWORK: 502,
    KIND_UNAVAILABLE: 502,
}

app = FastAPI(title="dota2coach", docs_url="/api/docs", redoc_url=None)

# Один конвейер на процесс: переиспользуются прогретые справочники и общий
# rate-limiter. RateLimiter однопоточный, поэтому разборы сериализуем локом —
# параллельно разбирать два матча локально всё равно незачем.
_pipeline_lock = threading.Lock()
_pipeline = None


def _generate_blocking(match_id, account_id, hero, policy):
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            # out_dir не используется: веб в output/ не пишет, файл отдаёт браузер.
            _pipeline = build_pipeline()
        return generate_prompt(match_id, account_id, hero, policy, pipeline=_pipeline)


class AnalyzeRequest(BaseModel):
    match_id: int = Field(..., gt=0, description="ID матча Dota 2")
    account_id: Optional[int] = Field(None, gt=0, description="твой account_id (Steam32)")
    hero: Optional[str] = Field(None, description="или имя героя, если account_id неизвестен")
    # depth=None означает «взять дефолт выбранной модели», см. render.resolve_depth.
    depth: Optional[Depth] = None
    focus: Focus = "full"
    model: Model = "chatgpt"
    lang: Lang = "ru"
    note: Optional[str] = Field(None, description="твой вопрос — станет главным приоритетом")
    mmr: Optional[str] = Field(None, description="MMR или бракет для калибровки советов")
    role: Optional[Role] = Field(None, description="позиция 1–5; null = эвристика матча")
    # Окно приходит двумя числами, а не строкой «30-40»: так его валидирует
    # pydantic, а не наш разбор текста.
    window_start: Optional[int] = Field(None, ge=0, le=180,
                                        description="начало окна разбора, минуты")
    window_end: Optional[int] = Field(None, ge=1, le=180,
                                      description="конец окна разбора, минуты")


class AnalyzeResponse(BaseModel):
    prompt: str
    filename: str
    size_bytes: int
    depth: str
    focus: str
    model: str
    lang: str
    has_note: bool
    has_mmr: bool
    role: Optional[str]
    parsed: bool
    window: Optional[str] = None
    warning: Optional[str] = None


def _index_html() -> str:
    """Страница с подставленными словарями интерфейса.

    Словари живут в Python (i18n/) и инжектятся в разметку при отдаче: так
    единственный источник строк остаётся один на весь проект, а браузеру не
    нужен отдельный запрос, из-за которого подписи моргали бы на другом языке.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    payload = {
        "strings": i18n.ui_catalogs(),
        "languages": [{"code": code, "name": i18n.LANGUAGE_NAMES[code]}
                      for code in i18n.LANGUAGES],
        "models": [{"code": p.name, "label": p.label, "defaultDepth": p.default_depth}
                   for p in PROFILES.values()],
        "roles": list(ROLES),
        "focuses": list(FOCUSES),
        "roleFocuses": ROLE_FOCUSES,
        "defaultLang": i18n.DEFAULT_LANG,
    }
    script = f"<script>window.I18N = {json.dumps(payload, ensure_ascii=False)};</script>"
    return html.replace("<!--I18N-->", script)


@app.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    # no-store: страница одна и лежит рядом, а закэшированная версия после правки
    # стоит дороже, чем её повторная отдача.
    return HTMLResponse(_index_html(), headers={"Cache-Control": "no-store"})


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if req.account_id is None and not (req.hero or "").strip():
        raise HTTPException(422, {"kind": "player_not_specified", "message": ""})

    window = None
    if req.window_start is not None and req.window_end is not None:
        if req.window_end <= req.window_start:
            raise HTTPException(422, {"kind": "bad_window", "message": ""})
        window = (req.window_start, req.window_end)

    policy = Policy(depth=resolve_depth(req.depth, req.model), focus=req.focus,
                    note=req.note, model=req.model, lang=req.lang, mmr=req.mmr,
                    role=req.role, window=window)

    try:
        # Блокирующие requests уводим в пул потоков, чтобы не держать event loop.
        # На таймауте поток продолжит работу (убить его нельзя) — просто ответим 504.
        result = await asyncio.wait_for(
            run_in_threadpool(_generate_blocking, req.match_id, req.account_id,
                              (req.hero or "").strip() or None, policy),
            timeout=REQUEST_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, {"kind": "parse_timeout", "message": ""})
    except DataSourceError as e:
        # detail отдаём объектом: страница локализует текст по `kind`, а `message`
        # нужен там, где в нём есть данные (например, список игроков матча).
        raise HTTPException(STATUS_BY_KIND.get(e.kind, 502),
                            {"kind": e.kind, "message": str(e)})

    return AnalyzeResponse(
        prompt=result.text,
        filename=result.filename,
        size_bytes=result.size_bytes,
        depth=policy.depth,
        focus=policy.focus,
        model=policy.model,
        lang=policy.lang,
        has_note=policy.has_note,
        has_mmr=bool(policy.mmr),
        role=policy.role,
        parsed=result.parsed,
        window=f"{policy.window[0]}–{policy.window[1]}" if policy.has_window else None,
        # Текст предупреждения собирает страница: он тоже локализован.
        warning="unparsed" if not result.parsed else None,
    )

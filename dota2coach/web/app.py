"""Локальный веб-интерфейс поверх core.generate_prompt().

Вторая обёртка над тем же ядром, что и CLI: сервер ничего не генерирует сам,
он только принимает форму, зовёт core и отдаёт текст. Ни БД, ни истории, ни
авторизации — инструмент личный и живёт на localhost.
"""

import asyncio
import hashlib
import json
import pathlib
import threading
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Literal, Optional, get_args

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import config, feedback, i18n
from ..core import build_pipeline, generate_profile_prompt, generate_prompt
from ..policy import DEPTHS, FOCUSES, ROLES, ROLE_FOCUSES, Policy
from ..profile import DEFAULT_MATCHES, MAX_MATCHES, MIN_MATCHES
from ..render import MODELS, PROFILES, resolve_depth
from ..sources.base import (KIND_HERO_UNKNOWN, KIND_NETWORK, KIND_NO_MATCHES,
                            KIND_NOT_FOUND, KIND_PLAYER_NOT_FOUND, KIND_RATE_LIMITED,
                            KIND_UNAVAILABLE, DataSourceError)

STATIC_DIR = pathlib.Path(__file__).parent / "static"

# Ждём чуть дольше, чем сам парсинг, и отвечаем понятным 504, а не рвём
# соединение молча. Привязано к PARSE_TIMEOUT_SEC: на хостинге его уменьшают,
# и разъехаться эти два значения не должны.
REQUEST_TIMEOUT_SEC = config.parse_timeout_sec() + 60.0

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
    KIND_NO_MATCHES: 404,
    KIND_HERO_UNKNOWN: 400,
    KIND_RATE_LIMITED: 429,
    KIND_NETWORK: 502,
    KIND_UNAVAILABLE: 502,
}

# Один конвейер на процесс: переиспользуются прогретые справочники и общий
# rate-limiter. Разборы сериализуем локом — лимит OpenDota (60 запросов/мин)
# общий на всех пользователей сервиса, а не на каждого.
_pipeline_lock = threading.Lock()
# Отдельный лок только на создание: иначе прогрев в фоне ждал бы, пока
# завершится чужой разбор, и весь смысл прогрева пропал бы.
_init_lock = threading.Lock()
_pipeline = None


def _shared_pipeline():
    global _pipeline
    with _init_lock:
        if _pipeline is None:
            # out_dir не используется: веб в output/ не пишет, файл отдаёт браузер.
            _pipeline = build_pipeline()
    return _pipeline


def _warm_up() -> None:
    """Тянет справочники OpenDota заранее, в фоне.

    Без прогрева за них платит первый посетитель: восемь ресурсов через общий
    rate-limiter — это секунды поверх и без того небыстрого холодного старта.
    Идёт БЕЗ _pipeline_lock, чтобы не задерживать разбор, если он начался
    раньше; очерёдность запросов к API всё равно держит rate-limiter.
    """
    try:
        _shared_pipeline().warm()
        print("dota2coach: справочники прогреты")
    except Exception as e:  # прогрев — оптимизация, его сбой не должен ронять сервис
        print(f"dota2coach: прогрев справочников не удался ({e})")


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm_up, name="warmup", daemon=True).start()
    yield


app = FastAPI(title="dota2coach", docs_url="/api/docs", redoc_url=None,
              lifespan=lifespan)


def _generate_blocking(match_id, account_id, hero, policy, raw_match=None):
    with _pipeline_lock:
        return generate_prompt(match_id, account_id, hero, policy,
                               pipeline=_shared_pipeline(), raw_match=raw_match)


def _profile_blocking(account_id, matches, hero, role, policy,
                      raw_matches=None, match_ids=None):
    with _pipeline_lock:
        return generate_profile_prompt(account_id, matches, hero, role, policy,
                                       pipeline=_shared_pipeline(),
                                       raw_matches=raw_matches, match_ids=match_ids)


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
    # Ответ OpenDota /matches/{id}, который страница скачала сама со своего IP.
    # Необязателен: без него сервер тянет матч обычным путём.
    raw_match: Optional[Dict[str, Any]] = Field(
        None, description="сырой ответ OpenDota, уже скачанный браузером")
    # Короткий промпт-уточнение по отрезку для того же чата (нужно окно).
    followup: bool = False
    # Разбор матча целиком, без привязки к игроку: account_id и hero не нужны.
    whole_game: bool = False


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
    # Сторона и исход нужны интерфейсу: результат окрашивается в цвета фракции
    # игрока, а не в один нейтральный акцент.
    side: str
    win: bool
    window: Optional[str] = None
    warning: Optional[str] = None
    overview: Dict[str, Any]


def _source_failure(e: DataSourceError) -> HTTPException:
    """Сбой источника: в лог — техническую причину, пользователю — локализованную.

    Печать в stdout здесь не отладочный мусор, а единственный след сбоя на
    хостинге: FastAPI пишет в лог только код ответа, а страница показывает текст,
    выбранный по `kind`, — по нему не отличить исчерпанный лимит от блокировки
    клиента или HTML-заглушки вместо JSON. Без этой строки разбирать «OpenDota
    недоступна» на проде не по чему.

    detail отдаём объектом: страница локализует текст по `kind`, а `message`
    нужен там, где в нём есть данные (например, список игроков матча).
    """
    print(f"dota2coach: сбой источника [{e.kind}] {e}", flush=True)
    return HTTPException(STATUS_BY_KIND.get(e.kind, 502),
                         {"kind": e.kind, "message": str(e)})


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
    return (html.replace("<!--I18N-->", script)
                .replace("__ASSET_VERSION__", _asset_version()))


# Стили и скрипт живут отдельными файлами рядом с index.html. Отдаём их явными
# маршрутами, а не StaticFiles на весь каталог: наружу должны смотреть ровно эти
# два файла, а не всё, что когда-нибудь окажется в static/.
_ASSETS = {"app.css": "text/css; charset=utf-8",
           "app.js": "text/javascript; charset=utf-8"}


def _asset_version() -> str:
    """Короткий хэш содержимого ассетов — меняется ровно тогда, когда меняются они.

    Версия в адресе позволяет отдавать файлы с долгим кэшем: после деплоя у
    страницы другой ?v=, и браузер не подсунет пользователю старый скрипт к новой
    разметке — именно такой рассинхрон ломает интерфейс «непонятно почему».
    """
    digest = hashlib.sha256()
    for name in sorted(_ASSETS):
        digest.update((STATIC_DIR / name).read_bytes())
    return digest.hexdigest()[:12]


@app.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    # no-store: страница одна и лежит рядом, а закэшированная версия после правки
    # стоит дороже, чем её повторная отдача.
    return HTMLResponse(_index_html(), headers={"Cache-Control": "no-store"})


def _asset(name: str) -> Response:
    return Response((STATIC_DIR / name).read_bytes(), media_type=_ASSETS[name],
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


# Два явных маршрута, а не шаблон «/{name}»: шаблон, объявленный выше /healthz,
# перехватил бы и его, и хостинг счёл бы сервис мёртвым.
@app.get("/app.css", include_in_schema=False)
async def app_css() -> Response:
    return _asset("app.css")


@app.get("/app.js", include_in_schema=False)
async def app_js() -> Response:
    return _asset("app.js")


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    """Проба живости для хостинга: отвечает сразу, в сеть не ходит."""
    return {"status": "ok", "warm": _pipeline is not None}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if not req.whole_game and req.account_id is None and not (req.hero or "").strip():
        raise HTTPException(422, {"kind": "player_not_specified", "message": ""})

    window = None
    if req.window_start is not None and req.window_end is not None:
        if req.window_end <= req.window_start:
            raise HTTPException(422, {"kind": "bad_window", "message": ""})
        window = (req.window_start, req.window_end)

    policy = Policy(depth=resolve_depth(req.depth, req.model), focus=req.focus,
                    note=req.note, model=req.model, lang=req.lang, mmr=req.mmr,
                    role=None if req.whole_game else req.role, window=window,
                    followup=req.followup and window is not None,
                    whole_game=req.whole_game)

    try:
        # Блокирующие requests уводим в пул потоков, чтобы не держать event loop.
        # На таймауте поток продолжит работу (убить его нельзя) — просто ответим 504.
        result = await asyncio.wait_for(
            run_in_threadpool(_generate_blocking, req.match_id, req.account_id,
                              (req.hero or "").strip() or None, policy, req.raw_match),
            timeout=REQUEST_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, {"kind": "parse_timeout", "message": ""})
    except DataSourceError as e:
        raise _source_failure(e)

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
        side=result.side,
        win=result.win,
        window=f"{policy.window[0]}–{policy.window[1]}" if policy.has_window else None,
        # Текст предупреждения собирает страница: он тоже локализован.
        warning="unparsed" if not result.parsed else None,
        overview=result.overview,
    )


class ProfileRequest(BaseModel):
    account_id: int = Field(..., gt=0, description="твой account_id (Steam32)")
    matches: int = Field(DEFAULT_MATCHES, ge=MIN_MATCHES, le=MAX_MATCHES,
                         description="сколько последних матчей агрегировать")
    hero: Optional[str] = Field(None, description="фильтр: только матчи на этом герое")
    role: Optional[Role] = Field(None, description="фильтр: только эта позиция 1–5")
    model: Model = "chatgpt"
    lang: Lang = "ru"
    note: Optional[str] = Field(None, description="твой вопрос — станет главным приоритетом")
    mmr: Optional[str] = Field(None, description="MMR или бракет для калибровки советов")
    # То, что страница уже скачала сама: список матчей игрока и ответы по ним.
    match_ids: Optional[List[int]] = Field(None, max_length=MAX_MATCHES * 2)
    raw_matches: Optional[List[Dict[str, Any]]] = Field(None, max_length=MAX_MATCHES * 2)


class ProfileResponse(BaseModel):
    prompt: str
    filename: str
    size_bytes: int
    account_id: int
    analyzed: int
    requested: int
    unparsed: int
    winrate: int
    model: str
    lang: str
    has_note: bool
    has_mmr: bool
    role: Optional[str]
    warning: Optional[str] = None


# Профиль тянет матчи по одному через общий rate-limiter (~1 запрос/сек), поэтому
# ждать приходится дольше одиночного разбора: своё окно таймаута.
PROFILE_TIMEOUT_SEC = 420.0


@app.get("/api/profile/plan")
async def profile_plan(matches: int = DEFAULT_MATCHES, hero: Optional[str] = None,
                       role: Optional[Role] = None) -> Dict[str, Optional[int]]:
    """Параметры запроса /players/{id}/matches для страницы.

    Сети не трогает, кроме справочника героев (у него есть зеркало на GitHub).
    """
    try:
        return await run_in_threadpool(
            _shared_pipeline().profile_query, matches, (hero or "").strip() or None, role)
    except DataSourceError as e:
        raise _source_failure(e)


@app.get("/api/heroes")
async def heroes() -> Response:
    """Имена героев по id — для списка последних матчей на странице.

    Сами матчи страница берёт у OpenDota со своего IP, а справочник у сервера
    уже прогрет (и у него есть зеркало). Список меняется с патчами, поэтому кэш
    на час, а не навсегда.
    """
    names = await run_in_threadpool(_shared_pipeline().hero_names)
    return Response(json.dumps(names, ensure_ascii=False), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/profile", response_model=ProfileResponse)
async def profile(req: ProfileRequest) -> ProfileResponse:
    policy = Policy(model=req.model, lang=req.lang, mmr=req.mmr, note=req.note)

    try:
        result = await asyncio.wait_for(
            run_in_threadpool(_profile_blocking, req.account_id, req.matches,
                              (req.hero or "").strip() or None, req.role, policy,
                              req.raw_matches, req.match_ids),
            timeout=PROFILE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, {"kind": "profile_timeout", "message": ""})
    except DataSourceError as e:
        raise _source_failure(e)

    # Одно предупреждение, а не два: неполнота данных важнее недобора выборки,
    # и два баннера подряд читаются как «всё сломалось».
    warning = None
    if result.unparsed:
        warning = "profile_unparsed"
    elif result.analyzed < result.requested:
        warning = "profile_short"

    return ProfileResponse(
        prompt=result.text,
        filename=result.filename,
        size_bytes=result.size_bytes,
        account_id=result.account_id,
        analyzed=result.analyzed,
        requested=result.requested,
        unparsed=result.unparsed,
        winrate=result.winrate,
        model=policy.model,
        lang=policy.lang,
        has_note=policy.has_note,
        has_mmr=bool(policy.mmr),
        role=req.role,
        warning=warning,
    )


# Отзывы. Хранилище собирается один раз: у JSONL внутри лок, у ограничителя —
# счётчик окна, и пересоздавать их на каждый запрос нельзя.
_feedback_store = feedback.build_store()

# Длинный комментарий никто не пишет, а вот залить мегабайт в лог можно легко.
MAX_COMMENT_CHARS = 2000


class FeedbackRequest(BaseModel):
    """Оценка разбора. account_id намеренно НЕ принимаем — см. feedback.py."""

    rating: Literal[1, -1] = Field(..., description="1 — полезно, -1 — нет")
    mode: Literal["match", "game", "profile"]
    lang: Lang = "ru"
    model: Model = "chatgpt"
    comment: Optional[str] = Field(None, max_length=MAX_COMMENT_CHARS,
                                   description="что не так или что улучшить")
    match_id: Optional[int] = Field(None, gt=0)
    role: Optional[Role] = None
    depth: Optional[Depth] = None
    focus: Optional[Focus] = None
    window: Optional[str] = Field(None, max_length=16)
    matches: Optional[int] = Field(None, ge=0, le=MAX_MATCHES)
    prompt_bytes: Optional[int] = Field(None, ge=0)
    followup: bool = False


@app.post("/api/feedback", status_code=202)
async def submit_feedback(req: FeedbackRequest) -> dict:
    entry = feedback.Feedback(
        rating=req.rating,
        mode=req.mode,
        lang=req.lang,
        model=req.model,
        created_at=feedback.Feedback.now_iso(),
        comment=(req.comment or "").strip() or None,
        match_id=req.match_id,
        role=req.role,
        depth=req.depth,
        focus=req.focus,
        window=req.window,
        matches=req.matches,
        prompt_bytes=req.prompt_bytes,
        followup=req.followup,
    )
    # Запись блокирующая (файл, возможно вебхук) — уводим в пул потоков, чтобы
    # не держать event loop. Ошибки хранилищ наружу не выходят: пользователь
    # своё дело сделал, и показывать ему чужие сбои незачем.
    await run_in_threadpool(_feedback_store.save, entry)
    return {"status": "accepted"}

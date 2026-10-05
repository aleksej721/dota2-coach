"""Скаффолд — методика разбора, вшитая в промпт.

Обычный игрок не знает приёмов промптинга и получает от модели вежливую воду:
«играй аккуратнее», «фарми лучше». Лечится это не длиной запроса, а тем, что
методику разбора мы задаём сами:

  * правила (guardrails) — что модели ЗАПРЕЩЕНО и чем она обязана подкреплять
    каждое утверждение;
  * формат ответа — фиксированные разделы в фиксированном порядке.

Модуль отвечает только за инструкцию модели. Что за данные лежат в промпте,
решает policy.py — это разные оси, и смешивать их нельзя: правка методики
не должна задевать отбор фактов.
"""

from typing import List

from .i18n import Strings
from .policy import Policy

# Разделы ответа. Их четыре, и это сознательно мало. Прежний формат из десяти
# обязательных разделов давал простыню, где главное тонуло, и заставлял модель
# заполнять каждый — в том числе «главную ошибку игрока» там, где честный ответ
# «значимой ошибки не было».
#
# why и control — два разных вопроса, и их нельзя смешивать: почему игра пошла
# так (на уровне матча) и что было в руках игрока (изменило бы это исход).
# clarify идёт последним и пропускается, если уточнять нечего: вопросы и
# предложение лупы в каждом ответе превращались в ритуал.
#
# Драфт подробно — отдельным разделом только при фокусе draft: в обычном разборе
# он одно из наблюдений, а не обязательная глава.
_FORMAT_SECTIONS = ("why", "control", "observations", "action", "clarify")


def method_lines(policy: Policy, s: Strings) -> List[str]:
    """Как модели думать над разбором.

    Принципов семь, и в них нет ни одного примера с конкретным героем. Раньше
    правил было больше двадцати: большинство появлялись заплатками на нехватку
    данных («не вини за фарм», «не утверждай про BKB»), и модель тратила внимание
    на соблюдение запретов вместо разбора. Теперь недостающее посчитано в секции
    «Картина матча», а знание игры модели разрешено и ожидается.
    """
    rules: List[str] = []
    if policy.has_note:
        rules.append(s("method.note_priority"))
    if policy.has_role:
        rules.append(s(f"method.role.{policy.role}"))
    for key in ("questions", "knowledge", "causality", "build", "draft", "solo", "brief"):
        rules.append(s(f"principle.{key}"))
    if policy.mmr:
        rules.append(s("method.calibrate", level=policy.mmr))
    rules.append(s("method.language", language=s("answer_language")))

    out = [s("method.intro")]
    out += [f"{i}. {rule}" for i, rule in enumerate(rules, 1)]
    if policy.focus != "full":
        out.append("")
        out.append(s("method.focus", focus=s(f"focus.{policy.focus}")))
    return out


# Разделы ответа для профиля. Другие, чем у одного матча: там разбирают эпизод,
# здесь — привычку, и «разбор по стадиям одного матча» смысла не имеет.
_PROFILE_SECTIONS = ("portrait", "stable", "leak", "timeline", "plan",
                     "hypotheses", "questions")


def _sections(keys: List[str], prefix: str, policy: Policy, s: Strings) -> List[str]:
    out = [s(f"{prefix}.intro"), ""]
    # Нумерация от нуля, если первым идёт ответ на вопрос игрока, иначе от единицы.
    first = 0 if keys and keys[0] == "note" else 1
    for number, key in enumerate(keys, first):
        out.append(f"### {number}. {s(f'{prefix}.{key}.title')}")
        role_key = f"{prefix}.{key}.body.role.{policy.role}"
        out.append(s(role_key) if policy.has_role and s.has(role_key)
                   else s(f"{prefix}.{key}.body"))
        out.append("")
    return out[:-1]  # лишняя пустая строка в конце документа не нужна


def format_lines(policy: Policy, s: Strings) -> List[str]:
    """Структура ответа: заголовок раздела + что в нём должно быть."""
    keys = list(_FORMAT_SECTIONS)
    if policy.focus == "draft":
        keys.insert(keys.index("observations"), "draft")
    if policy.has_note:
        keys.insert(0, "note")
    return _sections(keys, "format", policy, s)


def profile_method_lines(policy: Policy, matches: int, s: Strings) -> List[str]:
    """Правила для кросс-матчевого разбора.

    Свои правила профиля (повторяющееся, размер выборки, причинность, пул
    героев, нет полных данных) плюс общие принципы краткости и советов под
    соло-паб.
    """
    rules: List[str] = []

    if policy.has_note:
        rules.append(s("method.note_priority"))
    if policy.has_role:
        rules.append(s(f"method.role.{policy.role}"))
    rules.append(s("profile.method.repeating"))
    rules.append(s("profile.method.sample", matches=matches))
    # Причинность нужна и здесь, иначе режимы разъедутся по строгости: разбор
    # одного матча отделяет решение от следствия, а профиль по-прежнему выдаёт
    # низкий фарм в проигранных позициях за привычку игрока.
    rules.append(s("profile.method.agency"))
    # Что за игрок перед нами — тренирующий одного героя или подбирающий героя
    # под драфт — по одному матчу не видно вовсе, а по выборке видно сразу.
    # Поэтому правило про пул героев живёт только здесь.
    rules.append(s("profile.method.hero_pool"))
    rules.append(s("profile.method.no_raw"))
    rules.append(s("profile.method.knowledge"))
    rules.append(s("principle.solo"))
    rules.append(s("principle.brief"))
    if policy.mmr:
        rules.append(s("method.calibrate", level=policy.mmr))
    rules.append(s("method.language", language=s("answer_language")))

    out = [s("profile.method.intro", matches=matches)]
    out += [f"{i}. {rule}" for i, rule in enumerate(rules, 1)]
    return out


def profile_format_lines(policy: Policy, s: Strings) -> List[str]:
    keys = list(_PROFILE_SECTIONS)
    if policy.has_note:
        keys.insert(0, "note")
    return _sections(keys, "profile.format", policy, s)

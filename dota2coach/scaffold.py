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

# Разделы ответа в фиксированном порядке. Ключ 0 добавляется только тогда,
# когда у игрока есть свой вопрос: без него нумерация начинается с вердикта.
#
# s4 (драфт и билд) стоит после главного leak’а и до разбора по стадиям: это
# рамка, в которой стадии только и имеют смысл — герой, взятый под конкретную
# идею, и сборка против конкретного состава. Раздел обязателен всегда, даже
# когда ни драфт, ни билд проблемой не были: «вопросов нет» — тоже вывод.
#
# s7 (гипотезы) и s8 (вопросы игроку) закрывают ответ намеренно: разбор — это
# начало разговора, а не финальный вердикт. Модель обязана оставить на столе
# несколько версий и спросить то, чего в данных нет.
_FORMAT_SECTIONS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8")


def method_lines(policy: Policy, s: Strings) -> List[str]:
    """Правила, по которым модель обязана готовить разбор."""
    rules: List[str] = []

    # Порядок не случайный: сначала то, что чаще всего нарушается.
    if policy.has_note:
        rules.append(s("method.note_priority"))
    if policy.has_role:
        rules.append(s(f"method.role.{policy.role}"))
    rules.append(s("method.evidence"))
    rules.append(s("method.no_generic"))
    # Драфт и билд — единственные две оси, о которых модель молчит охотнее
    # всего: по ним нет готовых чисел, и без прямого требования разбор
    # сваливается в пересказ статистики. Правило про драфт заодно ставит
    # границу честности: рассуждать из общих знаний можно, выдумывать мету —
    # нельзя, и «не уверен» здесь допустимый ответ.
    rules.append(s("method.draft"))
    rules.append(s("method.build"))
    # Идут вместе: без разбора аномалий гипотезы вырождаются в общие места,
    # а без диалогового правила модель выдаёт «финальный вердикт» и замолкает.
    rules.append(s("method.anomalies"))
    rules.append(s("method.dialogue"))
    rules.append(s("method.impact_first"))
    rules.append(s("method.explain_why"))
    rules.append(s("method.balance"))
    rules.append(s("method.no_invention"))
    if policy.mmr:
        rules.append(s("method.calibrate", level=policy.mmr))
    rules.append(s("method.language", language=s("answer_language")))

    out = [s("method.intro")]
    out += [f"{i}. {rule}" for i, rule in enumerate(rules, 1)]
    out.append("")
    out.append(s("method.focus", focus=s(f"focus.{policy.focus}")))
    return out


# Разделы ответа для профиля. Другие, чем у одного матча: там разбирают эпизод,
# здесь — привычку, и «разбор по стадиям одного матча» смысла не имеет.
_PROFILE_SECTIONS = ("p1", "p2", "p3", "p4", "p5", "p6", "p7")


def _sections(keys: List[str], prefix: str, policy: Policy, s: Strings) -> List[str]:
    out = [s(f"{prefix}.intro"), ""]
    for key in keys:
        out.append(f"### {s(f'{prefix}.{key}.title')}")
        role_key = f"{prefix}.{key}.body.role.{policy.role}"
        out.append(s(role_key) if policy.has_role and s.has(role_key)
                   else s(f"{prefix}.{key}.body"))
        out.append("")
    return out[:-1]  # лишняя пустая строка в конце документа не нужна


def format_lines(policy: Policy, s: Strings) -> List[str]:
    """Структура ответа: заголовок раздела + что в нём должно быть."""
    keys = list(_FORMAT_SECTIONS)
    if policy.has_note:
        keys.insert(0, "s0")
    return _sections(keys, "format", policy, s)


def profile_method_lines(policy: Policy, matches: int, s: Strings) -> List[str]:
    """Правила для кросс-матчевого разбора.

    Общие с одиночным разбором правила переиспользуются как есть; добавляются
    три, специфичные именно для профиля: разбирать повторяющееся, помнить про
    размер выборки и не притворяться, что полные данные матчей под рукой.
    """
    rules: List[str] = []

    if policy.has_note:
        rules.append(s("method.note_priority"))
    if policy.has_role:
        rules.append(s(f"method.role.{policy.role}"))
    rules.append(s("profile.method.repeating"))
    rules.append(s("profile.method.sample", matches=matches))
    # Что за игрок перед нами — тренирующий одного героя или подбирающий героя
    # под драфт — по одному матчу не видно вовсе, а по выборке видно сразу.
    # Поэтому правило про пул героев живёт только здесь.
    rules.append(s("profile.method.hero_pool"))
    rules.append(s("profile.method.no_raw"))
    rules.append(s("method.evidence"))
    rules.append(s("method.no_generic"))
    rules.append(s("method.dialogue"))
    rules.append(s("method.impact_first"))
    rules.append(s("method.explain_why"))
    rules.append(s("method.balance"))
    rules.append(s("method.no_invention"))
    if policy.mmr:
        rules.append(s("method.calibrate", level=policy.mmr))
    rules.append(s("method.language", language=s("answer_language")))

    out = [s("profile.method.intro", matches=matches)]
    out += [f"{i}. {rule}" for i, rule in enumerate(rules, 1)]
    return out


def profile_format_lines(policy: Policy, s: Strings) -> List[str]:
    keys = list(_PROFILE_SECTIONS)
    if policy.has_note:
        keys.insert(0, "p0")
    return _sections(keys, "profile.format", policy, s)

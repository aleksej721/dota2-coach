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
_FORMAT_SECTIONS = ("s1", "s2", "s3", "s4", "s5", "s6")


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


def format_lines(policy: Policy, s: Strings) -> List[str]:
    """Структура ответа: заголовок раздела + что в нём должно быть."""
    out = [s("format.intro"), ""]

    keys = list(_FORMAT_SECTIONS)
    if policy.has_note:
        keys.insert(0, "s0")

    for key in keys:
        out.append(f"### {s(f'format.{key}.title')}")
        role_key = f"format.{key}.body.role.{policy.role}"
        out.append(s(role_key) if policy.has_role and s.has(role_key)
                   else s(f"format.{key}.body"))
        out.append("")
    return out[:-1]  # лишняя пустая строка в конце документа не нужна

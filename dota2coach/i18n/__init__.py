"""Словари текстов: и промпта, и интерфейса.

Единственный источник строк в проекте. Код нигде не печатает готовую прозу —
он отдаёт КЛЮЧ, а текст подставляется здесь. Благодаря этому язык промпта
переключается так же, как язык интерфейса, а новый язык добавляется одним
файлом рядом с ru.py.

Каждый языковой модуль экспортирует два словаря:
  PROMPT — то, что уходит в .txt для LLM;
  UI     — подписи веб-страницы (отдаются в браузер как есть).
"""

from typing import Any, Dict, List

from . import en, ru, uk

DEFAULT_LANG = "ru"

_MODULES = {"ru": ru, "en": en, "uk": uk}

LANGUAGES: List[str] = list(_MODULES)

# Как язык называется на самом себе — так его и показываем в переключателе.
LANGUAGE_NAMES: Dict[str, str] = {"ru": "Русский", "en": "English", "uk": "Українська"}


class Strings:
    """Доступ к текстам одного языка: s('sec.meta'), s('meta.me', hero=...)."""

    def __init__(self, lang: str):
        self.lang = lang
        module = _MODULES[lang]
        self._prompt: Dict[str, str] = module.PROMPT
        self.ui: Dict[str, Any] = module.UI

    def __call__(self, key: str, **params: Any) -> str:
        template = self._prompt.get(key)
        if template is None:
            # Явный маркер вместо тихой пустоты: недостающий перевод должен
            # бросаться в глаза при первом же просмотре промпта.
            return f"[{key}?]"
        return template.format(**params) if params else template

    def has(self, key: str) -> bool:
        return key in self._prompt


def load(lang: str) -> Strings:
    return Strings(lang if lang in _MODULES else DEFAULT_LANG)


def ui_catalogs() -> Dict[str, Dict[str, Any]]:
    """Все UI-словари разом — страница получает их одним куском при загрузке."""
    return {lang: module.UI for lang, module in _MODULES.items()}


def missing_keys() -> Dict[str, List[str]]:
    """Ключи, которые есть в русском, но забыты в других языках — для самотеста.

    Русский здесь эталон: именно на нём пишутся новые тексты, и именно с ним
    сверяются остальные переводы.
    """
    report: Dict[str, List[str]] = {}
    for lang, module in _MODULES.items():
        if lang == DEFAULT_LANG:
            continue
        gap = sorted((set(ru.PROMPT) - set(module.PROMPT))
                     | {f"UI:{k}" for k in set(ru.UI) - set(module.UI)})
        if gap:
            report[lang] = gap
    return report

"""Policy — единственное место, где решается «что вообще попадёт в промпт».

Главный принцип проекта: СИГНАЛ > ОБЪЁМ. Из OpenDota мы вытаскиваем максимум,
но экспортируем отобранное. Отбор задаётся двумя ручками:

  --depth quick|deep                     сколько подробностей вообще
  --focus full|laning|fights|farm|draft|vision|tempo|initiation|enable
                                             под какой вопрос заточен разбор
  --role 1|2|3|4|5                         как оценивать выбранного игрока

Здесь же лежат параметры, которые объём не меняют, но определяют, как промпт
подан модели: --note (вопрос игрока), --mmr (уровень для калибровки советов),
--model (упаковка, см. render.py) и --lang (язык промпта, см. i18n). Все они
живут в одном объекте, потому что все приходят от пользователя и вместе едут
через конвейер.

Заметка объёма промпта не меняет — она меняет ПРИОРИТЕТ: если она задана,
разбор начинается с неё, а базовые разделы становятся дополнением.

Каждая секция получает УРОВЕНЬ ДЕТАЛИЗАЦИИ 0..3:

  0 — секции нет в промпте;
  1 — сводка: только S-тир (мои данные + командные агрегаты);
  2 — развёрнуто: A-тир (все 10 игроков, поминутные ряды, поимённые раскладки);
  3 — полный лог: B-тир и сырые последовательности (только по явному фокусу).

FeatureExtractor смотрит на уровень, чтобы не считать лишнего; BundleBuilder —
чтобы не печатать лишнего. Больше нигде решений «показывать/не показывать» нет.
"""

from dataclasses import dataclass, field, replace
from typing import Dict, Optional, Tuple

from .i18n import DEFAULT_LANG, LANGUAGES
from .render import DEFAULT_MODEL, MODELS

DEPTHS = ("quick", "deep")
ROLES = ("1", "2", "3", "4", "5")
FOCUSES = (
    "full", "laning", "fights", "farm", "draft",
    "vision", "tempo", "initiation", "enable",
)

# UI показывает только осмысленные для выбранной позиции основные фокусы.
# CLI намеренно принимает любые комбинации: это сохраняет обратную совместимость
# и не мешает опытному пользователю запросить нестандартный срез.
ROLE_FOCUSES: Dict[str, Tuple[str, ...]] = {
    "1": ("full", "farm", "fights", "laning", "draft"),
    "2": ("full", "tempo", "laning", "fights", "draft"),
    "3": ("full", "initiation", "fights", "laning", "draft"),
    "4": ("full", "enable", "vision", "tempo", "fights", "laning", "draft"),
    "5": ("full", "enable", "vision", "fights", "laning", "draft"),
}

HIDDEN, SUMMARY, EXPANDED, FULL_LOG = 0, 1, 2, 3

# Базовый уровень секции: (quick, deep).
_BASE: Dict[str, Tuple[int, int]] = {
    "meta":       (SUMMARY, SUMMARY),
    # Отклонения в данных. Секция короткая (не больше семи строк), но именно из
    # неё модель строит гипотезы, поэтому фокус её не приглушает никогда:
    # в _FOCUS_OVERRIDES она сознательно не упомянута.
    "anomalies":  (SUMMARY, SUMMARY),
    "draft":      (SUMMARY, EXPANDED),
    "scoreboard": (SUMMARY, SUMMARY),
    "benchmarks": (SUMMARY, EXPANDED),
    "networth":   (SUMMARY, EXPANDED),
    "items":      (SUMMARY, EXPANDED),
    "abilities":  (SUMMARY, EXPANDED),
    "laning":     (SUMMARY, EXPANDED),
    "combat":     (SUMMARY, EXPANDED),
    "buffs":      (HIDDEN,  SUMMARY),
    "teamfights": (SUMMARY, EXPANDED),
    "damage":     (HIDDEN,  SUMMARY),
    "objectives": (SUMMARY, EXPANDED),
    # Компактный профиль только моего игрока. Содержание зависит от позиции,
    # поэтому даже summary здесь полезнее универсальной таблицы.
    "role_impact": (SUMMARY, SUMMARY),
}

# Фокус переопределяет уровень АБСОЛЮТНО: он не только поднимает профильные
# секции, но и приглушает непрофильные — иначе «фокус» не экономил бы внимание.
_FOCUS_OVERRIDES: Dict[str, Dict[str, int]] = {
    "full": {},
    "laning": {
        "laning": EXPANDED, "abilities": SUMMARY, "items": SUMMARY,
        "networth": SUMMARY, "combat": SUMMARY, "teamfights": SUMMARY,
        "damage": HIDDEN, "buffs": HIDDEN, "objectives": HIDDEN,
    },
    "fights": {
        "teamfights": EXPANDED, "damage": SUMMARY, "combat": EXPANDED,
        "buffs": SUMMARY, "laning": SUMMARY, "items": SUMMARY,
    },
    "farm": {
        "networth": EXPANDED, "items": FULL_LOG, "combat": SUMMARY,
        "laning": SUMMARY, "teamfights": SUMMARY, "damage": HIDDEN,
    },
    "draft": {
        "draft": EXPANDED, "abilities": SUMMARY, "items": SUMMARY,
        "networth": SUMMARY, "laning": SUMMARY, "combat": HIDDEN,
        "teamfights": SUMMARY, "damage": HIDDEN, "buffs": HIDDEN,
        "objectives": HIDDEN,
    },
    "vision": {
        "role_impact": EXPANDED, "combat": EXPANDED, "items": SUMMARY,
        "teamfights": SUMMARY, "benchmarks": SUMMARY, "laning": HIDDEN,
        "networth": HIDDEN, "damage": HIDDEN, "buffs": HIDDEN,
        "objectives": SUMMARY,
    },
    "tempo": {
        "role_impact": EXPANDED, "laning": EXPANDED, "combat": EXPANDED,
        "teamfights": EXPANDED, "objectives": EXPANDED, "items": SUMMARY,
        "networth": SUMMARY, "damage": HIDDEN, "buffs": HIDDEN,
    },
    "initiation": {
        "role_impact": EXPANDED, "teamfights": EXPANDED, "combat": EXPANDED,
        "damage": SUMMARY, "items": SUMMARY, "objectives": SUMMARY,
        "networth": HIDDEN, "laning": SUMMARY, "buffs": SUMMARY,
    },
    "enable": {
        "role_impact": EXPANDED, "combat": EXPANDED, "items": EXPANDED,
        "teamfights": EXPANDED, "objectives": SUMMARY, "laning": SUMMARY,
        "benchmarks": SUMMARY, "networth": HIDDEN, "damage": HIDDEN,
        "buffs": HIDDEN,
    },
}

@dataclass(frozen=True)
class Policy:
    depth: str = "quick"
    focus: str = "full"
    # Свободный вопрос игрока. Если задан — он становится главным приоритетом
    # разбора, а базовые разделы уходят на второй план (см. scaffold.py).
    note: Optional[str] = None
    # Под какую LLM упаковываем промпт (см. render.py). Данные не меняет.
    model: str = DEFAULT_MODEL
    # Язык промпта: и подписи, и инструкция модели отвечать на нём (см. i18n).
    lang: str = DEFAULT_LANG
    # Уровень игрока (MMR или бракет) — если задан, модель калибрует советы.
    mmr: Optional[str] = None
    # Явная позиция игрока. None означает «использовать эвристику матча».
    role: Optional[str] = None
    # Игровой промежуток (минуты, включительно): «разбери мне 30–40». Если задан,
    # окно печатается с максимальной детализацией, а ВСЁ остальное сжимается до
    # сводки. Иначе детализация окна утонула бы в общем объёме — а весь смысл
    # запроса в том, чтобы внимание модели ушло именно туда.
    window: Optional[Tuple[int, int]] = None
    # Внутреннее происхождение роли после Pipeline.resolve_role(); не является
    # пользовательским флагом и не участвует в сравнении Policy.
    role_source: str = field(default="auto", repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.depth not in DEPTHS:
            raise ValueError(f"depth должен быть одним из {DEPTHS}, получено {self.depth!r}")
        if self.focus not in FOCUSES:
            raise ValueError(f"focus должен быть одним из {FOCUSES}, получено {self.focus!r}")
        if self.role is not None and self.role not in ROLES:
            raise ValueError(f"role должен быть одним из {ROLES}, получено {self.role!r}")
        if self.window is not None:
            start, end = self.window
            if start < 0 or end <= start:
                raise ValueError(f"window должен быть парой (начало, конец) с концом "
                                 f"строго больше начала, получено {self.window!r}")
            object.__setattr__(self, "window", (int(start), int(end)))
        if self.model not in MODELS:
            raise ValueError(f"model должен быть одним из {MODELS}, получено {self.model!r}")
        # Незнакомый язык не роняет разбор — молча откатываемся на язык по умолчанию.
        if self.lang not in LANGUAGES:
            object.__setattr__(self, "lang", DEFAULT_LANG)
        # Пустая строка или одни пробелы — это отсутствие значения, а не значение.
        object.__setattr__(self, "note", (self.note or "").strip() or None)
        object.__setattr__(self, "mmr", " ".join((self.mmr or "").split()) or None)
        if self.role is not None and self.role_source == "auto":
            object.__setattr__(self, "role_source", "selected")

    @property
    def deep(self) -> bool:
        return self.depth == "deep"

    @property
    def has_note(self) -> bool:
        return self.note is not None

    @property
    def note_inline(self) -> str:
        """Заметка в одну строку — чтобы вставлять её в кавычках внутрь предложения."""
        return " ".join((self.note or "").split())

    def resolve_role(self, inferred: str) -> "Policy":
        """Возвращает Policy с эффективной ролью, не меняя исходный объект.

        Пользовательский --role всегда побеждает. Эвристику принимаем только
        если она уверенно дала позицию 1–5; расплывчатые core/support оставляем
        без ложной точности.
        """
        if self.role is not None:
            return self
        if inferred in ROLES:
            return replace(self, role=inferred, role_source="heuristic")
        return self

    @property
    def has_role(self) -> bool:
        return self.role in ROLES

    @property
    def has_window(self) -> bool:
        return self.window is not None

    def level(self, section: str) -> int:
        # Секция окна существует ровно тогда, когда окно задано, и всегда идёт
        # полным логом: ради этого её и просили.
        if section == "window":
            return FULL_LOG if self.has_window else HIDDEN

        override = _FOCUS_OVERRIDES[self.focus].get(section)
        if override is not None:
            level = override
        else:
            quick_lvl, deep_lvl = _BASE[section]
            level = deep_lvl if self.deep else quick_lvl

        # Окно перераспределяет внимание, а не добавляется поверх: остальной матч
        # ужимается до сводки. Аномалии не трогаем — из них строятся гипотезы,
        # и они нужны целиком независимо от того, какой отрезок разбирается.
        if self.has_window and section != "anomalies":
            level = min(level, SUMMARY)
        return level

    def shows(self, section: str) -> bool:
        return self.level(section) > HIDDEN

    def at_least(self, section: str, level: int) -> bool:
        return self.level(section) >= level

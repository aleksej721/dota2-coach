"""Policy — единственное место, где решается «что вообще попадёт в промпт».

Главный принцип проекта: СИГНАЛ > ОБЪЁМ. Из OpenDota мы вытаскиваем максимум,
но экспортируем отобранное. Отбор задаётся двумя ручками:

  --depth quick|deep                     сколько подробностей вообще
  --focus full|laning|fights|farm|draft  под какой вопрос заточен разбор

Каждая секция получает УРОВЕНЬ ДЕТАЛИЗАЦИИ 0..3:

  0 — секции нет в промпте;
  1 — сводка: только S-тир (мои данные + командные агрегаты);
  2 — развёрнуто: A-тир (все 10 игроков, поминутные ряды, поимённые раскладки);
  3 — полный лог: B-тир и сырые последовательности (только по явному фокусу).

FeatureExtractor смотрит на уровень, чтобы не считать лишнего; BundleBuilder —
чтобы не печатать лишнего. Больше нигде решений «показывать/не показывать» нет.
"""

from dataclasses import dataclass
from typing import Dict, Tuple

DEPTHS = ("quick", "deep")
FOCUSES = ("full", "laning", "fights", "farm", "draft")

HIDDEN, SUMMARY, EXPANDED, FULL_LOG = 0, 1, 2, 3

# Базовый уровень секции: (quick, deep).
_BASE: Dict[str, Tuple[int, int]] = {
    "meta":       (SUMMARY, SUMMARY),
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
}

# Вопросы в финальной секции ЗАДАЧА — тоже часть интента.
_TASKS: Dict[str, Tuple[str, ...]] = {
    "full": (
        "Оцени мою фазу лайнинга 0–10 (CS, лайн-эффективность, размены, тайминги).",
        "Разбери мой мид-/лейт-гейм по нетворт-кривой, таймингам предметов и тимфайтам: "
        "где я усиливал команду, где проседал.",
        "Сопоставь мои бенчмарки с типичными — что заметно ниже/выше нормы.",
        "Назови 2–3 переломных момента матча по объективам и балансу команд.",
        "Дай 3 конкретных совета на следующие игры на этом герое/позиции.",
    ),
    "laning": (
        "Разбери мою линию 0–10: динамика добиваний/денаев по минутам, лайн-эффективность "
        "против соперников по линии, размены (киллы/смерти).",
        "Где именно я терял CS и почему это видно по данным.",
        "Как мой выход с линии (нетворт и предметы к 10-й минуте) повлиял на дальнейшую игру.",
        "Дай 3 конкретных совета по лайн-стадии на этом герое/позиции.",
    ),
    "fights": (
        "Разбери мою игру в замесах: в каких боях мой вклад по урону был решающим, "
        "а где я отсутствовал или умирал первым.",
        "Сопоставь исходы боёв с балансом команд — какие бои переломили матч.",
        "Оцени мои смерти: были ли они разменом или чистой потерей.",
        "Дай 3 конкретных совета по позиционированию и таймингу входа в бой.",
    ),
    "farm": (
        "Оцени мою скорость фарма: нетворт-кривая, GPM/добивания против бенчмарков, "
        "стаки лагерей и добитые нейтралы.",
        "Разбери тайминги ключевых предметов — не поздние ли они для этого героя.",
        "Найди промежутки, где кривая нетворта плоская, и предположи, чем они заняты.",
        "Дай 3 конкретных совета по фарм-паттерну и порядку сборки.",
    ),
    "draft": (
        "Оцени драфт: сильные и слабые места обоих составов, кто кого контрит.",
        "Как мой герой вписан в состав и против чего ему тяжело.",
        "Какой план на игру давал этот драфт и совпал ли он с тем, что видно по данным матча.",
        "Дай 3 конкретных совета по выбору героя и стиля игры в подобных драфтах.",
    ),
}


@dataclass(frozen=True)
class Policy:
    depth: str = "quick"
    focus: str = "full"

    def __post_init__(self) -> None:
        if self.depth not in DEPTHS:
            raise ValueError(f"depth должен быть одним из {DEPTHS}, получено {self.depth!r}")
        if self.focus not in FOCUSES:
            raise ValueError(f"focus должен быть одним из {FOCUSES}, получено {self.focus!r}")

    @property
    def deep(self) -> bool:
        return self.depth == "deep"

    def level(self, section: str) -> int:
        override = _FOCUS_OVERRIDES[self.focus].get(section)
        if override is not None:
            return override
        quick_lvl, deep_lvl = _BASE[section]
        return deep_lvl if self.deep else quick_lvl

    def shows(self, section: str) -> bool:
        return self.level(section) > HIDDEN

    def at_least(self, section: str, level: int) -> bool:
        return self.level(section) >= level

    def tasks(self) -> Tuple[str, ...]:
        return _TASKS[self.focus]

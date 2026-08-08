"""Упаковка промпта под конкретную LLM.

Содержимое разбора от модели не зависит: те же факты, та же методика, тот же
порядок. Отличается только оболочка — как размечены границы блоков.

  claude            — верхнеуровневые XML-теги: модель заметно надёжнее держит
                      границы «данные / вопрос / инструкция», когда они размечены
                      тегами, а не заголовками;
  chatgpt, gemini   — обычный markdown.

Здесь же живёт «разумная глубина по умолчанию» для каждой модели: у чата с
маленьким практическим окном по умолчанию quick, у остальных deep. Явный
--depth всегда важнее этого дефолта.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODELS = ("chatgpt", "claude", "gemini")
DEFAULT_MODEL = "chatgpt"


@dataclass(frozen=True)
class ModelProfile:
    name: str
    label: str          # как показываем в UI и в секции МЕТА
    wrapper: str        # "markdown" | "xml"
    default_depth: str


PROFILES: Dict[str, ModelProfile] = {
    "chatgpt": ModelProfile("chatgpt", "ChatGPT", "markdown", "quick"),
    "claude": ModelProfile("claude", "Claude", "xml", "deep"),
    "gemini": ModelProfile("gemini", "Gemini", "markdown", "deep"),
}


def profile(model: Optional[str]) -> ModelProfile:
    return PROFILES.get(model or DEFAULT_MODEL, PROFILES[DEFAULT_MODEL])


def resolve_depth(depth: Optional[str], model: Optional[str]) -> str:
    """Явно заданный --depth побеждает; иначе берём дефолт модели."""
    return depth or profile(model).default_depth


@dataclass
class Section:
    """Один смысловой блок: заголовок (может отсутствовать) и строки."""
    heading: Optional[str]
    lines: List[str] = field(default_factory=list)


@dataclass
class Group:
    """Набор секций под одним XML-тегом (в markdown тег не печатается)."""
    tag: str
    sections: List[Section] = field(default_factory=list)

    def add(self, heading: Optional[str], lines: List[str]) -> None:
        if lines or heading:
            self.sections.append(Section(heading, lines))


class Renderer:
    def document(self, groups: List[Group]) -> str:
        raise NotImplementedError


class MarkdownRenderer(Renderer):
    def document(self, groups: List[Group]) -> str:
        out: List[str] = []
        for group in groups:
            for section in group.sections:
                if section.heading:
                    out.append(f"## {section.heading}")
                out += section.lines
                out.append("")
        return "\n".join(out).rstrip("\n") + "\n"


class XmlRenderer(Renderer):
    """Верхнеуровневые теги, markdown внутри них.

    Если в группе одна секция, её заголовок не печатаем: имя тега уже говорит,
    что это за блок, и дублировать смысла нет. В группе данных секций много,
    поэтому там заголовки остаются — иначе не отличить скорборд от драфта.
    """

    def document(self, groups: List[Group]) -> str:
        out: List[str] = []
        for group in groups:
            if not group.sections:
                continue
            drop_heading = len(group.sections) == 1
            out.append(f"<{group.tag}>")
            for i, section in enumerate(group.sections):
                if section.heading and not drop_heading:
                    if i:
                        out.append("")
                    out.append(f"## {section.heading}")
                out += section.lines
            out.append(f"</{group.tag}>")
            out.append("")
        return "\n".join(out).rstrip("\n") + "\n"


def renderer_for(model: Optional[str]) -> Renderer:
    return XmlRenderer() if profile(model).wrapper == "xml" else MarkdownRenderer()

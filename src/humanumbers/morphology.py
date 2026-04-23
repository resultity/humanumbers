from __future__ import annotations

import re
from dataclasses import dataclass

try:
    import pymorphy3
except ImportError:  # pragma: no cover
    pymorphy3 = None


CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)


@dataclass(frozen=True)
class MorphologySupport:
    language: str
    adapter: str
    available: bool
    packages: tuple[str, ...]
    note: str


REGISTRY: dict[str, MorphologySupport] = {
    "ru": MorphologySupport("ru", "pymorphy3", pymorphy3 is not None, ("pymorphy3", "pymorphy3-dicts-ru"), "Full prototype parsing and rendering path."),
    "en": MorphologySupport("en", "inflect", False, ("inflect",), "Declared in extras, not wired into the generator yet."),
    "zh": MorphologySupport("zh", "jieba+opencc", False, ("jieba", "opencc-python-reimplemented"), "Declared in extras, not wired into the generator yet."),
    "ar": MorphologySupport("ar", "camel-tools", False, ("camel-tools",), "Declared in extras, not wired into the generator yet."),
    "hi": MorphologySupport("hi", "indic-nlp-library", False, ("indic-nlp-library",), "Declared in extras, not wired into the generator yet."),
    "bn": MorphologySupport("bn", "indic-nlp-library", False, ("indic-nlp-library",), "Declared in extras, not wired into the generator yet."),
    "ur": MorphologySupport("ur", "urduhack", False, ("urduhack",), "Declared in extras, not wired into the generator yet."),
    "es": MorphologySupport("es", "surface-only", True, (), "Uses surface dictionaries for now."),
    "fr": MorphologySupport("fr", "surface-only", True, (), "Uses surface dictionaries for now."),
    "pt": MorphologySupport("pt", "surface-only", True, (), "Uses surface dictionaries for now."),
}


class BaseMorphology:
    def normalize_token(self, token: str) -> str:
        return token.lower().replace("ё", "е")


class RussianMorphology(BaseMorphology):
    def __init__(self) -> None:
        self._analyzer = pymorphy3.MorphAnalyzer() if pymorphy3 is not None else None

    def normalize_token(self, token: str) -> str:
        normalized = super().normalize_token(token)
        if self._analyzer is None:
            return normalized
        if len(normalized) <= 2 or not CYRILLIC_RE.search(normalized):
            return normalized
        parsed = self._analyzer.parse(normalized)
        if not parsed:
            return normalized
        return parsed[0].normal_form.replace("ё", "е")


def get_morphology(language: str) -> BaseMorphology:
    if language == "ru":
        return RussianMorphology()
    return BaseMorphology()


def list_morphology_support() -> list[dict[str, object]]:
    return [
        {
            "language": item.language,
            "adapter": item.adapter,
            "available": item.available,
            "packages": list(item.packages),
            "note": item.note,
        }
        for item in REGISTRY.values()
    ]

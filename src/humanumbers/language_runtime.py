from __future__ import annotations

"""Runtime phrase-pack loader.

This module provides one public lookup entry point:
`get_language_runtime_pack(language)`.

All phrase templates and benchmark band descriptors are stored in
assets/languages/runtime_pack.yaml. The loader validates the schema once,
caches parsed packs, and applies language fallback to the configured default.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from .assets import assets_root


@dataclass(frozen=True)
class LanguageRuntimePack:
    code: str
    word_separator: str
    about_fallback: str
    nearly_template: str
    less_than_template: str
    range_template: str
    level_match_template: str
    almost_like_template: str
    percent_lower_template: str
    percent_higher_template: str
    ratio_more_template: str
    ratio_less_template: str
    relative_more_template: str
    relative_less_template: str
    absolute_higher_template: str
    absolute_lower_template: str
    scale_lower_template: str
    scale_higher_template: str
    scale_lower_alt_template: str
    scale_higher_alt_template: str
    band_descriptors: tuple[str, ...]


RUNTIME_PACK_CONFIG_FIELDS: tuple[str, ...] = (
    "word_separator",
    "about_fallback",
    "nearly_template",
    "less_than_template",
    "range_template",
    "level_match_template",
    "almost_like_template",
    "percent_lower_template",
    "percent_higher_template",
    "ratio_more_template",
    "ratio_less_template",
    "relative_more_template",
    "relative_less_template",
    "absolute_higher_template",
    "absolute_lower_template",
    "scale_lower_template",
    "scale_higher_template",
    "scale_lower_alt_template",
    "scale_higher_alt_template",
    "band_descriptors",
)


def _config_path() -> Path:
    return assets_root() / "languages" / "runtime_pack.yaml"


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        raise RuntimeError(f"Runtime pack config is missing: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Runtime pack config must be a mapping.")
    return data


def _expect_text(value: Any, *, field: str, code: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"Runtime pack '{code}' field '{field}' must be a string.")
    return value


def _expect_descriptors(value: Any, *, code: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"Runtime pack '{code}' field 'band_descriptors' must be a list of strings.")
    descriptors = tuple(value)
    if not descriptors:
        raise RuntimeError(f"Runtime pack '{code}' field 'band_descriptors' cannot be empty.")
    return descriptors


def _build_pack(code: str, raw: Mapping[str, Any]) -> LanguageRuntimePack:
    missing = [field for field in RUNTIME_PACK_CONFIG_FIELDS if field not in raw]
    if missing:
        raise RuntimeError(f"Runtime pack '{code}' is missing fields: {', '.join(missing)}")

    return LanguageRuntimePack(
        code=code,
        word_separator=_expect_text(raw["word_separator"], field="word_separator", code=code),
        about_fallback=_expect_text(raw["about_fallback"], field="about_fallback", code=code),
        nearly_template=_expect_text(raw["nearly_template"], field="nearly_template", code=code),
        less_than_template=_expect_text(raw["less_than_template"], field="less_than_template", code=code),
        range_template=_expect_text(raw["range_template"], field="range_template", code=code),
        level_match_template=_expect_text(raw["level_match_template"], field="level_match_template", code=code),
        almost_like_template=_expect_text(raw["almost_like_template"], field="almost_like_template", code=code),
        percent_lower_template=_expect_text(raw["percent_lower_template"], field="percent_lower_template", code=code),
        percent_higher_template=_expect_text(raw["percent_higher_template"], field="percent_higher_template", code=code),
        ratio_more_template=_expect_text(raw["ratio_more_template"], field="ratio_more_template", code=code),
        ratio_less_template=_expect_text(raw["ratio_less_template"], field="ratio_less_template", code=code),
        relative_more_template=_expect_text(raw["relative_more_template"], field="relative_more_template", code=code),
        relative_less_template=_expect_text(raw["relative_less_template"], field="relative_less_template", code=code),
        absolute_higher_template=_expect_text(raw["absolute_higher_template"], field="absolute_higher_template", code=code),
        absolute_lower_template=_expect_text(raw["absolute_lower_template"], field="absolute_lower_template", code=code),
        scale_lower_template=_expect_text(raw["scale_lower_template"], field="scale_lower_template", code=code),
        scale_higher_template=_expect_text(raw["scale_higher_template"], field="scale_higher_template", code=code),
        scale_lower_alt_template=_expect_text(raw["scale_lower_alt_template"], field="scale_lower_alt_template", code=code),
        scale_higher_alt_template=_expect_text(raw["scale_higher_alt_template"], field="scale_higher_alt_template", code=code),
        band_descriptors=_expect_descriptors(raw["band_descriptors"], code=code),
    )


def _load_packs() -> tuple[str, dict[str, LanguageRuntimePack]]:
    config = _load_config()
    default_language = config.get("default_language", "en")
    raw_packs = config.get("packs")

    if not isinstance(default_language, str):
        raise RuntimeError("Runtime pack config field 'default_language' must be a string.")
    if not isinstance(raw_packs, dict):
        raise RuntimeError("Runtime pack config field 'packs' must be a mapping.")

    packs: dict[str, LanguageRuntimePack] = {}
    for code, raw_pack in raw_packs.items():
        if not isinstance(code, str):
            raise RuntimeError("Runtime pack keys must be language codes.")
        if not isinstance(raw_pack, Mapping):
            raise RuntimeError(f"Runtime pack '{code}' must be a mapping.")
        packs[code] = _build_pack(code, raw_pack)

    if default_language not in packs:
        raise RuntimeError(f"Default runtime language '{default_language}' is not defined in packs.")
    return default_language, packs


@lru_cache(maxsize=1)
def _runtime_cache() -> tuple[str, dict[str, LanguageRuntimePack]]:
    # Runtime packs are immutable in-process; a single cached parse keeps calls cheap.
    return _load_packs()


def load_runtime_pack(language: str) -> LanguageRuntimePack:
    default_language, packs = _runtime_cache()
    return packs.get(language, packs[default_language])


def get_language_runtime_pack(language: str) -> LanguageRuntimePack:
    return load_runtime_pack(language)


# Backward-compatible export for callers that still expect a mapping symbol.
LANGUAGE_RUNTIME_PACKS: dict[str, LanguageRuntimePack] = dict(_runtime_cache()[1])


__all__ = ["LanguageRuntimePack", "LANGUAGE_RUNTIME_PACKS", "load_runtime_pack", "get_language_runtime_pack"]
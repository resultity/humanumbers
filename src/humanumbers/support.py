from __future__ import annotations

from typing import Any

from .morphology import list_morphology_support

STABLE_APPROXIMATION_LEVELS: list[str] = ["normal", "rough"]
EXPERIMENTAL_APPROXIMATION_LEVELS: list[str] = ["very_rough"]


def support_payload() -> dict[str, Any]:
    return {
        "modes": ["humanize", "benchmark"],
        "approximation_levels": STABLE_APPROXIMATION_LEVELS,
        "experimental": {
            "approximation_levels": EXPERIMENTAL_APPROXIMATION_LEVELS,
        },
        "benchmark_registers": ["official", "colloquial", "rough", "profane"],
        "system_preferences": ["auto", "preserve", "si"],
        "generation_languages": ["ru", "en", "es", "fr", "pt", "zh", "ar", "hi", "bn", "ur"],
        "parser_languages": ["ru", "en", "es", "fr", "pt", "zh", "hi", "ar", "bn", "ur"],
        "morphology": list_morphology_support(),
    }

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=16)
def get_cached_service(language: str = "ru"):
    from .service import HumanumbersService

    return HumanumbersService(language)


def clear_service_cache() -> None:
    get_cached_service.cache_clear()

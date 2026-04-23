from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def assets_root() -> Path:
    configured = os.getenv("HUMANUMBERS_ASSETS_DIR")
    if configured:
        return Path(configured)

    project_assets = _project_root() / "assets"
    if project_assets.exists():
        return project_assets

    package_assets = Path(__file__).resolve().parent / "package_assets"
    if package_assets.exists():
        return package_assets

    return project_assets


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _build_generated_unit_name(base_unit: str, prefix: str) -> str:
    if base_unit.startswith("square_"):
        return f"square_{prefix}{base_unit.removeprefix('square_')}"
    if base_unit.startswith("cubic_"):
        return f"cubic_{prefix}{base_unit.removeprefix('cubic_')}"
    return f"{prefix}{base_unit}"


@dataclass(frozen=True)
class UnitRow:
    family: str
    unit: str
    factor_to_si: float | None
    relation_kind: str
    system: str
    composite_profile: str | None
    preserve_input_system_default: bool


@dataclass(frozen=True)
class CompiledAssets:
    family_rows: dict[str, list[UnitRow]]
    units_by_key: dict[str, UnitRow]
    scalar_values: dict[str, dict[str, Any]]
    system_bridge_policies: dict[str, dict[str, Any]]
    named_value_aliases: dict[str, list[str]]
    composition: dict[str, Any]
    function_words: dict[str, list[str]]
    derived_sets: dict[str, list[str]]
    unit_aliases: dict[str, list[str]]
    unit_render: dict[str, dict[str, str]]
    benchmark_bands: tuple[tuple[str, ...], ...]
    benchmark_register_modifiers: dict[str, tuple[str, ...]]
    benchmark_profane_lower_bands: tuple[tuple[str, ...], ...]
    benchmark_profane_higher_bands: tuple[tuple[str, ...], ...]


def _load_benchmark_words(language: str) -> tuple[tuple[tuple[str, ...], ...], dict[str, tuple[str, ...]], tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    lang_root = assets_root() / "languages" / language
    benchmark_path = lang_root / "benchmark_words.yaml"
    if not benchmark_path.exists():
        empty: tuple[tuple[str, ...], ...] = ()
        return empty, {}, empty, empty

    data = _read_yaml(benchmark_path)

    def to_band_tuple(key: str) -> tuple[tuple[str, ...], ...]:
        bands = data.get(key, [])
        return tuple(tuple(entry for entry in band if entry) for band in bands)

    register_modifiers = {
        register: tuple(entry for entry in values if entry)
        for register, values in data.get("register_modifiers", {}).items()
        if isinstance(values, list)
    }

    return (
        to_band_tuple("bands"),
        register_modifiers,
        to_band_tuple("profane_lower_bands"),
        to_band_tuple("profane_higher_bands"),
    )


def _profile_preserve_default(profile_name: str | None, profiles: dict[str, Any]) -> bool:
    if not profile_name:
        return False
    return bool(profiles.get(profile_name, {}).get("preserve_input_system_default", False))


@lru_cache(maxsize=1)
def compile_core_units() -> tuple[dict[str, list[UnitRow]], dict[str, UnitRow]]:
    core = assets_root() / "core"
    metric_families = _read_yaml(core / "metric_families.yaml")
    si_prefixes = _read_yaml(core / "si_prefixes.yaml")
    profiles = _read_yaml(core / "composite_policy_profiles.yaml")["profiles"]

    family_rows: dict[str, list[UnitRow]] = {}
    units_by_key: dict[str, UnitRow] = {}

    for family_name, spec in metric_families["families"].items():
        rows: list[UnitRow] = []

        prefix_spec = spec.get("prefix_generation")
        if prefix_spec:
            base_unit = prefix_spec["base_unit"]
            base_factor = float(prefix_spec["base_unit_factor_to_si"])
            profile_name = prefix_spec.get("generated_profile")
            preserve_default = _profile_preserve_default(profile_name, profiles)
            rows.append(
                UnitRow(
                    family=family_name,
                    unit=base_unit,
                    factor_to_si=base_factor,
                    relation_kind="exact_factor",
                    system="si",
                    composite_profile=profile_name,
                    preserve_input_system_default=preserve_default,
                )
            )
            for prefix_name in si_prefixes["prefix_sets"][prefix_spec["prefix_set"]]:
                prefix = si_prefixes["prefixes"][prefix_name]
                rows.append(
                    UnitRow(
                        family=family_name,
                        unit=_build_generated_unit_name(base_unit, prefix_name),
                        factor_to_si=base_factor * (10 ** int(prefix["power10"])),
                        relation_kind="exact_factor",
                        system="si",
                        composite_profile=profile_name,
                        preserve_input_system_default=preserve_default,
                    )
                )

        for explicit in spec.get("units", []):
            relation = explicit["relation_to_si"]
            rows.append(
                UnitRow(
                    family=family_name,
                    unit=explicit["unit"],
                    factor_to_si=float(relation["factor"]) if relation.get("kind") != "affine" else None,
                    relation_kind=relation["kind"],
                    system=explicit["system"],
                    composite_profile=explicit.get("composite_profile"),
                    preserve_input_system_default=bool(explicit.get("preserve_input_system_default", False)),
                )
            )

        for injected in spec.get("injected_units", []):
            relation = injected["relation_to_si"]
            rows.append(
                UnitRow(
                    family=family_name,
                    unit=injected["unit"],
                    factor_to_si=float(relation["factor"]),
                    relation_kind=relation["kind"],
                    system=injected["system"],
                    composite_profile=injected.get("composite_profile"),
                    preserve_input_system_default=bool(injected.get("preserve_input_system_default", False)),
                )
            )

        unique_rows = {row.unit: row for row in rows}
        sorted_rows = sorted(unique_rows.values(), key=lambda row: (row.factor_to_si is None, row.factor_to_si or 0.0))
        family_rows[family_name] = sorted_rows
        units_by_key.update({row.unit: row for row in sorted_rows})

    return family_rows, units_by_key


def _load_unit_aliases(language: str) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    lang_root = assets_root() / "languages" / language
    lexicon_path = lang_root / "unit_lexicon.yaml"
    if lexicon_path.exists():
        data = _read_yaml(lexicon_path)
        aliases = {unit: spec["aliases"] for unit, spec in data["units"].items()}
        render = {unit: spec["render"] for unit, spec in data["units"].items()}
        return aliases, render

    units_path = lang_root / "units.yaml"
    if units_path.exists():
        data = _read_yaml(units_path)
        if data.get("model") == "unit_alias_pack":
            aliases = data.get("unit_aliases", {})
            render = {
                unit: {
                    "one": values[0],
                    "few": values[1] if len(values) > 1 else values[0],
                    "many": values[1] if len(values) > 1 else values[0],
                    "short": values[0],
                }
                for unit, values in aliases.items()
                if values
            }
            return aliases, render

    return {}, {}


def _split_generated_prefixed_unit(unit_key: str, prefix_names: list[str]) -> tuple[str | None, str | None]:
    if unit_key.startswith("square_"):
        remainder = unit_key.removeprefix("square_")
        for prefix in prefix_names:
            if remainder.startswith(prefix):
                return f"square_{remainder.removeprefix(prefix)}", prefix
        return None, None
    if unit_key.startswith("cubic_"):
        remainder = unit_key.removeprefix("cubic_")
        for prefix in prefix_names:
            if remainder.startswith(prefix):
                return f"cubic_{remainder.removeprefix(prefix)}", prefix
        return None, None
    for prefix in prefix_names:
        if unit_key.startswith(prefix):
            return unit_key.removeprefix(prefix), prefix
    return None, None


def _augment_generated_prefix_aliases(
    language: str,
    units_by_key: dict[str, UnitRow],
    unit_aliases: dict[str, list[str]],
    unit_render: dict[str, dict[str, str]],
) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    lang_root = assets_root() / "languages" / language
    units_path = lang_root / "units.yaml"
    if not units_path.exists():
        return unit_aliases, unit_render

    data = _read_yaml(units_path)
    if data.get("model") != "unit_alias_pack":
        return unit_aliases, unit_render

    explicit_aliases = data.get("unit_aliases", {})
    prefix_aliases = data.get("prefix_aliases", {})
    prefix_names = sorted(prefix_aliases.keys(), key=len, reverse=True)

    aliases = dict(unit_aliases)
    render = dict(unit_render)
    for unit_key in units_by_key:
        if unit_key in aliases:
            continue
        base_key, prefix_key = _split_generated_prefixed_unit(unit_key, prefix_names)
        if not base_key or not prefix_key:
            continue
        if base_key not in explicit_aliases:
            continue

        generated_aliases = []
        for prefix_surface in prefix_aliases[prefix_key]:
            for base_surface in explicit_aliases[base_key]:
                generated_aliases.append(f"{prefix_surface}{base_surface}")
        if not generated_aliases:
            continue

        aliases[unit_key] = generated_aliases
        singular = generated_aliases[0]
        plural = generated_aliases[1] if len(generated_aliases) > 1 else singular
        render[unit_key] = {"one": singular, "few": plural, "many": plural, "short": singular}

    return aliases, render


@lru_cache(maxsize=10)
def load_language_assets(language: str) -> CompiledAssets:
    family_rows, units_by_key = compile_core_units()
    scalar_values = _read_yaml(assets_root() / "core" / "basic_values.yaml").get("values", {})
    system_bridge_policies = _read_yaml(assets_root() / "core" / "system_bridge_policies.yaml").get("families", {})
    lang_root = assets_root() / "languages" / language
    named_values = _read_yaml(lang_root / "named_values.yaml")
    function_words = _read_yaml(lang_root / "function_words.yaml")
    benchmark_bands, benchmark_register_modifiers, benchmark_profane_lower_bands, benchmark_profane_higher_bands = _load_benchmark_words(language)
    unit_aliases, unit_render = _load_unit_aliases(language)
    unit_aliases, unit_render = _augment_generated_prefix_aliases(language, units_by_key, unit_aliases, unit_render)
    return CompiledAssets(
        family_rows=family_rows,
        units_by_key=units_by_key,
        scalar_values=scalar_values,
        system_bridge_policies=system_bridge_policies,
        named_value_aliases=named_values.get("basic_aliases", {}),
        composition=named_values.get("composition", {}),
        function_words=function_words.get("groups", {}),
        derived_sets=function_words.get("derived_sets", {}),
        unit_aliases=unit_aliases,
        unit_render=unit_render,
        benchmark_bands=benchmark_bands,
        benchmark_register_modifiers=benchmark_register_modifiers,
        benchmark_profane_lower_bands=benchmark_profane_lower_bands,
        benchmark_profane_higher_bands=benchmark_profane_higher_bands,
    )

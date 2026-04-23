# YAML Asset Inventory And Publication Notes

## Scope
This document describes all YAML assets in the repository, which ones are loaded by runtime code, and what each YAML pack contains.

Primary runtime loaders:
- src/humanumbers/assets.py
- src/humanumbers/language_runtime.py

## Runtime-Loaded YAML

### Core packs
- assets/core/basic_values.yaml
  - Loaded into scalar_values.
  - Main key: values (normalized scalar aliases and composition primitives).
- assets/core/si_prefixes.yaml
  - Loaded for SI unit generation.
  - Main keys: prefixes, prefix_sets.
- assets/core/composite_policy_profiles.yaml
  - Loaded for per-unit composite capabilities.
  - Main key: profiles.
- assets/core/metric_families.yaml
  - Loaded for family ladders and unit relations.
  - Main key: families.
- assets/core/system_bridge_policies.yaml
  - Loaded for cross-system rendering policies.
  - Main key: families.

### Global language runtime pack
- assets/languages/runtime_pack.yaml
  - Loaded by language_runtime.py.
  - Contains per-language runtime phrase templates and descriptor bands.

### Per-language packs (for each supported language)
- assets/languages/<lang>/named_values.yaml
  - Loaded unconditionally.
  - Used keys:
    - basic_aliases
    - composition
- assets/languages/<lang>/function_words.yaml
  - Loaded unconditionally.
  - Used keys:
    - groups
    - derived_sets
- assets/languages/<lang>/benchmark_words.yaml
  - Loaded when present.
  - Used keys:
    - bands
    - register_modifiers
    - profane_lower_bands
    - profane_higher_bands
- assets/languages/<lang>/units.yaml
  - Loaded for alias packs and prefix alias augmentation.
  - For model unit_alias_pack: aliases/render forms are consumed.
  - For other models: file can still be read for model detection, but alias/render extraction may be skipped.
- assets/languages/<lang>/unit_lexicon.yaml
  - Optional, takes precedence over units.yaml for unit aliases/render forms.
  - Currently used by Russian.

## Not Loaded By Runtime

These files are not read by current runtime loaders:
- assets/core/composite_rules.yaml
- assets/language_pack_conventions.yaml
- assets/languages/index.yaml
- assets/languages/ru/rounding_seed_rules.yaml
- assets/languages/ru/composite_inventory.yaml

Notes:
- tests/test_benchmark_dictionary_coverage.py scans benchmark_words.yaml files for consistency checks.
- Non-runtime YAML above can still be useful as reference, migration, or seed material.

## Full YAML File Set In Repository

### Root assets docs/metadata
- assets/language_pack_conventions.yaml

### Core
- assets/core/basic_values.yaml
- assets/core/composite_policy_profiles.yaml
- assets/core/composite_rules.yaml
- assets/core/metric_families.yaml
- assets/core/si_prefixes.yaml
- assets/core/system_bridge_policies.yaml

### Languages (global)
- assets/languages/index.yaml
- assets/languages/runtime_pack.yaml

### Languages (per-language packs)
For each of: ar, bn, en, es, fr, hi, pt, ur, zh:
- assets/languages/<lang>/benchmark_words.yaml
- assets/languages/<lang>/function_words.yaml
- assets/languages/<lang>/named_values.yaml
- assets/languages/<lang>/units.yaml

For Russian:
- assets/languages/ru/benchmark_words.yaml
- assets/languages/ru/composite_inventory.yaml
- assets/languages/ru/function_words.yaml
- assets/languages/ru/named_values.yaml
- assets/languages/ru/rounding_seed_rules.yaml
- assets/languages/ru/unit_lexicon.yaml
- assets/languages/ru/units.yaml

## Publication Checklist
- Keep pack metadata fields stable: version, language, model/pack_kind, status, notes.
- For runtime-loaded packs, document consumed keys only (avoid implied schema drift).
- For non-runtime packs, keep explicit status markers like legacy_reference_not_loaded or seed_not_loaded.
- Treat this document as the source of truth for runtime-vs-reference YAML separation.

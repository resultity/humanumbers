# Runtime Pack Configuration

## Purpose

`runtime_pack.yaml` stores language-specific phrase templates that are used by runtime generation in humanize and benchmark modes.

This file replaces hardcoded runtime phrases in Python code. The code now only loads, validates, and serves this configuration.

## File Location

- `assets/languages/runtime_pack.yaml`

## Schema

Top-level fields:

- `version` (int): schema version.
- `default_language` (str): fallback language code used when a requested pack does not exist.
- `packs` (mapping): one pack per language code.

Each pack must include:

- `word_separator`
- `about_fallback`
- `nearly_template`
- `less_than_template`
- `range_template`
- `level_match_template`
- `almost_like_template`
- `percent_lower_template`
- `percent_higher_template`
- `ratio_more_template`
- `ratio_less_template`
- `relative_more_template`
- `relative_less_template`
- `absolute_higher_template`
- `absolute_lower_template`
- `scale_lower_template`
- `scale_higher_template`
- `scale_lower_alt_template`
- `scale_higher_alt_template`
- `band_descriptors` (ordered list of strings)

## Validation Behavior

`src/humanumbers/language_runtime.py` validates that:

- the YAML file exists and parses to a mapping,
- `default_language` is a string,
- `packs` is a mapping,
- every required field exists in each language pack,
- all template fields are strings,
- `band_descriptors` is a non-empty list of strings,
- `default_language` is present in `packs`.

If validation fails, the loader raises `RuntimeError` with a clear message.

## Runtime API

Use one public function:

- `get_language_runtime_pack(language)`

Behavior:

- Loads and validates YAML once per process.
- Caches parsed packs with `lru_cache`.
- Returns requested language pack if available.
- Falls back to `default_language` pack otherwise.

## Editing Guidelines

1. Keep placeholder names stable: `{unit}`, `{low}`, `{high}`, `{reference}`, `{pct}`, `{multiplier}`, `{delta}`, `{descriptor}`.
2. Keep `band_descriptors` semantic order from smallest to largest.
3. If you add a new required field, update loader validation and this document.
4. Avoid changing keys used by existing code paths unless you migrate all callsites.

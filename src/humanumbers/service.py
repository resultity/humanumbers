from __future__ import annotations

import math
import random

try:
    from num2words import num2words
except ImportError:  # pragma: no cover
    num2words = None

from .api_models import HumanizeRequest, HumanizeResponse, ParsedInputModel, VariantModel
from .assets import CompiledAssets, UnitRow, load_language_assets
from .language_runtime import get_language_runtime_pack
from .morphology import get_morphology, list_morphology_support
from .service_constants import API_TO_INTERNAL_STYLE, BOUND_NUMBER_WORDS, INTERNAL_TO_API_STYLE, SMALL_NUMBER_WORDS
from .service_lifecycle import get_cached_service
from .service_parsing import ServiceParsingMixin
from .service_benchmark import ServiceBenchmarkMixin
from .service_rendering_generic import ServiceGenericRenderingMixin
from .service_rendering_ru import ServiceRussianRenderingMixin
from .service_types import Candidate, HumanizeError, ParsedInput


class HumanumbersService(
    ServiceParsingMixin,
    ServiceBenchmarkMixin,
    ServiceGenericRenderingMixin,
    ServiceRussianRenderingMixin,
):
    LARGE_COMPOSITE_WHOLE_THRESHOLD = 1000

    def __init__(self, language: str = "ru") -> None:
        self.language = language
        self.assets = load_language_assets(language)
        self.morphology = get_morphology(language)
        self.runtime_pack = get_language_runtime_pack(language)
        self._alias_index = self._build_alias_index(self.assets)
        self._rng = random.SystemRandom()

    def _service_for_language(self, language: str) -> HumanumbersService:
        return get_cached_service(language)

    def _request_approximation(self, request: HumanizeRequest) -> str:
        if request.approximation:
            if request.rounding or request.roughness:
                legacy = self._approximation_from_legacy(request.rounding, request.roughness)
                return legacy if request.approximation == "normal" and legacy != "normal" else request.approximation
            return request.approximation
        return self._approximation_from_legacy(request.rounding, request.roughness)

    def _approximation_from_legacy(self, rounding: str | None, roughness: list[str] | None) -> str:
        if roughness:
            if "very_rough" in roughness:
                return "rough"
            if "rough" in roughness:
                return "rough"
        if rounding in {"coarse", "extreme"}:
            return "rough"
        return "normal"

    def _level_from_approximation(self, approximation: str) -> str:
        return {"normal": "normal", "rough": "coarse", "very_rough": "coarse"}[approximation]

    def _system_preference(self, request: HumanizeRequest) -> str:
        return request.system_preference or "auto"

    def _resolve_output_language(self, request: HumanizeRequest) -> str:
        return request.output_language or request.language or self.language

    def humanize(self, request: HumanizeRequest) -> HumanizeResponse:
        source_language = self._resolve_source_language(request)
        parser_service = self if source_language == self.language else self._service_for_language(source_language)

        parsed = parser_service.parse(request.text)
        benchmark_parsed: ParsedInput | None = None
        if request.mode == "benchmark":
            if request.benchmark is None:
                raise HumanizeError("Benchmark mode requires the benchmark field.")
            benchmark_parsed = parser_service.parse_benchmark(request.benchmark, parsed)
            candidates = self._generate_benchmark_candidates(parsed, benchmark_parsed, request)
        else:
            candidates = self._generate_candidates(parsed, request)
        deduped: dict[str, Candidate] = {}
        for candidate in candidates:
            existing = deduped.get(candidate.text)
            if existing is None or candidate.score > existing.score:
                deduped[candidate.text] = candidate
        ordered = self._randomized_candidate_order(list(deduped.values()), self._request_approximation(request))
        variants = ordered[: request.variants]
        warnings: list[str] = []
        if parsed.fuzzy_score is not None:
            warnings.append("Unit was matched fuzzily; check the parse if the input was very noisy.")
        if not variants:
            if request.mode == "benchmark" and benchmark_parsed is not None:
                warnings.append("No benchmark phrase survived filtering, falling back to a generic benchmark comparison.")
                variants = [self._fallback_benchmark_candidate(parsed, benchmark_parsed, self._level_from_approximation(self._request_approximation(request)))]
            else:
                warnings.append("No specialized rule fired, falling back to rounded numeric render.")
                variants = [self._fallback_candidate(parsed, self._level_from_approximation(self._request_approximation(request)))]
        debug = None
        if request.debug:
            debug = {
                "supported_morphology": list_morphology_support(),
                "candidate_count": len(ordered),
                "mode": request.mode,
                "source_language": source_language,
                "output_language": self.language,
                "approximation": self._request_approximation(request),
                "system_preference": self._system_preference(request),
            }
        return HumanizeResponse(
            parsed=ParsedInputModel(
                language=source_language,
                raw_text=parsed.raw_text,
                normalized_text=parsed.normalized_text,
                value=parsed.value,
                unit=parsed.unit,
                family=parsed.family,
                matched_alias=parsed.matched_alias,
                fuzzy_score=parsed.fuzzy_score,
            ),
            benchmark=(
                ParsedInputModel(
                    language=source_language,
                    raw_text=benchmark_parsed.raw_text,
                    normalized_text=benchmark_parsed.normalized_text,
                    value=benchmark_parsed.value,
                    unit=benchmark_parsed.unit,
                    family=benchmark_parsed.family,
                    matched_alias=benchmark_parsed.matched_alias,
                    fuzzy_score=benchmark_parsed.fuzzy_score,
                )
                if benchmark_parsed is not None
                else None
            ),
            variants=[
                VariantModel(
                    text=candidate.text,
                    score=candidate.score,
                    rule_kind=candidate.rule_kind,
                    style=INTERNAL_TO_API_STYLE.get(candidate.style, "official"),
                    approximation="rough" if candidate.roughness == "very_rough" else candidate.roughness,
                )
                for candidate in variants
            ],
            warnings=warnings,
            debug=debug,
        )

    def _generate_candidates(self, parsed: ParsedInput, request: HumanizeRequest) -> list[Candidate]:
        approximation = self._request_approximation(request)
        effective_level = self._level_from_approximation(approximation)
        system_preference = self._system_preference(request)

        if self.language != "ru":
            candidates = self._generate_generic_candidates(parsed, effective_level, system_preference)
            candidates = self._filter_system_preference_candidates(parsed, candidates, system_preference)
            allowed_styles, allowed_roughness = self._allowed_styles_and_approximation(request)
            return [
                candidate
                for candidate in candidates
                if candidate.style in allowed_styles and candidate.roughness in allowed_roughness
            ]

        candidates: list[Candidate] = []
        candidates.extend(self._generic_exact_same_unit_render(parsed, effective_level, system_preference))
        candidates.extend(self._small_collective_range_render(parsed, effective_level))
        candidates.extend(self._count_scale_fraction_render(parsed, effective_level))
        candidates.extend(self._fraction_of_current(parsed))
        candidates.extend(self._fraction_of_upper(parsed, effective_level))
        candidates.extend(self._upper_share_band_render(parsed, effective_level))
        candidates.extend(self._near_upper_unit(parsed, request.allow_profane, effective_level))
        candidates.extend(self._upper_with_small_tail(parsed))
        candidates.extend(self._calendar_duration_render(parsed, effective_level))
        candidates.extend(self._human_preferred_bucket_render(parsed, effective_level))
        candidates.extend(self._human_upper_near_integer_render(parsed, effective_level))
        candidates.extend(self._generic_decimal_anchor_render(parsed, effective_level))
        candidates.extend(self._generic_cross_system_bridge_render(parsed, effective_level, system_preference))
        candidates.extend(self._generic_locked_domain_same_unit(parsed, effective_level))
        candidates.extend(self._generic_count_render(parsed, effective_level))
        candidates.extend(self._generic_additive_bucket_render(parsed, effective_level))
        candidates.extend(self._composite_bucket_render(parsed, effective_level))
        candidates.extend(self._same_unit_bucket(parsed, effective_level))
        candidates.extend(self._generic_small_upper_bound(parsed, effective_level, system_preference))
        candidates.extend(self._same_unit_range(parsed, request.allow_profane, effective_level))
        candidates.extend(self._coarse_calendar(parsed))
        candidates.extend(self._subunit_render(parsed))
        candidates.extend(self._tiny_percentage(parsed))
        candidates.extend(self._count_render(parsed, request.allow_profane))
        candidates.extend(self._oldschool_candidates(parsed, effective_level))
        candidates = self._filter_system_preference_candidates(parsed, candidates, system_preference)

        allowed_styles, allowed_roughness = self._allowed_styles_and_approximation(request)

        return [
            candidate
            for candidate in candidates
            if candidate.style in allowed_styles and candidate.roughness in allowed_roughness
        ]

    def _row(self, unit: str) -> UnitRow:
        return self.assets.units_by_key[unit]

    def _family_rows(self, family: str) -> list[UnitRow]:
        return self.assets.family_rows[family]

    def _renderable_rows(self, family: str, source_unit: str | None = None) -> list[UnitRow]:
        rows = [row for row in self._family_rows(family) if row.unit == "count" or row.unit in self.assets.unit_render]
        if source_unit is None:
            return rows
        source_row = self._row(source_unit)
        same_system_rows = [row for row in rows if row.system == source_row.system]
        return same_system_rows or rows

    def _best_upper_renderable(self, parsed: ParsedInput) -> UnitRow | None:
        source_row = self._row(parsed.unit)
        candidates = [
            row
            for row in self._renderable_rows(parsed.family, parsed.unit)
            if row.factor_to_si is not None
            and source_row.factor_to_si is not None
            and row.factor_to_si > source_row.factor_to_si
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda row: row.factor_to_si or float("inf"))

    def _human_unit_penalty(self, unit: str) -> int:
        awkward_prefixes = ("deka", "hecto", "deci")
        return 4 if unit.startswith(awkward_prefixes) or unit.startswith("square_deka") or unit.startswith("cubic_deka") else 0

    def _human_unit_score_penalty(self, unit: str) -> float:
        return min(self._human_unit_penalty(unit) * 0.05, 0.22)

    def _human_bucket_context_penalty(self, family: str, unit: str, rounded: float) -> int:
        penalty = self._human_unit_penalty(unit)
        if family != "time":
            return penalty

        row = self._row(unit)
        magnitude = abs(rounded)
        if row.system != "calendar" and unit not in {"second", "minute", "hour"}:
            penalty += 6
        if unit == "second" and magnitude >= 90:
            penalty += 2
        elif unit == "minute" and magnitude >= 90:
            penalty += 2
        elif unit == "hour" and magnitude >= 36:
            penalty += 2
        elif unit == "day" and magnitude >= 10:
            penalty += 2
        elif unit == "week" and magnitude >= 8:
            penalty += 4
        elif unit == "month" and magnitude >= 18:
            penalty += 2
        return penalty

    def _should_suppress_generic_time_bucket(self, parsed: ParsedInput, row: UnitRow, rounded: float) -> bool:
        if parsed.family != "time" or self.language == "ru":
            return False

        upper = self._best_human_upper_renderable(parsed)
        if upper is None or upper.unit != "year":
            return False

        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        remainder = 1.0 - upper_value
        if not (0 < remainder <= self._near_upper_threshold("normal")):
            return False

        if row.unit == "month" and rounded >= 11:
            return True
        return False

    def _best_human_upper_renderable(self, parsed: ParsedInput) -> UnitRow | None:
        source_row = self._row(parsed.unit)
        candidates = [
            row
            for row in self._renderable_rows(parsed.family, parsed.unit)
            if row.factor_to_si is not None and source_row.factor_to_si is not None and row.factor_to_si > source_row.factor_to_si
        ]
        if not candidates:
            return None

        def rank(row: UnitRow) -> tuple[int, float, float]:
            converted = self._convert(parsed.value, parsed.unit, row.unit)
            return (self._human_unit_penalty(row.unit), abs(math.log10(max(converted, 1e-9))), abs(converted - 1.0))

        return min(candidates, key=rank)

    def _best_human_lower_renderable(self, parsed: ParsedInput) -> UnitRow | None:
        source_row = self._row(parsed.unit)
        candidates = [
            row
            for row in self._renderable_rows(parsed.family, parsed.unit)
            if row.factor_to_si is not None and source_row.factor_to_si is not None and row.factor_to_si < source_row.factor_to_si
        ]
        if not candidates:
            return None

        def rank(row: UnitRow) -> tuple[int, float, float]:
            converted = self._convert(parsed.value, parsed.unit, row.unit)
            return (self._human_unit_penalty(row.unit), abs(math.log10(max(converted, 1e-9))), abs(converted - 1.0))

        return min(candidates, key=rank)

    def _best_lower_renderable(self, parsed: ParsedInput) -> UnitRow | None:
        source_row = self._row(parsed.unit)
        candidates = [
            row
            for row in self._renderable_rows(parsed.family, parsed.unit)
            if row.factor_to_si is not None
            and source_row.factor_to_si is not None
            and row.factor_to_si < source_row.factor_to_si
        ]
        if not candidates:
            return None

        def rank(row: UnitRow) -> tuple[float, float]:
            converted = self._convert(parsed.value, parsed.unit, row.unit)
            if converted <= 0:
                return (float("inf"), float("inf"))
            return (abs(math.log10(converted)), abs(converted - 1.0))

        return min(candidates, key=rank)

    def _neighbor(self, unit: str, direction: int) -> UnitRow | None:
        row = self._row(unit)
        rows = self._family_rows(row.family)
        index = [item.unit for item in rows].index(unit)
        target_index = index + direction
        if 0 <= target_index < len(rows):
            return rows[target_index]
        return None

    def _convert(self, value: float, source: str, target: str) -> float:
        source_row = self._row(source)
        target_row = self._row(target)
        if source_row.factor_to_si is None or target_row.factor_to_si is None:
            raise HumanizeError(f"Cannot convert between '{source}' and '{target}'.")
        return value * source_row.factor_to_si / target_row.factor_to_si

    def _render_forms(self, unit: str) -> dict[str, str]:
        return self.assets.unit_render.get(unit, {"one": unit, "few": unit, "many": unit, "short": unit})

    def _named_alias(self, key: str, fallback: str, prefer_last: bool = False) -> str:
        aliases = self.assets.named_value_aliases.get(key)
        if not aliases:
            return fallback
        return aliases[-1] if prefer_last else aliases[0]

    def _approximation_groups_for_level(self, level: str) -> list[str]:
        if level == "extreme":
            return ["approximation_very_rough", "approximation_rough", "approximation"]
        if level == "coarse":
            return ["approximation_rough", "approximation"]
        return ["approximation_neutral", "approximation"]

    def _sample_approximation_words(self, level: str = "normal", limit: int = 3) -> list[str]:
        grouped_values: list[list[str]] = []
        for group_name in self._approximation_groups_for_level(level):
            current_group: list[str] = []
            for item in self.assets.function_words.get(group_name, []):
                if isinstance(item, str) and item and item not in current_group:
                    current_group.append(item)
            if current_group:
                grouped_values.append(current_group)
        if not grouped_values:
            return [self.runtime_pack.about_fallback]
        primary = grouped_values[0]
        if len(primary) >= limit:
            return self._rng.sample(primary, limit)

        values: list[str] = []
        for group in grouped_values:
            for item in group:
                if item not in values:
                    values.append(item)
        if len(values) <= limit:
            return values
        remainder = [item for item in values if item not in primary]
        sample = primary[:]
        needed = max(limit - len(sample), 0)
        if needed and remainder:
            sample.extend(self._rng.sample(remainder, min(needed, len(remainder))))
        return sample[:limit]

    def _approximation_word(self, level: str = "normal") -> str:
        words = self._sample_approximation_words(level, limit=1)
        return words[0] if words else self.runtime_pack.about_fallback

    def _sample_group_words(self, group_name: str, limit: int = 3) -> list[str]:
        values = [item for item in self.assets.function_words.get(group_name, []) if isinstance(item, str) and item]
        if not values:
            return []
        if len(values) <= limit:
            return values
        return self._rng.sample(values, limit)

    def _sample_formatted_group_words(self, group_name: str, limit: int = 3, **kwargs: str) -> list[str]:
        results: list[str] = []
        for template in self._sample_group_words(group_name, limit=limit):
            try:
                formatted = template.format(**kwargs)
            except KeyError:
                continue
            if formatted and formatted not in results:
                results.append(formatted)
        return results

    def _sample_aliases(self, key: str, fallback: str, limit: int = 3) -> list[str]:
        aliases = [item for item in self.assets.named_value_aliases.get(key, []) if isinstance(item, str) and item]
        if not aliases:
            return [fallback]
        if len(aliases) <= limit:
            return aliases
        return self._rng.sample(aliases, limit)

    def _join_parts(self, *parts: str) -> str:
        filtered = [part for part in parts if part]
        if not filtered:
            return ""
        separator = self.runtime_pack.word_separator
        return separator.join(filtered) if separator else "".join(filtered)

    def _compose_named_unit(self, left_text: str, unit_text: str, joiner_key: str) -> str:
        joiners = self.assets.composition.get("joiners", {}).get(joiner_key, [])
        if joiner_key == "bucket_on_unit" and self.language in {"hi", "ur"}:
            joiners = []
        joiner = joiners[-1] if len(joiners) > 1 else (joiners[0] if joiners else "")
        if joiner:
            return self._join_parts(left_text, joiner, unit_text)
        return self._join_parts(left_text, unit_text)

    def _compose_named_scale(self, left_text: str, right_text: str, joiner_key: str) -> str:
        joiners = self.assets.composition.get("joiners", {}).get(joiner_key, [])
        joiner = joiners[0] if joiners else ""
        if joiner:
            return self._join_parts(left_text, joiner, right_text)
        return self._join_parts(left_text, right_text)

    def _english_indefinite_phrase(self, text: str) -> str:
        if self.language != "en" or not text:
            return text
        lowered = text.lower()
        if lowered.startswith(("a ", "an ", "the ")):
            return text
        article = "an" if lowered[0] in "aeiou" or lowered.startswith(("hour", "honest", "honor", "heir")) else "a"
        return f"{article} {text}"

    def _should_suppress_generic_time_same_unit_bucket(self, parsed: ParsedInput) -> bool:
        if parsed.family != "time":
            return False
        upper = self._best_human_upper_renderable(parsed)
        if upper is None or upper.system != "calendar":
            return False
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        return 0.25 <= upper_value <= 2.5

    def _default_connector(self) -> str:
        connectors = self.assets.function_words.get("connectors", [])
        for connector in connectors:
            if isinstance(connector, str) and connector:
                return connector
        return "and" if self.language == "en" else "и"

    def _additive_bucket_templates(self, **kwargs: str) -> list[str]:
        return self._sample_formatted_group_words("additive_bucket_templates", limit=4, **kwargs)

    def _randomized_candidate_order(self, candidates: list[Candidate], approximation: str) -> list[Candidate]:
        if approximation == "normal":
            return sorted(candidates, key=lambda item: item.score + self._rng.uniform(0.0, 0.025), reverse=True)

        remaining = candidates[:]
        ordered: list[Candidate] = []
        seen_rule_kinds: set[str] = set()
        score_window = 0.12

        while remaining:
            top_score = max(item.score for item in remaining)
            window = [item for item in remaining if top_score - item.score <= score_window]
            diverse = [item for item in window if item.rule_kind not in seen_rule_kinds]
            choices = diverse or window
            weights = [max(item.score, 0.01) for item in choices]
            chosen = self._rng.choices(choices, weights=weights, k=1)[0]
            ordered.append(chosen)
            seen_rule_kinds.add(chosen.rule_kind)
            remaining.remove(chosen)

        return ordered

    def _plural_form(self, number: int, unit: str) -> str:
        forms = self._render_forms(unit)
        if self.language != "ru":
            return forms["one"] if abs(number) == 1 else forms["many"]
        value = abs(number) % 100
        if 11 <= value <= 14:
            return forms["many"]
        tail = value % 10
        if tail == 1:
            return forms["one"]
        if tail in (2, 3, 4):
            return forms["few"]
        return forms["many"]

    def _fraction_form(self, unit: str) -> str:
        if self.language != "ru":
            return self._render_forms(unit).get("many", unit)
        return self._render_forms(unit).get("few", unit)

    def _format_number(self, value: float, digits: int = 1) -> str:
        if float(value).is_integer():
            return str(int(value))
        rounded = round(value, digits)
        text = f"{rounded:.{digits}f}".rstrip("0").rstrip(".")
        return text

    def _number_word(self, number: int, bound: bool = False) -> str | None:
        lookup = BOUND_NUMBER_WORDS if bound else SMALL_NUMBER_WORDS
        return lookup.get(self.language, {}).get(number)

    def _quantity_word_variant(self, number: int, unit: str, bound: bool = False) -> str | None:
        word = self._number_word(number, bound=bound)
        if not word:
            return None
        return self._join_parts(word, self._plural_form(number, unit))

    def _count_noun_forms(self, parsed: ParsedInput) -> dict[str, str]:
        if parsed.unit != "count" or not parsed.count_noun:
            return {"one": "", "few": "", "many": "", "short": ""}

        if self.language != "ru":
            return {"one": parsed.count_noun, "few": parsed.count_noun, "many": parsed.count_noun, "short": parsed.count_noun}

        analyzer = getattr(self.morphology, "_analyzer", None)
        if analyzer is None or " " in parsed.count_noun:
            return {"one": parsed.count_noun, "few": parsed.count_noun, "many": parsed.count_noun, "short": parsed.count_noun}

        parsed_forms = analyzer.parse(parsed.count_noun)
        if not parsed_forms:
            return {"one": parsed.count_noun, "few": parsed.count_noun, "many": parsed.count_noun, "short": parsed.count_noun}

        lexeme = parsed_forms[0]
        one = (lexeme.inflect({"nomn", "sing"}) or lexeme).word
        few = (lexeme.inflect({"gent", "sing"}) or lexeme).word
        many = (lexeme.inflect({"gent", "plur"}) or lexeme).word
        return {"one": one, "few": few, "many": many, "short": many}

    def _count_form(self, parsed: ParsedInput, number: int) -> str:
        if parsed.unit != "count":
            return self._plural_form(number, parsed.unit)
        forms = self._count_noun_forms(parsed)
        if self.language != "ru":
            return forms["one"]
        value = abs(number) % 100
        if 11 <= value <= 14:
            return forms["many"]
        tail = value % 10
        if tail == 1:
            return forms["one"]
        if tail in (2, 3, 4):
            return forms["few"]
        return forms["many"]

    def _count_fraction_form(self, parsed: ParsedInput) -> str:
        if parsed.unit != "count":
            return self._fraction_form(parsed.unit)
        return self._count_noun_forms(parsed)["many"]

    def _render_parsed_quantity(self, parsed: ParsedInput, value: float, level: str = "normal") -> str:
        rounded = self._round_to_bucket(value, level)
        digits = 2 if level == "fine" else 1
        if float(rounded).is_integer():
            return self._join_parts(str(int(rounded)), self._count_form(parsed, int(rounded)))
        return self._join_parts(self._format_number(rounded, digits), self._count_fraction_form(parsed))

    def _scale_base_form(self, scale_key: str, quantity: int) -> str:
        aliases = self.assets.named_value_aliases.get(scale_key, [])
        if not aliases:
            return scale_key
        if self.language == "ru" and len(aliases) >= 3:
            value = abs(quantity) % 100
            if 11 <= value <= 14:
                return aliases[2]
            tail = value % 10
            if tail == 1:
                return aliases[0]
            if tail in (2, 3, 4):
                return aliases[1]
            return aliases[2]
        if len(aliases) >= 2 and abs(quantity) != 1:
            return aliases[-1]
        return aliases[0]

    def _num2words_lang(self) -> str | None:
        mapping = {"ru": "ru", "en": "en", "es": "es", "fr": "fr", "pt": "pt", "ar": "ar", "bn": "bn"}
        return mapping.get(self.language)

    def _whole_number_words(self, whole: int) -> str | None:
        if whole <= 0 or num2words is None:
            return None
        lang = self._num2words_lang()
        if not lang:
            return None
        try:
            phrase = str(num2words(whole, lang=lang))
            if self.language != "ru":
                return phrase
            analyzer = getattr(self.morphology, "_analyzer", None)
            if analyzer is None:
                return phrase
            inflected: list[str] = []
            for token in phrase.split():
                parsed_forms = analyzer.parse(token)
                if not parsed_forms:
                    inflected.append(token)
                    continue
                inflected.append((parsed_forms[0].inflect({"gent"}) or parsed_forms[0]).word)
            return " ".join(inflected)
        except Exception:
            return None

    def _count_scale_noun_joiner(self) -> str:
        return {"es": "de", "fr": "de", "pt": "de"}.get(self.language, "")

    def _join_count_scale_noun(self, scale_phrase: str, noun_many: str) -> str:
        if not noun_many:
            return scale_phrase
        joiner = self._count_scale_noun_joiner()
        return self._join_parts(scale_phrase, joiner, noun_many) if joiner else self._join_parts(scale_phrase, noun_many)

    def _fraction_alias_for_scale(self, anchor: float) -> str:
        key_map = {
            0.25: "fraction.quarter",
            round(1 / 3, 6): "fraction.third",
            0.5: "fraction.half",
            0.75: "fraction.three_quarters",
        }
        key = key_map[round(anchor, 6)]
        aliases = [item for item in self.assets.named_value_aliases.get(key, []) if isinstance(item, str) and item]
        if anchor == 0.5:
            half_overrides = {
                "ru": self._fraction_names(0.5)[1] or "половиной",
                "en": "a half",
                "es": "medio",
                "fr": "demi",
                "pt": "meio",
            }
            return half_overrides.get(self.language, aliases[0] if aliases else "half")
        if self.language in {"en", "es", "fr", "pt", "hi", "bn", "ur"} and len(aliases) > 1:
            return aliases[1]
        return aliases[0] if aliases else self._format_number(anchor, 2)

    def _count_fraction_threshold(self, anchor: float, level: str) -> float:
        if anchor == 0.5:
            return 0.06 if level == "normal" else 0.12
        if abs(anchor - (1 / 3)) < 0.001:
            return 0.04 if level == "normal" else 0.055
        if anchor == 0.25:
            return 0.04 if level == "normal" else 0.06
        return 0.04 if level == "normal" else 0.07

    def _count_fraction_score(self, anchor: float, distance: float) -> float:
        base = {
            0.25: 0.92,
            round(1 / 3, 6): 0.96,
            0.5: 1.02,
            0.75: 0.95,
        }[round(anchor, 6)]
        return base - distance

    def _count_fraction_scale_form(self, scale_key: str, whole: int, anchor: float) -> str:
        if anchor == 0.5:
            return self._scale_base_form(scale_key, whole)
        if self.language == "ru":
            aliases = self.assets.named_value_aliases.get(scale_key, [])
            return aliases[1] if len(aliases) > 1 else self._scale_base_form(scale_key, 1)
        if self.language in {"es", "fr", "pt"}:
            return self._scale_base_form(scale_key, whole)
        return self._scale_base_form(scale_key, 1)

    def _count_fraction_only_scale_form(self, scale_key: str) -> str:
        aliases = self.assets.named_value_aliases.get(scale_key, [])
        if not aliases:
            return scale_key
        if self.language == "ru":
            return aliases[1] if len(aliases) > 1 else aliases[0]
        return aliases[0]

    def _count_scale_pure_fraction_templates(self, fraction: str, scale: str, anchor: float) -> list[str]:
        if self.language == "ru":
            fraction_name, _ = self._fraction_names(anchor)
            if anchor == 0.5:
                compact = {
                    "тысячи": "полтысячи",
                    "миллиона": "полмиллиона",
                    "миллиарда": "полмиллиарда",
                }.get(scale)
                return [compact, f"половина {scale}"] if compact else [f"половина {scale}"]
            return [f"{fraction_name} {scale}"]
        if self.language == "en":
            if anchor == 0.5:
                return [f"half a {scale}"]
            if anchor == 0.25:
                return [f"a quarter of a {scale}"]
            if abs(anchor - (1 / 3)) < 0.001:
                return [f"a third of a {scale}"]
            return [f"three quarters of a {scale}"]
        if self.language == "es":
            mapping = {0.25: "un cuarto", round(1 / 3, 6): "un tercio", 0.5: "medio", 0.75: "tres cuartos"}
            return [f"{mapping[round(anchor, 6)]} {scale}" if anchor == 0.5 else f"{mapping[round(anchor, 6)]} de {scale}"]
        if self.language == "fr":
            mapping = {0.25: "un quart", round(1 / 3, 6): "un tiers", 0.5: "un demi", 0.75: "trois quarts"}
            return [f"{mapping[round(anchor, 6)]}-{scale}" if anchor == 0.5 else f"{mapping[round(anchor, 6)]} de {scale}"]
        if self.language == "pt":
            mapping = {0.25: "um quarto", round(1 / 3, 6): "um terço", 0.5: "meio", 0.75: "três quartos"}
            return [f"{mapping[round(anchor, 6)]} {scale}" if anchor == 0.5 else f"{mapping[round(anchor, 6)]} de {scale}"]
        if self.language == "zh":
            mapping = {0.25: "四分之一", round(1 / 3, 6): "三分之一", 0.5: "半", 0.75: "四分之三"}
            return [f"{mapping[round(anchor, 6)]}{scale}"]
        if self.language == "ar":
            mapping = {0.25: "ربع", round(1 / 3, 6): "ثلث", 0.5: "نصف", 0.75: "ثلاثة أرباع"}
            return [f"{mapping[round(anchor, 6)]} {scale}"]
        if self.language == "hi":
            mapping = {0.25: "एक चौथाई", round(1 / 3, 6): "एक तिहाई", 0.5: "आधा", 0.75: "तीन चौथाई"}
            return [f"{mapping[round(anchor, 6)]} {scale}"]
        if self.language == "bn":
            mapping = {0.25: "এক চতুর্থাংশ", round(1 / 3, 6): "এক তৃতীয়াংশ", 0.5: "অর্ধেক", 0.75: "তিন চতুর্থাংশ"}
            return [f"{mapping[round(anchor, 6)]} {scale}"]
        if self.language == "ur":
            mapping = {0.25: "ایک چوتھائی", round(1 / 3, 6): "ایک تہائی", 0.5: "آدھا", 0.75: "تین چوتھائی"}
            return [f"{mapping[round(anchor, 6)]} {scale}"]
        return [self._join_parts(fraction, scale)]

    def _count_scale_fraction_templates(self, whole: str, fraction: str, scale: str, anchor: float) -> list[str]:
        if self.language == "ru":
            fraction_name, instrumental = self._fraction_names(anchor)
            if anchor == 0.5:
                return [f"{whole} с {instrumental or fraction_name} {scale}"]
            return [f"{whole} и {fraction_name} {scale}"]
        if self.language == "en":
            return [f"{whole} and {fraction} {scale}"]
        if self.language in {"es", "fr", "pt"}:
            connector = {"es": "y", "fr": "et", "pt": "e"}[self.language]
            return [f"{whole} {scale} {connector} {fraction}"]
        if self.language == "zh":
            return [f"{whole}又{fraction}{scale}"]
        if self.language == "ar":
            return [f"{whole} و{fraction} {scale}"]
        if self.language == "hi":
            return [f"{whole} और {fraction} {scale}"]
        if self.language == "bn":
            return [f"{whole} আর {fraction} {scale}"]
        if self.language == "ur":
            return [f"{whole} اور {fraction} {scale}"]
        return [self._join_parts(whole, fraction, scale)]

    def _count_scale_fraction_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if parsed.unit != "count" or parsed.value < 1500:
            return []

        noun_many = self._count_noun_forms(parsed)["many"]
        scales = [
            (1000000000, "scale_base.billion"),
            (1000000, "scale_base.million"),
            (1000, "scale_base.thousand"),
        ]
        anchors = [0.25, 1 / 3, 0.5, 0.75]

        for base, scale_key in scales:
            scaled = parsed.value / base
            if 0 < scaled < 1:
                roughness = self._roughness_for_level(level)
                results: list[Candidate] = []
                for anchor in anchors:
                    distance = abs(scaled - anchor)
                    if distance > self._count_fraction_threshold(anchor, level):
                        continue
                    fraction_text = self._fraction_alias_for_scale(anchor)
                    scale_form = self._count_fraction_only_scale_form(scale_key)
                    phrase_score = self._count_fraction_score(anchor, distance) - 0.02
                    pure_templates = self._count_scale_pure_fraction_templates(fraction_text, scale_form, anchor)

                    for index, text in enumerate(pure_templates):
                        results.append(Candidate(self._join_count_scale_noun(text, noun_many), phrase_score - index * 0.03, "count_scale_fraction_render", "colloquial" if index == 0 else "official", roughness))

                    if pure_templates:
                        results.append(Candidate(self._join_count_scale_noun(self._join_parts(self._approximation_word(level), pure_templates[0]), noun_many), 0.75 - distance, "count_scale_fraction_render", "official", roughness))
                if results:
                    return results
                continue
            if scaled < 1.25:
                continue
            whole = math.floor(scaled)
            if whole >= 1000:
                continue
            fractional = scaled - whole
            roughness = self._roughness_for_level(level)
            results: list[Candidate] = []
            for anchor in anchors:
                distance = abs(fractional - anchor)
                if distance > self._count_fraction_threshold(anchor, level):
                    continue
                fraction_text = self._fraction_alias_for_scale(anchor)
                scale_form = self._count_fraction_scale_form(scale_key, whole, anchor)
                phrase_score = self._count_fraction_score(anchor, distance)

                for index, text in enumerate(self._count_scale_fraction_templates(str(whole), fraction_text, scale_form, anchor)):
                    results.append(Candidate(self._join_count_scale_noun(text, noun_many), phrase_score - index * 0.03, "count_scale_fraction_render", "colloquial" if index == 0 else "official", roughness))

                word_whole = self._whole_number_words(whole)
                if word_whole:
                    for index, text in enumerate(self._count_scale_fraction_templates(word_whole, fraction_text, scale_form, anchor)):
                        results.append(Candidate(self._join_count_scale_noun(text, noun_many), phrase_score - 0.05 - index * 0.03, "count_scale_fraction_render", "official", roughness))

                numeric_scale = self._scale_base_form(scale_key, max(whole, 2))
                results.append(Candidate(self._join_count_scale_noun(self._join_parts(self._approximation_word(level), self._format_number(whole + anchor, 1), numeric_scale), noun_many), 0.79 - distance, "count_scale_fraction_render", "official", roughness))

            if results:
                return results

        return []

    def _round_to_bucket(self, value: float, level: str = "normal") -> float:
        absolute = abs(value)
        if level == "fine":
            if absolute >= 1000:
                return round(value, -1)
            if absolute >= 100:
                return round(value)
            if absolute >= 10:
                return round(value, 1)
            if absolute >= 1:
                return round(value * 4) / 4
            return round(value, 3)
        if level == "coarse":
            if absolute >= 1000:
                return round(value, -3)
            if absolute >= 100:
                return round(value, -2)
            if absolute >= 10:
                return round(value / 5) * 5
            if absolute >= 1:
                return round(value)
            return round(value, 1)
        if level == "extreme":
            if absolute >= 1000:
                return round(value, -4)
            if absolute >= 100:
                return round(value, -2)
            if absolute >= 10:
                return round(value / 10) * 10
            if absolute >= 1:
                return round(value * 2) / 2
            return round(value, 1)
        if absolute >= 1000:
            return round(value, -2)
        if absolute >= 100:
            return round(value, -1)
        if absolute >= 10:
            return round(value)
        if absolute >= 1:
            return round(value * 2) / 2
        return round(value, 2)

    def _roughness_for_level(self, level: str) -> str:
        return {"normal": "normal", "coarse": "rough", "extreme": "very_rough"}.get(level, "normal")

    def _fraction_distance_threshold(self, level: str) -> float:
        return {"normal": 0.12, "coarse": 0.18, "extreme": 0.18}.get(level, 0.12)

    def _minimum_fraction_of_upper_value(self, level: str) -> float:
        return {"normal": 0.18, "coarse": 0.18, "extreme": 0.18}.get(level, 0.18)

    def _human_upper_near_integer_context(self, parsed: ParsedInput) -> tuple[UnitRow, float, int] | None:
        if parsed.unit == "count" or parsed.value <= 0:
            return None
        upper = self._best_human_upper_renderable(parsed)
        if upper is None or upper.unit == parsed.unit:
            return None
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        nearest_whole = round(upper_value)
        if nearest_whole < 1 or nearest_whole > 1000:
            return None
        distance = abs(upper_value - nearest_whole)
        if distance == 0 or distance > 0.05:
            return None
        source_closeness = abs(math.log10(max(abs(parsed.value), 1e-9)))
        upper_closeness = abs(math.log10(max(abs(upper_value), 1e-9)))
        if upper_closeness >= source_closeness - 0.35 and self._human_unit_penalty(parsed.unit) <= self._human_unit_penalty(upper.unit):
            return None
        return upper, upper_value, nearest_whole

    def _human_upper_near_integer_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        context = self._human_upper_near_integer_context(parsed)
        if context is None:
            return []
        upper, upper_value, nearest_whole = context
        delta = upper_value - nearest_whole
        if delta == 0:
            return []

        roughness = self._roughness_for_level(level)

        if nearest_whole == 1:
            exact_label = self._english_indefinite_phrase(self._render_forms(upper.unit)["one"])
            quantity = self._fraction_form(upper.unit)
        else:
            exact_label = self._join_parts(str(nearest_whole), self._plural_form(nearest_whole, upper.unit))
            quantity = exact_label

        if self.language != "ru":
            tail_descriptor_words = self._sample_group_words("decimal_anchor_small_tail_words", limit=1)
            tail_descriptor = tail_descriptor_words[0] if tail_descriptor_words else ({"en": "a bit", "ur": "تھوڑا"}.get(self.language, "a bit"))
            if delta > 0:
                templated = self._sample_formatted_group_words(
                    "decimal_anchor_above_templates",
                    limit=3,
                    anchor_words=exact_label,
                    anchor_short=exact_label,
                    tail_descriptor=tail_descriptor,
                )
                if templated:
                    return [
                        Candidate(text, 0.95 - delta - index * 0.03, "human_upper_near_integer", "colloquial" if index == 0 else "official", roughness)
                        for index, text in enumerate(templated)
                    ]
                return [
                    Candidate(self._join_parts(self._approximation_word(level), self._render_quantity(upper_value, upper.unit, "fine" if level == "normal" else "normal")), 0.9 - delta, "human_upper_near_integer", "official", roughness),
                    Candidate(self._join_parts(exact_label, tail_descriptor), 0.84 - delta, "human_upper_near_integer", "colloquial", roughness),
                ]

            gap = abs(delta)
            templated = self._sample_formatted_group_words(
                "decimal_anchor_below_templates",
                limit=3,
                anchor_words=exact_label,
                anchor_short=exact_label,
            )
            if templated:
                return [
                    Candidate(text, 0.95 - gap - index * 0.03, "human_upper_near_integer", "colloquial" if index == 0 else "official", roughness)
                    for index, text in enumerate(templated)
                ]
            return [
                Candidate(self.runtime_pack.nearly_template.format(unit=exact_label), 0.9 - gap, "human_upper_near_integer", "colloquial", roughness),
                Candidate(self._join_parts(self._approximation_word(level), self._render_quantity(upper_value, upper.unit, "fine" if level == "normal" else "normal")), 0.84 - gap, "human_upper_near_integer", "official", roughness),
            ]

        if delta > 0:
            return [
                Candidate(f"чуть больше {quantity}", 0.95 - delta, "human_upper_near_integer", "neutral", roughness),
                Candidate(f"{exact_label} с небольшим", 0.92 - delta, "human_upper_near_integer", "colloquial", roughness),
            ]

        gap = abs(delta)
        below_label = exact_label if nearest_whole == 1 and self.language == "ru" else quantity
        return [
            Candidate(f"почти {below_label}", 0.95 - gap, "human_upper_near_integer", "colloquial", roughness),
            Candidate(f"без малого {below_label}", 0.91 - gap, "human_upper_near_integer", "neutral", roughness),
        ]

    def _should_suppress_same_unit_time_fraction(self, parsed: ParsedInput) -> bool:
        if self.language != "ru" or parsed.family != "time" or parsed.value <= 0:
            return False

        upper = self._best_human_upper_renderable(parsed)
        if upper is None or upper.unit == parsed.unit:
            return False

        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        nearest_whole = round(upper_value)
        if nearest_whole < 1:
            return False

        remainder = nearest_whole - upper_value
        return 0 < remainder <= self._near_upper_threshold("normal")

    def _human_bucket_candidate_rows(self, parsed: ParsedInput) -> list[UnitRow]:
        source_row = self._row(parsed.unit)
        if parsed.family == "time":
            rows = [
                row
                for row in self._family_rows(parsed.family)
                if row.unit in self.assets.unit_render and row.unit != parsed.unit and row.factor_to_si is not None
            ]
            if source_row.system == "calendar":
                return [row for row in rows if row.system == "calendar"]
            if source_row.factor_to_si is not None and source_row.factor_to_si < 1:
                return [row for row in rows if (row.factor_to_si or 0) <= 1 or row.system == "calendar"]
            if parsed.unit == "second":
                return [row for row in rows if row.system == "calendar"]
            return rows
        return [
            row
            for row in self._renderable_rows(parsed.family, parsed.unit)
            if row.unit != parsed.unit and row.factor_to_si is not None
        ]

    def _human_preferred_bucket_context(self, parsed: ParsedInput, level: str) -> tuple[UnitRow, float, float] | None:
        if parsed.unit == "count" or parsed.value <= 0:
            return None
        source_row = self._row(parsed.unit)
        if parsed.family != "time" and (source_row.factor_to_si is None or source_row.factor_to_si >= 1):
            return None

        source_closeness = abs(math.log10(max(abs(parsed.value), 1e-9)))
        threshold = {"normal": 0.08, "coarse": 0.12, "extreme": 0.18}.get(level, 0.08)
        best: tuple[tuple[int, int, float, float, float], tuple[UnitRow, float, float]] | None = None

        for row in self._human_bucket_candidate_rows(parsed):
            converted = self._convert(parsed.value, parsed.unit, row.unit)
            if converted <= 0:
                continue
            rounded = self._estimation_bucket_value(converted, level)
            if rounded == 0:
                continue
            if abs(rounded) < 1:
                continue
            relative_gap = abs(converted - rounded) / max(abs(rounded), 1.0)
            if relative_gap > threshold:
                continue
            target_closeness = abs(math.log10(max(abs(rounded), 1e-9)))
            if source_closeness - target_closeness <= 0.5:
                continue

            magnitude = abs(rounded)
            if 1 <= magnitude <= 1000:
                scale_band = 0
            elif 0.1 <= magnitude < 1 or 1000 < magnitude <= 10000:
                scale_band = 1
            else:
                scale_band = 2

            rank = (
                self._human_bucket_context_penalty(parsed.family, row.unit, rounded),
                scale_band,
                relative_gap,
                target_closeness,
                abs(converted - rounded),
            )
            if best is None or rank < best[0]:
                best = (rank, (row, converted, rounded))

        return best[1] if best is not None else None

    def _human_preferred_bucket_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        context = self._human_preferred_bucket_context(parsed, level)
        if context is None:
            return []
        row, converted, rounded = context
        roughness = self._roughness_for_level(level)
        render_level = "fine" if level == "coarse" and not float(rounded).is_integer() else ("normal" if level == "coarse" else level)
        quantity = self._render_quantity(rounded, row.unit, render_level)
        relative_gap = abs(converted - rounded) / max(abs(rounded), 1.0)
        score_penalty = self._human_unit_score_penalty(row.unit)
        if self._should_suppress_time_lower_bucket_for_upper_fraction(parsed, row, level):
            return []
        if self.language == "ru":
            soft_upper = self._ru_soft_calendar_near_upper_context(parsed)
            if level == "normal" and soft_upper is not None and row.system == "calendar" and row.factor_to_si is not None and soft_upper[0].factor_to_si is not None and row.factor_to_si < soft_upper[0].factor_to_si:
                return []
            results: list[Candidate] = []
            mixed_phrase = self._human_preferred_mixed_quantity_phrase(converted, row.unit, level)
            if mixed_phrase:
                results.append(Candidate(mixed_phrase, 0.97 - min(relative_gap, 0.12) - score_penalty, "human_preferred_bucket", "neutral", roughness))

            recursive_labels = self._human_preferred_recursive_labels(rounded, row.unit, row.family, level)
            results.extend(self._human_preferred_recursive_candidates(recursive_labels, converted, rounded, relative_gap, roughness))

            results.append(Candidate(self._join_parts(self._approximation_word(level), quantity), 0.93 - min(relative_gap, 0.12) - score_penalty, "human_preferred_bucket", "official", roughness))

            if converted > rounded:
                tail_text = f"{quantity} с небольшим"
            elif converted < rounded:
                tail_text = f"без малого {quantity}"
            else:
                tail_text = quantity
            results.append(Candidate(tail_text, 0.89 - min(relative_gap, 0.12) - score_penalty, "human_preferred_bucket", "colloquial", roughness))
            return results

        if self._should_suppress_generic_time_bucket(parsed, row, rounded):
            return []

        tail_words = self._sample_group_words("decimal_anchor_small_tail_words", limit=1)
        tail_word = tail_words[0] if tail_words else "a bit"
        templated = self._sample_formatted_group_words(
            "decimal_anchor_above_templates",
            limit=2,
            anchor_words=quantity,
            anchor_short=quantity,
            tail_descriptor=tail_word,
        )
        results = [
            Candidate(text, 0.93 - min(relative_gap, 0.12) - score_penalty - index * 0.03, "human_preferred_bucket", "colloquial" if index == 0 else "official", roughness)
            for index, text in enumerate(templated)
        ]
        if results:
            return results
        return [
            Candidate(self._join_parts(self._approximation_word(level), quantity), 0.93 - min(relative_gap, 0.12) - score_penalty, "human_preferred_bucket", "official", roughness),
            Candidate(self._join_parts(quantity, tail_word), 0.89 - min(relative_gap, 0.12) - score_penalty, "human_preferred_bucket", "colloquial", roughness),
        ]

    def _small_collective_range_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if parsed.value < 2 or parsed.value > 4:
            return []
        if not float(parsed.value).is_integer():
            return []

        whole = int(parsed.value)
        roughness = self._roughness_for_level(level)
        results: list[Candidate] = []

        if whole == 2:
            unit_form = self._count_noun_forms(parsed)["many"] if parsed.unit == "count" else self._render_forms(parsed.unit)["many"]
            results.append(
                Candidate(
                    self._join_parts(self._named_alias("exact.pair", "пара"), unit_form),
                    0.98 if level == "coarse" else 0.82,
                    "small_collective_render",
                    "colloquial",
                    roughness,
                )
            )

        if whole >= 3:
            low = whole - 1
            results.append(
                Candidate(
                    f"{low}-{whole} {self._plural_form(whole, parsed.unit)}",
                    0.98 if level == "coarse" else 0.84,
                    "small_collective_range_render",
                    "colloquial" if level == "coarse" else "neutral",
                    roughness,
                )
            )

        if whole <= 4:
            high = whole + 1
            results.append(
                Candidate(
                    f"{whole}-{high} {self._plural_form(high, parsed.unit)}",
                    0.95 if level == "coarse" else 0.81,
                    "small_collective_range_render",
                    "colloquial" if level == "coarse" else "neutral",
                    roughness,
                )
            )

        return results

    def _human_preferred_mixed_quantity_phrase(self, value: float, unit: str, level: str) -> str | None:
        if self.language != "ru":
            return None
        whole = math.floor(value)
        if whole < 1 or whole >= self.LARGE_COMPOSITE_WHOLE_THRESHOLD:
            return None
        if unit in {"month", "year"} and whole >= 2:
            return None
        fractional = value - whole
        anchors = [0.25, 1 / 3, 0.5, 0.75]
        anchor = min(anchors, key=lambda item: abs(fractional - item))
        distance = abs(fractional - anchor)
        threshold = {"normal": 0.06, "coarse": 0.1, "extreme": 0.1}.get(level, 0.06)
        if distance > threshold:
            return None
        return self._ru_mixed_fraction_unit_phrase(whole, anchor, unit)

    def _calendar_duration_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self.language != "ru" or parsed.family != "time":
            return []

        results: list[Candidate] = []
        if parsed.unit not in {"month", "year"}:
            months = self._convert(parsed.value, parsed.unit, "month")
            results.extend(self._calendar_duration_unit_candidates(months, "month", level))
            results.extend(self._calendar_half_year_candidates(months, level))

        if parsed.unit != "year":
            years = self._convert(parsed.value, parsed.unit, "year")
            results.extend(self._calendar_duration_unit_candidates(years, "year", level))

        return results

    def _calendar_duration_unit_candidates(self, converted: float, unit: str, level: str) -> list[Candidate]:
        minimums = {"month": 2.0, "year": 0.8}
        maximums = {"month": 18.0, "year": 8.0}
        minimum = minimums.get(unit, 1.0)
        maximum = maximums.get(unit, float("inf"))
        if converted < minimum or converted > maximum:
            return []

        rounded = self._estimation_bucket_value(converted, level)
        if rounded < 1:
            return []

        relative_gap = abs(converted - rounded) / max(abs(rounded), 1.0)
        threshold = {"normal": 0.09, "coarse": 0.13, "extreme": 0.18}.get(level, 0.09)
        if relative_gap > threshold:
            return []

        render_level = "fine" if level == "coarse" and not float(rounded).is_integer() else ("normal" if level == "coarse" else level)
        quantity = self._render_quantity(rounded, unit, render_level)
        roughness = self._roughness_for_level(level)
        gap = min(relative_gap, threshold)

        if converted < rounded:
            return [
                Candidate(f"почти {quantity}", 0.982 - gap, "calendar_duration_render", "colloquial", roughness),
                Candidate(f"без малого {quantity}", 0.95 - gap, "calendar_duration_render", "official", roughness),
            ]
        if converted > rounded:
            return [
                Candidate(f"чуть больше {quantity}", 0.972 - gap, "calendar_duration_render", "official", roughness),
                Candidate(f"{quantity} с небольшим", 0.94 - gap, "calendar_duration_render", "colloquial", roughness),
            ]
        return [Candidate(quantity, 0.97, "calendar_duration_render", "official", roughness)]

    def _calendar_half_year_candidates(self, months: float, level: str) -> list[Candidate]:
        if months < 4.5 or months > 7.5:
            return []

        distance = abs(months - 6.0)
        roughness = self._roughness_for_level(level)
        score = 0.9 - distance / 12

        if months < 6:
            return [
                Candidate("почти полгода", score, "calendar_duration_render", "colloquial", roughness),
                Candidate("без малого полгода", score - 0.03, "calendar_duration_render", "official", roughness),
            ]
        if months > 6:
            return [
                Candidate("чуть больше полугода", score, "calendar_duration_render", "official", roughness),
                Candidate("полгода с небольшим", score - 0.03, "calendar_duration_render", "colloquial", roughness),
            ]
        return [Candidate("полгода", score, "calendar_duration_render", "official", roughness)]

    def _human_preferred_recursive_labels(self, rounded: float, unit: str, family: str, level: str) -> list[str]:
        if self.language != "ru" or rounded < 1 or not float(rounded).is_integer():
            return []

        synthetic = ParsedInput(
            raw_text="",
            normalized_text="",
            value=float(int(rounded)),
            unit=unit,
            family=family,
            matched_alias=None,
            fuzzy_score=None,
            count_noun=None,
        )
        safe_rule_kinds = {
            "small_collective_render",
            "composite_bucket_collective_render",
            "count_thousand_render",
            "count_million_render",
            "composite_scale_base_render",
        }
        candidates: list[Candidate] = []
        candidates.extend(self._small_collective_range_render(synthetic, level))
        if unit == "count":
            candidates.extend(self._count_render(synthetic, allow_profane=False))
        candidates.extend(self._composite_bucket_render(synthetic, level))

        deduped: list[str] = []
        for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
            if candidate.rule_kind not in safe_rule_kinds:
                continue
            if candidate.text.startswith(("примерно ", "около ", "ориентировочно ", "приближенно ")):
                continue
            if candidate.text not in deduped:
                deduped.append(candidate.text)
        return deduped[:3]

    def _ru_recursive_below_label(self, label: str) -> str:
        if label.startswith("пара "):
            return f"пару {label[5:]}"
        return label

    def _ru_recursive_above_label(self, label: str) -> str:
        if label.startswith("пара "):
            return f"пары {label[5:]}"
        if label.startswith("тройка "):
            return f"тройки {label[7:]}"
        return label

    def _human_preferred_recursive_candidates(
        self,
        labels: list[str],
        converted: float,
        rounded: float,
        relative_gap: float,
        roughness: str,
    ) -> list[Candidate]:
        if not labels:
            return []

        gap = min(relative_gap, 0.12)
        results: list[Candidate] = []
        below = converted < rounded
        above = converted > rounded

        for index, label in enumerate(labels[:2]):
            if below:
                below_label = self._ru_recursive_below_label(label)
                results.append(Candidate(f"почти {below_label}", 0.985 - gap - index * 0.03, "human_preferred_bucket", "colloquial", roughness))
                results.append(Candidate(f"без малого {below_label}", 0.955 - gap - index * 0.03, "human_preferred_bucket", "neutral", roughness))
            elif above:
                above_label = self._ru_recursive_above_label(label)
                results.append(Candidate(f"чуть больше {above_label}", 0.975 - gap - index * 0.03, "human_preferred_bucket", "neutral", roughness))
                results.append(Candidate(f"{label} с небольшим", 0.94 - gap - index * 0.03, "human_preferred_bucket", "colloquial", roughness))
            else:
                results.append(Candidate(label, 0.97 - index * 0.03, "human_preferred_bucket", "colloquial", roughness))
        return results

    def _near_upper_threshold(self, level: str) -> float:
        return {"normal": 0.15, "coarse": 0.28, "extreme": 0.28}.get(level, 0.15)

    def _ru_soft_calendar_near_upper_context(self, parsed: ParsedInput) -> tuple[UnitRow, float, float] | None:
        if self.language != "ru" or parsed.family != "time" or parsed.value <= 0:
            return None
        upper = self._best_human_upper_renderable(parsed)
        if upper is None or upper.system != "calendar":
            return None
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        remainder = 1.0 - upper_value
        if not (0 < remainder <= 0.35):
            return None
        return upper, upper_value, remainder

    def _time_upper_fraction_context(self, parsed: ParsedInput) -> tuple[UnitRow, float, float, float] | None:
        if parsed.family != "time" or parsed.value <= 0:
            return None
        upper = self._best_human_upper_renderable(parsed)
        if upper is None or upper.system != "calendar":
            return None
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        if not (self._minimum_fraction_of_upper_value("normal") <= upper_value < 1):
            return None
        anchors = [0.25, 1 / 3, 0.5, 0.75]
        anchor = min(anchors, key=lambda item: abs(upper_value - item))
        distance = abs(upper_value - anchor)
        if distance > self._fraction_distance_threshold("normal"):
            return None
        return upper, upper_value, anchor, distance

    def _should_suppress_ru_time_bucket_for_soft_upper(self, parsed: ParsedInput, level: str) -> bool:
        return level == "normal" and self._ru_soft_calendar_near_upper_context(parsed) is not None

    def _should_suppress_time_lower_bucket_for_upper_fraction(self, parsed: ParsedInput, row: UnitRow, level: str) -> bool:
        if level != "normal" or row.system != "calendar":
            return False
        context = self._time_upper_fraction_context(parsed)
        if context is None:
            return False
        upper = context[0]
        if row.factor_to_si is None or upper.factor_to_si is None:
            return False
        return row.factor_to_si < upper.factor_to_si

    def _bucket_step(self, value: float, level: str) -> float:
        absolute = abs(value)
        if level == "fine":
            if absolute >= 1000:
                return 10
            if absolute >= 100:
                return 1
            if absolute >= 10:
                return 0.1
            if absolute >= 1:
                return 0.25
            return 0.001
        if level == "coarse":
            if absolute >= 1000:
                return 1000
            if absolute >= 100:
                return 100
            if absolute >= 10:
                return 5
            if absolute >= 1:
                return 1
            return 0.1
        if level == "extreme":
            if absolute >= 1000:
                return 1000
            if absolute >= 100:
                return 100
            if absolute >= 10:
                return 10
            if absolute >= 1:
                return 0.5
            return 0.1
        if absolute >= 1000:
            return 100
        if absolute >= 100:
            return 10
        if absolute >= 10:
            return 1
        if absolute >= 1:
            return 0.5
        return 0.01

    def _rounded_percentage(self, ratio: float, level: str) -> str:
        percent = ratio * 100
        if level == "fine":
            rounded = round(percent, 1)
        elif level == "coarse":
            rounded = round(percent / 5) * 5
        elif level == "extreme":
            rounded = round(percent / 10) * 10
        else:
            rounded = round(percent)
        return self._format_number(rounded, 1)

    def _rounded_multiplier(self, value: float, level: str) -> str:
        if level == "fine":
            rounded = round(value, 2)
        elif level == "coarse":
            rounded = round(value * 2) / 2
        elif level == "extreme":
            rounded = round(value)
        else:
            rounded = round(value, 1)
        return self._format_number(rounded, 2)

    def _render_quantity(self, value: float, unit: str, level: str = "normal") -> str:
        rounded = self._round_to_bucket(value, level)
        digits = 2 if level == "fine" else 1
        if unit == "count":
            if float(rounded).is_integer():
                return str(int(rounded))
            return self._format_number(rounded, digits)
        if float(rounded).is_integer():
            return self._join_parts(str(int(rounded)), self._plural_form(int(rounded), unit))
        rendered_number = self._format_number(rounded, digits)
        try:
            display_value = float(rendered_number)
        except ValueError:
            display_value = rounded
        if float(display_value).is_integer():
            display_int = int(display_value)
            return self._join_parts(rendered_number, self._plural_form(display_int, unit))
        return self._join_parts(rendered_number, self._fraction_form(unit))

    def _nearest_decimal_anchor_value(self, value: float) -> float | None:
        absolute = abs(value)
        if absolute < 100:
            return None
        magnitude = 10 ** math.floor(math.log10(absolute))
        candidates: list[float] = []
        for multiplier in (1, 2, 2.5, 5, 10):
            candidate = multiplier * magnitude
            if candidate >= 100:
                candidates.append(candidate)
        if not candidates:
            return None
        return min(candidates, key=lambda candidate: abs(absolute - candidate))

    def _decimal_anchor_threshold(self, level: str) -> float:
        return {"normal": 0.04, "coarse": 0.12, "extreme": 0.18}.get(level, 0.08)

    def _decimal_anchor_texts(self, anchor: float, unit: str) -> tuple[str, str]:
        forms = self._render_forms(unit)
        short_unit = "" if unit == "count" else forms.get("short", forms["many"])
        whole = int(anchor) if float(anchor).is_integer() else None
        scale_key_map = {
            1000: "scale_base.thousand",
            10000: "scale_base.ten_thousand",
            1000000: "scale_base.million",
            1000000000: "scale_base.billion",
        }

        anchor_words = self._render_quantity(anchor, unit, "normal")
        if whole in scale_key_map and unit != "count":
            anchor_words = self._join_parts(self._named_alias(scale_key_map[whole], str(whole)), forms["many"])

        anchor_short = self._join_parts(self._format_number(anchor, 0), short_unit)
        if whole is not None:
            if self.language == "ru":
                if whole >= 10000 and whole % 1000 == 0 and whole < 1000000:
                    anchor_short = self._join_parts(str(whole // 1000), "тыс", short_unit)
                elif whole >= 1000000 and whole % 1000000 == 0:
                    anchor_short = self._join_parts(str(whole // 1000000), "млн", short_unit)
            elif self.language == "en":
                if whole >= 1000 and whole % 1000 == 0 and whole < 1000000:
                    anchor_short = self._join_parts(f"{whole // 1000}k", short_unit)
                elif whole >= 1000000 and whole % 1000000 == 0:
                    anchor_short = self._join_parts(f"{whole // 1000000}M", short_unit)
            elif self.language == "ur":
                if whole >= 1000 and whole % 1000 == 0 and whole < 1000000:
                    anchor_short = self._join_parts(str(whole // 1000), "ہزار", short_unit)
                elif whole >= 1000000 and whole % 1000000 == 0:
                    anchor_short = self._join_parts(str(whole // 1000000), "ملین", short_unit)

        return anchor_words, anchor_short

    def _decimal_anchor_fraction_tail_texts(self, tail_value: float, anchor: float, unit: str) -> list[str]:
        if tail_value <= 0 or anchor < 100:
            return []

        chunk = anchor / 10
        if chunk < 100:
            return []

        ratio = tail_value / chunk
        results: list[str] = []
        forms = self._render_forms(unit)
        short_unit = forms.get("short", forms["many"])
        chunk_words, _ = self._decimal_anchor_texts(chunk, unit)
        ru_chunk_genitive = {
            100: "сотни",
            1000: "тысячи",
            10000: "десяти тысяч",
            1000000: "миллиона",
            1000000000: "миллиарда",
        }

        if abs(ratio - 0.5) <= 0.08:
            if self.language == "ru":
                if int(chunk) == 1000:
                    results.extend([self._join_parts("полтысячи", short_unit), f"половина тысячи {forms['many']}"])
                elif int(chunk) == 100:
                    results.extend([self._join_parts("полсотни", short_unit), self._join_parts("полста", short_unit)])
                else:
                    chunk_head = ru_chunk_genitive.get(int(chunk))
                    results.append(f"половина {chunk_head} {forms['many']}" if chunk_head else f"половина {chunk_words}")
            elif self.language == "en":
                results.append(f"half of {chunk_words}")
            elif self.language == "ur":
                results.append(self._join_parts("آدھی", chunk_words))
            else:
                results.append(self._join_parts(self._sample_aliases("fraction.half", "half", limit=1)[0], chunk_words))

        if abs(ratio - (1 / 3)) <= 0.07:
            if self.language == "ru":
                chunk_head = ru_chunk_genitive.get(int(chunk))
                results.append(f"треть {chunk_head} {forms['many']}" if chunk_head else f"треть {chunk_words}")
            elif self.language == "en":
                results.append(f"a third of {chunk_words}")
            elif self.language == "ur":
                results.append(self._join_parts("تہائی", chunk_words))
            else:
                results.append(self._join_parts(self._sample_aliases("fraction.third", "third", limit=1)[0], chunk_words))

        deduped: list[str] = []
        for item in results:
            if item and item not in deduped:
                deduped.append(item)
        return deduped

    def _tail_solver_texts(self, parsed: ParsedInput, level: str) -> list[str]:
        if parsed.value <= 0:
            return []

        if self.language == "ru":
            candidates = [
                *self._upper_with_small_tail(parsed),
                *self._fraction_of_current(parsed),
                *self._fraction_of_upper(parsed, level),
                *self._upper_share_band_render(parsed, level),
                *self._composite_bucket_render(parsed, level),
                *self._same_unit_bucket(parsed, level),
                *self._subunit_render(parsed),
            ]
        else:
            candidates = [
                *self._generic_upper_with_small_tail(parsed, level),
                *self._generic_fraction_of_upper(parsed, level),
                *self._generic_composite_bucket_render(parsed, level),
                *self._generic_same_unit_bucket(parsed, level),
                *self._generic_subunit_render(parsed),
            ]

        deduped: dict[str, Candidate] = {}
        for candidate in candidates:
            existing = deduped.get(candidate.text)
            if existing is None or candidate.score > existing.score:
                deduped[candidate.text] = candidate
        return [candidate.text for candidate in sorted(deduped.values(), key=lambda item: item.score, reverse=True)[:3]]

    def _decimal_anchor_tail_texts(self, tail_value: float, anchor: float, unit: str) -> list[str]:
        if tail_value <= 0:
            return []

        family = self._row(unit).family
        tail_parsed = ParsedInput(raw_text="", normalized_text="", value=tail_value, unit=unit, family=family, matched_alias=None, fuzzy_score=None, count_noun=None)
        recursive_tail_texts = self._tail_solver_texts(tail_parsed, "coarse")
        bucket_candidates = self._composite_bucket_render(tail_parsed, "coarse") if self.language == "ru" else self._generic_composite_bucket_render(tail_parsed, "coarse")
        bucket_text = bucket_candidates[0].text if bucket_candidates else ""
        forms = self._render_forms(unit)
        short_unit = forms.get("short", forms["many"])
        rounded_value = self._round_to_bucket(tail_value, "coarse")
        upper_value = self._nice_upper_bound(tail_value) or rounded_value
        rounded_tail = self._join_parts(self._format_number(rounded_value, 0), short_unit)
        upper_tail = self._join_parts(self._format_number(upper_value, 0), short_unit)

        fraction_texts = self._decimal_anchor_fraction_tail_texts(tail_value, anchor, unit)

        templated = self._sample_formatted_group_words(
            "decimal_anchor_tail_templates",
            limit=4,
            bucket_text=bucket_text,
            rounded_tail=rounded_tail,
            upper_tail=upper_tail,
        )
        if templated and not bucket_text:
            templated = [
                text
                for text in templated
                if text.strip() not in {"несколько", "a few", "چند", "some"}
            ]
        if templated:
            for recursive_text in reversed(recursive_tail_texts):
                if recursive_text not in templated:
                    templated.insert(0, recursive_text)
            for fraction_text in reversed(fraction_texts):
                if fraction_text not in templated:
                    templated.insert(0, fraction_text)
            if self.language == "ru" and float(upper_value).is_integer() and int(upper_value) == 50:
                polsta = self._join_parts("полста", short_unit)
                if polsta not in templated:
                    templated.insert(0, polsta)
            return templated

        results: list[str] = recursive_tail_texts[:]
        for fraction_text in fraction_texts:
            if fraction_text not in results:
                results.append(fraction_text)
        if bucket_text:
            prefix = {"ru": "несколько", "en": "a few", "ur": "چند"}.get(self.language, "some")
            candidate = self._join_parts(prefix, bucket_text)
            if candidate not in results:
                results.append(candidate)
        if self.language == "ru" and float(upper_value).is_integer() and int(upper_value) == 50:
            polsta = self._join_parts("полста", short_unit)
            if polsta not in results:
                results.append(polsta)
        for item in (upper_tail, rounded_tail):
            if item not in results:
                results.append(item)
        return results

    def _generic_decimal_anchor_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if parsed.value <= 0:
            return []
        if self._human_upper_near_integer_context(parsed) is not None or self._human_preferred_bucket_context(parsed, level) is not None:
            return []

        anchor = self._nearest_decimal_anchor_value(parsed.value)
        if anchor is None:
            return []

        gap = parsed.value - anchor
        if gap == 0:
            return []
        if abs(gap) / anchor > self._decimal_anchor_threshold(level):
            return []

        anchor_words, anchor_short = self._decimal_anchor_texts(anchor, parsed.unit)
        noun_many = self._count_noun_forms(parsed)["many"] if parsed.unit == "count" else ""
        if noun_many:
            anchor_words = self._join_count_scale_noun(anchor_words, noun_many)
            anchor_short = self._join_count_scale_noun(anchor_short, noun_many)
        roughness = self._roughness_for_level(level)
        score_penalty = 0.12 if parsed.unit == "count" and self._count_scale_fraction_render(parsed, level) else 0.0
        tail_descriptor_words = self._sample_group_words("decimal_anchor_small_tail_words", limit=2)
        tail_descriptor = tail_descriptor_words[0] if tail_descriptor_words else ({"ru": "немного", "en": "a bit", "ur": "تھوڑا"}.get(self.language, "a bit"))
        tail_texts = self._decimal_anchor_tail_texts(abs(gap), anchor, parsed.unit)
        results: list[Candidate] = []

        if gap > 0:
            results.extend(
                Candidate(text, 0.87 - score_penalty - index * 0.03, "same_unit_decimal_anchor", "colloquial" if index == 0 else "official", roughness)
                for index, text in enumerate(
                    self._sample_formatted_group_words(
                        "decimal_anchor_above_templates",
                        limit=4,
                        anchor_words=anchor_words,
                        anchor_short=anchor_short,
                        tail_descriptor=tail_descriptor,
                    )
                )
            )
            for tail_index, tail_text in enumerate(tail_texts[:2]):
                results.extend(
                    Candidate(text, 0.84 - score_penalty - tail_index * 0.04 - index * 0.02, "same_unit_decimal_anchor", "official" if index == 0 else "colloquial", roughness)
                    for index, text in enumerate(
                        self._sample_formatted_group_words(
                            "decimal_anchor_above_tail_templates",
                            limit=3,
                            anchor_words=anchor_words,
                            anchor_short=anchor_short,
                            tail_text=tail_text,
                        )
                    )
                )
        else:
            if level == "normal":
                results.append(
                    Candidate(
                        self._join_parts(self._approximation_word(level), anchor_words),
                        0.88 - score_penalty,
                        "same_unit_decimal_anchor",
                        "official",
                        roughness,
                    )
                )
            else:
                results.extend(
                    Candidate(text, 0.9 - score_penalty - index * 0.04, "same_unit_decimal_anchor", "colloquial" if index == 0 else "official", roughness)
                    for index, text in enumerate(
                        self._sample_formatted_group_words(
                            "decimal_anchor_below_templates",
                            limit=4,
                            anchor_words=anchor_words,
                            anchor_short=anchor_short,
                        )
                    )
                )
            if abs(gap) <= max(3, anchor * 0.01):
                results.append(Candidate(anchor_words, 0.83 - score_penalty, "same_unit_decimal_anchor", "official", roughness))

        if not results:
            if gap > 0:
                results.append(Candidate(f"{anchor_short} {self._default_connector()} {tail_descriptor}", 0.83 - score_penalty, "same_unit_decimal_anchor", "official", roughness))
            else:
                results.append(Candidate(self.runtime_pack.nearly_template.format(unit=anchor_words), 0.86 - score_penalty, "same_unit_decimal_anchor", "colloquial", roughness))

        return results

    def _generic_additive_bucket_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self._should_suppress_generic_time_same_unit_bucket(parsed):
            return []
        if level == "normal" or parsed.unit == "count" or not float(parsed.value).is_integer():
            return []

        absolute = abs(int(parsed.value))
        if absolute < 20:
            return []

        if absolute < 100:
            base = 10
            bucket_key = "scale_bucket.tens"
        elif absolute < 1000:
            base = 100
            bucket_key = "scale_bucket.hundreds"
        else:
            return []

        major = (absolute // base) * base
        remainder = absolute - major
        if remainder <= 0 or remainder > max(3, base // 3):
            return []

        bucket_count = major // base
        bucket_label = self._named_alias(bucket_key, str(base), prefer_last=self.language == "ru")
        bucket_phrase = self._compose_named_unit(f"{bucket_count} {bucket_label}", self._render_forms(parsed.unit)["many"], "bucket_on_unit")
        remainder_quantity = self._join_parts(str(remainder), self._plural_form(remainder, parsed.unit))
        connector = self._default_connector()
        roughness = self._roughness_for_level(level)
        unit_forms = self._render_forms(parsed.unit)

        templated = self._additive_bucket_templates(
            bucket_phrase=bucket_phrase,
            remainder_quantity=remainder_quantity,
            major=str(major),
            unit_form=unit_forms["many"],
            short_unit=unit_forms.get("short", unit_forms["many"]),
            connector=connector,
        )
        results = [
            Candidate(text, 0.82 - index * 0.03, "additive_bucket_render", "colloquial" if index == 0 else "official", roughness)
            for index, text in enumerate(templated)
        ]
        results.append(Candidate(self._join_parts(bucket_phrase, connector, remainder_quantity), 0.76, "additive_bucket_render", "colloquial", roughness))
        return results



def get_service(language: str = "ru") -> HumanumbersService:
    return get_cached_service(language)

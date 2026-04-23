from __future__ import annotations

import math

from .service_types import Candidate, ParsedInput


class ServiceGenericRenderingMixin:
    def _generate_generic_candidates(self, parsed: ParsedInput, level: str, system_preference: str) -> list[Candidate]:
        candidates: list[Candidate] = []
        candidates.extend(self._generic_exact_same_unit_render(parsed, level, system_preference))
        candidates.extend(self._english_hundred_count_render(parsed, level))
        candidates.extend(self._count_scale_fraction_render(parsed, level))
        candidates.extend(self._generic_fraction_of_upper(parsed, level))
        candidates.extend(self._generic_near_upper(parsed, level))
        candidates.extend(self._generic_upper_with_small_tail(parsed, level))
        candidates.extend(self._human_preferred_bucket_render(parsed, level))
        candidates.extend(self._human_upper_near_integer_render(parsed, level))
        candidates.extend(self._generic_decimal_anchor_render(parsed, level))
        candidates.extend(self._generic_cross_system_bridge_render(parsed, level, system_preference))
        candidates.extend(self._generic_locked_domain_same_unit(parsed, level))
        candidates.extend(self._generic_additive_bucket_render(parsed, level))
        candidates.extend(self._generic_composite_bucket_render(parsed, level))
        candidates.extend(self._generic_same_unit_bucket(parsed, level))
        candidates.extend(self._generic_small_upper_bound(parsed, level, system_preference))
        candidates.extend(self._generic_same_unit_range(parsed, level))
        candidates.extend(self._generic_subunit_render(parsed))
        candidates.extend(self._generic_count_render(parsed, level))
        return candidates

    def _generic_exact_same_unit_render(self, parsed: ParsedInput, level: str, system_preference: str) -> list[Candidate]:
        if parsed.value <= 0:
            return []

        roughness = self._roughness_for_level(level)
        if float(parsed.value).is_integer():
            whole = int(parsed.value)
            base_score = 0.56 if level == "normal" else 0.34
            if system_preference == "preserve":
                base_score += 0.03
            elif system_preference == "si":
                base_score -= 0.08
            results = [Candidate(self._join_parts(str(whole), self._count_form(parsed, whole)), base_score, "exact_same_unit", "official", roughness)]
            word_variant = self._quantity_word_variant(whole, parsed.unit)
            if word_variant and parsed.unit != "count":
                results.append(Candidate(word_variant, base_score - 0.02, "exact_same_unit_words", "official", roughness))
            return results

        if self.language == "ru":
            fraction_variants = self._ru_exact_same_unit_fraction_variants(parsed)
            if fraction_variants:
                results = [Candidate(fraction_variants[0], 0.5 if level == "normal" else 0.32, "exact_same_unit", "official", roughness)]
                if len(fraction_variants) > 1:
                    results.append(Candidate(fraction_variants[1], 0.48 if level == "normal" else 0.30, "exact_same_unit_words", "official", roughness))
                return results

        quantity = self._render_parsed_quantity(parsed, parsed.value, "fine" if level == "normal" else "normal")
        return [Candidate(quantity, 0.5 if level == "normal" else 0.32, "exact_same_unit", "official", roughness)]

    def _estimation_bucket_value(self, value: float, level: str) -> float:
        absolute = abs(value)
        if level == "normal":
            if absolute >= 100000:
                return round(value / 10000) * 10000
            if absolute >= 10000:
                return round(value / 1000) * 1000
            if absolute >= 1000:
                return round(value / 100) * 100
            if absolute >= 100:
                return round(value / 50) * 50
            if absolute >= 20:
                return round(value / 10) * 10
            if absolute >= 1:
                return round(value)
            return round(value, 1)
        if level == "coarse":
            if absolute >= 1000:
                return round(value / 1000) * 1000
            if absolute >= 100:
                return round(value / 100) * 100
            if absolute >= 20:
                return round(value / 10) * 10
            if absolute >= 1:
                return round(value * 2) / 2
            return round(value, 1)
        if absolute >= 1000:
            return round(value / 1000) * 1000
        if absolute >= 100:
            return round(value / 100) * 100
        if absolute >= 20:
            return round(value / 10) * 10
        if absolute >= 1:
            return round(value)
        return round(value, 1)

    def _bridge_policy(self, parsed: ParsedInput) -> dict[str, object]:
        source_row = self._row(parsed.unit)
        family_policy = self.assets.system_bridge_policies.get(parsed.family, {})
        policy = family_policy.get(source_row.system, {})
        return policy if isinstance(policy, dict) else {}

    def _bridge_target_rows(self, parsed: ParsedInput) -> list[UnitRow]:
        policy = self._bridge_policy(parsed)
        if not policy or bool(policy.get("locked", False)):
            return []

        target_units = policy.get("preferred_target_units", [])
        if not isinstance(target_units, list):
            return []

        rows: list[UnitRow] = []
        for unit in target_units:
            if not isinstance(unit, str) or unit not in self.assets.units_by_key or unit not in self.assets.unit_render:
                continue
            row = self._row(unit)
            if row.family != parsed.family or row.factor_to_si is None:
                continue
            rows.append(row)
        return rows

    def _has_viable_cross_system_bridge(self, parsed: ParsedInput) -> bool:
        source_row = self._row(parsed.unit)
        if parsed.unit == "count" or source_row.factor_to_si is None:
            return False

        policy = self._bridge_policy(parsed)
        if not policy or bool(policy.get("locked", False)):
            return False

        min_human_value = float(policy.get("min_human_value", 0.25))
        max_human_value = float(policy.get("max_human_value", 500.0))
        for row in self._bridge_target_rows(parsed):
            converted = self._convert(parsed.value, parsed.unit, row.unit)
            if min_human_value <= abs(converted) <= max_human_value:
                return True
        return False

    def _should_suppress_same_system_for_si(self, parsed: ParsedInput, system_preference: str) -> bool:
        if system_preference != "si" or parsed.unit == "count":
            return False
        if self._row(parsed.unit).system == "si":
            return False
        return self._has_viable_cross_system_bridge(parsed)

    def _filter_system_preference_candidates(self, parsed: ParsedInput, candidates: list[Candidate], system_preference: str) -> list[Candidate]:
        if not self._should_suppress_same_system_for_si(parsed, system_preference):
            return candidates

        suppressed_rule_kinds = {
            "exact_same_unit",
            "exact_same_unit_words",
            "named_fraction_of_upper_unit",
            "near_upper_unit",
            "upper_fraction_with_small_tail",
            "upper_unit_with_small_tail",
            "human_upper_near_integer",
            "composite_bucket_render",
            "composite_bucket_collective_render",
            "same_unit_decade_bucket",
            "same_unit_small_upper_bound",
            "same_unit_small_upper_bound_words",
            "same_unit_decade_range",
            "subunit_render",
            "additive_bucket_render",
        }
        return [candidate for candidate in candidates if candidate.rule_kind not in suppressed_rule_kinds]

    def _generic_cross_system_bridge_render(self, parsed: ParsedInput, level: str, system_preference: str) -> list[Candidate]:
        if parsed.unit == "count":
            return []
        if system_preference == "preserve":
            return []

        source_row = self._row(parsed.unit)
        if source_row.factor_to_si is None:
            return []

        policy = self._bridge_policy(parsed)
        if not policy or bool(policy.get("locked", False)):
            return []

        min_human_value = float(policy.get("min_human_value", 0.25))
        max_human_value = float(policy.get("max_human_value", 500.0))
        render_level = "fine" if level == "normal" else "normal"
        candidate_roughness = "normal" if level == "normal" else "rough"
        results: list[Candidate] = []

        for index, row in enumerate(self._bridge_target_rows(parsed)):
            converted = self._convert(parsed.value, parsed.unit, row.unit)
            if not (min_human_value <= abs(converted) <= max_human_value):
                continue
            quantity = self._render_quantity(converted, row.unit, render_level)
            closeness = abs(math.log10(max(abs(converted), 1e-9)))
            score = 0.81 - min(closeness, 2.5) * 0.05 - index * 0.03 + (0.08 if system_preference == "si" else 0.0)
            results.append(
                Candidate(
                    self._join_parts(self._approximation_word(level), quantity),
                    score,
                    "cross_system_bridge_render",
                    "official",
                    candidate_roughness,
                )
            )
        return results

    def _generic_locked_domain_same_unit(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        policy = self._bridge_policy(parsed)
        if not policy or not bool(policy.get("locked", False)):
            return []

        return [
            Candidate(
                self._join_parts(self._approximation_word(level), self._render_quantity(parsed.value, parsed.unit, level)),
                0.7,
                "locked_domain_same_unit",
                "official",
                "normal" if level == "normal" else "rough",
            )
        ]

    def _nice_upper_bound(self, value: float) -> float | None:
        absolute = abs(value)
        if absolute < 0.1:
            return None
        magnitude = 10 ** math.floor(math.log10(absolute))
        for multiplier in (1, 2, 5, 10):
            candidate = multiplier * magnitude
            if candidate > absolute:
                return candidate
        return 10 * magnitude

    def _generic_small_upper_bound(self, parsed: ParsedInput, level: str, system_preference: str) -> list[Candidate]:
        if parsed.unit == "count" or level == "normal" or system_preference == "si":
            return []

        if parsed.unit != "count":
            if self.language == "ru":
                if self._fraction_of_current(parsed) or self._fraction_of_upper(parsed, level) or self._near_upper_unit(parsed, False, level) or self._upper_with_small_tail(parsed):
                    return []
                if parsed.value >= 1 and self._same_unit_bucket(parsed, level):
                    return []
            upper = self._best_human_upper_renderable(parsed)
            if upper is not None:
                upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
                if 0.2 <= upper_value <= 2.5:
                    return []

        anchor = self._nearest_decimal_anchor_value(parsed.value)
        if anchor is not None and abs(parsed.value - anchor) / anchor <= self._decimal_anchor_threshold(level):
            return []

        upper_bound = self._nice_upper_bound(parsed.value)
        if upper_bound is None or upper_bound == parsed.value or upper_bound > 10 * max(abs(parsed.value), 1.0):
            return []
        if upper_bound > 10 and abs(parsed.value) < 5:
            return []

        quantity = self._render_quantity(upper_bound, parsed.unit, "fine" if upper_bound < 10 else "normal")
        roughness = "rough" if level == "coarse" else "very_rough"
        results = [Candidate(self.runtime_pack.less_than_template.format(unit=quantity), 0.76, "same_unit_small_upper_bound", "official", roughness)]
        if float(upper_bound).is_integer():
            whole = int(upper_bound)
            word_quantity = self._quantity_word_variant(whole, parsed.unit, bound=True)
            if word_quantity:
                results.append(Candidate(self.runtime_pack.less_than_template.format(unit=word_quantity), 0.74, "same_unit_small_upper_bound_words", "official", roughness))
            if self.language == "en":
                results.append(Candidate(f"up to {quantity}", 0.72, "same_unit_small_upper_bound", "official", roughness))
            elif self.language == "ru":
                results.append(Candidate(f"до {quantity}", 0.72, "same_unit_small_upper_bound", "official", roughness))
        return results

    def _generic_fraction_of_upper(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        upper = self._best_human_upper_renderable(parsed)
        if upper is None:
            return []
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        if upper_value < self._minimum_fraction_of_upper_value(level) or upper_value >= 1:
            if not (1 <= upper_value < 3):
                return []
            anchors = [0.25, 1 / 3, 0.5, 0.75]
            roughness = self._roughness_for_level(level)
            results: list[Candidate] = []

            pair_distance = abs(upper_value - 2.0)
            pair_threshold = 0.04 if level == "normal" else 0.08
            pair_phrase = self._pair_unit_phrase(upper.unit)
            if pair_phrase and pair_distance <= pair_threshold:
                results.append(Candidate(pair_phrase, 0.9 - pair_distance, "named_fraction_of_upper_unit", "colloquial", roughness))

            whole = math.floor(upper_value)
            fractional = upper_value - whole
            anchor_value = min(anchors, key=lambda item: abs(fractional - item))
            distance = abs(fractional - anchor_value)
            allow_mixed = not (upper.unit == "decade" and abs(anchor_value - 0.5) > 0.001)
            if allow_mixed and distance <= self._fraction_distance_threshold(level):
                mixed_phrase = self._mixed_fraction_upper_phrase(whole, anchor_value, upper.unit)
                if mixed_phrase:
                    results.append(Candidate(mixed_phrase, 0.88 - distance, "named_fraction_of_upper_unit", "official", roughness))

            render_level = "fine" if level == "normal" else "normal"
            results.append(Candidate(self._join_parts(self._approximation_word(level), self._render_quantity(upper_value, upper.unit, render_level)), 0.72 - min(pair_distance, 0.2), "named_fraction_of_upper_unit", "official", roughness))
            return results
        anchors = [
            (0.25, "fraction.quarter"),
            (0.5, "fraction.half"),
            (0.75, "fraction.three_quarters"),
        ]
        anchor_value, anchor_key = min(anchors, key=lambda item: abs(upper_value - item[0]))
        if abs(upper_value - anchor_value) > self._fraction_distance_threshold(level):
            return []
        fraction_options = self._sample_aliases(anchor_key, self._format_number(anchor_value, 2), limit=2)
        unit_text = self._render_forms(upper.unit)["one"]
        roughness = self._roughness_for_level(level)
        base_score = 0.88 if level == "normal" else 0.86
        results = [
            Candidate(self._compose_named_unit(fraction_text, unit_text, "multiplier_on_unit"), base_score - index * 0.03, "named_fraction_of_upper_unit", "colloquial", roughness)
            for index, fraction_text in enumerate(fraction_options)
        ]
        render_level = "fine" if level == "normal" else "normal"
        for index, approx_word in enumerate(self._sample_approximation_words(level if level != "normal" else "normal", limit=2)):
            results.append(Candidate(self._join_parts(approx_word, self._render_quantity(upper_value, upper.unit, render_level)), 0.72 - index * 0.02, "named_fraction_of_upper_unit", "official", roughness))
        return results

    def _generic_near_upper(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        upper = self._best_human_upper_renderable(parsed)
        if upper is None:
            return []
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        remainder = 1.0 - upper_value
        if not (0 < remainder <= self._near_upper_threshold(level)):
            return []
        roughness = self._roughness_for_level(level)
        unit_text = self._english_indefinite_phrase(self._render_forms(upper.unit)["one"])
        results = [Candidate(self.runtime_pack.nearly_template.format(unit=unit_text), 0.9 - remainder, "near_upper_unit", "colloquial", roughness)]
        render_level = "fine" if level == "normal" else "normal"
        for index, approx_word in enumerate(self._sample_approximation_words(level if level != "normal" else "normal", limit=2)):
            results.append(Candidate(self._join_parts(approx_word, self._render_quantity(upper_value, upper.unit, render_level)), 0.74 - remainder - index * 0.02, "near_upper_unit", "official", roughness))
        return results

    def _generic_upper_with_small_tail(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self._human_preferred_bucket_context(parsed, level) is not None:
            return []
        upper = self._best_human_upper_renderable(parsed)
        if upper is None:
            return []
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        if 0 < upper_value < 1:
            anchors = [
                (0.25, "fraction.quarter"),
                (1 / 3, "fraction.third"),
                (0.5, "fraction.half"),
                (0.75, "fraction.three_quarters"),
            ]
            anchor_value, anchor_key = min(anchors, key=lambda item: abs(upper_value - item[0]))
            distance = abs(upper_value - anchor_value)
            if distance <= min(self._fraction_distance_threshold(level), 0.08):
                fraction_text = self._sample_aliases(anchor_key, self._format_number(anchor_value, 2), limit=1)[0]
                unit_text = self._render_forms(upper.unit)["one"]
                base_phrase = self._compose_named_unit(fraction_text, unit_text, "multiplier_on_unit")
                roughness = self._roughness_for_level(level)
                if upper_value >= anchor_value:
                    return [
                        Candidate(f"{base_phrase} and a bit", 0.9 - distance, "upper_fraction_with_small_tail", "colloquial", roughness),
                        Candidate(f"just over {base_phrase}", 0.84 - distance, "upper_fraction_with_small_tail", "official", roughness),
                    ]
                return [
                    Candidate(self.runtime_pack.nearly_template.format(unit=base_phrase), 0.91 - distance, "upper_fraction_with_small_tail", "colloquial", roughness),
                    Candidate(f"just under {base_phrase}", 0.84 - distance, "upper_fraction_with_small_tail", "official", roughness),
                ]
        whole = math.floor(upper_value)
        frac = upper_value - whole
        if whole < 1 or frac <= 0.05 or frac >= 0.35:
            return []
        roughness = self._roughness_for_level(level)
        return [
            Candidate(self._join_parts(self._approximation_word(level), self._render_quantity(upper_value, upper.unit, level)), 0.82 - frac, "upper_unit_with_small_tail", "official", roughness),
            Candidate(self._join_parts(self.runtime_pack.about_fallback, self._format_number(whole, 0), self._plural_form(whole, upper.unit)), 0.72 - frac, "upper_unit_with_small_tail", "colloquial", roughness),
        ]

    def _generic_composite_bucket_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self._should_suppress_generic_time_same_unit_bucket(parsed):
            return []
        rounded = abs(self._round_to_bucket(parsed.value, level))
        if rounded < 20:
            return []
        roughness = self._roughness_for_level(level)

        bucket_specs = [
            (1000000, "scale_bucket.millions"),
            (1000, "scale_bucket.thousands"),
            (100, "scale_bucket.hundreds"),
            (10, "scale_bucket.tens"),
        ]
        for base, bucket_key in bucket_specs:
            if rounded < base * 1.5 or rounded >= base * 9.5:
                continue
            bucket_text = self._named_alias(bucket_key, self._format_number(base, 0), prefer_last=rounded / base >= 2)
            if parsed.unit == "count":
                phrase = bucket_text
            else:
                phrase = self._compose_named_unit(bucket_text, self._render_forms(parsed.unit)["many"], "bucket_on_unit")
            return [
                Candidate(phrase, 0.79, "composite_bucket_render", "colloquial", roughness),
            ]
        return []

    def _generic_same_unit_bucket(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self._should_suppress_generic_time_same_unit_bucket(parsed):
            return []
        if self._human_upper_near_integer_context(parsed) is not None or self._human_preferred_bucket_context(parsed, level) is not None:
            return []
        rounded = self._estimation_bucket_value(parsed.value, level)
        if rounded == parsed.value or rounded == 0:
            return []
        quantity = self._render_quantity(rounded, parsed.unit, level)
        return [
            Candidate(self._join_parts(self._approximation_word(level), quantity), 0.84 if level == "normal" else 0.7, "same_unit_decade_bucket", "official", self._roughness_for_level(level)),
        ]

    def _generic_same_unit_range(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if parsed.value < 10 or level != "extreme":
            return []
        if parsed.unit != "count":
            upper = self._best_human_upper_renderable(parsed)
            if upper is not None:
                upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
                if 0.25 <= upper_value <= 2.5:
                    return []
        rounded = self._round_to_bucket(parsed.value, level)
        step = self._bucket_step(parsed.value, level)
        low = self._format_number(max(rounded - step, 0), 1)
        high = self._format_number(rounded + step, 1)
        return [
            Candidate(self.runtime_pack.range_template.format(low=low, high=high, unit=self._render_forms(parsed.unit)["many"]), 0.58, "same_unit_decade_range", "colloquial", "very_rough"),
        ]

    def _generic_subunit_render(self, parsed: ParsedInput) -> list[Candidate]:
        if parsed.value >= 1:
            return []
        lower = self._best_human_lower_renderable(parsed)
        if lower is None:
            return []
        lower_value = self._convert(parsed.value, parsed.unit, lower.unit)
        if lower_value <= 0 or lower_value >= 1000:
            return []
        quantity = self._render_quantity(lower_value, lower.unit, "fine")
        results = [Candidate(quantity, 0.84, "subunit_render", "official", "normal")]
        if lower_value < 1:
            results.append(Candidate(self.runtime_pack.less_than_template.format(unit=self._render_forms(lower.unit)["one"]), 0.72, "subunit_render", "colloquial", "rough"))
        return results

    def _generic_count_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if parsed.unit != "count":
            return []
        value = parsed.value
        results: list[Candidate] = []
        roughness = self._roughness_for_level(level)
        noun_many = self._count_noun_forms(parsed)["many"]
        if 900 <= value < 900000:
            quantity = self._format_number(self._round_to_bucket(value / 1000, level), 1)
            thousand_text = self._scale_base_form("scale_base.thousand", max(int(round(value / 1000)), 1))
            results.append(Candidate(self._join_count_scale_noun(self._join_parts(self._approximation_word(level), quantity, thousand_text), noun_many), 0.75, "count_thousand_render", "official", roughness))
        if 900000 <= value < 900000000:
            million_text = self._scale_base_form("scale_base.million", max(int(round(value / 1000000)), 1))
            results.append(Candidate(self._join_count_scale_noun(self._join_parts(self._approximation_word(level), self._format_number(value / 1000000, 1), million_text), noun_many), 0.8, "count_million_render", "official", roughness))
        return results

    def _english_hundred_count_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self.language != "en" or parsed.unit != "count" or not float(parsed.value).is_integer():
            return []

        whole = int(parsed.value)
        if whole < 1100 or whole >= 10000:
            return []

        hundreds = whole // 100
        remainder = whole % 100
        if hundreds < 11:
            return []

        hundreds_text = self._whole_number_words(hundreds) or str(hundreds)
        phrase = f"{hundreds_text} hundred"
        if remainder > 0:
            remainder_text = self._whole_number_words(remainder) or str(remainder)
            phrase = f"{phrase} and {remainder_text}"

        noun_many = self._count_noun_forms(parsed)["many"]
        roughness = self._roughness_for_level(level)
        numeric_phrase = f"{hundreds} hundred" + (f" and {remainder}" if remainder > 0 else "")

        return [
            Candidate(self._join_parts(phrase, noun_many), 0.86 if level == "normal" else 0.68, "count_hundred_plus_tail_render", "colloquial", roughness),
            Candidate(self._join_parts(numeric_phrase, noun_many), 0.80 if level == "normal" else 0.64, "count_hundred_plus_tail_render", "official", roughness),
        ]

    def _oldschool_candidates(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self.language != "ru":
            return []
        results: list[Candidate] = []
        if parsed.family == "length":
            centimeters = self._convert(parsed.value, parsed.unit, "centimeter")
            meters = self._convert(parsed.value, parsed.unit, "meter")
            if 4 <= centimeters <= 20:
                vershok = centimeters / 4.445
                results.append(Candidate(f"примерно {self._format_number(vershok, 1)} вершка", 0.73, "oldschool_length_render", "oldschool", "rough"))
            if meters >= 500:
                versts = meters / 1066.8
                results.append(Candidate(f"около {self._format_number(versts, 1)} версты", 0.75, "oldschool_length_render", "oldschool", "rough"))
        if parsed.family == "mass":
            kilograms = self._convert(parsed.value, parsed.unit, "kilogram")
            if kilograms >= 5:
                poods = kilograms / 16.38
                results.append(Candidate(f"порядка {self._format_number(poods, 1)} пуда", 0.74, "oldschool_mass_render", "oldschool", "very_rough" if level == "extreme" else "rough"))
        return results


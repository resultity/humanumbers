from __future__ import annotations

import math

from .service_types import Candidate, ParsedInput


class ServiceRussianRenderingMixin:
    def _fraction_names(self, anchor: float) -> tuple[str, str | None]:
        anchor_key = round(anchor, 6)
        mapping = {
            0.25: ("четверть", "четвертью"),
            round(1 / 3, 6): ("треть", "третью"),
            0.5: ("половина", "половиной"),
            0.75: ("три четверти", "тремя четвертями"),
            0.1: ("одна десятая", None),
        }
        return mapping[anchor_key]

    def _fraction_alias_form(self, anchor: float, index: int = 0) -> str:
        key_map = {
            0.25: "fraction.quarter",
            round(1 / 3, 6): "fraction.third",
            0.5: "fraction.half",
            0.75: "fraction.three_quarters",
        }
        key = key_map.get(round(anchor, 6))
        if key is None:
            return self._fraction_names(anchor)[0]
        aliases = [item for item in self.assets.named_value_aliases.get(key, []) if isinstance(item, str) and item]
        if 0 <= index < len(aliases):
            return aliases[index]
        return aliases[0] if aliases else self._fraction_names(anchor)[0]

    def _pair_unit_phrase(self, unit: str) -> str | None:
        aliases = [item for item in self.assets.named_value_aliases.get("exact.pair", []) if isinstance(item, str) and item]
        if not aliases:
            return None
        if self.language == "en":
            return f"a couple of {self._fraction_form(unit)}"
        if self.language == "ru":
            pair_text = aliases[1] if len(aliases) > 1 else aliases[0]
            return self._join_parts(pair_text, self._render_forms(unit)["many"])
        pair_text = aliases[1] if len(aliases) > 1 else aliases[0]
        return self._compose_named_unit(pair_text, self._fraction_form(unit), "multiplier_on_unit")

    def _mixed_fraction_upper_phrase(self, whole: int, anchor: float, unit: str) -> str | None:
        if whole < 1:
            return None
        if self.language == "ru":
            return self._ru_mixed_fraction_unit_phrase(whole, anchor, unit)
        if self.language == "en":
            whole_text = self._number_word(whole) or str(whole)
            unit_text = self._fraction_form(unit)
            if anchor == 0.5:
                return f"{whole_text} and a half {unit_text}"
            if anchor == 0.25:
                return f"{whole_text} and a quarter {unit_text}"
            if abs(anchor - (1 / 3)) < 0.001:
                return f"{whole_text} and a third {unit_text}"
            return f"{whole_text} and three quarters {unit_text}"
        return self._render_quantity(whole + anchor, unit, "fine")

    def _ru_mixed_fraction_unit_phrase(self, whole: int, anchor: float, unit: str) -> str:
        forms = self._render_forms(unit)
        if whole == 1:
            if anchor == 0.25:
                return f"{forms['one']} с четвертью"
            if abs(anchor - (1 / 3)) < 0.001:
                return f"{forms['one']} с третью"
            if anchor == 0.5:
                return f"полтора {forms['few']}"
            if anchor == 0.75:
                return f"{forms['one']} с тремя четвертями"
        if anchor == 0.5:
            return f"{whole} с половиной {self._plural_form(whole, unit)}"
        _, instrumental = self._fraction_names(anchor)
        if instrumental:
            return f"{whole} с {instrumental} {self._fraction_form(unit)}"
        return f"{whole} {self._fraction_names(anchor)[0]} {self._fraction_form(unit)}"

    def _ru_word_mixed_fraction_unit_phrase(self, whole: int, anchor: float, unit: str) -> str | None:
        word_whole = self._number_word(whole)
        if not word_whole:
            return None
        forms = self._render_forms(unit)
        if whole == 1:
            if anchor == 0.25:
                return f"{forms['one']} с четвертью"
            if abs(anchor - (1 / 3)) < 0.001:
                return f"{forms['one']} с третью"
            if anchor == 0.5:
                return f"полтора {forms['few']}"
            if anchor == 0.75:
                return f"{forms['one']} с тремя четвертями"
        if anchor == 0.5:
            return f"{word_whole} с половиной {self._plural_form(whole, unit)}"
        _, instrumental = self._fraction_names(anchor)
        if instrumental:
            return f"{word_whole} с {instrumental} {self._fraction_form(unit)}"
        return f"{word_whole} {self._fraction_names(anchor)[0]} {self._fraction_form(unit)}"

    def _ru_exact_same_unit_fraction_variants(self, parsed: ParsedInput) -> list[str]:
        whole = math.floor(parsed.value)
        if whole < 1 or whole >= self.LARGE_COMPOSITE_WHOLE_THRESHOLD:
            return []

        anchors = [0.25, 1 / 3, 0.5, 0.75]
        fractional = parsed.value - whole
        anchor = min(anchors, key=lambda item: abs(fractional - item))
        distance = abs(fractional - anchor)
        if distance > 0.08:
            return []

        variants = [self._ru_mixed_fraction_unit_phrase(whole, anchor, parsed.unit)]
        word_variant = self._ru_word_mixed_fraction_unit_phrase(whole, anchor, parsed.unit)
        if word_variant and word_variant not in variants:
            variants.append(word_variant)
        return variants

    def _fraction_of_current(self, parsed: ParsedInput) -> list[Candidate]:
        value = parsed.value
        anchors = [0.25, 1 / 3, 0.5, 0.75]
        results: list[Candidate] = []

        if 0 < value < 1:
            anchor = min(anchors, key=lambda item: abs(value - item))
            distance = abs(value - anchor)
            if distance <= 0.08:
                fraction_name, _ = self._fraction_names(anchor)
                prefix = "почти " if value < anchor else ("чуть больше " if value > anchor else "")
                results.append(Candidate(f"{prefix}{fraction_name} {self._fraction_form(parsed.unit)}", 0.96 - distance, "named_fraction_of_current_unit", "colloquial", "normal"))
                results.append(Candidate(f"около {self._format_number(value, 2)} {self._fraction_form(parsed.unit)}", 0.72 - distance, "named_fraction_of_current_unit", "neutral", "normal"))
            return results

        fractional = value - math.floor(value)
        anchor = min(anchors, key=lambda item: abs(fractional - item))
        distance = abs(fractional - anchor)
        whole = math.floor(value)
        if whole < 1 or distance > 0.08:
            return results

        if abs(whole) >= self.LARGE_COMPOSITE_WHOLE_THRESHOLD:
            return results

        if self._should_suppress_same_unit_time_fraction(parsed):
            return results

        if anchor == 0.5:
            results.append(Candidate(self._ru_mixed_fraction_unit_phrase(whole, anchor, parsed.unit), 0.94 - distance, "decimal_half_render", "neutral", "normal"))
            word_variant = self._ru_word_mixed_fraction_unit_phrase(whole, anchor, parsed.unit)
            if word_variant:
                results.append(Candidate(f"примерно {word_variant}", 0.82 - distance, "decimal_half_render", "neutral", "normal"))
            results.append(Candidate(f"{self._plural_form(whole, parsed.unit)} {whole} с хвостом", 0.68 - distance, "decimal_half_render", "colloquial", "rough"))
            return results

        results.append(Candidate(self._ru_mixed_fraction_unit_phrase(whole, anchor, parsed.unit), 0.90 - distance, "decimal_fraction_render", "neutral", "normal"))
        results.append(Candidate(f"около {self._format_number(value, 2)} {self._fraction_form(parsed.unit)}", 0.78 - distance, "decimal_fraction_render", "neutral", "normal"))
        return results

    def _fraction_of_upper(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if parsed.family == "time":
            upper = self._best_human_upper_renderable(parsed)
        else:
            upper = self._best_upper_renderable(parsed)
        if upper is None:
            return []
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        if upper_value < self._minimum_fraction_of_upper_value(level) or upper_value >= 3:
            return []
        roughness = self._roughness_for_level(level)
        render_level = "fine" if level == "normal" else "normal"
        anchors = [0.25, 1 / 3, 0.5, 0.75]

        if upper_value >= 1:
            results: list[Candidate] = []
            pair_distance = abs(upper_value - 2.0)
            pair_threshold = 0.04 if level == "normal" else 0.08
            pair_phrase = self._pair_unit_phrase(upper.unit)
            if pair_phrase and pair_distance <= pair_threshold:
                results.append(Candidate(pair_phrase, 0.92 - pair_distance, "named_fraction_of_upper_unit", "colloquial", roughness))

            whole = math.floor(upper_value)
            fractional = upper_value - whole
            anchor = min(anchors, key=lambda item: abs(fractional - item))
            distance = abs(fractional - anchor)
            allow_mixed = not (upper.unit == "decade" and abs(anchor - 0.5) > 0.001)
            if allow_mixed and distance <= self._fraction_distance_threshold(level):
                mixed_phrase = self._mixed_fraction_upper_phrase(whole, anchor, upper.unit)
                if mixed_phrase:
                    results.append(Candidate(mixed_phrase, 0.9 - distance, "named_fraction_of_upper_unit", "neutral", roughness))

            results.append(Candidate(f"{self._approximation_word(level)} {self._render_quantity(upper_value, upper.unit, render_level)}", 0.76 - min(pair_distance, 0.2), "named_fraction_of_upper_unit", "neutral", roughness))
            if results:
                return results

        anchor = min(anchors, key=lambda item: abs(upper_value - item))
        distance = abs(upper_value - anchor)
        if distance > (0.14 if level == "normal" else 0.18):
            return []
        fraction_name, instrumental = self._fraction_names(anchor)
        approx = "почти " if upper_value < anchor else "чуть больше "
        results: list[Candidate] = []
        if anchor == 0.5:
            results.append(Candidate(self._ru_mixed_fraction_unit_phrase(max(math.floor(upper_value), 1), anchor, upper.unit) if upper_value >= 1 else f"половина {self._fraction_form(upper.unit)}", 0.9 - distance, "named_fraction_of_upper_unit", "colloquial", roughness))
        elif upper_value < 1:
            fraction_surface = fraction_name if upper_value < anchor else self._fraction_alias_form(anchor, 1)
            results.append(Candidate(f"{approx}{fraction_surface} {self._fraction_form(upper.unit)}", 0.92 - distance, "named_fraction_of_upper_unit", "colloquial", roughness))
        elif instrumental:
            results.append(Candidate(self._ru_mixed_fraction_unit_phrase(math.floor(upper_value), anchor, upper.unit), 0.88 - distance, "named_fraction_of_upper_unit", "neutral", roughness))
        results.append(Candidate(f"{self._approximation_word(level)} {self._render_quantity(upper_value, upper.unit, render_level)}", 0.76 - distance, "named_fraction_of_upper_unit", "neutral", roughness))
        results.append(Candidate(f"где-то {self._render_quantity(parsed.value, parsed.unit, 'normal')}", 0.62 - distance, "named_fraction_of_upper_unit", "colloquial", roughness))
        return results

    def _upper_share_band_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        upper = self._best_upper_renderable(parsed)
        if upper is None:
            return []

        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        if upper_value <= 0 or upper_value >= 1:
            return []

        unit_form = self._fraction_form(upper.unit)
        roughness = self._roughness_for_level(level)
        results: list[Candidate] = []

        third_distance = abs(upper_value - (1 / 3))
        if third_distance <= (0.11 if level == "normal" else 0.14):
            results.append(Candidate(f"примерно треть {unit_form}", 0.90 - third_distance, "upper_share_band_render", "official", roughness))
            results.append(Candidate(f"около трети {unit_form}", 0.86 - third_distance, "upper_share_band_render", "official", roughness))
            if upper_value >= (1 / 3):
                results.append(Candidate(f"треть с хвостиком {unit_form}", 0.80 - third_distance, "upper_share_band_render", "colloquial", roughness))

        if 0.2 <= upper_value < 0.5:
            half_gap = 0.5 - upper_value
            results.append(Candidate(f"меньше половины {unit_form}", 0.94 - half_gap, "upper_share_band_render", "official", roughness))
            results.append(Candidate(f"не дотягивает до половины {unit_form}", 0.88 - half_gap, "upper_share_band_render", "colloquial", roughness))
            if upper_value >= 0.38:
                results.append(Candidate(f"под половину {unit_form}", 0.84 - half_gap, "upper_share_band_render", "colloquial", roughness))

        return results

    def _near_upper_unit(self, parsed: ParsedInput, allow_profane: bool, level: str) -> list[Candidate]:
        if self.language == "ru" and parsed.family == "time":
            upper = self._best_human_upper_renderable(parsed)
        else:
            upper = self._best_upper_renderable(parsed)
        if upper is None:
            return []
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        remainder = 1.0 - upper_value
        threshold = self._near_upper_threshold(level)
        if self.language == "ru" and parsed.family == "time" and upper.system == "calendar":
            threshold = max(threshold, 0.35)
        if not (0 < remainder <= threshold):
            return []
        label = self._render_forms(upper.unit)["one"]
        roughness = self._roughness_for_level(level)
        templated = self._sample_formatted_group_words("near_upper_templates", limit=4, label=label)
        results = [
            Candidate(text, 0.95 - remainder - index * 0.05, "near_upper_unit", "colloquial" if index != 1 else "neutral", roughness)
            for index, text in enumerate(templated)
        ] or [
            Candidate(f"почти {label}", 0.95 - remainder, "near_upper_unit", "colloquial", roughness),
            Candidate(f"без малого {label}", 0.90 - remainder, "near_upper_unit", "neutral", roughness),
            Candidate(f"под {label} уже", 0.82 - remainder, "near_upper_unit", "colloquial", roughness),
        ]
        if allow_profane:
            profane = self._sample_formatted_group_words("near_upper_profane_templates", limit=2, label=label)
            results.extend(
                Candidate(text, 0.78 - remainder - index * 0.04, "near_upper_unit", "profane", "very_rough")
                for index, text in enumerate(profane or [f"почти {label}, бля"])
            )
        return results

    def _upper_with_small_tail(self, parsed: ParsedInput) -> list[Candidate]:
        if self._human_preferred_bucket_context(parsed, "normal") is not None or self._human_preferred_bucket_context(parsed, "coarse") is not None:
            return []
        upper = self._best_upper_renderable(parsed)
        if upper is None:
            return []
        if upper.unit == "decade":
            return []
        upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
        if 0 < upper_value < 1:
            anchors = [0.25, 1 / 3, 0.5, 0.75]
            anchor = min(anchors, key=lambda item: abs(upper_value - item))
            distance = abs(upper_value - anchor)
            if distance <= 0.08:
                fraction_name, _ = self._fraction_names(anchor)
                base_phrase = f"{fraction_name} {self._fraction_form(upper.unit)}"
                above_phrase = f"{self._fraction_alias_form(anchor, 1)} {self._fraction_form(upper.unit)}"
                if upper_value >= anchor:
                    return [
                        Candidate(f"{base_phrase} с небольшим", 0.92 - distance, "upper_fraction_with_small_tail", "colloquial", "normal"),
                        Candidate(f"{base_phrase} с хвостиком", 0.86 - distance, "upper_fraction_with_small_tail", "colloquial", "rough"),
                        Candidate(f"чуть больше {above_phrase}", 0.82 - distance, "upper_fraction_with_small_tail", "neutral", "normal"),
                    ]
                return [
                    Candidate(f"почти {base_phrase}", 0.93 - distance, "upper_fraction_with_small_tail", "colloquial", "normal"),
                    Candidate(f"без малого {base_phrase}", 0.88 - distance, "upper_fraction_with_small_tail", "neutral", "rough"),
                ]
        whole = math.floor(upper_value)
        frac = upper_value - whole
        if whole < 1 or frac <= 0.05 or frac >= 0.35:
            return []
        rounded = self._format_number(upper_value, 2)
        results = [
            Candidate(f"{whole} с небольшим {self._plural_form(whole, upper.unit)}", 0.89 - frac, "upper_unit_with_small_tail", "colloquial", "normal"),
            Candidate(f"около {rounded} {self._fraction_form(upper.unit)}", 0.78 - frac, "upper_unit_with_small_tail", "neutral", "normal"),
            Candidate(f"{self._plural_form(whole, upper.unit)} {whole} с хвостом", 0.74 - frac, "upper_unit_with_small_tail", "colloquial", "rough"),
        ]
        quarter_distance = abs(frac - 0.25)
        if quarter_distance <= 0.08:
            results.insert(0, Candidate(f"{whole} с четвертью {self._fraction_form(upper.unit)}", 0.93 - quarter_distance, "upper_unit_with_small_tail", "neutral", "normal"))
        return results

    def _same_unit_bucket(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self._should_suppress_ru_time_bucket_for_soft_upper(parsed, level):
            return []
        if self._human_upper_near_integer_context(parsed) is not None or self._human_preferred_bucket_context(parsed, level) is not None:
            return []
        rounded = self._estimation_bucket_value(parsed.value, level)
        if rounded == parsed.value or rounded == 0:
            return []
        text_value = self._format_number(rounded, 1)
        unit_form = self._count_fraction_form(parsed) if parsed.unit == "count" and not float(rounded).is_integer() else self._count_form(parsed, int(abs(rounded) or 1))
        if parsed.unit != "count":
            unit_form = self._fraction_form(parsed.unit) if not float(rounded).is_integer() else self._plural_form(int(abs(rounded) or 1), parsed.unit)
            if self.language == "ru" and float(rounded).is_integer() and int(abs(rounded)) == 1:
                unit_form = self._render_forms(parsed.unit)["few"]
        roughness = self._roughness_for_level(level)
        return [
            Candidate(self._join_parts("около", text_value, unit_form), 0.84 if level == "normal" else 0.72, "same_unit_decade_bucket", "neutral", roughness),
            Candidate(self._join_parts("порядка", text_value, unit_form), 0.8 if level == "normal" else 0.68, "same_unit_decade_bucket", "neutral", roughness),
            Candidate(self._join_parts("где-то", text_value, unit_form), 0.74 if level == "normal" else 0.64, "same_unit_decade_bucket", "colloquial", roughness),
        ]

    def _composite_bucket_render(self, parsed: ParsedInput, level: str) -> list[Candidate]:
        if self._should_suppress_ru_time_bucket_for_soft_upper(parsed, level):
            return []
        rounded = abs(self._round_to_bucket(parsed.value, level))
        if rounded < 20:
            return []
        roughness = self._roughness_for_level(level)

        scale_bases = {
            1000: "scale_base.thousand",
            10000: "scale_base.ten_thousand",
            1000000: "scale_base.million",
            1000000000: "scale_base.billion",
        }
        if float(rounded).is_integer() and int(rounded) in scale_bases:
            base_text = self._named_alias(scale_bases[int(rounded)], str(int(rounded)))
            noun_many = self._count_noun_forms(parsed)["many"] if parsed.unit == "count" else self._render_forms(parsed.unit)["many"]
            return [
                Candidate(
                    self._join_parts(base_text, noun_many),
                    0.73,
                    "composite_scale_base_render",
                    "neutral",
                    roughness,
                )
            ]

        bucket_specs = [
            (1000000, "scale_bucket.millions"),
            (1000, "scale_bucket.thousands"),
            (100, "scale_bucket.hundreds"),
            (10, "scale_bucket.tens"),
        ]

        for base, bucket_key in bucket_specs:
            if rounded < base * 1.5 or rounded >= base * 9.5:
                continue

            multiplier = rounded / base
            bucket_text = self._named_alias(bucket_key, bucket_key, prefer_last=multiplier >= 1.5)
            unit_form = self._count_noun_forms(parsed)["many"] if parsed.unit == "count" else self._render_forms(parsed.unit)["many"]

            if 1.5 <= multiplier < 2.5:
                pair_text = self._named_alias("exact.pair", "пара")
                return [
                    Candidate(self._join_parts(pair_text, bucket_text, unit_form), 0.77, "composite_bucket_collective_render", "colloquial", roughness),
                    Candidate(self._join_parts("примерно", pair_text, bucket_text, unit_form), 0.71, "composite_bucket_collective_render", "neutral", roughness),
                ]

            if 2.5 <= multiplier < 3.5:
                pair_text = self._named_alias("exact.pair", "пара")
                triple_text = self._named_alias("exact.triple", "тройка")
                return [
                    Candidate(self._join_parts(f"{pair_text}-{triple_text}", bucket_text, unit_form), 0.78, "composite_bucket_collective_render", "colloquial", roughness),
                    Candidate(self._join_parts("примерно", f"{pair_text}-{triple_text}", bucket_text, unit_form), 0.72, "composite_bucket_collective_render", "neutral", roughness),
                ]

            return [
                Candidate(self._join_parts("несколько", bucket_text, unit_form), 0.69, "composite_bucket_render", "colloquial", roughness),
                Candidate(self._join_parts(bucket_text, unit_form), 0.63, "composite_bucket_render", "colloquial", roughness),
            ]

        return []

    def _same_unit_range(self, parsed: ParsedInput, allow_profane: bool, level: str) -> list[Candidate]:
        if parsed.value < 10 or level != "extreme":
            return []
        if parsed.unit != "count":
            upper = self._best_upper_renderable(parsed)
            if upper is not None:
                upper_value = self._convert(parsed.value, parsed.unit, upper.unit)
                if 0.25 <= upper_value <= 2.5:
                    return []
        rounded = self._round_to_bucket(parsed.value, level)
        step = self._bucket_step(parsed.value, level)
        low = self._format_number(max(rounded - step, 0), 1)
        high = self._format_number(rounded + step, 1)
        unit_form = self._count_noun_forms(parsed)["many"] if parsed.unit == "count" else self._render_forms(parsed.unit)["many"]
        templated = self._sample_formatted_group_words("same_unit_range_templates", limit=4, low=low, high=high, unit_form=unit_form)
        results = [
            Candidate(text, 0.56 - index * 0.04, "same_unit_decade_range", "neutral" if index == 0 else "colloquial", "rough" if index == 0 else "very_rough")
            for index, text in enumerate(templated)
        ] or [
            Candidate(f"в пределах {low}-{high} {unit_form}", 0.56, "same_unit_decade_range", "neutral", "rough"),
            Candidate(f"что-то типа {low}-{high} {unit_form}", 0.52, "same_unit_decade_range", "colloquial", "very_rough"),
        ]
        if allow_profane:
            profane = self._sample_formatted_group_words("same_unit_range_profane_templates", limit=2, low=low, high=high, unit_form=unit_form)
            results.extend(
                Candidate(text, 0.48 - index * 0.03, "same_unit_decade_range", "profane", "very_rough")
                for index, text in enumerate(profane or [f"дохрена, но где-то {low}-{high} {unit_form}"])
            )
        return results

    def _coarse_calendar(self, parsed: ParsedInput) -> list[Candidate]:
        if parsed.unit != "day":
            return []
        if 28 <= parsed.value <= 31:
            templates = self._sample_group_words("coarse_calendar_month_templates", limit=4)
            if templates:
                return [
                    Candidate(text, 0.93 - index * 0.05, "coarse_calendar_fold", "neutral" if index < 2 else "colloquial", "normal" if index < 2 else "rough")
                    for index, text in enumerate(templates)
                ]
            return [
                Candidate("примерно месяц", 0.93, "coarse_calendar_fold", "neutral", "normal"),
                Candidate("около месяца", 0.88, "coarse_calendar_fold", "neutral", "normal"),
                Candidate("почти целый месяц", 0.80, "coarse_calendar_fold", "colloquial", "rough"),
            ]
        return []

    def _subunit_render(self, parsed: ParsedInput) -> list[Candidate]:
        if parsed.value >= 1:
            return []
        lower = self._best_lower_renderable(parsed)
        if lower is None:
            return []
        lower_value = self._convert(parsed.value, parsed.unit, lower.unit)
        if lower_value <= 0 or lower_value >= 1000:
            return []
        number_text = self._format_number(lower_value, 2)
        if float(lower_value).is_integer():
            unit_form = self._plural_form(int(lower_value), lower.unit)
        else:
            unit_form = self._fraction_form(lower.unit)
        results = [Candidate(f"{number_text} {unit_form}", 0.86, "subunit_render", "neutral", "normal")]
        if lower_value < 1:
            results.append(Candidate(f"меньше {self._fraction_form(lower.unit)}", 0.74, "subunit_render", "colloquial", "rough"))
        return results

    def _tiny_percentage(self, parsed: ParsedInput) -> list[Candidate]:
        if parsed.unit != "percent" or parsed.value >= 1:
            return []
        rounded = round(parsed.value, 1)
        templates = self._sample_formatted_group_words("tiny_percentage_templates", limit=4, rounded=self._format_number(rounded, 1))
        if templates:
            return [
                Candidate(text, 0.90 - index * 0.07, "tiny_fractional_percentage", "neutral" if index == 0 else "colloquial", "normal" if index == 0 else "rough")
                for index, text in enumerate(templates)
            ]
        return [
            Candidate(f"около {self._format_number(rounded, 1)} процента", 0.90, "tiny_fractional_percentage", "neutral", "normal"),
            Candidate("десятые доли процента", 0.76, "tiny_fractional_percentage", "colloquial", "rough"),
            Candidate("совсем крошечный процент", 0.70, "tiny_fractional_percentage", "colloquial", "rough"),
        ]

    def _count_render(self, parsed: ParsedInput, allow_profane: bool) -> list[Candidate]:
        if parsed.unit != "count":
            return []
        value = parsed.value
        results: list[Candidate] = []
        noun_many = self._count_noun_forms(parsed)["many"]
        if 900 <= value < 2000:
            thousands = value / 1000
            thousand_templates = self._sample_formatted_group_words("count_thousand_templates", limit=4, thousands=self._format_number(thousands, 1))
            if thousand_templates:
                results.extend(
                    Candidate(self._join_count_scale_noun(text, noun_many), 0.93 - index * 0.06, "count_thousand_render", "neutral" if index in (0, 2) else "colloquial", "normal" if index < 2 else "rough")
                    for index, text in enumerate(thousand_templates)
                )
            else:
                results.extend(
                    [
                        Candidate(self._join_count_scale_noun(f"около {self._format_number(thousands, 1)} тысячи", noun_many), 0.93, "count_thousand_render", "neutral", "normal"),
                        Candidate(self._join_count_scale_noun("тысяча с хвостиком", noun_many), 0.86, "count_thousand_render", "colloquial", "normal"),
                        Candidate(self._join_count_scale_noun("больше тысячи", noun_many), 0.80, "count_thousand_render", "neutral", "rough"),
                    ]
                )
            if allow_profane:
                profane = self._sample_group_words("count_thousand_profane_templates", limit=2)
                results.extend(Candidate(self._join_count_scale_noun(text, noun_many), 0.70 - index * 0.04, "count_thousand_render", "profane", "very_rough") for index, text in enumerate(profane or ["ну, тысяча с хером"]))
        if 900000 <= value < 1200000:
            millions = value / 1000000
            million_templates = self._sample_formatted_group_words("count_million_templates", limit=4, millions=self._format_number(millions, 2))
            if million_templates:
                results.extend(
                    Candidate(self._join_count_scale_noun(text, noun_many), 0.95 - index * 0.07, "count_million_render", "colloquial" if index == 0 else "neutral", "rough" if index < 2 else "normal")
                    for index, text in enumerate(million_templates)
                )
            else:
                results.extend(
                    [
                        Candidate(self._join_count_scale_noun("почти миллион", noun_many), 0.95, "count_million_render", "colloquial", "rough"),
                        Candidate(self._join_count_scale_noun("без малого миллион", noun_many), 0.90, "count_million_render", "neutral", "rough"),
                        Candidate(self._join_count_scale_noun(f"около {self._format_number(millions, 2)} миллиона", noun_many), 0.74, "count_million_render", "neutral", "normal"),
                    ]
                )
            if allow_profane:
                profane = self._sample_group_words("count_million_profane_templates", limit=2)
                results.extend(Candidate(self._join_count_scale_noun(text, noun_many), 0.68 - index * 0.04, "count_million_render", "profane", "very_rough") for index, text in enumerate(profane or ["считай миллион, бля"]))
        return results

    def _fallback_candidate(self, parsed: ParsedInput, level: str) -> Candidate:
        rounded = self._round_to_bucket(parsed.value, level)
        return Candidate(self._join_parts(self._approximation_word(level), self._render_parsed_quantity(parsed, rounded, level)), 0.4, "fallback_numeric_round", "official", "normal")

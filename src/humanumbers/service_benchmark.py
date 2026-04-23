from __future__ import annotations

from .service_constants import API_TO_INTERNAL_STYLE, BENCHMARK_NUMBER_WORDS, BENCHMARK_SCALE_BANDS
from .service_types import Candidate, HumanizeError, ParsedInput


class ServiceBenchmarkMixin:
    def _generate_benchmark_candidates(self, parsed: ParsedInput, benchmark: ParsedInput, request: HumanizeRequest) -> list[Candidate]:
        source_value = self._convert(parsed.value, parsed.unit, benchmark.unit) if parsed.unit != benchmark.unit else parsed.value
        benchmark_value = benchmark.value
        if benchmark_value == 0:
            raise HumanizeError("Benchmark value must be non-zero.")

        ratio = source_value / benchmark_value
        registers = self._requested_benchmark_registers(request)
        reference_label = request.benchmark.label if request.benchmark else None
        return self._benchmark_scale_candidates(ratio, registers, benchmark, reference_label)

    def _fallback_benchmark_candidate(self, parsed: ParsedInput, benchmark: ParsedInput, level: str) -> Candidate:
        source_value = self._convert(parsed.value, parsed.unit, benchmark.unit) if parsed.unit != benchmark.unit else parsed.value
        ratio = source_value / benchmark.value
        return self._benchmark_scale_candidates(ratio, ["official"], benchmark)[0]

    def _requested_benchmark_registers(self, request: HumanizeRequest) -> list[str]:
        requested = request.benchmark_registers or request.styles or ["official", "colloquial"]
        registers: list[str] = []
        for register in requested:
            normalized = "rough" if register == "oldschool" else register
            if normalized not in {"official", "colloquial", "rough", "profane"}:
                continue
            if normalized == "profane" and not request.allow_profane and request.benchmark_registers is None and request.styles is None:
                continue
            if normalized not in registers:
                registers.append(normalized)
        if not registers:
            registers = ["official", "colloquial"]
        if request.allow_profane and "profane" not in registers:
            registers.append("profane")
        return registers

    def _allowed_styles_and_approximation(self, request: HumanizeRequest) -> tuple[set[str], set[str]]:
        requested_styles = request.styles or ["official", "colloquial"]
        requested_base_styles = [style for style in requested_styles if style in {"official", "colloquial"}]
        if not requested_base_styles:
            requested_base_styles = ["official", "colloquial"]
        allowed_styles: set[str] = set()
        for style in requested_base_styles + [style for style in requested_styles if style not in {"official", "colloquial"}]:
            internal = API_TO_INTERNAL_STYLE.get(style, style)
            allowed_styles.add(internal)
            if style == "official":
                allowed_styles.add("neutral")
        if request.allow_profane:
            allowed_styles.add("profane")
        approximation = self._request_approximation(request)
        if approximation == "rough":
            return allowed_styles, {"normal", "rough", "very_rough"}
        return allowed_styles, {approximation}

    def _benchmark_scale_band(self, ratio: float) -> dict[str, object]:
        absolute_ratio = abs(ratio)
        for band in BENCHMARK_SCALE_BANDS:
            if band["min"] <= absolute_ratio < band["max"]:
                return band
        return BENCHMARK_SCALE_BANDS[-1]

    def _benchmark_scale_candidates(
        self,
        ratio: float,
        registers: list[str] | None = None,
        benchmark: ParsedInput | None = None,
        reference_label: str | None = None,
    ) -> list[Candidate]:
        band = self._benchmark_scale_band(ratio)
        index = BENCHMARK_SCALE_BANDS.index(band)
        score = float(band["score"])
        requested_registers = registers or ["official"]
        results: list[Candidate] = []
        style_penalty = {"official": 0.0, "colloquial": 0.02, "rough": 0.05, "profane": 0.08}
        roughness_map = {"official": "normal", "colloquial": "normal", "rough": "rough", "profane": "rough"}
        for register in requested_registers:
            results.extend(
                self._benchmark_anchor_candidates(
                    ratio,
                    register,
                    style_penalty.get(register, 0.0),
                    roughness_map.get(register, "normal"),
                    benchmark,
                    reference_label,
                )
            )
            descriptors = self._benchmark_band_words(index, register, ratio)
            for variant_index, descriptor in enumerate(descriptors[:12]):
                results.append(
                    Candidate(
                        descriptor,
                        max(score - style_penalty.get(register, 0.0) - variant_index * 0.03, 0.1),
                        "benchmark_scale_compare",
                        register,
                        roughness_map.get(register, "normal"),
                    )
                )
        return results

    def _benchmark_base_band_words(self, index: int) -> list[str]:
        if 0 <= index < len(self.assets.benchmark_bands) and self.assets.benchmark_bands[index]:
            return list(self.assets.benchmark_bands[index])
        legacy = getattr(self.runtime_pack, "band_descriptors", ())
        if 0 <= index < len(legacy):
            return [legacy[index]]
        return [self.runtime_pack.about_fallback]

    def _benchmark_band_words(self, index: int, register: str, ratio: float) -> list[str]:
        if register == "profane":
            profane_words = self._benchmark_profane_band_words(index, ratio)
            if profane_words:
                return profane_words

        base_words = self._benchmark_base_band_words(index)
        return self._benchmark_descriptor_variants(base_words, register)

    def _benchmark_phrase_word_count(self, text: str) -> int:
        return len([token for token in text.split() if token])

    def _benchmark_max_phrase_word_count(self) -> int:
        return 5

    def _benchmark_descriptor_variants(self, base_words: list[str], register: str) -> list[str]:
        deduped: list[str] = []
        modifiers = list(self.assets.benchmark_register_modifiers.get(register, ())) if register != "official" else []
        for word in base_words:
            for modifier in modifiers:
                candidate = f"{modifier} {word}".strip()
                if candidate and self._benchmark_phrase_word_count(candidate) <= self._benchmark_max_phrase_word_count() and candidate not in deduped:
                    deduped.append(candidate)
            if self._benchmark_phrase_word_count(word) == 1:
                for left_index, left_modifier in enumerate(modifiers):
                    for right_modifier in modifiers[left_index + 1 :]:
                        candidate = f"{left_modifier} {right_modifier} {word}".strip()
                        if candidate and self._benchmark_phrase_word_count(candidate) <= self._benchmark_max_phrase_word_count() and candidate not in deduped:
                            deduped.append(candidate)
            if word and word not in deduped:
                deduped.append(word)
        return deduped

    def _benchmark_anchor_candidates(
        self,
        ratio: float,
        register: str,
        style_penalty: float,
        roughness: str,
        benchmark: ParsedInput | None = None,
        reference_label: str | None = None,
    ) -> list[Candidate]:
        anchors = self._benchmark_anchor_descriptors(ratio, benchmark, reference_label)
        if not anchors:
            return []

        results: list[Candidate] = []
        for score, descriptors in anchors:
            variants = self._benchmark_descriptor_variants(descriptors, register)
            for variant_index, descriptor in enumerate(variants[:12]):
                results.append(
                    Candidate(
                        descriptor,
                        max(score - style_penalty - variant_index * 0.02, 0.1),
                        "benchmark_scale_compare",
                        register,
                        roughness,
                    )
                )
        return results

    def _benchmark_anchor_descriptors(
        self,
        ratio: float,
        benchmark: ParsedInput | None = None,
        reference_label: str | None = None,
    ) -> list[tuple[float, list[str]]]:
        if ratio <= 0:
            return []

        absolute_ratio = abs(ratio)
        matches: list[tuple[float, list[str]]] = []

        fraction_anchors: list[float] = [0.1, 0.2, 0.25, 1 / 3, 0.4, 0.5, 2 / 3, 0.75, 0.8, 0.9, 1.0]
        for anchor in fraction_anchors:
            distance = abs(absolute_ratio - anchor) / max(anchor, 1e-9)
            if distance > self._benchmark_anchor_threshold(anchor):
                continue
            score = 1.03 - min(distance, 1.0) * 0.55
            matches.append((score, self._benchmark_fraction_anchor_phrases(anchor, benchmark, reference_label)))

        multiplier_anchors: list[float] = [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0]
        if ratio > 1.2:
            for anchor in multiplier_anchors:
                distance = abs(ratio - anchor) / anchor
                if distance > self._benchmark_anchor_threshold(anchor):
                    continue
                score = 1.04 - min(distance, 1.0) * 0.4
                matches.append((score, self._benchmark_multiplier_anchor_phrases(anchor, "more")))
        elif ratio < 0.22:
            inverse_ratio = 1 / ratio
            for anchor in multiplier_anchors:
                distance = abs(inverse_ratio - anchor) / anchor
                if distance > self._benchmark_anchor_threshold(anchor):
                    continue
                score = 1.01 - min(distance, 1.0) * 0.38
                matches.append((score, self._benchmark_multiplier_anchor_phrases(anchor, "less")))
        return sorted(matches, key=lambda item: item[0], reverse=True)

    def _benchmark_anchor_threshold(self, anchor: float) -> float:
        if anchor < 0.2:
            return 0.2
        if anchor < 1:
            return 0.1
        if anchor < 3:
            return 0.12
        return 0.18

    def _benchmark_fraction_anchor_phrases(
        self,
        anchor: float,
        benchmark: ParsedInput | None = None,
        reference_label: str | None = None,
    ) -> list[str]:
        rounded = round(anchor, 6)
        maps: dict[str, dict[float, list[str]]] = {
            "ru": {
                0.1: ["около десятой", "примерно десятая часть", "что-то вроде десятой"],
                0.2: ["около пятой части", "примерно пятая часть", "что-то вроде пятой"],
                0.25: ["около четверти", "примерно четверть", "почти четверть"],
                round(1 / 3, 6): ["около трети", "примерно треть", "почти треть"],
                0.4: ["около двух пятых", "примерно две пятых", "что-то вроде двух пятых"],
                0.5: ["около половины", "примерно половина", "почти половина"],
                round(2 / 3, 6): ["около двух третей", "примерно две трети", "почти две трети"],
                0.75: ["около трех четвертей", "примерно три четверти", "почти три четверти"],
                0.8: ["около четырех пятых", "примерно четыре пятых", "почти целиком"],
                0.9: ["почти столько же", "почти равно", "почти целиком"],
                1.0: ["примерно столько же", "почти один в один", "один к одному"],
            },
            "en": {
                0.1: ["one tenth", "about a tenth", "roughly a tenth"],
                0.2: ["one fifth", "about a fifth", "roughly a fifth"],
                0.25: ["a quarter", "about a quarter", "roughly a quarter"],
                round(1 / 3, 6): ["a third", "about a third", "roughly a third"],
                0.4: ["two fifths", "about two fifths", "roughly two fifths"],
                0.5: ["half", "about half", "roughly half"],
                round(2 / 3, 6): ["two thirds", "about two thirds", "roughly two thirds"],
                0.75: ["three quarters", "about three quarters", "roughly three quarters"],
                0.8: ["four fifths", "about four fifths", "almost all of it"],
                0.9: ["almost as much", "nearly as much", "almost level"],
                1.0: ["about the same", "almost the same", "one to one"],
            },
            "es": {
                0.1: ["una décima parte", "como una décima", "más o menos una décima"],
                0.2: ["una quinta parte", "como una quinta", "más o menos una quinta"],
                0.25: ["un cuarto", "cerca de un cuarto", "más o menos un cuarto"],
                round(1 / 3, 6): ["un tercio", "cerca de un tercio", "más o menos un tercio"],
                0.4: ["dos quintos", "cerca de dos quintos", "más o menos dos quintos"],
                0.5: ["la mitad", "casi la mitad", "más o menos la mitad"],
                round(2 / 3, 6): ["dos tercios", "cerca de dos tercios", "más o menos dos tercios"],
                0.75: ["tres cuartos", "cerca de tres cuartos", "más o menos tres cuartos"],
                0.8: ["cuatro quintos", "cerca de cuatro quintos", "casi todo"],
                0.9: ["casi lo mismo", "casi igual", "prácticamente igual"],
                1.0: ["más o menos igual", "casi igual", "uno a uno"],
            },
            "fr": {
                0.1: ["un dixième", "à peu près un dixième", "autour d'un dixième"],
                0.2: ["un cinquième", "à peu près un cinquième", "autour d'un cinquième"],
                0.25: ["un quart", "à peu près un quart", "autour d'un quart"],
                round(1 / 3, 6): ["un tiers", "à peu près un tiers", "autour d'un tiers"],
                0.4: ["deux cinquièmes", "à peu près deux cinquièmes", "autour de deux cinquièmes"],
                0.5: ["la moitié", "à peu près la moitié", "autour de la moitié"],
                round(2 / 3, 6): ["deux tiers", "à peu près deux tiers", "autour de deux tiers"],
                0.75: ["trois quarts", "à peu près trois quarts", "autour de trois quarts"],
                0.8: ["quatre cinquièmes", "à peu près quatre cinquièmes", "presque tout"],
                0.9: ["presque autant", "presque pareil", "quasiment pareil"],
                1.0: ["à peu près pareil", "presque pareil", "un pour un"],
            },
            "pt": {
                0.1: ["um décimo", "cerca de um décimo", "mais ou menos um décimo"],
                0.2: ["um quinto", "cerca de um quinto", "mais ou menos um quinto"],
                0.25: ["um quarto", "cerca de um quarto", "mais ou menos um quarto"],
                round(1 / 3, 6): ["um terço", "cerca de um terço", "mais ou menos um terço"],
                0.4: ["dois quintos", "cerca de dois quintos", "mais ou menos dois quintos"],
                0.5: ["metade", "cerca da metade", "mais ou menos metade"],
                round(2 / 3, 6): ["dois terços", "cerca de dois terços", "mais ou menos dois terços"],
                0.75: ["três quartos", "cerca de três quartos", "mais ou menos três quartos"],
                0.8: ["quatro quintos", "cerca de quatro quintos", "quase tudo"],
                0.9: ["quase o mesmo", "quase igual", "praticamente igual"],
                1.0: ["mais ou menos igual", "quase igual", "um para um"],
            },
            "zh": {
                0.1: ["十分之一", "约十分之一", "差不多十分之一"],
                0.2: ["五分之一", "约五分之一", "差不多五分之一"],
                0.25: ["四分之一", "约四分之一", "差不多四分之一"],
                round(1 / 3, 6): ["三分之一", "约三分之一", "差不多三分之一"],
                0.4: ["五分之二", "约五分之二", "差不多五分之二"],
                0.5: ["一半", "约一半", "差不多一半"],
                round(2 / 3, 6): ["三分之二", "约三分之二", "差不多三分之二"],
                0.75: ["四分之三", "约四分之三", "差不多四分之三"],
                0.8: ["五分之四", "约五分之四", "几乎全都"],
                0.9: ["几乎一样多", "差不多一样多", "几乎持平"],
                1.0: ["差不多一样", "基本一样", "几乎一比一"],
            },
            "ar": {
                0.1: ["عشر", "حوالي العشر", "قرابة العشر"],
                0.2: ["خمس", "حوالي الخمس", "قرابة الخمس"],
                0.25: ["ربع", "حوالي الربع", "قرابة الربع"],
                round(1 / 3, 6): ["ثلث", "حوالي الثلث", "قرابة الثلث"],
                0.4: ["خمسان", "حوالي الخمسين", "قرابة الخمسين"],
                0.5: ["نصف", "حوالي النصف", "قرابة النصف"],
                round(2 / 3, 6): ["ثلثان", "حوالي الثلثين", "قرابة الثلثين"],
                0.75: ["ثلاثة أرباع", "حوالي ثلاثة أرباع", "قرابة ثلاثة أرباع"],
                0.8: ["أربعة أخماس", "حوالي أربعة أخماس", "يكاد يكون كله"],
                0.9: ["يكاد يساويه", "قريب جداً منه", "شبه مماثل"],
                1.0: ["تقريباً مثله", "شبه مماثل", "واحد لواحد"],
            },
            "hi": {
                0.1: ["एक-दसवां", "लगभग एक-दसवां", "करीब एक-दसवां"],
                0.2: ["एक-पांचवां", "लगभग एक-पांचवां", "करीब एक-पांचवां"],
                0.25: ["एक चौथाई", "लगभग एक चौथाई", "करीब एक चौथाई"],
                round(1 / 3, 6): ["एक तिहाई", "लगभग एक तिहाई", "करीब एक तिहाई"],
                0.4: ["दो-पांचवां", "लगभग दो-पांचवां", "करीब दो-पांचवां"],
                0.5: ["आधा", "लगभग आधा", "करीब आधा"],
                round(2 / 3, 6): ["दो तिहाई", "लगभग दो तिहाई", "करीब दो तिहाई"],
                0.75: ["तीन चौथाई", "लगभग तीन चौथाई", "करीब तीन चौथाई"],
                0.8: ["चार-पांचवां", "लगभग चार-पांचवां", "लगभग पूरा"],
                0.9: ["लगभग उतना ही", "करीब-करीब बराबर", "लगभग समान"],
                1.0: ["लगभग बराबर", "करीब बराबर", "एक के मुकाबले एक"],
            },
            "bn": {
                0.1: ["এক-দশমাংশ", "প্রায় এক-দশমাংশ", "মোটামুটি এক-দশমাংশ"],
                0.2: ["এক-পঞ্চমাংশ", "প্রায় এক-পঞ্চমাংশ", "মোটামুটি এক-পঞ্চমাংশ"],
                0.25: ["এক-চতুর্থাংশ", "প্রায় এক-চতুর্থাংশ", "মোটামুটি এক-চতুর্থাংশ"],
                round(1 / 3, 6): ["এক-তৃতীয়াংশ", "প্রায় এক-তৃতীয়াংশ", "মোটামুটি এক-তৃতীয়াংশ"],
                0.4: ["দুই-পঞ্চমাংশ", "প্রায় দুই-পঞ্চমাংশ", "মোটামুটি দুই-পঞ্চমাংশ"],
                0.5: ["অর্ধেক", "প্রায় অর্ধেক", "মোটামুটি অর্ধেক"],
                round(2 / 3, 6): ["দুই-তৃতীয়াংশ", "প্রায় দুই-তৃতীয়াংশ", "মোটামুটি দুই-তৃতীয়াংশ"],
                0.75: ["তিন-চতুর্থাংশ", "প্রায় তিন-চতুর্থাংশ", "মোটামুটি তিন-চতুর্থাংশ"],
                0.8: ["চার-পঞ্চমাংশ", "প্রায় চার-পঞ্চমাংশ", "প্রায় পুরোটা"],
                0.9: ["প্রায় সমান", "কাছাকাছি সমান", "প্রায় একই রকম"],
                1.0: ["মোটামুটি সমান", "প্রায় সমান", "এক-এক"],
            },
            "ur": {
                0.1: ["ایک دسویں", "تقریباً ایک دسویں", "لگ بھگ ایک دسویں"],
                0.2: ["ایک پانچواں", "تقریباً ایک پانچواں", "لگ بھگ ایک پانچواں"],
                0.25: ["ایک چوتھائی", "تقریباً ایک چوتھائی", "لگ بھگ ایک چوتھائی"],
                round(1 / 3, 6): ["ایک تہائی", "تقریباً ایک تہائی", "لگ بھگ ایک تہائی"],
                0.4: ["دو پانچواں", "تقریباً دو پانچواں", "لگ بھگ دو پانچواں"],
                0.5: ["آدھا", "تقریباً آدھا", "لگ بھگ آدھا"],
                round(2 / 3, 6): ["دو تہائی", "تقریباً دو تہائی", "لگ بھگ دو تہائی"],
                0.75: ["تین چوتھائی", "تقریباً تین چوتھائی", "لگ بھگ تین چوتھائی"],
                0.8: ["چار پانچواں", "تقریباً چار پانچواں", "تقریباً پورا"],
                0.9: ["تقریباً برابر", "قریب قریب برابر", "لگ بھگ ایک جیسا"],
                1.0: ["تقریباً برابر", "قریب قریب برابر", "ایک کے مقابل ایک"],
            },
        }
        phrases = maps.get(self.language, maps["en"])
        return phrases.get(rounded, maps["en"].get(rounded, [self.runtime_pack.about_fallback]))

    def _benchmark_number_surface(self, number: int) -> str:
        return BENCHMARK_NUMBER_WORDS.get(self.language, {}).get(number) or self._number_word(number) or str(number)

    def _benchmark_multiplier_anchor_phrases(self, anchor: float, direction: str) -> list[str]:
        if self.language == "ru":
            if anchor == 1.5:
                if direction == "more":
                    return ["в полтора раза больше", "раза в полтора больше", "примерно в полтора раза больше"]
                return ["в полтора раза меньше", "раза в полтора меньше", "примерно в полтора раза меньше"]
            special_more = {2.0: ["вдвое больше", "примерно вдвое больше", "раза в два больше"], 3.0: ["втрое больше", "примерно втрое больше", "раза в три больше"], 4.0: ["вчетверо больше", "примерно вчетверо больше", "раза в четыре больше"], 5.0: ["впятеро больше", "примерно впятеро больше", "раза в пять больше"]}
            special_less = {2.0: ["вдвое меньше", "примерно вдвое меньше", "раза в два меньше"], 3.0: ["втрое меньше", "примерно втрое меньше", "раза в три меньше"], 4.0: ["вчетверо меньше", "примерно вчетверо меньше", "раза в четыре меньше"], 5.0: ["впятеро меньше", "примерно впятеро меньше", "раза в пять меньше"]}
            if direction == "more" and anchor in special_more:
                return special_more[anchor]
            if direction == "less" and anchor in special_less:
                return special_less[anchor]
            number = self._benchmark_number_surface(int(round(anchor)))
            if direction == "more":
                return [f"в {number} раз больше", f"примерно в {number} раз больше", f"раз в {number} больше"]
            return [f"в {number} раз меньше", f"примерно в {number} раз меньше", f"раз в {number} меньше"]

        number = self._benchmark_number_surface(int(round(anchor)))
        if self.language == "en":
            return [f"{number} times more", f"about {number} times more", f"roughly {number} times more"] if direction == "more" else [f"{number} times less", f"about {number} times less", f"roughly {number} times less"]
        if self.language == "es":
            return [f"{number} veces más", f"unas {number} veces más", f"aproximadamente {number} veces más"] if direction == "more" else [f"{number} veces menos", f"unas {number} veces menos", f"aproximadamente {number} veces menos"]
        if self.language == "fr":
            return [f"{number} fois plus", f"environ {number} fois plus", f"à peu près {number} fois plus"] if direction == "more" else [f"{number} fois moins", f"environ {number} fois moins", f"à peu près {number} fois moins"]
        if self.language == "pt":
            return [f"{number} vezes mais", f"umas {number} vezes mais", f"aproximadamente {number} vezes mais"] if direction == "more" else [f"{number} vezes menos", f"umas {number} vezes menos", f"aproximadamente {number} vezes menos"]
        if self.language == "zh":
            return [f"{number}倍多", f"大约{number}倍多", f"差不多{number}倍多"] if direction == "more" else [f"{number}分之一左右", f"约{number}分之一", f"差不多{number}分之一"]
        if self.language == "ar":
            return [f"أكثر ب{number} مرات", f"حوالي {number} مرات أكثر", f"قرابة {number} مرات أكثر"] if direction == "more" else [f"أقل ب{number} مرات", f"حوالي {number} مرات أقل", f"قرابة {number} مرات أقل"]
        if self.language == "hi":
            return [f"{number} गुना ज़्यादा", f"करीब {number} गुना ज़्यादा", f"लगभग {number} गुना अधिक"] if direction == "more" else [f"{number} गुना कम", f"करीब {number} गुना कम", f"लगभग {number} गुना कम"]
        if self.language == "bn":
            return [f"{number} গুণ বেশি", f"প্রায় {number} গুণ বেশি", f"মোটামুটি {number} গুণ বেশি"] if direction == "more" else [f"{number} গুণ কম", f"প্রায় {number} গুণ কম", f"মোটামুটি {number} গুণ কম"]
        if self.language == "ur":
            return [f"{number} گنا زیادہ", f"تقریباً {number} گنا زیادہ", f"لگ بھگ {number} گنا زیادہ"] if direction == "more" else [f"{number} گنا کم", f"تقریباً {number} گنا کم", f"لگ بھگ {number} گنا کم"]
        return [f"{number}x more", f"about {number}x more", f"roughly {number}x more"] if direction == "more" else [f"{number}x less", f"about {number}x less", f"roughly {number}x less"]

    def _benchmark_profane_band_words(self, index: int, ratio: float) -> list[str]:
        band_sets = self.assets.benchmark_profane_higher_bands if ratio > 1 else self.assets.benchmark_profane_lower_bands
        if 0 <= index < len(band_sets) and band_sets[index]:
            return list(band_sets[index])
        return []

    def _benchmark_ratio_candidate(self, ratio: float, reference: str, level: str) -> Candidate | None:
        absolute_ratio = abs(ratio)
        if absolute_ratio == 0 or absolute_ratio < 0.15 or absolute_ratio > 10:
            return None
        if absolute_ratio >= 1:
            multiplier = self._rounded_multiplier(absolute_ratio, level)
            return Candidate(
                self.runtime_pack.ratio_more_template.format(multiplier=multiplier, reference=reference),
                0.78 - min(abs(absolute_ratio - 1), 2.0) * 0.03,
                "benchmark_ratio_compare",
                "neutral",
                "normal",
            )

        inverse_multiplier = self._rounded_multiplier(1 / absolute_ratio, level)
        return Candidate(
            self.runtime_pack.ratio_less_template.format(multiplier=inverse_multiplier, reference=reference),
            0.78 - min(abs(absolute_ratio - 1), 0.85) * 0.04,
            "benchmark_ratio_compare",
            "neutral",
            "normal",
        )


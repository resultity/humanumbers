from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rapidfuzz import fuzz, process
from rapidfuzz.distance import Levenshtein

from .api_models import BenchmarkRequest
from .service_constants import NUMBER_RE, SCRIPT_HINTS, SUPPORTED_LANGUAGES, TOKEN_RE
from .service_types import HumanizeError, ParsedInput

if TYPE_CHECKING:
    from .api_models import HumanizeRequest
    from .assets import CompiledAssets


class ServiceParsingMixin:
    def _language_score(self, text: str) -> float:
        score = 0.0
        hint_re = SCRIPT_HINTS.get(self.language)
        if hint_re and hint_re.search(text):
            score += 20.0
        stop_words = self._stop_words()
        normalized_text = self._normalize_phrase(text, stop_words)
        if normalized_text in self._alias_index:
            return score + 120.0
        if normalized_text:
            choice = process.extractOne(normalized_text, list(self._alias_index.keys()), scorer=fuzz.WRatio)
            if choice:
                score += float(choice[1])
        lower_text = text.lower()
        for group_name in ("approximation", "discourse", "prepositions"):
            for token in self.assets.function_words.get(group_name, []):
                if isinstance(token, str) and token and token.lower() in lower_text:
                    score += 1.5
        return score

    def _detect_source_language(self, text: str) -> str:
        best_language = self.language
        best_score = float("-inf")
        for language in SUPPORTED_LANGUAGES:
            candidate_service = self if language == self.language else self._service_for_language(language)
            score = candidate_service._language_score(text)
            if score > best_score:
                best_score = score
                best_language = language
        return best_language

    def _resolve_source_language(self, request: HumanizeRequest) -> str:
        source_language = request.source_language or request.language or "auto"
        if source_language == "auto":
            return self._detect_source_language(request.text)
        if source_language not in SUPPORTED_LANGUAGES:
            raise HumanizeError(f"Unsupported source language '{source_language}'.")
        return source_language

    def _build_alias_index(self, assets: CompiledAssets) -> dict[str, tuple[str, str]]:
        index: dict[str, tuple[str, str]] = {}
        for unit_key, aliases in assets.unit_aliases.items():
            for alias in aliases:
                normalized = self._normalize_phrase(alias, stop_words=set())
                index[normalized] = (unit_key, alias)
        index["%"] = ("percent", "%")
        return index

    def _can_fuzzy_match_unit(self, normalized_text: str) -> bool:
        compact = normalized_text.replace(" ", "")
        return len(compact) >= 2

    def _fuzzy_alias_candidates(self, normalized_text: str) -> list[str]:
        compact = normalized_text.replace(" ", "")
        candidates = list(self._alias_index.keys())
        if len(compact) < 5:
            return candidates
        filtered = [key for key in candidates if len(key.replace(" ", "")) >= 3]
        return filtered or candidates

    def _fuzzy_alias_is_plausible(self, normalized_text: str, candidate_key: str, score: float) -> bool:
        source_compact = normalized_text.replace(" ", "")
        candidate_compact = candidate_key.replace(" ", "")
        if not source_compact or not candidate_compact:
            return False
        if len(source_compact) < 2:
            return False

        source_tokens = [token for token in normalized_text.split() if token]
        candidate_tokens = [token for token in candidate_key.split() if token]
        if len(source_tokens) != len(candidate_tokens) and score < 90:
            return False

        distance = Levenshtein.distance(source_compact, candidate_compact)
        similarity = Levenshtein.normalized_similarity(source_compact, candidate_compact)
        if len(source_compact) <= 4:
            return distance <= 1
        if len(source_compact) <= 8:
            return distance <= 2 or (score >= 90 and similarity >= 0.7)
        return distance <= max(2, len(source_compact) // 4) or similarity >= 0.78

    def _count_noun_surface(self, text: str, number_match: re.Match[str]) -> str | None:
        tail = f"{text[:number_match.start()]} {text[number_match.end():]}".strip()
        cleaned = re.sub(r"^[\s,;:()\[\]{}\-–—]+|[\s,;:()\[\]{}\-–—]+$", "", tail)
        return cleaned or None

    def _raw_unit_tail_candidates(self, text: str, number_match: re.Match[str]) -> list[str]:
        tail = self._count_noun_surface(text, number_match)
        if not tail:
            return []
        candidates: list[str] = []
        normalized_tail = self._normalize_phrase(tail, stop_words=set())
        if normalized_tail:
            candidates.append(normalized_tail)
        raw_tokens = [self.morphology.normalize_token(token) for token in TOKEN_RE.findall(tail.lower().replace("ё", "е")) if not NUMBER_RE.fullmatch(token)]
        raw_tokens = [token for token in raw_tokens if token]
        if raw_tokens:
            joined = " ".join(raw_tokens)
            if joined and joined not in candidates:
                candidates.append(joined)
            last = raw_tokens[-1]
            if last not in candidates:
                candidates.append(last)
        return candidates

    def _normalize_phrase(self, text: str, stop_words: set[str]) -> str:
        tokens = []
        for token in TOKEN_RE.findall(text.lower().replace("ё", "е")):
            if NUMBER_RE.fullmatch(token):
                continue
            normalized = self.morphology.normalize_token(token)
            if normalized and normalized not in stop_words:
                tokens.append(normalized)
        return " ".join(tokens).strip()

    def _stop_words(self) -> set[str]:
        groups = self.assets.derived_sets.get("composition.stop_token_groups", [])
        stop_words: set[str] = set()
        for group in groups:
            stop_words.update(self.assets.function_words.get(group, []))
        return {self.morphology.normalize_token(str(item)) for item in stop_words if item is not None}

    def parse(self, text: str) -> ParsedInput:
        match = NUMBER_RE.search(text.replace("−", "-"))
        if not match:
            raise HumanizeError("Could not find a numeric value in the input.")

        value = float(match.group(0).replace(",", "."))
        stop_words = self._stop_words()
        normalized_text = self._normalize_phrase(text, stop_words)
        unit_key = "count"
        family = "count"
        matched_alias = None
        fuzzy_score = None
        count_noun = None

        for raw_candidate in self._raw_unit_tail_candidates(text, match):
            exact = self._alias_index.get(raw_candidate)
            if exact:
                unit_key, matched_alias = exact
                break

        if unit_key == "count" and normalized_text:
            exact = self._alias_index.get(normalized_text)
            if exact:
                unit_key, matched_alias = exact
            elif self._can_fuzzy_match_unit(normalized_text):
                min_fuzzy_score = 74 if len(normalized_text.replace(" ", "")) <= 4 else 88
                choice = process.extractOne(normalized_text, self._fuzzy_alias_candidates(normalized_text), scorer=fuzz.WRatio)
                if choice and choice[1] >= min_fuzzy_score and self._fuzzy_alias_is_plausible(normalized_text, str(choice[0]), float(choice[1])):
                    unit_key, matched_alias = self._alias_index[choice[0]]
                    fuzzy_score = float(choice[1])

        if unit_key != "count":
            family = self.assets.units_by_key[unit_key].family
        elif normalized_text:
            count_noun = self._count_noun_surface(text, match) or normalized_text

        return ParsedInput(
            raw_text=text,
            normalized_text=normalized_text,
            value=value,
            unit=unit_key,
            family=family,
            matched_alias=matched_alias,
            fuzzy_score=fuzzy_score,
            count_noun=count_noun,
        )

    def _resolve_unit_text(self, unit_text: str) -> tuple[str, str | None, float | None]:
        normalized = self._normalize_phrase(unit_text, self._stop_words())
        if normalized in self.assets.units_by_key:
            return normalized, normalized, None
        exact = self._alias_index.get(normalized)
        if exact:
            unit_key, matched_alias = exact
            return unit_key, matched_alias, None
        if not self._can_fuzzy_match_unit(normalized):
            raise HumanizeError(f"Could not resolve benchmark unit '{unit_text}'.")
        choice = process.extractOne(normalized, self._fuzzy_alias_candidates(normalized), scorer=fuzz.WRatio)
        if choice and choice[1] >= 74 and self._fuzzy_alias_is_plausible(normalized, str(choice[0]), float(choice[1])):
            unit_key, matched_alias = self._alias_index[choice[0]]
            return unit_key, matched_alias, float(choice[1])
        raise HumanizeError(f"Could not resolve benchmark unit '{unit_text}'.")

    def parse_benchmark(self, benchmark: BenchmarkRequest, source: ParsedInput) -> ParsedInput:
        if benchmark.text:
            parsed = self.parse(benchmark.text)
            if parsed.family != source.family:
                raise HumanizeError("Benchmark must belong to the same family as the source value.")
            return parsed

        if benchmark.value is None:
            raise HumanizeError("Benchmark mode requires benchmark.text or benchmark.value.")

        unit_key = source.unit
        matched_alias = source.matched_alias
        fuzzy_score = None
        family = source.family
        count_noun = source.count_noun

        if benchmark.unit:
            unit_key, matched_alias, fuzzy_score = self._resolve_unit_text(benchmark.unit)
            family = self.assets.units_by_key[unit_key].family if unit_key != "count" else "count"
            if family != source.family:
                raise HumanizeError("Benchmark must belong to the same family as the source value.")

        return ParsedInput(
            raw_text=benchmark.text or f"{benchmark.value} {benchmark.unit or unit_key}",
            normalized_text=self._normalize_phrase(benchmark.unit or unit_key, self._stop_words()) if benchmark.unit else source.normalized_text,
            value=float(benchmark.value),
            unit=unit_key,
            family=family,
            matched_alias=matched_alias,
            fuzzy_score=fuzzy_score,
            count_noun=count_noun,
        )

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BenchmarkRequest(BaseModel):
    text: str | None = Field(default=None, description="Optional raw benchmark text, for example '100 кг'.")
    value: float | None = Field(default=None, description="Numeric benchmark value if text is not provided.")
    unit: str | None = Field(default=None, description="Benchmark unit key or surface alias, for example 'kg' or 'кг'.")
    label: str | None = Field(default=None, description="Optional human label for the benchmark reference.")


class HumanizeRequest(BaseModel):
    text: str = Field(min_length=1, description="Raw user input, for example 'ну около 73 сантиметров'.")
    source_language: str = Field(default="auto", description="Input language code or 'auto' for detection.")
    output_language: str = Field(default="ru", description="Language code for generated output.")
    system_preference: Literal["auto", "preserve", "si"] = Field(default="auto", description="Whether to preserve the incoming unit system, prefer SI renderings, or let the runtime choose.")
    mode: Literal["humanize", "benchmark"] = Field(default="humanize")
    variants: int = Field(default=3, ge=1, le=10)
    approximation: Literal["normal", "rough", "very_rough"] = Field(default="normal", description="Controls numeric rounding / estimation strength.")
    benchmark_registers: list[Literal["official", "colloquial", "rough", "profane"]] | None = Field(
        default=None,
        description="Benchmark-only comparison register selection. Ignored in normal humanize mode.",
    )
    styles: list[Literal["official", "colloquial", "oldschool", "rough", "profane"]] | None = Field(
        default=None,
        description="Deprecated compatibility field. Use benchmark_registers for benchmark mode.",
        deprecated=True,
    )
    allow_profane: bool = False
    benchmark: BenchmarkRequest | None = None
    debug: bool = False
    language: str | None = Field(default=None, description="Deprecated: old single language field.", deprecated=True)
    rounding: Literal["fine", "normal", "coarse", "extreme"] | None = Field(default=None, description="Deprecated: use approximation.", deprecated=True)
    roughness: list[Literal["normal", "rough", "very_rough"]] | None = Field(default=None, description="Deprecated: use approximation.", deprecated=True)


class ParsedInputModel(BaseModel):
    language: str
    raw_text: str
    normalized_text: str
    value: float
    unit: str
    family: str
    matched_alias: str | None = None
    fuzzy_score: float | None = None


class VariantModel(BaseModel):
    text: str
    score: float
    rule_kind: str
    style: Literal["official", "colloquial", "oldschool", "rough", "profane"]
    approximation: Literal["normal", "rough"]


class HumanizeResponse(BaseModel):
    parsed: ParsedInputModel
    benchmark: ParsedInputModel | None = None
    variants: list[VariantModel]
    warnings: list[str] = Field(default_factory=list)
    debug: dict[str, object] | None = None

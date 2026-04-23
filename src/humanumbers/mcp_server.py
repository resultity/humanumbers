from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .api_models import BenchmarkRequest, HumanizeRequest
from .service import get_service
from .support import support_payload


mcp = FastMCP("humanumbers")


def _support_payload() -> dict[str, Any]:
    return support_payload()


@mcp.tool(description="Inspect humanumbers capabilities before rewriting: available languages, approximation levels, benchmark registers, and system preference options.")
def get_humanumbers_support() -> dict[str, Any]:
    return _support_payload()


@mcp.tool(description="Convert one numeric-heavy fragment into more natural wording using humanumbers directly from the project source tree.")
def humanize_number(
    text: str,
    output_language: str = "en",
    source_language: str = "auto",
    mode: str = "humanize",
    approximation: str = "normal",
    system_preference: str = "auto",
    variants: int = 5,
    benchmark_text: str | None = None,
    benchmark_register: str = "colloquial",
) -> dict[str, Any]:
    benchmark = None
    benchmark_registers = None
    allow_profane = False
    styles = None

    if mode == "benchmark":
        benchmark = BenchmarkRequest(text=benchmark_text or "1 km")
        benchmark_registers = [benchmark_register]
        allow_profane = benchmark_register == "profane"
    else:
        styles = ["official", "colloquial"]

    request = HumanizeRequest(
        text=text,
        source_language=source_language,
        output_language=output_language,
        mode=mode,
        approximation=approximation,
        system_preference=system_preference,
        variants=variants,
        benchmark=benchmark,
        benchmark_registers=benchmark_registers,
        allow_profane=allow_profane,
        styles=styles,
    )
    response = get_service(output_language).humanize(request)
    return response.model_dump()


@mcp.tool(description="Rewrite a batch of numeric-heavy spec fragments into human-friendly wording with humanumbers. Useful when a source text contains many raw dimensions, weights, power figures, or distances.")
def humanize_fragments(
    fragments: list[str],
    output_language: str = "en",
    source_language: str = "auto",
    approximation: str = "normal",
    system_preference: str = "auto",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for fragment in fragments:
        text = fragment.strip()
        if not text:
            continue
        response = humanize_number(
            text=text,
            output_language=output_language,
            source_language=source_language,
            mode="humanize",
            approximation=approximation,
            system_preference=system_preference,
            variants=3,
        )
        variants = response.get("variants", []) if isinstance(response, dict) else []
        top_variant = variants[0] if variants else None
        results.append(
            {
                "source": text,
                "top_variant": top_variant,
                "variants": variants,
            }
        )
    return {"results": results}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
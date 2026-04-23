from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from openai import OpenAI


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from humanumbers.api_models import BenchmarkRequest, HumanizeRequest
from humanumbers.service import HumanizeError, get_service


DEFAULT_CHAT_COMPLETIONS_URL = "https://api.example.com/v1/chat/completions"
MIN_TOOL_CALLS = 4
MIN_BENCHMARK_CALLS_IF_AVAILABLE = 1

COMPARISON_RE = re.compile(
    r"(?P<left>-?[0-9]+(?:[.,][0-9]+)?)\s*(?P<unit>[^\s,;:()]+)\s*(?:,?\s*)(?:versus|vs\.?|against|compared\s+to)\s*(?P<right>-?[0-9]+(?:[.,][0-9]+)?)\s*(?P=unit)",
    re.IGNORECASE,
)

TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "humanize_number",
            "description": "Convert one numeric-heavy fragment into more natural wording via a direct local humanumbers import.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Numeric-heavy fragment to rewrite."},
                    "output_language": {"type": "string", "default": "en"},
                    "source_language": {"type": "string", "default": "auto"},
                    "mode": {"type": "string", "enum": ["humanize", "benchmark"], "default": "humanize"},
                    "approximation": {"type": "string", "enum": ["normal", "rough"], "default": "normal"},
                    "system_preference": {"type": "string", "enum": ["auto", "preserve", "si"], "default": "auto"},
                    "variants": {"type": "integer", "default": 5},
                    "benchmark_text": {"type": "string"},
                    "benchmark_register": {"type": "string", "enum": ["official", "colloquial", "rough", "profane"], "default": "colloquial"},
                },
                "required": ["text"],
            },
        },
    }
]


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def build_prompt(prompt_file: Path, source_file: Path) -> str:
    return load_text(prompt_file).format(source_text=load_text(source_file))


def derive_openai_base_url(chat_completions_url: str) -> str:
    parts = urlsplit(chat_completions_url)
    path = parts.path
    suffix = "/chat/completions"
    if path.endswith(suffix):
        path = path[: -len(suffix)]
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))


def build_client() -> tuple[OpenAI, str]:
    chat_completions_url = os.environ.get("CHAT_COMPLETIONS_URL", DEFAULT_CHAT_COMPLETIONS_URL)
    api_key = os.environ.get("CHAT_COMPLETIONS_BEARER_TOKEN")
    if not api_key:
        raise RuntimeError("CHAT_COMPLETIONS_BEARER_TOKEN is required.")
    base_url = derive_openai_base_url(chat_completions_url)
    return OpenAI(api_key=api_key, base_url=base_url), os.environ.get("CHAT_COMPLETIONS_MODEL", "chat-model")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare plain chat completions against a local import-backed tool run.")
    parser.add_argument("--prompt-file", default=str(Path(__file__).with_name("prompt.txt")))
    parser.add_argument("--source-file", default=str(Path(__file__).with_name("source_text.txt")))
    parser.add_argument("--output-file", default=None)
    parser.add_argument("--system-preference", choices=["auto", "preserve", "si"], default="si")
    return parser.parse_args()


def parse_tool_arguments(arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(arguments, str):
        return json.loads(arguments) if arguments.strip() else {}
    return arguments if isinstance(arguments, dict) else {}


def pick_preferred_variant(variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not variants:
        return None

    for predicate in (
        lambda v: v.get("approximation") == "rough" and v.get("style") == "colloquial",
        lambda v: v.get("approximation") == "rough",
        lambda v: v.get("style") == "colloquial",
        lambda v: True,
    ):
        for variant in variants:
            if predicate(variant):
                return variant
    return variants[0]


def looks_humanized(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "about ",
        "around ",
        "roughly ",
        "nearly ",
        "almost ",
        "a little over",
        "a little under",
        "just under",
        "just over",
    )
    return any(marker in lowered for marker in markers)


def extract_comparison_pairs(source_text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in COMPARISON_RE.finditer(source_text):
        left = f"{match.group('left')} {match.group('unit')}"
        right = f"{match.group('right')} {match.group('unit')}"
        key = (left, right)
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    return pairs


def count_benchmark_calls(tool_trace: list[dict[str, Any]]) -> int:
    count = 0
    for item in tool_trace:
        arguments = item.get("arguments") if isinstance(item, dict) else None
        if isinstance(arguments, dict) and arguments.get("mode") == "benchmark":
            count += 1
    return count


def summarize_humanize_response(response: dict[str, Any], source_text: str, fallback_warning: str | None = None) -> dict[str, Any]:
    variants = response.get("variants", []) if isinstance(response, dict) else []
    preferred = pick_preferred_variant(variants)
    alternatives = [
        {
            "text": item.get("text"),
            "style": item.get("style"),
            "approximation": item.get("approximation"),
            "rule_kind": item.get("rule_kind"),
        }
        for item in variants[:4]
    ]
    payload: dict[str, Any] = {
        "source": source_text,
        "preferred_rewrite": preferred,
        "alternatives": alternatives,
    }
    if fallback_warning:
        payload["warning"] = fallback_warning
    return payload


def handle_tool_call(arguments: dict[str, Any]) -> dict[str, Any]:
    output_language = arguments.get("output_language", "en")
    mode = arguments.get("mode", "humanize")
    benchmark = None
    benchmark_registers = None
    allow_profane = False
    styles = None

    if mode == "benchmark":
        benchmark = BenchmarkRequest(text=arguments.get("benchmark_text") or "1 km")
        benchmark_register = arguments.get("benchmark_register", "colloquial")
        benchmark_registers = [benchmark_register]
        allow_profane = benchmark_register == "profane"
    else:
        styles = ["official", "colloquial"]

    request_model = HumanizeRequest(
        text=arguments["text"],
        source_language=arguments.get("source_language", "auto"),
        output_language=output_language,
        mode=mode,
        approximation=arguments.get("approximation", "rough"),
        system_preference=arguments.get("system_preference", "auto"),
        variants=arguments.get("variants", 8),
        benchmark=benchmark,
        benchmark_registers=benchmark_registers,
        allow_profane=allow_profane,
        styles=styles,
    )
    try:
        response = get_service(output_language).humanize(request_model).model_dump()
    except HumanizeError as exc:
        if mode != "benchmark":
            return {
                "source": arguments.get("text", ""),
                "error": str(exc),
                "failed_mode": mode,
            }

        fallback_request = HumanizeRequest(
            text=arguments["text"],
            source_language=arguments.get("source_language", "auto"),
            output_language=output_language,
            mode="humanize",
            approximation=arguments.get("approximation", "rough"),
            system_preference=arguments.get("system_preference", "auto"),
            variants=arguments.get("variants", 8),
            styles=["official", "colloquial"],
        )
        fallback_response = get_service(output_language).humanize(fallback_request).model_dump()
        return summarize_humanize_response(
            fallback_response,
            arguments["text"],
            fallback_warning=f"Benchmark fallback applied: {exc}",
        )

    if mode != "humanize":
        return response

    return summarize_humanize_response(response, arguments["text"])


def save_report(path: Path, prompt: str, plain_text: str, tooled_text: str, tool_trace: list[dict[str, Any]], model: str) -> None:
    report = "\n".join(
        [
            "# Direct Tool Demo Report",
            "",
            f"- Model: {model}",
            f"- Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
            "",
            "## Prompt",
            "",
            "```text",
            prompt,
            "```",
            "",
            "## Tool Trace",
            "",
            *([json.dumps(item, ensure_ascii=False, indent=2) for item in tool_trace] or ["<no tool calls recorded>"]),
            "",
            "## Without Tool",
            "",
            plain_text.strip() or "<empty>",
            "",
            "## With Local Import Tool",
            "",
            tooled_text.strip() or "<empty>",
            "",
        ]
    )
    path.write_text(report, encoding="utf-8")


def run_plain_completion(client: OpenAI, model: str, prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a concise assistant. Write exactly one polished paragraph. "
                    "Keep SI units primary and keep numeric values exact as stated in the source. "
                    "Do not round or approximate numbers."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    return response.choices[0].message.content or ""


async def run_tool_completion(
    client: OpenAI,
    model: str,
    prompt: str,
    source_text: str,
    system_preference: str,
) -> tuple[str, list[dict[str, Any]]]:
    tool_trace: list[dict[str, Any]] = []
    comparison_pairs = extract_comparison_pairs(source_text)
    comparison_hint = "\n".join(f"- {left} vs {right}" for left, right in comparison_pairs)

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a concise assistant. Write exactly one polished English paragraph. "
                "Before the final answer, call the humanize_number tool on multiple numeric-heavy fragments from the source. "
                "Your final paragraph must clearly differ from an exact spec-sheet restatement by using rounded, humanized wording. "
                "Use preferred_rewrite values from tool outputs whenever available. "
                "Include at least four approximate numeric expressions (for example: about, around, roughly, nearly, almost). "
                "When the source contains direct numeric comparison pairs, call the tool in benchmark mode for at least one pair "
                "using a colloquial benchmark register. "
                f"Keep {system_preference.upper()} as the primary system for numeric phrasing."
            ),
        },
        {
            "role": "user",
            "content": (
                prompt
                + (
                    "\n\nDetected numeric comparison pairs:\n"
                    + comparison_hint
                    + "\nUse benchmark mode for at least one of these pairs."
                    if comparison_hint
                    else ""
                )
            ),
        },
    ]

    for _ in range(7):
        response = client.chat.completions.create(model=model, messages=messages, tools=TOOL_SCHEMA, tool_choice="auto", temperature=0.1)
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            if len(tool_trace) < MIN_TOOL_CALLS:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"You have used only {len(tool_trace)} tool call(s). "
                            f"Call humanize_number at least {MIN_TOOL_CALLS} times on different numeric fragments from the source, "
                            "then produce the final paragraph."
                        ),
                    }
                )
                continue
            if comparison_pairs and count_benchmark_calls(tool_trace) < MIN_BENCHMARK_CALLS_IF_AVAILABLE:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You still have not used benchmark mode for a direct comparison pair. "
                            "Call humanize_number with mode='benchmark' for at least one detected pair "
                            "(text=<left value>, benchmark_text=<right value>, benchmark_register='colloquial'), then rewrite the paragraph."
                        ),
                    }
                )
                continue

            final_text = message.content or ""
            if not looks_humanized(final_text):
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your paragraph still looks too exact. Rewrite it using rounded, humanized expressions "
                            "from the tool outputs with at least four approximate markers (about/around/roughly/nearly/almost)."
                        ),
                    }
                )
                continue
            return final_text, tool_trace

        for tool_call in message.tool_calls:
            arguments = parse_tool_arguments(tool_call.function.arguments)
            if tool_call.function.name == "humanize_number":
                arguments.setdefault("system_preference", system_preference)
                arguments.setdefault("approximation", "rough")
                arguments.setdefault("benchmark_register", "colloquial")
                arguments.setdefault("variants", 8)

            try:
                result = handle_tool_call(arguments)
            except Exception as exc:  # pragma: no cover - defensive demo guardrail
                result = {
                    "source": arguments.get("text", ""),
                    "error": f"Tool execution failed: {exc}",
                    "failed_mode": arguments.get("mode", "humanize"),
                }
            tool_trace.append(
                {
                    "tool_name": tool_call.function.name,
                    "arguments": arguments,
                    "result": result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    raise RuntimeError("Tool loop did not finish within the iteration limit.")


async def main() -> int:
    load_dotenv(Path(__file__).with_name(".env"))
    args = parse_args()
    client, model = build_client()
    source_text = load_text(Path(args.source_file))
    prompt = build_prompt(Path(args.prompt_file), Path(args.source_file))
    output_path = Path(args.output_file).resolve() if args.output_file else Path(__file__).with_name(f"tool_demo_report_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.md")

    plain_text = run_plain_completion(client, model, prompt)
    tooled_text, tool_trace = await run_tool_completion(client, model, prompt, source_text, args.system_preference)
    save_report(output_path, prompt, plain_text, tooled_text, tool_trace, model)

    print(f"Saved report to: {output_path}")
    print("\n=== WITHOUT TOOL ===\n")
    print(plain_text)
    print("\n=== WITH LOCAL IMPORT TOOL ===\n")
    print(tooled_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
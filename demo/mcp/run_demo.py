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

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI


DEFAULT_CHAT_COMPLETIONS_URL = "https://api.example.com/v1/chat/completions"
MIN_TOOL_CALLS = 4
MIN_BENCHMARK_CALLS_IF_AVAILABLE = 1

COMPARISON_RE = re.compile(
    r"(?P<left>-?[0-9]+(?:[.,][0-9]+)?)\s*(?P<unit>[^\s,;:()]+)\s*(?:,?\s*)(?:versus|vs\.?|against|compared\s+to)\s*(?P<right>-?[0-9]+(?:[.,][0-9]+)?)\s*(?P=unit)",
    re.IGNORECASE,
)


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
    parser = argparse.ArgumentParser(description="Compare plain chat completions against a local MCP-backed tool run.")
    parser.add_argument("--prompt-file", default=str(Path(__file__).with_name("prompt.txt")))
    parser.add_argument("--source-file", default=str(Path(__file__).with_name("source_text.txt")))
    parser.add_argument("--output-file", default=None)
    parser.add_argument("--system-preference", choices=["auto", "preserve", "si"], default="si")
    return parser.parse_args()


def mcp_tools_to_openai(tools_response: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in getattr(tools_response, "tools", []):
        input_schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": input_schema,
                },
            }
        )
    return tools


def parse_tool_arguments(arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(arguments, str):
        return json.loads(arguments) if arguments.strip() else {}
    return arguments if isinstance(arguments, dict) else {}


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


def serialize_mcp_result(result: Any) -> str:
    content = getattr(result, "content", None)
    if not content:
        if hasattr(result, "model_dump"):
            return json.dumps(result.model_dump(), ensure_ascii=False)
        return json.dumps(str(result), ensure_ascii=False)

    chunks: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            chunks.append(text)
            continue
        if hasattr(item, "model_dump"):
            chunks.append(json.dumps(item.model_dump(), ensure_ascii=False))
            continue
        chunks.append(str(item))
    return "\n".join(chunks)


def save_report(path: Path, prompt: str, plain_text: str, tooled_text: str, tool_trace: list[dict[str, Any]], tool_descriptions: list[str], model: str) -> None:
    report = "\n".join(
        [
            "# MCP Demo Report",
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
            "## Tool Descriptions",
            "",
            *([f"- {item}" for item in tool_descriptions] or ["<none>"]),
            "",
            "## Tool Trace",
            "",
            *([json.dumps(item, ensure_ascii=False, indent=2) for item in tool_trace] or ["<no tool calls recorded>"]),
            "",
            "## Without Tool",
            "",
            plain_text.strip() or "<empty>",
            "",
            "## With Local MCP Tool",
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


async def run_mcp_completion(
    client: OpenAI,
    model: str,
    prompt: str,
    source_text: str,
    system_preference: str,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    repo_root = Path(__file__).resolve().parents[2]
    pythonpath = str(repo_root / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath = f"{pythonpath}{os.pathsep}{existing_pythonpath}"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "humanumbers.mcp_server"],
        env={**os.environ, "PYTHONPATH": pythonpath},
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            tools = mcp_tools_to_openai(tools_response)
            tool_descriptions = [f"{tool['function']['name']}: {tool['function']['description']}" for tool in tools]
            tool_trace: list[dict[str, Any]] = []
            comparison_pairs = extract_comparison_pairs(source_text)
            comparison_hint = "\n".join(f"- {left} vs {right}" for left, right in comparison_pairs)

            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "You are a concise assistant. Write exactly one polished English paragraph. "
                        "Before the final answer, call tools on multiple numeric-heavy fragments from the source. "
                        "The final paragraph must clearly use rounded, humanized numeric phrasing. "
                        "Include at least four approximate numeric expressions (about, around, roughly, nearly, almost). "
                        "When direct numeric comparison pairs exist, call humanize_number in benchmark mode for at least one pair "
                        "using benchmark_register='colloquial'. "
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
                response = client.chat.completions.create(model=model, messages=messages, tools=tools, tool_choice="auto", temperature=0.1)
                message = response.choices[0].message
                assistant_message = message.model_dump(exclude_none=True)
                messages.append(assistant_message)

                if not message.tool_calls:
                    if len(tool_trace) < MIN_TOOL_CALLS:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"You have used only {len(tool_trace)} tool call(s). "
                                    f"Call tools at least {MIN_TOOL_CALLS} times on different numeric fragments, then rewrite the paragraph."
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
                                    "Your paragraph still looks too exact. Rewrite it with rounded, humanized phrasing "
                                    "from tool outputs and include at least four approximate markers."
                                ),
                            }
                        )
                        continue
                    return final_text, tool_trace, tool_descriptions

                for tool_call in message.tool_calls:
                    arguments = parse_tool_arguments(tool_call.function.arguments)
                    if tool_call.function.name == "humanize_number":
                        arguments.setdefault("system_preference", system_preference)
                        arguments.setdefault("approximation", "rough")
                        arguments.setdefault("benchmark_register", "colloquial")
                        arguments.setdefault("variants", 8)
                    result = await session.call_tool(tool_call.function.name, arguments)
                    serialized_result = serialize_mcp_result(result)
                    try:
                        parsed_result = json.loads(serialized_result)
                    except json.JSONDecodeError:
                        parsed_result = serialized_result
                    tool_trace.append(
                        {
                            "tool_name": tool_call.function.name,
                            "arguments": arguments,
                            "result": parsed_result,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": serialized_result,
                        }
                    )

    raise RuntimeError("Tool loop did not finish within the iteration limit.")


async def main() -> int:
    load_dotenv(Path(__file__).with_name(".env"))
    args = parse_args()
    client, model = build_client()
    source_text = load_text(Path(args.source_file))
    prompt = build_prompt(Path(args.prompt_file), Path(args.source_file))
    output_path = Path(args.output_file).resolve() if args.output_file else Path(__file__).with_name(f"mcp_demo_report_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.md")

    plain_text = run_plain_completion(client, model, prompt)
    tooled_text, tool_trace, tool_descriptions = await run_mcp_completion(client, model, prompt, source_text, args.system_preference)
    save_report(output_path, prompt, plain_text, tooled_text, tool_trace, tool_descriptions, model)

    print(f"Saved report to: {output_path}")
    print("\n=== WITHOUT TOOL ===\n")
    print(plain_text)
    print("\n=== WITH LOCAL MCP TOOL ===\n")
    print(tooled_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
# Humanumbers MCP Demo

This is the closest thing to the “real agent wiring” path.

The demo compares two runs over the same source text:

1. plain model output with no tools
2. model output with Humanumbers exposed through MCP over stdio

If you want to show why Humanumbers matters in an agent stack, this is the demo.

## What happens under the hood

- the model is called through an OpenAI-compatible chat completions interface
- available tools are discovered from the local Humanumbers MCP server
- tool calls are executed against `src/humanumbers/mcp_server.py`
- the run writes a markdown report with the tool trace

## Setup

```bash
export PROJECT_ROOT=<path-to-humanumbers>
cd "$PROJECT_ROOT"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[mcp]
pip install -r demo/mcp/requirements.txt
```

## Run

```bash
cd "$PROJECT_ROOT"/demo/mcp
python run_demo.py
```

Optional custom report path:

```bash
python run_demo.py --output-file ./mcp_report.md
```

## What to look for

- the plain paragraph usually keeps exact values or improvises badly
- the MCP-assisted paragraph should show controlled rounding and cleaner numeric language
- the report shows the actual tool calls instead of hand-wavy “magic”

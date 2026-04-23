# Humanumbers Local Tool Demo

This is the fastest no-server proof that Humanumbers changes output quality.

Instead of MCP, the model gets a normal function tool schema and the script executes Humanumbers locally from `src/`.

## What it demonstrates

1. A plain run with no tool access.
2. A tool-assisted run backed by a direct local import.
3. A saved markdown report that captures the exact tool trace.

If you want the shortest path from “does this help?” to “show me the output,” start here.

## Setup

```bash
export PROJECT_ROOT=<path-to-humanumbers>
cd "$PROJECT_ROOT"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
pip install -r demo/tool/requirements.txt
```

## Run

```bash
cd "$PROJECT_ROOT"/demo/tool
python run_demo.py
```

Optional custom report path:

```bash
python run_demo.py --output-file ./tool_report.md
```

## What to look for

- the plain result often stays too exact or drifts into odd phrasing
- the tool-assisted result should show explicit Humanumbers intervention
- the report shows the exact local tool input and output used during the run

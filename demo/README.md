# Humanumbers Demos

These demos answer one practical question:

What changes when a model gets access to Humanumbers instead of being left alone with raw numbers?

The `demo/` folder contains two comparison flows:

- `demo/tool` — local tool execution, no MCP required
- `demo/mcp` — MCP-based tool access over stdio

## Repo surfaces

- Package runtime: `src/humanumbers/*`
- HTTP API: `src/humanumbers/app.py`
- MCP server: `src/humanumbers/mcp_server.py`
- Demos: `demo/tool`, `demo/mcp`

## One-time setup

```bash
export PROJECT_ROOT=<path-to-humanumbers>
cd "$PROJECT_ROOT"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
pip install -r demo/tool/requirements.txt
pip install -r demo/mcp/requirements.txt
```

If you want MCP mounted into the API process too:

```bash
pip install -e .[mcp]
```

## Optional product runtime checks

### API

```bash
python run_product.py
```

### API + MCP

```bash
python run_product.py --mcp
```

### Standalone MCP

```bash
humanumbers-mcp
```

## MCP client template

```json
{
  "mcpServers": {
    "humanumbers": {
      "command": "<PROJECT_ROOT>/.venv/bin/python",
      "args": ["-m", "humanumbers.mcp_server"],
      "cwd": "<PROJECT_ROOT>",
      "env": {
        "PYTHONPATH": "<PROJECT_ROOT>/src"
      }
    }
  }
}
```

## Pick a demo path

### 1. Local tool flow

```bash
cd demo/tool
python run_demo.py
```

Use this when you want the fastest possible A/B test without standing up a server.

### 2. MCP flow

```bash
cd demo/mcp
python run_demo.py
```

Use this when you want to test the shape that agent stacks and MCP clients will actually see.

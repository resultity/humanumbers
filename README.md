# Humanumbers

Make numeric language stop sounding like a spreadsheet.

Humanumbers is a Python package and API for turning rigid numeric text into phrasing that feels more human without losing the meaning of the original value. It supports direct API usage, MCP integration, and local tool flows for agent stacks.

The published package name is `humanumbers`.
The Python module name is `humanumbers`.

## What lives here

- Core runtime: `src/humanumbers/service.py`
- HTTP API: `src/humanumbers/app.py`
- MCP server: `src/humanumbers/mcp_server.py`
- Product launcher: `run.py`
- Demo flows: `demo/tool`, `demo/mcp`
- Website frontend: `ws/`

If you are splitting this into separate repos for PyPI, Python source, and the website, start with `docs/publishing-guide.md`.

## Why Humanumbers exists

Most systems store exact numeric values. Most LLMs then repeat those values exactly, even when the result sounds stiff, robotic, or over-precise for real human communication.

Humanumbers gives you a controlled middle layer:

- parse the incoming numeric text
- preserve the unit meaning
- apply explicit rounding or benchmark comparison rules
- emit variants that sound more natural in the target language

## Quick start

```bash
export PROJECT_ROOT=<path-to-humanumbers>
cd "$PROJECT_ROOT"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

If you need MCP support:

```bash
pip install -e .[mcp]
```

Optional install straight from GitHub:

```bash
pip install "humanumbers[mcp] @ git+https://github.com/<org>/<repo>.git"
```

## Run the product

### API only

```bash
python run.py
```

### API + MCP on the same process

```bash
python run.py --mcp
```

### Custom bind

```bash
python run.py --host 0.0.0.0 --port 8000 --mcp --mcp-path /mcp
```

Direct entrypoints are also installed:

```bash
humanumbers-api
humanumbers-mcp
```

## Production note: CORS

If the website and API are deployed on different origins, configure the API allowlist explicitly:

```bash
HUMANUMBERS_CORS_ORIGINS=https://humanumbers.resultity.com
```

For the split-domain production setup:

- frontend: `https://humanumbers.resultity.com`
- API: `https://api-humanumbers.resultity.com`

## Demos

Humanumbers ships with two demo paths.

### Local tool demo

This path does not require a running API or MCP server.

```bash
pip install -r demo/tool/requirements.txt
cd demo/tool
python run_demo.py
```

### MCP demo

This path launches the Humanumbers MCP server from the package and lets the model call tools over stdio.

```bash
pip install -r demo/mcp/requirements.txt
cd demo/mcp
python run_demo.py
```

## Separate publication surfaces

This monorepo currently contains three surfaces:

1. The Python package for PyPI.
2. The Python source repository.
3. The standalone website for Vercel.

The exact split workflow is documented in `docs/publishing-guide.md`.

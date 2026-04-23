# Publishing Guide

This repository currently contains three publishable surfaces:

1. A Python package for PyPI.
2. A Python-focused GitHub repository.
3. A standalone website repository for Vercel.

## 1. PyPI package repository

Goal: ship only Python code and dictionaries required at runtime.

Keep:
- `pyproject.toml`
- `MANIFEST.in`
- `README.md`
- `src/humanumbers/**`
- `src/humanumbers/package_assets/**`

Drop:
- `ws/`
- `demo/`
- `tests/`
- `docs/`
- `dumps/`
- top-level `assets/` once `package_assets/` is present and verified

Release flow:

```bash
export PROJECT_ROOT=<path-to-humanumbers>
cd "$PROJECT_ROOT"
source .venv/bin/activate
bash scripts/sync_package_assets.sh
python -m pip install -U build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

## 2. Python GitHub repository

Goal: keep the product source, tests, demos, and docs for development.

Keep:
- `src/`
- `assets/`
- `tests/`
- `demo/`
- `chat_mcp_demo/`
- `docs/`
- `run.py`
- `pyproject.toml`
- `README.md`
- `.gitignore`
- `scripts/sync_package_assets.sh`
- `src/humanumbers/package_assets/`

Recommended release discipline:
- Treat `assets/` as the editable source of truth.
- Run `bash scripts/sync_package_assets.sh` before any PyPI build.
- Do not commit `ws/dist`, `node_modules`, `.venv*`, demo reports, or dumps.

## 3. Website repository for Vercel

Goal: deploy only the frontend.

Move the contents of `ws/` into the root of the website repository:
- `package.json`
- `package-lock.json`
- `vite.config.js`
- `index.html`
- `src/`
- `.gitignore`
- `.env.example`
- `README.md`

Vercel settings:
- Framework preset: `Vite`
- Build command: `npm run build`
- Output directory: `dist`
- Environment variable: `VITE_API_BASE_URL=https://api.example.com`

## Sanity checklist before publishing

- Website builds with `npm run build`.
- Python package assets were synced into `src/humanumbers/package_assets/`.
- Python package builds with `python -m build`.
- MCP instructions use placeholders or environment variables, not machine-specific absolute paths.
- No demo secrets or local `.env` files are tracked.

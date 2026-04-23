from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn


REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from humanumbers.app import app as api_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run humanumbers product server. Default: API only. Use --mcp to expose MCP on the same uvicorn process.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--mcp", action="store_true", help="Mount MCP streamable HTTP endpoint into the API app.")
    parser.add_argument("--mcp-path", default="/mcp", help="Mount path for MCP when --mcp is enabled.")
    return parser.parse_args()


def ensure_mcp_mounted(path: str) -> None:
    try:
        from humanumbers.mcp_server import mcp
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MCP dependencies are not installed. Install with: pip install -e .[mcp]"
        ) from exc

    mount_path = path if path.startswith("/") else f"/{path}"
    already_mounted = any(getattr(route, "path", None) == mount_path for route in api_app.routes)
    if not already_mounted:
        api_app.mount(mount_path, mcp.streamable_http_app())


def main() -> None:
    args = parse_args()
    if args.mcp:
        ensure_mcp_mounted(args.mcp_path)
    uvicorn.run(api_app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

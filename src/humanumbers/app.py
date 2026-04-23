from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .api_models import HumanizeRequest, HumanizeResponse
from .service import HumanizeError, get_service
from .support import support_payload


app = FastAPI(
    title="humanumbers API",
    version="0.1.0",
    description="Prototype numeric humanization API built on normalized assets and lightweight rule heuristics.",
)


def _cors_origins() -> list[str]:
    raw = os.getenv("HUMANUMBERS_CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


cors_origins = _cors_origins()
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/support")
def support() -> dict[str, object]:
    return support_payload()


@app.post("/v1/humanize", response_model=HumanizeResponse)
def humanize(request: HumanizeRequest) -> HumanizeResponse:
    try:
        output_language = request.output_language or request.language or "ru"
        service = get_service(output_language)
        return service.humanize(request)
    except HumanizeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def main() -> None:
    import uvicorn

    uvicorn.run("humanumbers.app:app", host="127.0.0.1", port=8000, reload=False)

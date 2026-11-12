"""FastAPI surface: POST /v1/ask, GET /healthz (process up), GET /readyz (index + key).

`create_app` is a factory so tests (and `crag serve`) pass explicit Settings; there is no
module-level app and no import-time side effect. Invalid input is a 422; runtime faults are not
errors here because `answer()` degrades instead of raising.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import Settings, get_settings
from .ingest import index_ready
from .pipeline import Answer, Engine, answer


class AskRequest(BaseModel):
    question: str


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    engine = Engine(s)  # built once: Chroma client, BM25 model and LLM client are reused
    app = FastAPI(title="corrective-rag", version="1.0.0")

    @app.post("/v1/ask", response_model=Answer)
    def ask(req: AskRequest) -> Answer:
        try:
            return answer(req.question, engine=engine)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        reasons = []
        if not index_ready(s):
            reasons.append("index not built: run `crag ingest`")
        if not s.key_configured:
            reasons.append("NVIDIA_API_KEY not configured")
        if reasons:
            return JSONResponse({"status": "not_ready", "reasons": reasons}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app

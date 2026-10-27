"""FastAPI server: the JSON API plus the built frontend."""

from __future__ import annotations

import os
import signal
import threading
import time
import webbrowser
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .runs import RunStore
from .tracer import REPO, Tracer

WEB_DIST = REPO / "web" / "dist"

tracer = Tracer()
store = RunStore(tracer)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    tracer.close()


app = FastAPI(title="DSA Visualizer", lifespan=lifespan)
last_request = time.monotonic()


@app.middleware("http")
async def track_activity(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    global last_request
    last_request = time.monotonic()
    return await call_next(request)


@app.get("/api/ping")
def ping() -> dict[str, bool]:
    """Heartbeat from open pages; keeps an --idle-exit server alive."""
    return {"ok": True}


class AnalyzeRequest(BaseModel):
    code: str


class RunRequest(BaseModel):
    code: str
    method: str | None = None
    cls: str | None = None
    inputs: dict[str, str] = {}
    overrides: dict[str, str] = {}


class OverridesRequest(BaseModel):
    overrides: dict[str, str]


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict[str, Any]:
    return tracer.analyze(req.code)


@app.post("/api/runs")
def start_run(req: RunRequest) -> dict[str, Any]:
    return store.start(req.code, req.method, req.cls, req.inputs, req.overrides)


@app.post("/api/runs/{run_id}/overrides")
def set_overrides(run_id: str, req: OverridesRequest) -> dict[str, Any]:
    if run_id not in store.runs:
        raise HTTPException(404, "Unknown run")
    return store.set_overrides(run_id, req.overrides)


@app.get("/api/runs/{run_id}/status")
def status(run_id: str) -> dict[str, Any]:
    if run_id not in store.runs:
        raise HTTPException(404, "Unknown run")
    return store.status(run_id)


@app.get("/api/runs/{run_id}/clips/{version}/{index}.mp4")
def clip(run_id: str, version: int, index: int) -> FileResponse:
    if run_id not in store.runs:
        raise HTTPException(404, "Unknown run")
    path = store.clip(run_id, version, index)
    if path is None or not path.exists():
        raise HTTPException(404, "Clip not ready")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "public, max-age=31536000, immutable"})


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Java DSA visualizer")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the browser")
    parser.add_argument("--idle-exit", type=float, metavar="MINUTES",
                        help="stop after this many minutes with no open page and nothing rendering")
    args = parser.parse_args()
    if args.idle_exit:
        threading.Thread(target=_exit_when_idle, args=(args.idle_exit * 60,), daemon=True).start()
    if args.open:
        webbrowser.open(f"http://localhost:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


def _exit_when_idle(limit: float) -> None:
    while True:
        time.sleep(10)
        rendering = any(r.state == "rendering" and not r.cancelled for r in store.active.values())
        if not rendering and time.monotonic() - last_request > limit:
            os.kill(os.getpid(), signal.SIGTERM)
            return

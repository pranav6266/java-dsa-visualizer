"""Runs: trace once, then render (and re-render on dropdown changes) in the background."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import pipeline, values
from .render import renderer
from .tracer import REPO, Tracer

RUNS_DIR = REPO / ".runs"
CACHE_DIR = RUNS_DIR / "cache"
MAX_RENDERED_STEPS = 1500


@dataclass
class Render:
    states_hash: str
    total: int
    dir: Path
    ready: set[int] = field(default_factory=set)
    state: str = "rendering"  # rendering | ready | error
    error: str | None = None
    cancelled: bool = False


@dataclass
class Run:
    id: str
    result: dict[str, Any]
    overrides: dict[str, str] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    version: int = 0
    render: Render | None = None


class RunStore:
    def __init__(self, tracer: Tracer) -> None:
        self.tracer = tracer
        self.runs: dict[str, Run] = {}
        self.latest: Run | None = None
        self.active: dict[str, Render] = {}
        self.lock = threading.Lock()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def start(self, code: str, method: str | None, cls: str | None, inputs: dict[str, str],
              overrides: dict[str, str]) -> dict[str, Any]:
        result = self.tracer.run(code, method, cls, inputs)
        response: dict[str, Any] = {
            "ok": result.get("ok", False),
            "message": result.get("message"),
            "methods": result.get("methods", []),
            "diagnostics": result.get("diagnostics", []),
            "inputError": result.get("inputError"),
        }
        trace = result.get("trace")
        if not trace:
            return response
        previous = self.latest.render if self.latest else None
        run = Run(id=uuid.uuid4().hex[:12], result=result, overrides=dict(overrides))
        self.runs[run.id] = run
        self.latest = run
        self._prepare(run)
        if previous is not None and previous is not run.render:
            previous.cancelled = True
        response.update(self._describe(run))
        return response

    def set_overrides(self, run_id: str, overrides: dict[str, str]) -> dict[str, Any]:
        run = self.runs[run_id]
        previous = run.render
        run.overrides = dict(overrides)
        self._prepare(run)
        if previous is not None and previous is not run.render:
            previous.cancelled = True
        return self._describe(run)

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.runs[run_id]
        r = run.render
        assert r is not None
        return {"version": run.version, "total": r.total, "ready": sorted(r.ready), "state": r.state, "error": r.error}

    def clip(self, run_id: str, version: int, index: int) -> Path | None:
        run = self.runs[run_id]
        r = run.render
        if r is None or run.version != version or index not in r.ready:
            return None
        return r.dir / "clips" / f"{index}.mp4"

    # ---------------------------------------------------------------------------------------------------------

    def _prepare(self, run: Run) -> None:
        trace = run.result["trace"]
        trace["steps"] = trace["steps"][:MAX_RENDERED_STEPS]
        ui_steps, states = pipeline.prepare(run.result, run.overrides)
        run.steps = ui_steps
        digest = hashlib.sha256(json.dumps(states, sort_keys=True).encode()).hexdigest()[:20]
        run.version += 1
        with self.lock:
            active = self.active.get(digest)
            if active is not None and not active.cancelled and active.state != "error":
                run.render = active
                return
            render = Render(states_hash=digest, total=len(states), dir=CACHE_DIR / digest)
            run.render = render
            if (render.dir / "done").exists():
                render.ready = set(range(len(states)))
                render.state = "ready"
                return
            self.active[digest] = render
        shutil.rmtree(render.dir, ignore_errors=True)
        threading.Thread(target=self._render, args=(render, states), daemon=True).start()

    def _render(self, render: Render, states: list[dict[str, Any]]) -> None:
        try:
            renderer.render(states, render.dir, render.ready.update, lambda: render.cancelled)
            if not render.cancelled:
                render.state = "ready"
                (render.dir / "done").touch()
        except Exception as e:  # noqa: BLE001 - surfaced in the UI
            render.state = "error"
            render.error = str(e)[-800:]

    def _describe(self, run: Run) -> dict[str, Any]:
        trace = run.result["trace"]
        assert run.render is not None
        returned = trace.get("returned")
        last_heap = trace["steps"][-1]["heap"] if trace["steps"] else {}
        return {
            "id": run.id,
            "version": run.version,
            "steps": run.steps,
            "total": run.render.total,
            "truncated": len(run.result["trace"]["steps"]) >= MAX_RENDERED_STEPS,
            "error": trace.get("error"),
            "returned": values.text(returned, last_heap, limit=80) if returned else None,
            "stdout": trace.get("stdout", ""),
            "stdoutTruncated": trace.get("stdoutTruncated", False),
            "overrides": run.overrides,
        }

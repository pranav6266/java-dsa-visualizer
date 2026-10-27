"""Turns a raw trace into what the UI steps through: lines, variables, call stack and loop iterations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import values
from .visual.classify import Classifier


@dataclass(frozen=True)
class Loop:
    method: str
    start: int
    end: int
    header: int

    def contains(self, method: str, line: int) -> bool:
        return method == self.method and self.start <= line <= self.end


def loops_of(analysis: dict[str, Any]) -> list[Loop]:
    return [Loop(l["method"], l["start"], l["end"], l["header"]) for l in analysis.get("loops", [])]


def innermost(loops: list[Loop], method: str, line: int) -> int | None:
    best = None
    for i, loop in enumerate(loops):
        if loop.contains(method, line) and (best is None or loop.end - loop.start < loops[best].end - loops[best].start):
            best = i
    return best


def top(step: dict[str, Any]) -> dict[str, Any] | None:
    frames = step.get("frames") or []
    return frames[0] if frames else None


def frame_of(step: dict[str, Any], call_id: int) -> dict[str, Any] | None:
    for f in step.get("frames", []):
        if f["callId"] == call_id:
            return f
    return None


def iterations(trace: dict[str, Any], loops: list[Loop]) -> tuple[list[dict[str, Any] | None], list[int]]:
    """For each step: which iteration of its innermost loop it is in, and where "Next iteration" jumps."""
    steps = trace["steps"]
    n = len(steps)
    info: list[dict[str, Any] | None] = [None] * n
    next_iter = list(range(1, n + 1))
    if n:
        next_iter[-1] = n - 1

    activations: dict[tuple[int, int], list[tuple[int, int, list[int]]]] = {}
    headers = {(l.method, l.header) for l in loops}
    # Outside any loop, "Next iteration" runs ahead to the next loop condition check in the same call.
    upcoming: int | None = None
    for i in range(n - 1, -1, -1):
        f = top(steps[i])
        if f is not None and innermost(loops, f["method"], f["line"]) is None:
            if upcoming is not None and (u := top(steps[upcoming])) and u["callId"] == f["callId"]:
                next_iter[i] = upcoming
        if f is not None and (f["method"], f["line"]) in headers:
            upcoming = i

    for i, step in enumerate(steps):
        f = top(step)
        if f is None:
            continue
        li = innermost(loops, f["method"], f["line"])
        if li is None:
            continue
        loop = loops[li]
        call = f["callId"]
        known = activations.setdefault((call, li), [])
        found = next((act for act in known if act[0] <= i <= act[1]), None)
        if found is None:
            found = _activation(steps, loop, call, i)
            known.append(found)
        a, b, headers = found
        if not headers:
            continue
        # The last header visit is the failing condition check when the loop ends right after it.
        last = headers[-1]
        exits_on_check = b + 1 < n and all(
            (t := top(steps[j])) is None or t["callId"] != call or t["line"] == loop.header for j in range(last, b + 1)
        )
        total = len(headers) - 1 if exits_on_check and len(headers) > 1 else len(headers)
        current = sum(1 for h in headers if h <= i)
        info[i] = {"loop": li, "header": loop.header, "iteration": max(1, min(current, total)), "total": max(total, 1)}
        later = [h for h in headers if h > i]
        next_iter[i] = later[0] if later else min(b + 1, n - 1)
    return info, next_iter


def _activation(steps: list[dict[str, Any]], loop: Loop, call: int, i: int) -> tuple[int, int, list[int]]:
    """The run of steps around `i` where frame `call` stays inside `loop`, and its condition-check steps."""

    def inside(j: int) -> bool:
        fr = frame_of(steps[j], call)
        return fr is not None and loop.contains(fr["method"], fr["line"])

    a = i
    while a > 0 and inside(a - 1):
        a -= 1
    b = i
    while b + 1 < len(steps) and inside(b + 1):
        b += 1
    headers = [j for j in range(a, b + 1) if (t := top(steps[j])) and t["callId"] == call and t["line"] == loop.header]
    return a, b, headers


def build(trace: dict[str, Any], analysis: dict[str, Any], classifier: Classifier) -> list[dict[str, Any]]:
    """The per-step data the frontend shows next to the animation."""
    loops = loops_of(analysis)
    iter_info, next_iter = iterations(trace, loops)
    entry = trace.get("entry", {})
    params = next((
        {p["name"] for p in m["params"]} for m in analysis.get("methods", [])
        if m["name"] == entry.get("method") and m["cls"] == entry.get("cls")
    ), set())
    out = []
    previous: dict[tuple[int, str], str] = {}
    for i, step in enumerate(trace["steps"]):
        heap = step["heap"]
        frames = []
        seen: dict[tuple[int, str], str] = {}
        for f in step["frames"]:
            locals_out = []
            for local in f["locals"]:
                display = values.text(local["value"], heap, limit=60)
                key = (f["callId"], local["name"])
                seen[key] = display
                locals_out.append(
                    {
                        "name": local["name"],
                        "type": values.short_type(local["type"]),
                        "value": display,
                        "changed": i > 0 and previous.get(key) != display,
                        "kind": classifier.kind_of_value(local["value"], heap),
                        # The input decides how a structure is drawn, so only parameters get a type picker.
                        "kindOptions": classifier.options_for(local["value"], heap)
                        if f["method"] == entry.get("method") and local["name"] in params else [],
                    }
                )
            frames.append({"callId": f["callId"], "method": f["method"], "line": f["line"], "locals": locals_out})
        previous = seen
        returns = [
            {"method": r["method"], "value": values.text(r.get("value"), heap) if "value" in r else None}
            for r in step.get("returns", [])
        ]
        out.append(
            {
                "line": step["line"],
                "event": step["event"],
                "frames": frames,
                "iteration": iter_info[i],
                "nextIteration": next_iter[i],
                "returns": returns,
                "printed": step.get("out", 0),
            }
        )
    return out

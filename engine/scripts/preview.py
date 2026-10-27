"""Renders still frames of chosen steps for the example cases into a contact sheet, for visual review.

Usage: uv run python scripts/preview.py OUT_DIR [case ...] [--steps first,mid,last|0,3,7]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dsaviz.pipeline import prepare
from dsaviz.render.renderer import SCENE
from dsaviz.tracer import REPO, Tracer

CASES = REPO / "examples" / "cases.json"


def pick(spec: str, n: int, error_step: int | None) -> list[int]:
    if spec != "auto":
        return [min(n - 1, int(x)) for x in spec.split(",")]
    picks = {0, n // 3, (2 * n) // 3, n - 1}
    if error_step is not None and error_step >= 0:
        picks.add(error_step)
    return sorted(picks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--steps", default="auto")
    args = parser.parse_args()
    cases = json.loads(CASES.read_text())
    names = args.cases or list(cases)
    tracer = Tracer()
    args.out.mkdir(parents=True, exist_ok=True)
    for name in names:
        case = cases[name]
        code = (REPO / "examples" / "cases" / f"{name}.java").read_text()
        result = tracer.run(code, case["method"], None, case["inputs"])
        if not result.get("trace"):
            print(name, "no trace:", result.get("diagnostics"), result.get("inputError"))
            continue
        _, states = prepare(result)
        err = result["trace"].get("error")
        steps = pick(args.steps, len(states), err.get("step") if err else None)
        work = args.out / f"work-{name}"
        plan = work / "plan.json"
        work.mkdir(parents=True, exist_ok=True)
        plan.write_text(json.dumps({"states": states}))
        env = {"DSAVIZ_PLAN": str(plan), "DSAVIZ_STEPS": ",".join(map(str, steps))}
        cmd = [sys.executable, "-m", "manim", "render", "--save_sections", "--disable_caching", "--progress_bar",
               "none", "--verbosity", "WARNING", "-r", "1280,720", "--media_dir", str(work), str(SCENE), "PreviewScene"]
        r = subprocess.run(cmd, env=dict(os.environ, **env), capture_output=True, text=True)
        if r.returncode:
            print(name, "render failed", r.stderr[-1500:])
            continue
        sections = sorted(work.glob("videos/scene/*/sections/PreviewScene_*.mp4"))
        frames = []
        for k, video in enumerate(sections):
            png = work / f"f{k}.png"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-frames:v", "1", str(png)], check=True)
            frames.append(png)
        inputs = sum([["-i", str(f)] for f in frames], [])
        sheet = args.out / f"{name}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", _grid(len(frames)),
                        str(sheet)], check=True)
        print(name, "steps", steps, "->", sheet)


def _grid(n: int) -> str:
    cols = 2
    layout = "|".join(f"{(i % cols) * 1280}_{(i // cols) * 720}" for i in range(n))
    inputs = "".join(f"[{i}]" for i in range(n))
    if n == 1:
        return "[0]null"
    return f"{inputs}xstack=inputs={n}:layout={layout}:fill=#303030"


if __name__ == "__main__":
    main()

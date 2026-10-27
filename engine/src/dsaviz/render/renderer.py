"""Renders visual states to one MP4 clip per step, in parallel chunks, reporting progress as clips land."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

SCENE = Path(__file__).with_name("scene.py")
FIRST_CHUNK = 6
CHUNK = 24
RESOLUTION = "1280,720"
FPS = "30"


def workers() -> int:
    return max(1, min(8, (os.cpu_count() or 2) - 2))


def chunks(n: int) -> list[tuple[int, int]]:
    """Step ranges to render. The first is small so the first steps are ready quickly."""
    out = []
    start = 0
    size = FIRST_CHUNK
    while start < n:
        end = min(n, start + size) - 1
        out.append((start, end))
        start = end + 1
        size = CHUNK
    return out


def render(states: list[dict[str, Any]], out_dir: Path, on_ready: Callable[[list[int]], None],
           cancelled: Callable[[], bool] = lambda: False) -> None:
    """Writes out_dir/clips/{i}.mp4 for every state. Calls on_ready with the step indices of each finished chunk."""
    clips = out_dir / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    plan = out_dir / "plan.json"
    plan.write_text(json.dumps({"states": states}))
    ranges = chunks(len(states))
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers()) as pool:
        futures = {pool.submit(_render_chunk, plan, out_dir / f"work{a:05d}", a, b, clips, cancelled): (a, b)
                   for a, b in ranges}
        for future in as_completed(futures):
            a, b = futures[future]
            try:
                if future.result():
                    on_ready(list(range(a, b + 1)))
            except Exception as e:  # noqa: BLE001 - reported to the UI as a render failure
                errors.append(f"steps {a}-{b}: {e}")
    if errors:
        raise RuntimeError("; ".join(errors))


def _render_chunk(plan: Path, work: Path, a: int, b: int, clips: Path, cancelled: Callable[[], bool]) -> bool:
    """Renders steps a..b. Returns False when skipped because the render was cancelled."""
    if cancelled():
        return False
    env = dict(os.environ, DSAVIZ_PLAN=str(plan), DSAVIZ_RANGE=f"{a}:{b}")
    cmd = [
        sys.executable, "-m", "manim", "render",
        "--save_sections", "--disable_caching", "--progress_bar", "none", "--verbosity", "WARNING",
        "-r", RESOLUTION, "--fps", FPS,
        "--media_dir", str(work), str(SCENE), "StepScene",
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-1500:] or "manim failed")
    index = next(work.glob("videos/scene/*/sections/StepScene.json"))
    for section in json.loads(index.read_text()):
        step = int(section["name"].removeprefix("step"))
        shutil.move(str(index.parent / section["video"]), clips / f"{step}.mp4")
    shutil.rmtree(work, ignore_errors=True)
    return True

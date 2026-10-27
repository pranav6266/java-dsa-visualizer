"""From a tracer result to what the UI and the renderer need."""

from __future__ import annotations

from typing import Any

from . import steps
from .visual.builder import Builder
from .visual.classify import Classifier


def prepare(result: dict[str, Any], overrides: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (ui_steps, visual_states) for a successful run."""
    trace = result["trace"]
    classifier = Classifier(trace, overrides)
    ui_steps = steps.build(trace, result, classifier)
    states = Builder(trace, result, classifier).build()
    return ui_steps, states

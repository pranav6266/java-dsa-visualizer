"""Manim scene that animates a range of visual states, one section (one clip) per step.

Run by renderer.py in a subprocess:
    DSAVIZ_PLAN=plan.json DSAVIZ_RANGE=a:b manim render ... scene.py StepScene

Section ``step{i:05d}`` animates state i-1 -> state i (section ``step00000`` fades in state 0).
"""

from __future__ import annotations

import json
import os
from typing import Any

import numpy as np
from manim import (
    Arrow,
    Circle,
    Circumscribe,
    Create,
    CurvedArrow,
    DashedVMobject,
    FadeIn,
    FadeOut,
    FadeTransform,
    GrowArrow,
    RoundedRectangle,
    Scene,
    Text,
    Transform,
    VGroup,
    VMobject,
    config,
)

from dsaviz.visual import style as S

MOVE_TIME = 0.75
FLASH_TIME = 0.45
IDLE_TIME = 0.35

config.background_color = S.BACKGROUND

Element = dict[str, Any]


def point(x: float, y: float) -> np.ndarray:
    return np.array([x, y, 0.0])


def make_text(el: Element) -> Text | None:
    if not el.get("text"):
        return None
    # Invisible bars on both sides give every label the same ascender-to-descender height, so "prev" and "curr"
    # line up on a shared baseline instead of each being centered on its own glyph box.
    text = Text("|" + el["text"] + "|", font=S.FONT, font_size=el["fs"], color=el["color"])
    text[0].set_opacity(0)
    text[-1].set_opacity(0)
    return text


def build(el: Element) -> VMobject:
    kind = el["type"]
    if kind == "circle":
        shape = Circle(radius=el["r"], color=el["stroke"], stroke_width=3)
        shape.set_fill(el["fill"], opacity=1.0)
        shape.move_to(point(el["x"], el["y"]))
        group = VGroup(shape)
        if (t := make_text(el)) is not None:
            group.add(t.move_to(shape.get_center()))
    elif kind == "box":
        shape = RoundedRectangle(corner_radius=min(el["corner"], el["h"] / 2, el["w"] / 2), width=el["w"],
                                 height=el["h"], color=el["stroke"], stroke_width=2.5)
        shape.set_fill(el["fill"], opacity=1.0)
        shape.move_to(point(el["x"], el["y"]))
        if el.get("dashed"):
            shape = VGroup(shape.copy().set_stroke(opacity=0), DashedVMobject(shape, num_dashes=24))
        group = VGroup(shape)
        if (t := make_text(el)) is not None:
            group.add(t.move_to(point(el["x"], el["y"])))
    elif kind == "text":
        group = VGroup(make_text(el) or VGroup())
        group.move_to(point(el["x"], el["y"]))
    elif kind == "arrow":
        start, end = point(el["x1"], el["y1"]), point(el["x2"], el["y2"])
        if el.get("curve"):
            group = CurvedArrow(start, end, angle=el["curve"], color=el["color"], stroke_width=el["width"],
                                tip_length=0.15)
        else:
            group = Arrow(start, end, buff=0, color=el["color"], stroke_width=el["width"], tip_length=0.15,
                          max_tip_length_to_length_ratio=0.45, max_stroke_width_to_length_ratio=12)
    else:
        raise ValueError(f"unknown element type {kind}")
    group.set_z_index(el.get("z", 0))
    return group


def text_changed(a: Element, b: Element) -> bool:
    return a.get("text") != b.get("text")


class StepScene(Scene):
    def construct(self) -> None:
        with open(os.environ["DSAVIZ_PLAN"]) as f:
            states: list[dict[str, Any]] = json.load(f)["states"]
        first, last = (int(x) for x in os.environ["DSAVIZ_RANGE"].split(":"))
        mobs: dict[str, VMobject] = {}
        current: dict[str, Element] = {}

        if first > 0:
            current = {el["key"]: el for el in states[first - 1]["elements"]}
            for key, el in current.items():
                mobs[key] = build(el)
                self.add(mobs[key])

        for i in range(first, last + 1):
            self.next_section(f"step{i:05d}")
            target = {el["key"]: el for el in states[i]["elements"]}
            self.transition(mobs, current, target, intro=(i == 0))
            current = target

    def transition(self, mobs: dict[str, VMobject], old: dict[str, Element], new: dict[str, Element],
                   intro: bool) -> None:
        anims = []
        flashes = []
        for key, el in new.items():
            if key not in old:
                mob = build(el)
                mobs[key] = mob
                if el["type"] == "arrow" and not el.get("curve"):
                    anims.append(GrowArrow(mob))
                elif el["type"] == "arrow":
                    anims.append(Create(mob))
                else:
                    anims.append(FadeIn(mob, scale=0.85))
                continue
            if old[key] == el:
                continue
            mob = mobs[key]
            target = build(el)
            if text_changed(old[key], el):
                anims.append(FadeTransform(mob, target))
                mobs[key] = target
                if not intro and el["type"] in ("box", "circle", "text") and not key.startswith("error:"):
                    flashes.append(key)
            else:
                anims.append(Transform(mob, target))
        for key in old:
            if key not in new:
                anims.append(FadeOut(mobs.pop(key)))
        if anims:
            self.play(*anims, run_time=0.5 if intro else MOVE_TIME)
        else:
            self.wait(IDLE_TIME)
        if flashes:
            self.play(*(Circumscribe(mobs[k], color=S.POINTER_COLORS[4], buff=0.05, stroke_width=3)
                        for k in flashes), run_time=FLASH_TIME)


class PreviewScene(Scene):
    """Development aid: one short section per requested state, for still-frame review (see scripts/preview.py)."""

    def construct(self) -> None:
        with open(os.environ["DSAVIZ_PLAN"]) as f:
            states: list[dict[str, Any]] = json.load(f)["states"]
        for i in (int(x) for x in os.environ["DSAVIZ_STEPS"].split(",")):
            self.next_section(f"step{i:05d}")
            self.clear()
            for el in states[i]["elements"]:
                self.add(build(el))
            self.wait(0.1)

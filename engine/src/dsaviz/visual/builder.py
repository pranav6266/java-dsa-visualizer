"""Builds one visual state per trace step: a list of keyed shapes in Manim coordinates.

Every shape has a stable key (e.g. ``node:179`` or ``arr0:c3``). The renderer animates a step by morphing shapes
whose key exists in both states, fading in new keys and fading out missing ones. Positions are planned over the whole
trace up front, so nodes and boxes stay put unless the code actually moved them.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .. import values
from ..values import Heap, Value
from . import style as S
from .classify import LIST_KINDS, Classifier, NodeShape

Element = dict[str, Any]

# Natural sizes, in Manim units, before any structure is scaled to fit the canvas.
NODE_R = 0.36
LIST_SP = 1.55
TREE_SP = 0.85
TREE_LEVEL = 1.15
LABEL_LINE = 0.34
CELL = 0.66
CELL_STEP = 0.70
FS_NODE = 24
FS_CELL = 24
FS_SMALL = 15
FS_LABEL = 19
FS_NAME = 21
STRUCT_GAP = 0.5
CANVAS_W = 13.4
CANVAS_TOP = 3.75
CANVAS_BOTTOM = -3.75
MAX_UPSCALE = 1.45
BANNER_H = 0.6


# ---- shape constructors ---------------------------------------------------------------------------------------------

def circle(key: str, x: float, y: float, r: float, fill: str, stroke: str, text: str, color: str, fs: float) -> Element:
    return {"key": key, "type": "circle", "x": x, "y": y, "r": r, "fill": fill, "stroke": stroke, "text": text,
            "color": color, "fs": fs, "z": 2}


def box(key: str, x: float, y: float, w: float, h: float, fill: str, stroke: str, text: str, color: str, fs: float,
        corner: float = 0.06, dashed: bool = False) -> Element:
    return {"key": key, "type": "box", "x": x, "y": y, "w": w, "h": h, "fill": fill, "stroke": stroke, "text": text,
            "color": color, "fs": fs, "corner": corner, "dashed": dashed, "z": 2}


def label(key: str, x: float, y: float, text: str, color: str, fs: float) -> Element:
    return {"key": key, "type": "text", "x": x, "y": y, "text": text, "color": color, "fs": fs, "z": 3}


def arrow(key: str, x1: float, y1: float, x2: float, y2: float, color: str, curve: float = 0.0,
          width: float = 3.0) -> Element:
    return {"key": key, "type": "arrow", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": color, "curve": curve,
            "width": width, "z": 1}


def cell_text(v: Value, heap: Heap, limit: int = 8) -> str:
    """A value inside a box. Chars drop their quotes: the box already shows it is one character."""
    if v.get("k") == "prim" and v.get("t") in ("char", "Character"):
        return v["v"]
    return values.text(v, heap, 0, limit)


def fit_font(text: str, width: float, base: float) -> float:
    if not text:
        return base
    return max(9.0, min(base, width * 0.9 / (len(text) * S.CHAR_WIDTH)))


# ---- per-step view of the trace ---------------------------------------------------------------------------------

@dataclass
class Named:
    name: str
    value: Value
    top: bool


@dataclass
class StepView:
    index: int
    step: dict[str, Any]
    heap: Heap
    named: list[Named]  # every named root: top frame locals and `this` fields, statics, then outer frames

    @property
    def top_named(self) -> list[Named]:
        return [n for n in self.named if n.top]


def make_view(index: int, step: dict[str, Any], entry_cls: str) -> StepView:
    heap = step["heap"]
    named: list[Named] = []
    frames = step.get("frames") or []
    for depth, frame in enumerate(frames):
        is_top = depth == 0
        for local in frame["locals"]:
            # The solution object's fields (memo tables, counters) are shown like variables. Any other `this`
            # (a node being constructed, say) is just a reference named "this".
            if local["name"] == "this" and values.short_type(local["type"]) == entry_cls:
                obj = heap.get(values.ref_id(local["value"])) if values.is_ref(local["value"]) else None
                for f in (obj or {}).get("fields", []):
                    named.append(Named(f["name"], f["value"], is_top))
                continue
            named.append(Named(local["name"], local["value"], is_top))
        if is_top:
            for qualified, value in (step.get("statics") or {}).items():
                named.append(Named(qualified.rsplit(".", 1)[-1], value, True))
    return StepView(index, step, heap, named)


# ---- structures -----------------------------------------------------------------------------------------------------

@dataclass
class Slot:
    """A box-shaped structure (array, string, map, ...) that keeps its place on the canvas across steps."""

    key: str
    kind: str
    name: str
    current: Any = None
    by_step: dict[int, Any] = field(default_factory=dict)  # step -> heap id (or the string value for strings)
    labels: dict[int, str] = field(default_factory=dict)
    max_len: int = 0
    max_rows: int = 0
    max_cols: int = 0
    order: list[str] = field(default_factory=list)  # stable key order for maps and sets
    max_text: int = 1
    max_name: int = 1
    max_pointers: int = 0
    row_aliases: dict[int, dict[int, list[str]]] = field(default_factory=dict)


class Builder:
    def __init__(self, trace: dict[str, Any], analysis: dict[str, Any], classifier: Classifier) -> None:
        self.trace = trace
        self.analysis = analysis
        self.cls = classifier
        entry_cls = trace.get("entry", {}).get("cls", "Solution")
        self.views = [make_view(i, s, entry_cls) for i, s in enumerate(trace["steps"])]
        self.error = trace.get("error")
        self.index_uses = analysis.get("indexUses", [])
        self.pointer_colors: dict[str, str] = {}
        self.slots: list[Slot] = []
        self.list_pos: dict[str, tuple[float, float]] = {}
        self.label_lines = 1
        self.var_order: list[str] = []
        self.var_width: dict[str, float] = {}
        # A linked-list kind picked in the dropdown applies to every list drawn in this run.
        self.list_override = next((k for k in classifier.overrides.values() if k in LIST_KINDS), None)

    # -- public --------------------------------------------------------------------------------------------------

    def build(self) -> list[dict[str, Any]]:
        self._survey_slots()
        self._layout_lists()
        self._survey_colors()
        self._survey_vars()
        structures = self._structures()
        placements = self._place(structures)
        states = []
        previous_nodes: set[str] = set()
        for view in self.views:
            elements: list[Element] = []
            for struct, (scale, dx, dy) in zip(structures, placements):
                for el in struct.emit(view):
                    elements.append(transform(el, scale, dx, dy))
            nodes_now = {el["key"] for el in elements if el["key"].startswith("node:")}
            elements.extend(self._ghosts(view, previous_nodes - nodes_now, structures, placements))
            previous_nodes = nodes_now
            elements.extend(self._error_marks(view, elements))
            states.append({"elements": elements})
        return states

    # -- pointer colors -----------------------------------------------------------------------------------------

    def color_for(self, var: str) -> str:
        if var not in self.pointer_colors:
            self.pointer_colors[var] = S.POINTER_COLORS[len(self.pointer_colors) % len(S.POINTER_COLORS)]
        return self.pointer_colors[var]

    # -- survey: slots ------------------------------------------------------------------------------------------

    def _node_shape(self, obj: dict[str, Any] | None) -> NodeShape | None:
        return self.cls.node_shape_of(obj)

    def _struct_refs(self, view: StepView) -> tuple[dict[str, list[Named]], dict[str, tuple[str, int]]]:
        """Heap objects drawn as their own slot, with the names that refer to them, and grid-row aliases."""
        refs: dict[str, list[Named]] = {}
        for n in view.named:
            if not values.is_ref(n.value):
                continue
            oid = values.ref_id(n.value)
            obj = view.heap.get(oid)
            if obj is None or self._node_shape(obj) is not None or obj.get("kind") == "opaque":
                continue
            refs.setdefault(oid, []).append(n)
        inner_rows: dict[str, tuple[str, int]] = {}
        for oid in refs:
            obj = view.heap[oid]
            if obj.get("kind") == "array" and obj.get("type", "").endswith("[][]"):
                for r, item in enumerate(obj.get("items", [])):
                    if values.is_ref(item):
                        inner_rows[values.ref_id(item)] = (oid, r)
        return refs, inner_rows

    @staticmethod
    def _label_of(names: list[Named]) -> str:
        top = [n.name for n in names if n.top]
        chosen = top or [names[0].name]
        return ", ".join(dict.fromkeys(chosen))

    def _survey_slots(self) -> None:
        by_id: dict[Any, Slot] = {}
        for view in self.views:
            refs, inner_rows = self._struct_refs(view)
            present: list[tuple[Any, str, str]] = []  # (identity, kind, label)
            aliases: dict[str, dict[int, list[str]]] = {}
            for oid, names in refs.items():
                if oid in inner_rows:
                    grid, row = inner_rows[oid]
                    aliases.setdefault(grid, {}).setdefault(row, []).extend(n.name for n in names if n.top)
                    continue
                kind = self.cls.kind_of_object(oid, view.heap) or "object"
                present.append((oid, kind, self._label_of(names)))
            for n in view.top_named:
                if n.value.get("k") == "str":
                    present.append((("str", n.name), "string", n.name))
            ids_now = {p[0] for p in present}
            for identity, kind, name in present:
                slot = by_id.get(identity)
                if slot is None:
                    base = name.split(", ")[0]
                    slot = next((s for s in self.slots if s.kind == kind and s.name == base
                                 and s.current not in ids_now), None)
                    if slot is None:
                        slot = Slot(key=f"s{len(self.slots)}", kind=kind, name=base)
                        self.slots.append(slot)
                    by_id[identity] = slot
                slot.current = identity
                slot.by_step[view.index] = identity
                slot.labels[view.index] = name
                slot.max_name = max(slot.max_name, len(name))
                self._measure(slot, identity, view)
                if isinstance(identity, str) and identity in aliases:
                    slot.row_aliases[view.index] = aliases[identity]

    def _measure(self, slot: Slot, identity: Any, view: StepView) -> None:
        if slot.kind == "string":
            text = next(n.value["v"] for n in view.top_named if n.name == identity[1] and n.value.get("k") == "str")
            slot.max_len = max(slot.max_len, len(text))
            slot.max_pointers = max(slot.max_pointers, len(self._index_vars(view, [identity[1]], len(text))))
            return
        obj = view.heap[identity]
        kind = slot.kind
        if kind in ("array", "list"):
            n = obj.get("length", len(obj.get("items", [])))
            slot.max_len = max(slot.max_len, min(n, len(obj.get("items", []))))
            names = slot.labels[view.index].split(", ")
            slot.max_pointers = max(slot.max_pointers, len(self._index_vars(view, names, n)))
            for item in obj.get("items", []):
                slot.max_text = max(slot.max_text, len(values.text(item, view.heap, 0, 8)))
        elif kind == "grid":
            rows = obj.get("items", [])
            slot.max_rows = max(slot.max_rows, len(rows))
            for item in rows:
                inner = view.heap.get(values.ref_id(item)) if values.is_ref(item) else None
                if inner:
                    slot.max_cols = max(slot.max_cols, len(inner.get("items", [])))
                    for cell in inner.get("items", []):
                        slot.max_text = max(slot.max_text, len(values.text(cell, view.heap, 0, 6)))
        elif kind == "builder":
            slot.max_len = max(slot.max_len, len(obj.get("value", "")))
        elif kind == "map":
            for k, v in obj.get("entries", []):
                kt = values.text(k, view.heap, 0, 10)
                if kt not in slot.order:
                    slot.order.append(kt)
                slot.max_text = max(slot.max_text, len(kt), len(values.text(v, view.heap, 1, 12)))
        elif kind == "set":
            for item in obj.get("items", []):
                t = values.text(item, view.heap, 0, 10)
                if t not in slot.order:
                    slot.order.append(t)
                slot.max_text = max(slot.max_text, len(t))
        else:
            slot.max_text = max(slot.max_text, len(values.text({"k": "ref", "id": identity}, view.heap, 2, 48)))

    def _index_vars(self, view: StepView, array_names: list[str], length: int, dim: int = 0) -> list[tuple[str, int]]:
        """Top-frame int variables used to index one of these arrays, with their current value when in range."""
        frame = (view.step.get("frames") or [{}])[0]
        method = frame.get("method")
        wanted = {u["index"] for u in self.index_uses
                  if u["array"] in array_names and u["method"] == method and u["dim"] == dim}
        out = []
        for n in view.top_named:
            if n.name in wanted and n.value.get("k") == "prim" and n.value.get("t") in ("int", "Integer", "long", "short"):
                v = int(n.value["v"])
                if 0 <= v <= length:
                    out.append((n.name, v))
        return out

    # -- survey: linked list positions -------------------------------------------------------------------------

    def _list_nodes(self, view: StepView) -> list[str]:
        return [oid for oid, obj in view.heap.items() if (s := self._node_shape(obj)) and s.kind == "list"]

    def _layout_lists(self) -> None:
        pos: dict[str, tuple[float, float]] = {}
        occupied: set[tuple[float, float]] = set()
        bottom = [0.0]
        row_sp = 1.45 + LABEL_LINE * 2

        max_labels = 1
        for view in self.views:
            per_node: dict[str, int] = {}
            for n in view.top_named:
                if values.is_ref(n.value):
                    oid = values.ref_id(n.value)
                    shape = self._node_shape(view.heap.get(oid))
                    if shape and shape.kind == "list":
                        per_node[oid] = per_node.get(oid, 0) + 1
            if per_node:
                max_labels = max(max_labels, max(per_node.values()))
        self.label_lines = max_labels
        row_sp = 1.45 + LABEL_LINE * max_labels

        def new_row() -> float:
            y = bottom[0]
            bottom[0] -= row_sp
            return y

        def place(oid: str, x: float, y: float) -> None:
            pos[oid] = (x, y)
            occupied.add((round(x, 2), round(y, 2)))

        def free(x: float, y: float) -> bool:
            return (round(x, 2), round(y, 2)) not in occupied

        for view in self.views:
            heap = view.heap
            nodes = self._list_nodes(view)
            if not nodes:
                continue
            starts: list[str] = []
            for n in view.named:
                if values.is_ref(n.value) and values.ref_id(n.value) in heap:
                    oid = values.ref_id(n.value)
                    if (s := self._node_shape(heap[oid])) and s.kind == "list":
                        starts.append(oid)
            starts.extend(nodes)
            for start in starts:
                shape = self._node_shape(heap[start])
                assert shape is not None
                chain = [start]
                while True:
                    nxt = self.cls.next_of(heap[chain[-1]], shape.next_field)
                    if nxt is None or nxt in chain or nxt not in heap:
                        break
                    chain.append(nxt)
                cyclic = len(chain) > 2 and self.cls.next_of(heap[chain[-1]], shape.next_field) == chain[0]
                cyclic = cyclic or (len(chain) > 2 and self.list_override == "circular")
                if cyclic and all(c not in pos for c in chain):
                    radius = max(1.0, len(chain) * LIST_SP / (2 * math.pi))
                    top_y = new_row()
                    extra = 2 * radius + 0.4 - row_sp
                    if extra > 0:
                        bottom[0] -= extra
                    cy = top_y - radius
                    for k, oid in enumerate(chain):
                        angle = math.pi / 2 - 2 * math.pi * k / len(chain)
                        place(oid, radius + radius * math.cos(angle), cy + radius * math.sin(angle))
                    continue
                for k, oid in enumerate(chain):
                    if oid in pos:
                        continue
                    prev = chain[k - 1] if k > 0 else None
                    succ = chain[k + 1] if k + 1 < len(chain) else None
                    if prev is None and succ is None:
                        prev, succ = self._future_neighbors(view.index, oid, pos, shape)
                    if prev in pos:
                        px, py = pos[prev]
                        if free(px + LIST_SP, py):
                            place(oid, px + LIST_SP, py)
                        elif free(px + LIST_SP / 2, py - row_sp / 2):
                            place(oid, px + LIST_SP / 2, py - row_sp / 2)
                        else:
                            place(oid, 0.0, new_row())
                    elif succ in pos and free(pos[succ][0] - LIST_SP, pos[succ][1]):
                        place(oid, pos[succ][0] - LIST_SP, pos[succ][1])
                    else:
                        place(oid, 0.0, new_row())
        self.list_pos = pos

    def _future_neighbors(self, index: int, oid: str, pos: dict[str, tuple[float, float]],
                          shape: NodeShape) -> tuple[str | None, str | None]:
        """For a node that appears on its own: the first placed node that will point to it, or that it will point to.

        Lets a freshly created node (a dummy head, a node about to be appended) appear where it is going to be linked,
        instead of on a row of its own.
        """
        for view in self.views[index:index + 400]:
            heap = view.heap
            if oid not in heap:
                continue
            for other, obj in heap.items():
                if other != oid and other in pos and self.cls.next_of(obj, shape.next_field) == oid:
                    return other, None
            nxt = self.cls.next_of(heap[oid], shape.next_field)
            if nxt is not None and nxt in pos:
                return None, nxt
        return None, None

    # -- survey: pointer colors ---------------------------------------------------------------------------------

    def _survey_colors(self) -> None:
        """Gives every pointer-like variable its color up front so it never changes color between steps."""
        index_vars = {u["index"] for u in self.index_uses}
        for view in self.views:
            for n in view.top_named:
                if values.is_ref(n.value) and self._node_shape(view.heap.get(values.ref_id(n.value))) is not None:
                    self.color_for(n.name)
                elif n.name in index_vars and n.value.get("k") == "prim":
                    self.color_for(n.name)
            for slot in self.slots:
                if view.index in slot.by_step and slot.kind != "string":
                    self.color_for(slot.labels[view.index].split(", ")[0])

    # -- survey: variables row ------------------------------------------------------------------------------------

    def _row_value(self, n: Named, heap: Heap) -> str | None:
        """Text for the variables row, or None when the variable is drawn elsewhere (pointer label or slot)."""
        v = n.value
        if v.get("k") in ("prim", "null"):
            return values.text(v, heap)
        if v.get("k") == "str":
            return None
        obj = heap.get(values.ref_id(v))
        if obj is None:
            return v.get("cls", "?")
        if self._node_shape(obj) is not None:
            return None
        if obj.get("kind") == "opaque":
            return values.text(v, heap, limit=16)
        return None

    def _survey_vars(self) -> None:
        for view in self.views:
            for n in view.top_named:
                text = self._row_value(n, view.heap)
                if text is None:
                    continue
                if n.name not in self.var_width:
                    self.var_order.append(n.name)
                    self.var_width[n.name] = 0.0
                self.var_width[n.name] = max(self.var_width[n.name], S.text_width(values.clip(text, 14), FS_CELL) + 0.3)
            for r in view.step.get("returns", []):
                if view.step["event"] == "return" and "value" in r:
                    if "return" not in self.var_width:
                        self.var_order.append("return")
                        self.var_width["return"] = 0.0
                    text = values.text(r["value"], view.heap, limit=14)
                    self.var_width["return"] = max(self.var_width["return"], S.text_width(text, FS_CELL) + 0.3)

    # -- structures and placement ---------------------------------------------------------------------------------

    def _structures(self) -> list["Struct"]:
        out: list[Struct] = []
        if self.list_pos:
            out.append(ListStruct(self))
        if any(self._tree_roots(v) for v in self.views):
            out.append(TreeStruct(self))
        for slot in self.slots:
            out.append(SlotStruct(self, slot))
        if self.var_order:
            out.append(VarsStruct(self))
        return out

    def _place(self, structures: list["Struct"]) -> list[tuple[float, float, float]]:
        boxes = [s.bbox() for s in structures]
        scales = []
        for struct, (x0, x1, y0, y1) in zip(structures, boxes):
            w = max(x1 - x0, 0.01)
            scales.append(min(struct.max_scale, CANVAS_W / w))
        banner = BANNER_H if self.error else 0.0
        avail = CANVAS_TOP - CANVAS_BOTTOM - banner
        total = sum((b[3] - b[2]) * s for b, s in zip(boxes, scales)) + STRUCT_GAP * max(0, len(boxes) - 1)
        g = min(1.0, avail / total) if total > 0 else 1.0
        if g < 1.0:
            scales = [min(sc, 1.0) for sc in scales]
            total = sum((b[3] - b[2]) * s for b, s in zip(boxes, scales)) + STRUCT_GAP * max(0, len(boxes) - 1)
            g = min(1.0, avail / total)
        y = CANVAS_TOP - banner - max(0.0, (avail - total * g) / 2)
        out = []
        for (x0, x1, y0, y1), s in zip(boxes, scales):
            s *= g
            dx = -(x0 + x1) / 2 * s
            dy = y - y1 * s
            out.append((s, dx, dy))
            y -= (y1 - y0) * s + STRUCT_GAP * g
        return out

    # -- trees ----------------------------------------------------------------------------------------------------

    def _tree_nodes(self, view: StepView) -> list[str]:
        return [oid for oid, obj in view.heap.items() if (s := self._node_shape(obj)) and s.kind == "tree"]

    def _tree_roots(self, view: StepView) -> list[str]:
        nodes = self._tree_nodes(view)
        children = set()
        for oid in nodes:
            shape = self._node_shape(view.heap[oid])
            for f in shape.child_fields if shape else ():
                c = self.cls.next_of(view.heap[oid], f)
                if c:
                    children.add(c)
        roots = [oid for oid in nodes if oid not in children]
        named = [values.ref_id(n.value) for n in view.named if values.is_ref(n.value)]
        roots.sort(key=lambda r: named.index(r) if r in named else len(named))
        return roots

    def tree_layout(self, view: StepView) -> dict[str, tuple[float, float]]:
        pos: dict[str, tuple[float, float]] = {}
        counter = [0]

        def walk(oid: str, depth: int, seen: set[str]) -> None:
            if oid in seen or oid not in view.heap:
                return
            seen.add(oid)
            obj = view.heap[oid]
            shape = self._node_shape(obj)
            left = self.cls.next_of(obj, "left") if shape and "left" in shape.child_fields else None
            right = self.cls.next_of(obj, "right") if shape and "right" in shape.child_fields else None
            if left:
                walk(left, depth + 1, seen)
            pos[oid] = (counter[0] * TREE_SP, -depth * TREE_LEVEL)
            counter[0] += 1
            if right:
                walk(right, depth + 1, seen)

        seen: set[str] = set()
        for root in self._tree_roots(view):
            walk(root, 0, seen)
            counter[0] += 1
        return pos

    # -- ghosts and errors ----------------------------------------------------------------------------------------

    def _ghosts(self, view: StepView, gone: set[str], structures: list["Struct"],
                placements: list[tuple[float, float, float]]) -> list[Element]:
        out = []
        for struct, (s, dx, dy) in zip(structures, placements):
            if not isinstance(struct, ListStruct):
                continue
            for key in sorted(gone):
                oid = key.split(":", 1)[1]
                if oid in self.list_pos:
                    x, y = self.list_pos[oid]
                    text = self._last_value(view.index, oid)
                    el = circle(key, x, y, NODE_R, S.GHOST_FILL, S.GHOST, text, S.MUTED, fit_font(text, NODE_R * 1.7, FS_NODE))
                    el["ghost"] = True
                    out.append(transform(el, s, dx, dy))
        return out

    def _last_value(self, index: int, oid: str) -> str:
        for view in reversed(self.views[:index]):
            obj = view.heap.get(oid)
            if obj is not None:
                shape = self._node_shape(obj)
                field_name = shape.value_field if shape else None
                return next((values.text(f["value"], view.heap, 0, 6) for f in obj["fields"] if f["name"] == field_name), "")
        return ""

    def _error_marks(self, view: StepView, elements: list[Element]) -> list[Element]:
        err = self.error
        if not err or view.step.get("event") != "exception":
            return []
        name = values.short_type(err.get("type") or "Error")
        message = err.get("message") or ""
        banner = f"{name}: {message}" if message else name
        out = [label("error:banner", 0.0, CANVAS_TOP - BANNER_H / 2 + 0.05, values.clip(banner, 92), S.ERROR,
                     fit_font(values.clip(banner, 92), CANVAS_W, 20))]
        by_key = {el["key"]: el for el in elements}
        np = re.search(r'because "([^"]+)" is null', message)
        if np:
            expr = np.group(1)
            parts = expr.split(".")
            if len(parts) == 1:
                for key in (f"varval:{expr}", f"varname:{expr}"):
                    if key in by_key:
                        by_key[key]["stroke"] = S.ERROR
                        by_key[key]["color"] = S.ERROR
            else:
                target = self._resolve(view, parts[:-1])
                if target:
                    for key in (f"nullarrow:{target}:{parts[-1]}", f"nulltext:{target}:{parts[-1]}"):
                        if key in by_key:
                            by_key[key]["color"] = S.ERROR
                    if f"node:{target}" in by_key:
                        by_key[f"node:{target}"]["stroke"] = S.ERROR
        oob = re.search(r"[Ii]ndex:? (-?\d+),? out of bounds for length:? (\d+)", message) or \
            re.search(r"index (-?\d+), ?length (\d+)", message)
        if oob:
            index, length = int(oob.group(1)), int(oob.group(2))
            out.extend(self._ghost_cell(view, by_key, index, length))
        return out

    def _resolve(self, view: StepView, path: list[str]) -> str | None:
        cur: str | None = None
        for k, part in enumerate(path):
            if k == 0:
                n = next((n for n in view.top_named if n.name == part), None)
                cur = values.ref_id(n.value) if n and values.is_ref(n.value) else None
            elif cur is not None:
                cur = self.cls.next_of(view.heap.get(cur, {}), part)
            if cur is None:
                return None
        return cur

    def _ghost_cell(self, view: StepView, by_key: dict[str, Element], index: int, length: int) -> list[Element]:
        line = view.step.get("line")
        used = {u["array"] for u in self.index_uses if u["line"] == line}
        candidates = []
        for slot in self.slots:
            if view.index not in slot.by_step:
                continue
            names = set(slot.labels[view.index].split(", "))
            cells = [by_key.get(f"{slot.key}:c{i}") for i in range(length)]
            if length == 0:
                first = by_key.get(f"{slot.key}:name")
                if first is None:
                    continue
            elif not all(cells):
                continue
            candidates.append((0 if names & used else 1, slot, cells))
        if not candidates:
            return []
        candidates.sort(key=lambda c: c[0])
        _, slot, cells = candidates[0]
        if cells and cells[0] is not None:
            ref = cells[-1] if index >= length else cells[0]
            step = (cells[1]["x"] - cells[0]["x"]) if len(cells) > 1 else ref["w"] * CELL_STEP / CELL
            x = ref["x"] + step if index >= length else ref["x"] - step
            ghost = box(f"{slot.key}:ghost", x, ref["y"], ref["w"], ref["h"], S.ERROR_FILL, S.ERROR, f"[{index}]",
                        S.ERROR, fit_font(f"[{index}]", ref["w"], ref["fs"]), dashed=True)
            return [ghost]
        return []


def transform(el: Element, s: float, dx: float, dy: float) -> Element:
    out = dict(el)
    for kx, ky in (("x", "y"), ("x1", "y1"), ("x2", "y2")):
        if kx in out:
            out[kx] = round(out[kx] * s + dx, 4)
            out[ky] = round(out[ky] * s + dy, 4)
    for k in ("r", "w", "h", "fs", "corner"):
        if k in out:
            out[k] = round(out[k] * s, 4)
    if "width" in out:
        out["width"] = round(max(1.5, out["width"] * min(1.0, s * 1.2)), 3)
    return out


# ---- structure renderers ----------------------------------------------------------------------------------------

class Struct:
    max_scale = MAX_UPSCALE

    def __init__(self, builder: Builder) -> None:
        self.b = builder

    def bbox(self) -> tuple[float, float, float, float]:
        raise NotImplementedError

    def emit(self, view: StepView) -> list[Element]:
        raise NotImplementedError


def pointer_labels(b: Builder, view: StepView, targets: dict[str, tuple[float, float]], r: float,
                   extra: Iterable[tuple[str, str]] = ()) -> list[Element]:
    """Variable names stacked above the node each one points at, with one arrow per node."""
    per_node: dict[str, list[str]] = {}
    for n in view.top_named:
        if values.is_ref(n.value) and values.ref_id(n.value) in targets:
            per_node.setdefault(values.ref_id(n.value), []).append(n.name)
    for name, oid in extra:
        if oid in targets:
            per_node.setdefault(oid, []).append(name)
    out = []
    for oid, names in per_node.items():
        x, y = targets[oid]
        base = y + r + 0.42
        for k, name in enumerate(dict.fromkeys(names)):
            out.append(label(f"varname:{name}", x, base + k * LABEL_LINE, name, b.color_for(name), FS_LABEL))
        out.append(arrow(f"ptrarrow:{oid}", x, base - 0.15, x, y + r + 0.03, S.MUTED, width=2.0))
    return out


class ListStruct(Struct):
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.b.list_pos.values()]
        ys = [p[1] for p in self.b.list_pos.values()]
        top = max(ys) + NODE_R + 0.42 + LABEL_LINE * self.b.label_lines
        return min(xs) - NODE_R - 0.8, max(xs) + NODE_R + 0.8, min(ys) - NODE_R - 0.85, top

    def emit(self, view: StepView) -> list[Element]:
        b = self.b
        pos = b.list_pos
        out: list[Element] = []
        nodes = [oid for oid in b._list_nodes(view) if oid in pos]
        for oid in nodes:
            obj = view.heap[oid]
            shape = b._node_shape(obj)
            assert shape is not None
            x, y = pos[oid]
            val = next((values.text(f["value"], view.heap, 0, 6) for f in obj["fields"] if f["name"] == shape.value_field), "")
            out.append(circle(f"node:{oid}", x, y, NODE_R, S.LIST_FILL, S.LIST_STROKE, val, "#FFFFFF",
                              fit_font(val, NODE_R * 1.7, FS_NODE)))
            draw_prev = shape.prev_field is not None and b.list_override != "singly"
            for field_name, is_prev in ((shape.next_field, False), (shape.prev_field if draw_prev else None, True)):
                if field_name is None:
                    continue
                target = b.cls.next_of(obj, field_name)
                if target is None:
                    out.extend(self._null_marker(oid, field_name, x, y, is_prev, draw_prev))
                elif target in pos:
                    out.append(self._edge(f"edge:{oid}:{field_name}", (x, y), pos[target], is_prev, draw_prev))
        extra = []
        if view.step.get("event") == "return":
            for r in view.step.get("returns", []):
                if values.is_ref(r.get("value")):
                    extra.append(("return", values.ref_id(r["value"])))
        out.extend(pointer_labels(b, view, {oid: pos[oid] for oid in nodes}, NODE_R, extra))
        return out

    @staticmethod
    def _null_marker(oid: str, field_name: str, x: float, y: float, is_prev: bool, doubly: bool) -> list[Element]:
        if not doubly:
            x1, y1, x2, y2, tx, ty = x, y - NODE_R, x, y - NODE_R - 0.38, x, y - NODE_R - 0.56
        else:
            sign = -1 if is_prev else 1
            x1, y1 = x + sign * NODE_R * 0.7, y - NODE_R * 0.7
            x2, y2 = x + sign * 0.62, y - 0.78
            tx, ty = x + sign * 0.72, y - 0.95
        return [
            arrow(f"nullarrow:{oid}:{field_name}", x1, y1, x2, y2, S.NULL_TEXT, width=2.0),
            label(f"nulltext:{oid}:{field_name}", tx, ty, "null", S.NULL_TEXT, FS_SMALL),
        ]

    @staticmethod
    def _edge(key: str, a: tuple[float, float], b: tuple[float, float], is_prev: bool, doubly: bool) -> Element:
        (ax, ay), (bx, by) = a, b
        dx, dy = bx - ax, by - ay
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return arrow(key, ax + 0.12, ay + NODE_R, ax - 0.12, ay + NODE_R, S.LIST_EDGE, curve=-4.4)
        same_row = abs(dy) < 1e-6
        if same_row and abs(dx) <= LIST_SP * 1.01:
            off = (0.1 if dx > 0 else -0.1) if doubly else (0.0 if dx > 0 else -0.08)
            sx = 1 if dx > 0 else -1
            gap = math.sqrt(max(NODE_R ** 2 - off ** 2, 0.0))
            return arrow(key, ax + sx * gap, ay + off, bx - sx * gap, by + off, S.LIST_EDGE)
        if same_row:
            sx = 1 if dx > 0 else -1
            sy = 1 if dx > 0 else -1
            return arrow(key, ax + sx * NODE_R * 0.5, ay + sy * NODE_R * 0.87, bx - sx * NODE_R * 0.5,
                         by + sy * NODE_R * 0.87, S.LIST_EDGE, curve=-0.9)
        d = math.hypot(dx, dy)
        ux, uy = dx / d, dy / d
        if abs(dx) < LIST_SP * 0.6:
            # Nearly vertical: start and end off-center and bow to the side, clear of the label stack above nodes.
            side = 1 if dy < 0 else -1
            ang = math.radians(35)
            sx, sy = math.sin(ang) * NODE_R * side, math.cos(ang) * NODE_R
            vy = -1 if dy < 0 else 1
            return arrow(key, ax + sx, ay + vy * sy, bx + sx, by - vy * sy, S.LIST_EDGE, curve=0.7 * side * -vy)
        return arrow(key, ax + ux * NODE_R, ay + uy * NODE_R, bx - ux * NODE_R, by - uy * NODE_R, S.LIST_EDGE)


class TreeStruct(Struct):
    def __init__(self, builder: Builder) -> None:
        super().__init__(builder)
        self.layouts = [builder.tree_layout(v) for v in builder.views]

    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for lay in self.layouts for p in lay.values()] or [0.0]
        ys = [p[1] for lay in self.layouts for p in lay.values()] or [0.0]
        top = NODE_R + 0.42 + LABEL_LINE * 2
        return min(xs) - NODE_R - 0.3, max(xs) + NODE_R + 0.3, min(ys) - NODE_R - 0.2, top

    def emit(self, view: StepView) -> list[Element]:
        b = self.b
        pos = self.layouts[view.index]
        if pos:
            xs = [p[0] for p in pos.values()]
            all_xs = [p[0] for lay in self.layouts for p in lay.values()]
            shift = (min(all_xs) + max(all_xs)) / 2 - (min(xs) + max(xs)) / 2
            pos = {k: (x + shift, y) for k, (x, y) in pos.items()}
        out: list[Element] = []
        for oid, (x, y) in pos.items():
            obj = view.heap[oid]
            shape = b._node_shape(obj)
            assert shape is not None
            val = next((values.text(f["value"], view.heap, 0, 6) for f in obj["fields"] if f["name"] == shape.value_field), "")
            out.append(circle(f"node:{oid}", x, y, NODE_R, S.TREE_FILL, S.TREE_STROKE, val, "#FFFFFF",
                              fit_font(val, NODE_R * 1.7, FS_NODE)))
            for f in shape.child_fields:
                c = b.cls.next_of(obj, f)
                if c and c in pos:
                    cx, cy = pos[c]
                    d = math.hypot(cx - x, cy - y)
                    ux, uy = (cx - x) / d, (cy - y) / d
                    out.append(arrow(f"edge:{oid}:{f}", x + ux * NODE_R, y + uy * NODE_R, cx - ux * NODE_R,
                                     cy - uy * NODE_R, S.TREE_EDGE, width=2.5))
        out.extend(pointer_labels(b, view, pos, NODE_R))
        return out


class SlotStruct(Struct):
    max_scale = 1.3
    def __init__(self, builder: Builder, slot: Slot) -> None:
        super().__init__(builder)
        self.slot = slot

    def name_width(self) -> float:
        return S.text_width("m" * self.slot.max_name, FS_NAME) + 0.3

    def cell_width(self) -> float:
        return max(CELL, S.text_width("m" * min(self.slot.max_text, 8), FS_CELL * 0.8) + 0.2)

    def bbox(self) -> tuple[float, float, float, float]:
        slot = self.slot
        nw = self.name_width()
        if slot.kind in ("array", "list", "string", "builder"):
            w = max(1, slot.max_len) * (self.cell_width() + CELL_STEP - CELL)
            depth = CELL + 0.32 + (0.5 + 0.36 * (slot.max_pointers - 1) + 0.1 if slot.max_pointers else 0)
            return -nw, w, -depth, 0.0
        if slot.kind == "grid":
            cw = self.cell_width() + CELL_STEP - CELL
            return -nw - 0.4, max(1, slot.max_cols) * cw, -max(1, slot.max_rows) * CELL_STEP, 0.65
        if slot.kind in ("map", "set"):
            cw = self.cell_width() + 0.1
            rows = 2 if slot.kind == "map" else 1
            return -nw, max(1, len(slot.order)) * cw, -rows * CELL_STEP, 0.0
        w = S.text_width("m" * slot.max_text, FS_CELL * 0.8) + 0.4
        return -nw, w, -CELL, 0.0

    def emit(self, view: StepView) -> list[Element]:
        slot = self.slot
        if view.index not in slot.by_step:
            return []
        identity = slot.by_step[view.index]
        name = slot.labels[view.index]
        nw = self.name_width()
        out: list[Element] = []
        top_names = name.split(", ")
        name_color = self.b.color_for(top_names[0]) if slot.kind != "string" else S.STRING_STROKE
        cw = self.cell_width()
        step_w = cw + CELL_STEP - CELL

        if slot.kind == "grid":
            out.append(label(f"{slot.key}:name", -nw - 0.4 + S.text_width(name, FS_NAME) / 2, 0.45, name,
                             name_color, FS_NAME))
        else:
            out.append(label(f"{slot.key}:name", -0.25 - S.text_width(name, FS_NAME) / 2, -CELL / 2, name,
                             name_color, FS_NAME))

        if slot.kind == "string":
            text = next(n.value["v"] for n in view.top_named if n.name == identity[1] and n.value.get("k") == "str")
            out.extend(self._cells(list(text), S.STRING_FILL, S.STRING_STROKE, S.STRING_TEXT, cw, step_w))
            out.extend(self._pointers(view, [identity[1]], len(text), step_w, cw))
            return out
        obj = view.heap[identity]
        if slot.kind in ("array", "list"):
            items = [cell_text(i, view.heap) for i in obj.get("items", [])]
            fill, stroke, color = (S.ARRAY_FILL, S.ARRAY_STROKE, S.ARRAY_TEXT) if slot.kind == "array" else \
                (S.COLLECTION_FILL, S.COLLECTION_STROKE, "#FFFFFF")
            out.extend(self._cells(items, fill, stroke, color, cw, step_w))
            if slot.kind == "array":
                out.extend(self._pointers(view, top_names, obj.get("length", len(items)), step_w, cw))
        elif slot.kind == "builder":
            out.extend(self._cells(list(obj.get("value", "")), S.STRING_FILL, S.STRING_STROKE, S.STRING_TEXT, cw, step_w))
        elif slot.kind == "grid":
            out.extend(self._grid(view, obj, cw, step_w, top_names))
        elif slot.kind == "map":
            entries = {values.text(k, view.heap, 0, 10): values.text(v, view.heap, 1, 12) for k, v in obj.get("entries", [])}
            for i, k in enumerate(slot.order):
                if k not in entries:
                    continue
                x = i * (cw + 0.1) + cw / 2
                out.append(box(f"{slot.key}:k:{k}", x, -CELL / 2, cw, CELL, S.MAP_KEY_FILL, S.MAP_STROKE, k, "#FFFFFF",
                               fit_font(k, cw, FS_CELL)))
                v = entries[k]
                out.append(box(f"{slot.key}:v:{k}", x, -CELL / 2 - CELL_STEP, cw, CELL, S.MAP_VALUE_FILL, S.MAP_STROKE,
                               v, "#FFFFFF", fit_font(v, cw, FS_CELL)))
        elif slot.kind == "set":
            present = {values.text(i, view.heap, 0, 10) for i in obj.get("items", [])}
            for i, k in enumerate(slot.order):
                if k in present:
                    out.append(box(f"{slot.key}:m:{k}", i * (cw + 0.1) + cw / 2, -CELL / 2, cw, CELL, S.SET_FILL,
                                   S.SET_STROKE, k, "#FFFFFF", fit_font(k, cw, FS_CELL), corner=0.3))
        else:
            text = values.text({"k": "ref", "id": identity}, view.heap, 2, 48)
            w = S.text_width("m" * slot.max_text, FS_CELL * 0.8) + 0.4
            out.append(box(f"{slot.key}:obj", w / 2, -CELL / 2, w, CELL, S.OBJECT_FILL, S.OBJECT_STROKE, text, S.TEXT,
                           fit_font(text, w, FS_CELL * 0.8)))
        return out

    def _cells(self, items: list[str], fill: str, stroke: str, color: str, cw: float, step_w: float) -> list[Element]:
        out = []
        for i, t in enumerate(items):
            x = i * step_w + cw / 2
            out.append(box(f"{self.slot.key}:c{i}", x, -CELL / 2, cw, CELL, fill, stroke, t, color, fit_font(t, cw, FS_CELL)))
            out.append(label(f"{self.slot.key}:i{i}", x, -CELL - 0.17, str(i), S.MUTED, FS_SMALL))
        return out

    def _pointers(self, view: StepView, names: list[str], length: int, step_w: float, cw: float) -> list[Element]:
        out = []
        stacks: dict[int, int] = {}
        for var, v in self.b._index_vars(view, names, length):
            k = stacks.get(v, 0)
            stacks[v] = k + 1
            x = v * step_w + cw / 2
            y_text = -CELL - 0.62 - k * 0.36
            color = self.b.color_for(var)
            if k == 0:
                out.append(arrow(f"{self.slot.key}:pa:{var}", x, y_text + 0.17, x, -CELL - 0.3, color, width=2.5))
            out.append(label(f"{self.slot.key}:p:{var}", x, y_text, var, color, FS_LABEL))
        return out

    def _grid(self, view: StepView, obj: dict[str, Any], cw: float, step_w: float, names: list[str]) -> list[Element]:
        slot = self.slot
        out = []
        rows = obj.get("items", [])
        aliases = slot.row_aliases.get(view.index, {})
        ncols = 0
        for r, item in enumerate(rows):
            y = -r * CELL_STEP - CELL / 2
            out.append(label(f"{slot.key}:ri{r}", -0.3, y, str(r), S.MUTED, FS_SMALL))
            if r in aliases and aliases[r]:
                alias = ", ".join(aliases[r])
                out.append(label(f"{slot.key}:ra{r}", -0.55 - S.text_width(alias, FS_SMALL) / 2, y, alias,
                                 self.b.color_for(aliases[r][0]), FS_SMALL))
            inner = view.heap.get(values.ref_id(item)) if values.is_ref(item) else None
            if inner is None:
                continue
            cells = inner.get("items", [])
            ncols = max(ncols, len(cells))
            for c, cell in enumerate(cells):
                t = cell_text(cell, view.heap, 6)
                out.append(box(f"{slot.key}:r{r}c{c}", c * step_w + cw / 2, y, cw, CELL, S.ARRAY_FILL, S.ARRAY_STROKE,
                               t, S.ARRAY_TEXT, fit_font(t, cw, FS_CELL)))
        for c in range(ncols):
            out.append(label(f"{slot.key}:ci{c}", c * step_w + cw / 2, 0.2, str(c), S.MUTED, FS_SMALL))
        for var, v in self.b._index_vars(view, names, len(rows), dim=0):
            y = -v * CELL_STEP - CELL / 2
            color = self.b.color_for(var)
            out.append(label(f"{slot.key}:p:{var}", -1.0 - S.text_width(var, FS_SMALL) / 2, y, var, color, FS_SMALL))
        for var, v in self.b._index_vars(view, names, ncols, dim=1):
            color = self.b.color_for(var)
            out.append(label(f"{slot.key}:q:{var}", v * step_w + cw / 2, 0.45, var, color, FS_SMALL))
        return out


class VarsStruct(Struct):
    """The row of plain variables (ints, chars, booleans, null pointers) at the bottom of the canvas."""

    ROW_H = 0.62
    max_scale = 1.15

    def __init__(self, builder: Builder) -> None:
        super().__init__(builder)
        self.slots: dict[str, tuple[float, float, float]] = {}  # name -> (x of name center, x of box center, row y)
        x, row = 0.0, 0
        for name in builder.var_order:
            nw = S.text_width(name, FS_LABEL)
            bw = builder.var_width[name]
            needed = nw + 0.15 + bw
            if x > 0 and x + needed > CANVAS_W:
                x, row = 0.0, row + 1
            self.slots[name] = (x + nw / 2, x + nw + 0.15 + bw / 2, -row * self.ROW_H - CELL / 2)
            x += needed + 0.45
        self.rows = row + 1
        self.width = max((v[1] + builder.var_width[k] / 2 for k, v in self.slots.items()), default=1.0)

    def bbox(self) -> tuple[float, float, float, float]:
        return 0.0, self.width, -self.rows * self.ROW_H, 0.0

    def emit(self, view: StepView) -> list[Element]:
        b = self.b
        out = []
        shown: list[tuple[str, str]] = []
        for n in view.top_named:
            text = b._row_value(n, view.heap)
            if text is not None and n.name in self.slots:
                shown.append((n.name, text))
        if view.step.get("event") == "return":
            for r in view.step.get("returns", []):
                if "value" in r and not values.is_ref(r["value"]):
                    shown.append(("return", values.text(r["value"], view.heap, limit=14)))
        for name, text in dict(shown).items():
            nx, bx, y = self.slots[name]
            text = values.clip(text, 14)
            bw = b.var_width[name]
            is_null = text == "null"
            color = b.pointer_colors.get(name, S.VAR_NAME)
            out.append(label(f"varname:{name}", nx, y, name, color, FS_LABEL))
            out.append(box(f"varval:{name}", bx, y, bw, 0.5, S.VAR_FILL, S.VAR_STROKE, text,
                           S.NULL_TEXT if is_null else S.TEXT, fit_font(text, bw, FS_CELL * 0.85)))
        return out

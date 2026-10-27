"""Decides what each runtime object is (linked list node, tree node, array, map, ...) and how to draw it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import values

LIST_KINDS = {"singly": "Linked list (singly)", "doubly": "Linked list (doubly)", "circular": "Linked list (circular)"}
TREE_FIELDS = ("left", "right")
NEXT_NAMES = ("next", "nxt", "link")
PREV_NAMES = ("prev", "previous", "back")
VALUE_NAMES = ("val", "value", "data", "key")


@dataclass(frozen=True)
class NodeShape:
    """A class whose objects are nodes in a linked structure."""

    kind: str  # "list" or "tree"
    value_field: str | None
    next_field: str | None = None
    prev_field: str | None = None
    child_fields: tuple[str, ...] = ()


class Classifier:
    def __init__(self, trace: dict[str, Any], overrides: dict[str, str] | None = None) -> None:
        self.classes: dict[str, Any] = trace.get("classes", {})
        self.overrides = overrides or {}
        self._shapes: dict[str, NodeShape | None] = {}

    def shape(self, type_name: str) -> NodeShape | None:
        if type_name not in self._shapes:
            self._shapes[type_name] = self._compute_shape(type_name)
        return self._shapes[type_name]

    def _compute_shape(self, type_name: str) -> NodeShape | None:
        info = self.classes.get(type_name)
        if not info:
            return None
        fields = info["fields"]
        self_fields = [f["name"] for f in fields if f["type"] == type_name]
        others = [f["name"] for f in fields if f["type"] != type_name]
        value_field = next((n for n in VALUE_NAMES if n in others), others[0] if others else None)
        if not self_fields:
            return None
        if any(n in self_fields for n in TREE_FIELDS):
            children = tuple(n for n in TREE_FIELDS if n in self_fields)
            return NodeShape("tree", value_field, child_fields=children)
        next_field = next((n for n in NEXT_NAMES if n in self_fields), self_fields[0])
        rest = [n for n in self_fields if n != next_field]
        prev_field = next((n for n in PREV_NAMES if n in rest), rest[0] if rest else None)
        return NodeShape("list", value_field, next_field=next_field, prev_field=prev_field)

    def node_shape_of(self, obj: dict[str, Any] | None) -> NodeShape | None:
        if not obj or obj.get("kind") != "object":
            return None
        return self.shape(obj["type"])

    def kind_of_object(self, obj_id: str, heap: values.Heap, var: str | None = None) -> str | None:
        obj = heap.get(obj_id)
        if obj is None:
            return None
        if var and var in self.overrides:
            return self.overrides[var]
        shape = self.node_shape_of(obj)
        if shape is not None:
            if shape.kind == "tree":
                return "tree"
            if self.is_cycle_start(obj_id, heap, shape):
                return "circular"
            return "doubly" if shape.prev_field else "singly"
        kind = obj.get("kind")
        if kind == "array":
            return "grid" if obj.get("type", "").endswith("[][]") else "array"
        if kind in ("list", "map", "set", "builder", "object"):
            return kind
        return None

    def kind_of_value(self, value: values.Value, heap: values.Heap, var: str | None = None) -> str | None:
        if value.get("k") == "str":
            return "string"
        if not values.is_ref(value):
            return None
        return self.kind_of_object(values.ref_id(value), heap, var)

    def options_for(self, value: values.Value, heap: values.Heap) -> list[dict[str, str]]:
        """Dropdown choices for a variable; empty when there is nothing to choose."""
        kind = self.kind_of_value(value, heap)
        if kind in LIST_KINDS:
            return [{"value": k, "label": label} for k, label in LIST_KINDS.items()]
        return []

    def next_of(self, obj: dict[str, Any], field: str | None) -> str | None:
        if field is None:
            return None
        for f in obj.get("fields", []):
            if f["name"] == field and values.is_ref(f["value"]):
                return values.ref_id(f["value"])
        return None

    def is_cycle_start(self, obj_id: str, heap: values.Heap, shape: NodeShape) -> bool:
        seen = set()
        cur: str | None = obj_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            obj = heap.get(cur)
            if obj is None:
                return False
            cur = self.next_of(obj, shape.next_field)
            if cur == obj_id:
                return True
        return False

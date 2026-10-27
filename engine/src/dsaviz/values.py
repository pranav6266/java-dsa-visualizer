"""Helpers for the tracer's value encoding.

A value is one of:
  {"k": "null"}
  {"k": "prim", "t": "int", "v": 5}            (also boxed types, with t = "Integer" etc.)
  {"k": "str", "v": "abc"}
  {"k": "ref", "id": 123, "cls": "ListNode"}   (the object itself lives in the step's heap)
"""

from __future__ import annotations

from typing import Any

Value = dict[str, Any]
Heap = dict[str, dict[str, Any]]


def is_ref(v: Value | None) -> bool:
    return bool(v) and v.get("k") == "ref"


def ref_id(v: Value) -> str:
    return str(v["id"])


def short_type(type_name: str) -> str:
    """`java.util.List` -> `List`, `Solution$Pair` -> `Pair`, `int[]` stays."""
    base = type_name.rsplit(".", 1)[-1]
    return base.rsplit("$", 1)[-1]


def prim_text(v: Value) -> str:
    t, x = v.get("t"), v.get("v")
    if t in ("char", "Character"):
        return f"'{x}'"
    if t in ("boolean", "Boolean"):
        return "true" if x else "false"
    if t in ("double", "float", "Double", "Float"):
        return format_float(x)
    return str(x)


def format_float(x: float) -> str:
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x)}.0"
    return f"{x:.4g}"


def text(v: Value | None, heap: Heap, depth: int = 2, limit: int = 40) -> str:
    """Compact human-readable text for a value, like a debugger's variable view."""
    if v is None:
        return ""
    kind = v.get("k")
    if kind == "null":
        return "null"
    if kind == "prim":
        return prim_text(v)
    if kind == "str":
        return clip('"' + v["v"] + '"', limit)
    obj = heap.get(ref_id(v))
    if obj is None:
        return v.get("cls", "object")
    return clip(object_text(obj, heap, depth), limit)


def object_text(obj: dict[str, Any], heap: Heap, depth: int) -> str:
    kind = obj.get("kind")
    cls = obj.get("cls", "")
    if depth <= 0:
        if kind == "array":
            return f"{cls.split('[')[0]}[{obj.get('length', 0)}]"
        return cls
    if kind in ("array", "list"):
        items = ", ".join(text(i, heap, depth - 1, 16) for i in obj.get("items", []))
        more = obj.get("length", len(obj.get("items", []))) > len(obj.get("items", []))
        body = "[" + items + (", ..." if more else "") + "]"
        return body if kind == "array" else f"{cls}{body}"
    if kind == "set":
        return cls + "{" + ", ".join(text(i, heap, depth - 1, 16) for i in obj.get("items", [])) + "}"
    if kind == "map":
        parts = [f"{text(k, heap, depth - 1, 12)}={text(val, heap, depth - 1, 16)}" for k, val in obj.get("entries", [])]
        return cls + "{" + ", ".join(parts) + "}"
    if kind == "builder":
        return f'{cls}("{obj.get("value", "")}")'
    if kind == "object":
        fields = obj.get("fields", [])
        shown = [f for f in fields if not is_ref(f["value"]) or depth > 1][:3]
        parts = []
        for f in shown:
            fv = f["value"]
            parts.append(f"{f['name']}={text(fv, heap, 0, 12) if is_ref(fv) else text(fv, heap)}")
        return f"{cls}(" + ", ".join(parts) + ")"
    return cls


def clip(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"

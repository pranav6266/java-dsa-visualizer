"""Colors, sizes and text metrics shared by the layout and the Manim renderer."""

from __future__ import annotations

BACKGROUND = "#0B0C0E"

LIST_FILL = "#6D28D9"
LIST_STROKE = "#C4B5FD"
LIST_EDGE = "#C4B5FD"
TREE_FILL = "#166534"
TREE_STROKE = "#86EFAC"
TREE_EDGE = "#86EFAC"
GHOST = "#4B5563"
GHOST_FILL = "#1F2329"

ARRAY_FILL = "#FACC15"
ARRAY_STROKE = "#FDE68A"
ARRAY_TEXT = "#1C1917"
STRING_FILL = "#0EA5E9"
STRING_STROKE = "#7DD3FC"
STRING_TEXT = "#F8FAFC"
MAP_KEY_FILL = "#0F766E"
MAP_VALUE_FILL = "#134E4A"
MAP_STROKE = "#5EEAD4"
SET_FILL = "#C2410C"
SET_STROKE = "#FDBA74"
COLLECTION_FILL = "#BE185D"
COLLECTION_STROKE = "#F9A8D4"
OBJECT_FILL = "#1F2937"
OBJECT_STROKE = "#9CA3AF"

VAR_NAME = "#9CA3AF"
VAR_FILL = "#16181D"
VAR_STROKE = "#4B5563"
TEXT = "#E5E7EB"
MUTED = "#8B9099"
NULL_TEXT = "#8B9099"
ERROR = "#EF4444"
ERROR_FILL = "#450A0A"

POINTER_COLORS = ["#FB923C", "#4ADE80", "#38BDF8", "#F472B6", "#FDE047", "#A78BFA", "#2DD4BF", "#FCA5A5"]

FONT = "JetBrains Mono"
CHAR_WIDTH = 0.00814  # Manim units per character per font-size point, measured for JetBrains Mono.
CAP_HEIGHT = 0.0102


def text_width(text: str, font_size: float) -> float:
    return len(text) * CHAR_WIDTH * font_size

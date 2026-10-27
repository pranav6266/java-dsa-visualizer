# Java DSA Visualizer

A debugger with Manim animations for LeetCode-style Java solutions.
Paste a `class Solution`, type the input the way LeetCode shows it, press Run, and step through your code line by line while each data structure animates next to it.

## Run it

Open **DSA Visualizer** from the app launcher.
It starts the server, opens an app window, and the server stops itself about three minutes after you close the window.
The launcher is `app/dsaviz-app`; its desktop entry lives in `~/.local/share/applications/DSA Visualizer.desktop`.

From a terminal instead:

```bash
./dsaviz          # then open http://localhost:8765
./dsaviz --open   # also opens the browser
```

The first start builds the Java tracer and the web app.
It needs Java 21 (pinned in `.mise.toml`), Maven, `uv`, Node, and ffmpeg.

## Keys

- `F7` or `→`: step one line
- `F8` or `Shift+→`: jump to the next loop iteration
- `←`: back one line
- `Home`: back to the start
- `Ctrl+Enter` in the editor: run

## Input format

Inputs use LeetCode's format: `[1,2,3]` for arrays and lists, `[3,9,20,null,null,15,7]` for trees, `"abc"` for strings, `{"a": 1}` for maps.
Add `pos=1` after a linked list (`[3,2,0,-4] pos=1`) to make its tail point back to node 1.

## Layout

- `tracer/`: Java 21 program that compiles your code and records every step through JDI.
- `engine/`: Python server, step analysis, layout, and the Manim renderer.
- `web/`: React + Monaco frontend.
- `examples/`: LeetCode cases used by the tests (`cd engine && uv run pytest`).
- `docs/superpowers/specs/`: the design.

`cd engine && uv run python scripts/preview.py OUT_DIR` renders still frames of the examples for visual review.

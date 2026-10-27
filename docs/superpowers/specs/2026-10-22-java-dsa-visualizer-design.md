# Java DSA Visualizer - Design

Date: 2026-10-22

## Intent

Pranav is learning data structures and algorithms in Java, solving LeetCode-style problems.
The hard moments are inside loops and recursion: where a temporary pointer goes, when a node's `next` changes, which call is running.
Text debuggers show this as a list of variable values, which is hard to picture.

This tool is a debugger with visualization.
You paste a LeetCode-style solution, type the input the way LeetCode shows it, and step through the code line by line.
Next to the code, a Manim animation shows every data structure in its own shape and color, with pointers sliding and arrows rewiring as each line runs.

The purpose is learning: understanding how the code works, one iteration at a time.

## Goals

- Step through one loop iteration line by line, IntelliJ-debugger style, with a Manim animation of the data structures alongside.
- Automatically recognize the data structures in the code, with a per-variable dropdown to override the guess.
- Draw a structure the same way no matter how the code stores it (a graph is always circles and edges, whether it is a matrix, an adjacency list, or `Node` objects).
- Show the call stack, especially for recursion.
- Show compile errors and runtime errors in red, at the line and on the object involved.
- Recursion mode: the first call line by line, then a recursion tree that grows one node per call.

## Non-goals

- Languages other than Java.
- Libraries beyond the JDK collections listed below.
- Detecting logic errors (wrong answers). The user will not provide expected output.
- Live editing while stepping. You edit, click Run, wait, then step.
- Hosting it online or multi-user use. It runs locally on Pranav's machine.

## Anti-goals

- A complicated general-purpose tool. If a feature makes the common case (paste, input, run, step) slower or more confusing, it does not belong.
- Animations whose layout jumps around between steps. Nodes must stay where they are unless the structure actually moved them; otherwise the animation hides what the code did.
- Visual noise. Only what the current step changed should move.

## Scope: data structures

| Kind | How the code stores it | Shape on canvas |
|---|---|---|
| int, long, double, boolean, char | local variable | small labeled value box |
| String | local variable | row of small character boxes |
| Array (1D) | `int[]`, `char[]`, `String[]`, ... | yellow square boxes with indices |
| 2D array / DP table | `int[][]`, `boolean[][]` | grid of boxes with row and column indices |
| HashMap | `HashMap`, `Map` | key-value table (teal) |
| HashSet | `HashSet`, `Set` | rounded bag of values (orange) |
| Linked list: singly, doubly, circular | `ListNode` with `next` (and `prev`) | purple circles with arrows; circular drawn as a ring |
| Trees: binary, BST, n-ary, trie | `TreeNode` with `left`/`right`, children list or array | circles in a tree layout (green) |
| Tree stored in an array (heap, segment tree) | `int[]` + dropdown | drawn as a tree |
| Graph | `Node` with `neighbors`, adjacency matrix `int[][]`, adjacency list `List<List<Integer>>` or `Map<Integer, List<Integer>>`, edge list `int[][]` | blue circles and edges |
| Recursion and DP | recursive method, memo array or map | recursion tree + memo table |
| Supporting: Stack, Queue, Deque, ArrayList | JDK collections | horizontal or vertical strips of boxes |

Stack, queue and ArrayList were not in the original list.
They are included because BFS, DFS and most tree and graph solutions need them, and a solution that uses one would otherwise show a blank.

Exact colors are the builder's call, as long as each kind is distinct and arrays are yellow and linked lists are purple.

## The screen (layout A, chosen by Pranav)

- Top bar: mode toggle (Single iteration / Full run), method picker, input fields, Run button, and step controls (Back, Step line, Next iteration), plus a position readout ("iteration 2 / 4 - line 5").
- Left: the code, in an editor with Java highlighting, with the line about to run highlighted.
- Right: the Manim animation on a black canvas.
- Below: a Variables panel (every variable in the current frame, with the ones that just changed highlighted, and a type dropdown on each structure) and a Call stack panel (one box per active call, top call highlighted).

The Variables and Call stack panels are plain HTML built from the recorded trace, so they update instantly.
Only the canvas is Manim video.

## User flow

1. Paste a LeetCode-style `class Solution { ... }`. No `main` method.
2. The tool reads the method signature and shows one input field per parameter, e.g. `head = [1,2,3,4]`, `root = [3,9,20,null,null,15,7]`, `edges = [[0,1],[1,2]]`, `n = 5`.
   If the class has more than one public method, a picker chooses which one to run.
3. Click Run.
   The tool compiles, runs the code under a debugger, records every step, then renders the animation.
   Pranav accepts about a minute of waiting here.
4. Step through.
5. To change a structure's type (e.g. `int[][]` from "DP table" to "Graph: adjacency matrix"), use the dropdown.
   The animation re-renders using the already-recorded trace (no re-run needed).

## Stepping modes

### Single iteration mode (top priority)

- "Step line" runs one line and plays its animation.
- "Next iteration" jumps to the start of the next pass of the innermost loop containing the current line, playing the intermediate steps quickly.
- "Back" shows the previous step's end state.

### Recursion mode

Turned on automatically when the trace shows a method calling itself.

1. The first call runs line by line, like single iteration mode, until it reaches its first recursive call.
2. From then on, each "next" adds the next call as a new node in the recursion tree.
   The running call is highlighted, the Call stack panel pushes and pops in sync, and returned values float up to the parent.
   Any returns that happen between two calls are animated within the same step.
3. Memo reads show the cached value being reused, with no new branch.
4. Pranav can still drop into line-by-line stepping inside any call.

### Full run mode (later phase)

Plays the whole execution as one continuous animation.
Not needed in the first version.

## Errors (red)

Red is only for errors the compiler or the JVM reports.

- Compile errors: nothing runs.
  The offending lines turn red in the editor with the compiler message, like IntelliJ's red underline.
- Runtime errors (`NullPointerException`, `ArrayIndexOutOfBoundsException`, `StackOverflowError`, `ArithmeticException`, ...): the animation stops on the line that threw it.
  The line turns red, the object involved turns red on the canvas (the `null` being dereferenced, the slot one past the array's end), and the exception message is shown.
- Infinite loops: execution is cut off after a step limit, shown as a runtime error ("stopped after 10,000 steps, possible infinite loop").

Nodes that become unreachable are not errors.
They fade to grey and disappear, mirroring garbage collection.

## Technical approach

### Overview

```
browser (React + Monaco)  <-->  local server (Python, FastAPI)
                                   |
                                   |-- tracer (Java 21, JDI)  -> trace.json
                                   |-- analyzer (Python)      -> steps, iterations, structures
                                   '-- renderer (Manim CE)    -> one video clip per step
```

Everything runs locally and starts with one command that opens the browser.

### 1. Tracer (Java)

A Java 21 program, built with Maven into a single jar.

- **Harness.** Supplies LeetCode's standard helper classes (`ListNode`, `TreeNode`, graph `Node`, n-ary `Node`) the same way LeetCode does, and parses LeetCode-format input strings into real objects.
  Generates a small `main` that builds the inputs and calls the chosen method.
- **Compilation.** Uses `javax.tools.JavaCompiler` in-process with `-g` (needed for local variable names), and returns diagnostics with line, column and message.
- **Source structure.** Uses JavaParser to find methods, parameter types, and every loop's header line and body range.
  The analyzer needs this to group steps into iterations.
- **Recording.** Uses JDI (Java Debug Interface, the API IntelliJ's debugger is built on) to launch the program in a separate JVM and single-step it line by line, restricted to the user's classes.
  At each step it records the call stack, every local variable, and every object reachable from them, keyed by JDI's stable object IDs.
  JDK collections (`HashMap`, `HashSet`, `ArrayList`, `ArrayDeque`, `Stack`, `LinkedList`, `PriorityQueue`) are read from their internal fields, which is fast and safe because the JDK version is pinned.
- **Limits.** 10,000 steps and 10 seconds wall time.
  Uncaught exceptions are captured with their type, message and the line that threw.

Output: one `trace.json` holding the source structure, and a list of steps, each with line number, stack frames, locals, and a heap snapshot.
Python Tutor's Java backend uses the same JDI approach, which shows it works.

### 2. Analyzer (Python)

- **Classification.** Recognizes each structure from its runtime shape.
  One self-typed reference field is a singly linked list, `next` + `prev` is doubly, a chain that returns to its start is circular, `left`/`right` is a binary tree, a self-typed list or array of children is an n-ary tree or trie, a `neighbors` list is a graph.
  Ambiguous types (`int[][]`, `List<List<Integer>>`, `Map<Integer, List<Integer>>`) get a default, which the dropdown overrides.
  The parameter types from the method signature are used as strong hints.
- **Step grouping.** Marks iteration boundaries using the loop ranges from the tracer, and marks call and return events for recursion mode.
- **Diffing.** Computes what changed between consecutive steps (pointer moved, field rewired, value written, object created, object unreachable).
  The renderer animates only these changes.
- **Layout, computed once for the whole trace.** Because the full trace is known before rendering, positions are chosen up front so nothing jumps.
  Linked list nodes keep the position where they first appeared.
  Graph positions come from a single seeded layout over every edge that ever existed.
  The recursion tree is laid out from the complete call tree, so new calls appear in their final spot.
  Trees re-layout only when their structure changes, and the move is animated.
- **Canvas regions.** The main structure gets the center, and supporting structures (memo table, visited set, queue, primitives) get side and bottom strips.

### 3. Renderer (Manim Community Edition)

- One Manim scene per run, with one section per step, rendered with `--save_sections` so each step becomes its own short clip.
- One mobject class per structure kind (array strip, linked list, tree, graph, hash table, set, grid, recursion tree, value box, pointer label), each with methods that animate a diff (move pointer, rewire arrow, write value, appear, fade out, flash red).
- The rendered steps are split into chunks rendered in parallel processes, each starting from the snapshot at its first step, so a typical problem renders within about a minute at 720p.
- Text uses Manim's `Text`, not LaTeX, so no LaTeX install is needed.
- Rendered output is cached by a hash of code, input and type overrides.
  Changing a dropdown re-renders without re-running Java.

### 4. Server (Python, FastAPI)

- `POST /api/analyze`: compile and parse; returns methods, parameters, and compile errors.
- `POST /api/runs`: trace, analyze, start rendering; returns a run ID.
- `GET /api/runs/{id}/status`: render progress, polled by the frontend.
- `GET /api/runs/{id}/clips/{version}/{n}.mp4`: the clip for step `n`.
- `POST /api/runs/{id}/overrides`: re-render with dropdown choices.
- Serves the built frontend.

### 5. Frontend (React + TypeScript + Vite)

- Monaco editor for the code: Java highlighting, current line highlight, red error markers.
- A video element that plays the current step's clip; Back shows the previous clip's last frame.
- Variables and Call stack panels built from the trace.

### Toolchain

- Java 21 LTS (pinned so JDK collection internals stay stable).
- Python 3.11 managed with `uv`.
- Node for building the frontend.
- System packages Manim needs: ffmpeg (installed), cairo, pango.

### Repository layout

```
visualizer/
  tracer/     Java: harness, compiler, JavaParser structure, JDI recorder
  engine/     Python: FastAPI server, analyzer, Manim renderer
  web/        React + TypeScript + Monaco frontend
  examples/   LeetCode problems with inputs, used as end-to-end tests
  docs/
```

### Testing

- `examples/` holds real LeetCode solutions (reverse linked list, two sum, binary tree level order, number of islands, clone graph, fibonacci with memo, climbing stairs, ...) with inputs.
- Tracer: golden `trace.json` tests per example.
- Analyzer: unit tests for classification, iteration grouping, diffing and layout stability.
- Renderer: low-quality smoke renders per structure kind, plus still-frame snapshots to catch visual regressions.
- End-to-end: drive the real browser UI through paste, input, run and step, and check the canvas visually.

## Phases

1. **Core and linked lists.**
   Tracer, analyzer, renderer, server and UI end to end, in single iteration mode, with primitives, strings, 1D arrays, all three linked lists, and compile and runtime errors in red.
   This is Pranav's original use case and covers the riskiest parts.
2. **Maps, sets, trees.**
   HashMap, HashSet, supporting stack/queue/list, 2D arrays, all tree kinds, array-as-tree via dropdown.
3. **Graphs, recursion, DP.**
   All graph representations, recursion mode with the growing recursion tree, memo tables.
4. **Full run mode.**
5. **Future: captions.**
   A short plain-English caption under each step, generated from the step's diff (e.g. "`curr.next = prev`: node 2 now points back to node 1"), with no AI required.

## Calls made by Claude (not yet confirmed by Pranav)

- The whole technical stack above.
- Including Stack, Queue, Deque and ArrayList as supporting structures.
- "Next iteration" means the innermost loop containing the current line; with no loop, it behaves like "Step line".
- Unreachable nodes fade to grey and disappear rather than vanishing instantly.
- Recursion mode turns on automatically, and line-by-line stepping inside any call stays available.
- Dropdown choices are remembered per method and parameter name for the session.

## Left to the builder

- Exact colors, fonts, animation timings and easing.
- Exact JSON schema of the trace.
- How many parallel render workers to use.
- Default classification for each ambiguous type.

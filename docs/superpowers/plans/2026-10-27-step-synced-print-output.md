# Step-Synced Print Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show what `System.out` prints inside the visualizer pane, step by step, so stepping past a `print`/`println` line makes exactly that text appear, highlighted, with wrapping or horizontal scrolling for long lines.

**Architecture:** The debuggee's `System.out` is wrapped in a byte-counting stream, and the recorder reads that counter at every snapshot, so each step knows how much output existed before it ran.
The tracer turns those byte offsets into UTF-16 character offsets into the final `stdout` string, the engine passes them through as `printed` on each UI step, and the web app slices `stdout` to the current step.
A new Output dock under the animation renders the sliced text as numbered terminal lines, highlights the part the just-executed line printed, and shows a caret where the next `print` will continue.

**Tech Stack:** Java 21 + JDI (tracer), Python 3 + pytest (engine), React 19 + TypeScript + Vite (web), Vitest (new, web unit tests).

**Spec:** No separate spec; the design decisions are recorded in the next section.
The request: "whenever the print statement prints something, it should also be visualized in the visualizer ... pretty ... long sentences should wrap, or give an option to scroll ... while it goes step by step, it should also print the sout line by line."

## Design Decisions

- **HTML dock, not Manim.** The output is drawn by the web app inside the canvas pane, not rendered into the Manim clips.
  Manim text cannot wrap or scroll, would add render time per step, and would change every state hash for runs that print.
  The HTML dock is crisp at any size, scrolls, wraps, and updates instantly when the clip for a step starts showing.
- **Offsets come from inside the debuggee.** Today stdout is drained asynchronously from the process pipe, so it cannot be tied to steps.
  A counting `OutputStream` installed as `System.out` by the generated `__Main` updates synchronously with each `print`, and JDI reads its static counter while the thread is suspended at each snapshot.
- **Offsets are UTF-16 units.** Java strings and JavaScript strings both index in UTF-16 code units, so `stdout.slice(0, printed)` in the browser is exact even for emoji.
- **Highlight = what the line just did.** At step `s`, the fresh text is `stdout[steps[s-1].printed : steps[s].printed]`.
  This is the output of the line that was highlighted one step earlier, which is exactly what the user just stepped over, and it works the same whether they got there by stepping forward, back, or jumping.
- **The dock never resizes while stepping.** Its height is set once per run from the line count of the whole run's output (3 to 10 rows, capped at 42% of the pane), so the video does not shrink and grow every step.
- **Hidden when the run never prints.** Existing DSA examples look exactly as they do today.
- **The Console panel follows the step too.** It currently shows the whole run's output at step 1, which leaks the future; it now shows the same slice as the dock.

## Global Constraints

- Never use the em dash character anywhere (code, comments, copy, commit messages); use "-".
- Write code that matches the surrounding style: sparse comments, short JSDoc/Javadoc on non-obvious units, no new abstractions beyond those named here.
- Output stays capped at `MAX_OUTPUT = 64 * 1024` bytes, now counted in bytes, not chars.
- UI copy uses sentence case and plain words: "Output", "Wrap lines", "N earlier lines not shown", "Output stopped being recorded after 64 KB."
- `System.err` is out of scope; it stays captured as today and is not shown.
- The repo has no commits yet; ask Pranav before making the first commit, then commit per task.
- After code changes, run `graphify update .` from the repo root.

## Review Focus

- A line that prints nothing (`print("")`, `" ".repeat(0)`) should leave `printed` unchanged and show no highlight, not an empty highlight box (tests in Task 1 and Task 2).
- Non-ASCII and emoji output (`✓`, `🎉`) must slice at the right place in the browser; Python's `len` counts code points, so engine tests compare against UTF-16 lengths (Task 1).
- Output past the 64 KB cap must clamp every step's `printed` to the captured text and say it was cut off (Task 1 test, Task 3 note).
- A run that prints and then throws, or hits the step limit, must still show everything printed up to the failing step (Task 1 test).
- One very long line with no newline must wrap inside the text column when wrapping is on, scroll horizontally when it is off, and never widen the page (Task 4 E2E check).

---

### Task 1: Per-step output offsets from the tracer through the engine

**Files:**
- Create: `tracer/src/main/resources/harness/__Out.java`
- Create: `examples/cases/print-pyramid.java`
- Modify: `examples/cases.json`
- Modify: `tracer/src/main/java/dsaviz/tracer/Workspace.java` (constructor, copy the new harness file)
- Modify: `tracer/src/main/java/dsaviz/tracer/InputBuilder.java` (`mainSource`)
- Modify: `tracer/src/main/java/dsaviz/tracer/Recorder.java` (stdout drain, `snapshot`, `record`)
- Modify: `engine/src/dsaviz/steps.py` (`build`)
- Modify: `engine/src/dsaviz/runs.py` (`_describe`)
- Modify: `web/src/types.ts` (`Step`, `RunInfo`)
- Test: `engine/tests/test_examples.py`

**Interfaces:**
- Produces, raw trace: each `trace["steps"][i]["out"]` is an `int`, the number of UTF-16 units of `trace["stdout"]` printed before step `i` ran; `trace["stdoutTruncated"]` is a `bool`.
- Produces, UI step: `step["printed"]: int` (same value as `out`, `0` if absent).
- Produces, run description: `"stdoutTruncated": bool` next to `"stdout"`.
- Produces, TypeScript: `Step.printed: number`, `RunInfo.stdoutTruncated: boolean`.

- [ ] **Step 1: Add the example case**

`examples/cases/print-pyramid.java`, with the line numbers the tests rely on (the `print` is line 4, the `println` is line 5):

```java
class Solution {
    public void pyramid(int n) {
        for (int i = 1; i <= n; i++) {
            System.out.print(" ".repeat(n - i));
            System.out.println("* ".repeat(2 * i - 1));
        }
        System.out.println("done ✓ 🎉");
    }
}
```

Add `"print-pyramid": {"method": "pyramid", "inputs": {"n": "3"}}` to `examples/cases.json`.

- [ ] **Step 2: Write the failing tests**

Append to `engine/tests/test_examples.py`:

```python
def u16(s: str) -> int:
    """Length in UTF-16 code units, the way Java and the browser count string offsets."""
    return len(s.encode("utf-16-le")) // 2


def test_each_step_knows_how_much_output_came_before_it() -> None:
    result = traced("print-pyramid")
    stdout = result["trace"]["stdout"]
    assert stdout == "  * \n * * * \n* * * * * \ndone ✓ 🎉\n"
    assert result["trace"]["stdoutTruncated"] is False
    ui, _ = prepare(result)
    printed = [s["printed"] for s in ui]
    assert printed[0] == 0
    assert printed == sorted(printed)
    assert printed[-1] == u16(stdout)
    first_println = next(i for i, s in enumerate(ui) if s["line"] == 5)
    assert printed[first_println] == u16("  ")
    assert printed[first_println + 1] == u16("  * \n")


def test_a_print_of_nothing_adds_no_output() -> None:
    ui, _ = prepare(traced("print-pyramid"))
    last_print = [i for i, s in enumerate(ui) if s["line"] == 4][-1]  # i == n prints " ".repeat(0)
    assert ui[last_print + 1]["printed"] == ui[last_print]["printed"]


def test_output_before_a_crash_is_kept() -> None:
    code = "class Solution {\n  void f(int n) {\n    System.out.print(\"before\");\n    int[] a = new int[n];\n    a[n] = 1;\n  }\n}"
    result = tracer().run(code, "f", None, {"n": "1"})
    ui, _ = prepare(result)
    assert result["trace"]["stdout"] == "before"
    assert ui[-1]["event"] == "exception" and ui[-1]["printed"] == 6


def test_huge_output_is_capped_and_offsets_stay_inside_it() -> None:
    code = "class Solution {\n  void f(int n) {\n    System.out.print(\"x\".repeat(n));\n  }\n}"
    result = tracer().run(code, "f", None, {"n": "100000"})
    trace = result["trace"]
    assert len(trace["stdout"]) == 64 * 1024 and trace["stdoutTruncated"] is True
    ui, _ = prepare(result)
    assert ui[-1]["printed"] == 64 * 1024
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd engine && uv run pytest tests/test_examples.py -k "output or printed or print" -v`
Expected: FAIL with `KeyError: 'stdoutTruncated'` / `KeyError: 'printed'`.

- [ ] **Step 4: Implement the counting stream and install it**

`__Out.java` (harness, default package, javadoc "Counts what the user's code prints. Generated by the visualizer; never stepped through."): `final class __Out extends OutputStream` with `static long written`, a constructor taking the sink `OutputStream`, and `write(int)`, `write(byte[], int, int)`, `flush()` that forward to the sink and add the byte count to `written`.
The sink is the unbuffered `new FileOutputStream(FileDescriptor.out)`, so no bytes sit in a buffer the counter has already counted.

In `Workspace`'s constructor, `copyResource("__Out.java")` next to `__LC.java`.

In `InputBuilder.mainSource`, make the first statement of `main`:
`System.setOut(new java.io.PrintStream(new __Out(new java.io.FileOutputStream(java.io.FileDescriptor.out)), true, java.nio.charset.StandardCharsets.UTF_8));`
`PrintStream` flushes its encoder into the underlying stream on every `print` call, so `written` is current whenever the thread is suspended at a line.
`__Out` matches the `"__*"` step exclusion, so it is never stepped into.

- [ ] **Step 5: Record the counter at each snapshot and convert to char offsets**

In `Recorder`:
- Collect stdout as bytes: a `ByteArrayOutputStream stdoutBytes` filled by its drain thread, writing at most `MAX_OUTPUT - size()` bytes per read and setting `boolean stdoutTruncated` when it drops any.
  It keeps reading after the cap so the debuggee never blocks on a full pipe.
  This also fixes today's bug where a multi-byte character split across two 4096-byte reads was decoded as garbage.
  stderr keeps its current `StringBuilder` drain.
- `private long written()` reads the static `written` field of the class named `__Out` via `vm.classesByName("__Out")`, caching the `ReferenceType` and `Field` after the first lookup; returns `0` if the class is not loaded.
- In `snapshot`, add `s.addProperty("out", written())`.
- In `record`, after `waitForOutput()`, rewrite every step's `out` from bytes to UTF-16 units: walk the steps in order, clamp each byte offset to `bytes.length`, decode only the new slice `[previousBytes, clampedBytes)` as UTF-8 and add its `String.length()` to a running total.
  Slices always end on character boundaries because each `print` writes whole encoded strings; only the truncation point can split one, and it is the last offset.
- Emit `out.addProperty("stdout", new String(bytes, UTF_8))` and `out.addProperty("stdoutTruncated", stdoutTruncated)`.

- [ ] **Step 6: Pass it through the engine and types**

`steps.build`: add `"printed": step.get("out", 0)` to each UI step dict.
`RunStore._describe`: add `"stdoutTruncated": trace.get("stdoutTruncated", False)`.
`web/src/types.ts`: add `printed: number` to `Step` (doc comment: "UTF-16 length of `RunInfo.stdout` printed before this step ran.") and `stdoutTruncated: boolean` to `RunInfo`.

- [ ] **Step 7: Rebuild the tracer and run the whole suite**

Run: `cd tracer && mise exec -- mvn -q -B package && cd ../engine && uv run pytest -v`
Expected: all tests PASS, including `test_every_case_traces_and_builds[print-pyramid]`.

- [ ] **Step 8: Commit**

```bash
git add tracer examples engine web/src/types.ts
git commit -m "feat: record how much stdout each step printed"
```

---

### Task 2: Output view model with unit tests

**Files:**
- Create: `web/src/output.ts`
- Create: `web/src/output.test.ts`
- Modify: `web/package.json` (add `vitest` dev dependency, `"test": "vitest run"` script)

**Interfaces:**
- Consumes: `RunInfo.stdout`, `Step.printed` from Task 1.
- Produces:

```ts
export interface OutputLine {
  number: number // 1-based line number in the whole output
  text: string // without the trailing newline or a "\r" before it
  fresh: { from: number; to: number } | null // part of `text` the just-run line printed; null when empty
  freshBreak: boolean // the newline ending this line was just printed
}
export interface OutputView {
  lines: OutputLine[] // the last line is where the next print continues, and may be ""
  hiddenLines: number // lines dropped above the window
}
export function outputView(stdout: string, printed: number, before: number, maxLines = 1000): OutputView
export function outputRows(stdout: string): number // dock height in rows: line count of the whole output, clamped to 3..10
```

- [ ] **Step 1: Install Vitest**

Run: `cd web && npm install -D vitest` and add `"test": "vitest run"` to `scripts`.

- [ ] **Step 2: Write the failing tests**

`web/src/output.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { outputRows, outputView } from './output'

const OUT = '  * \n * * * \n'

describe('outputView', () => {
  it('shows one empty line before anything is printed', () => {
    expect(outputView('', 0, 0)).toEqual({
      lines: [{ number: 1, text: '', fresh: null, freshBreak: false }],
      hiddenLines: 0,
    })
  })

  it('marks what a print() just wrote and keeps the caret on that line', () => {
    expect(outputView(OUT, 2, 0).lines).toEqual([{ number: 1, text: '  ', fresh: { from: 0, to: 2 }, freshBreak: false }])
  })

  it('marks the newline a println() adds and starts a new line', () => {
    expect(outputView(OUT, 5, 2).lines).toEqual([
      { number: 1, text: '  * ', fresh: { from: 2, to: 4 }, freshBreak: true },
      { number: 2, text: '', fresh: null, freshBreak: false },
    ])
  })

  it('marks every line one print touched', () => {
    expect(outputView('a\nb\nc', 5, 0).lines.map((l) => [l.fresh, l.freshBreak])).toEqual([
      [{ from: 0, to: 1 }, true],
      [{ from: 0, to: 1 }, true],
      [{ from: 0, to: 1 }, false],
    ])
  })

  it('has nothing fresh when the line printed nothing', () => {
    expect(outputView(OUT, 2, 2).lines[0].fresh).toBeNull()
  })

  it('keeps only the last maxLines lines', () => {
    const many = 'x\n'.repeat(1500)
    const view = outputView(many, many.length, many.length, 1000)
    expect(view.hiddenLines).toBe(501)
    expect(view.lines).toHaveLength(1000)
    expect(view.lines[0].number).toBe(502)
  })

  it('drops a carriage return before a newline', () => {
    expect(outputView('a\r\nb', 4, 0).lines[0]).toEqual({ number: 1, text: 'a', fresh: { from: 0, to: 1 }, freshBreak: true })
  })
})

describe('outputRows', () => {
  it('fits the whole output between 3 and 10 rows', () => {
    expect(outputRows('a\n')).toBe(3)
    expect(outputRows('a\n'.repeat(4))).toBe(5)
    expect(outputRows('a\n'.repeat(50))).toBe(10)
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL, `Failed to resolve import "./output"`.

- [ ] **Step 4: Implement `outputView` and `outputRows` in `web/src/output.ts`**

Split `stdout.slice(0, printed)` on `"\n"` while tracking each line's start offset; intersect `[before, printed)` with each line's `[start, start + rawLength)` for `fresh`, and set `freshBreak` when the line's newline offset is in `[before, printed)`.
Strip a trailing `"\r"` from `text` and clamp `fresh` to the stripped length, turning an empty range into `null`.
`outputRows` counts `"\n"` plus one for the caret line.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npm test`
Expected: 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/package-lock.json web/src/output.ts web/src/output.test.ts
git commit -m "feat: model step-synced output lines for the visualizer"
```

---

### Task 3: Output dock in the visualizer, Console synced to the step

**Files:**
- Create: `web/src/OutputDock.tsx`
- Modify: `web/src/App.tsx` (`Saved`, `load`, canvas pane markup, `ConsolePanel` props)
- Modify: `web/src/Panels.tsx` (`ConsolePanel`)
- Modify: `web/src/styles.css` (new `/* ---- output dock ---- */` section, one new `:root` token)

**Interfaces:**
- Consumes: `outputView`, `outputRows`, `OutputLine` from Task 2; `Step.printed`, `RunInfo.stdout`, `RunInfo.stdoutTruncated` from Task 1.
- Produces: `export default function OutputDock(props: { stdout: string; printed: number; before: number; truncated: boolean; stepKey: string; wrap: boolean; onWrapChange: (wrap: boolean) => void })`.
  `before` is `steps[display - 1]?.printed ?? printed`; `stepKey` is `` `${run.id}/${display}` `` and keys the fresh `<mark>` so its animation replays on every step.
- Produces: `ConsolePanel({ run, atEnd, printed }: { run: RunInfo | null; atEnd: boolean; printed: number })`.

- [ ] **Step 1: Build `OutputDock`**

Markup: `<section className="output-dock" aria-label="Output" style={{ '--output-rows': outputRows(stdout) }}>` containing
- a header row: title "Output", a muted "{n} lines" count (`n` = number of the last line with text), and a small toggle button "Wrap lines" with `aria-pressed={wrap}` on the right;
- a body `<div className={wrap ? 'output-body wrap' : 'output-body'} role="log">` holding an `<ol className="output-lines">` where each `<li>` is a two-column grid: a gutter `<span className="ln">` with the line number (left empty for the trailing caret line when its text is ""), and a `<span className="text">` with the text before `fresh`, `<mark className="fresh" key={stepKey}>` around `fresh`, the rest, a `<span className="fresh-break">↵</span>` when `freshBreak`, and `<span className="caret" aria-hidden="true" />` on the last line only;
- a first row "{hiddenLines} earlier lines not shown" when `hiddenLines > 0`, and a footer note "Output stopped being recorded after 64 KB." when `truncated`.

Scrolling: keep a `stuckToBottom` ref updated in `onScroll` (true when within 24px of the bottom); in a `useLayoutEffect` on `[printed, stepKey]`, scroll to the bottom if it was stuck, so new output stays in view unless the user scrolled up to read.

- [ ] **Step 2: Style it**

Add `--output-bg: #121316;` to `:root`.
`.output-dock`: `flex: none; height: calc(var(--output-rows) * 20px + 46px); max-height: 42%; display: flex; flex-direction: column; background: var(--output-bg); border-top: 1px solid var(--border)`.
Header: 30px tall, `padding: 0 10px`, title in the `.panel-title` weight and color, toggle as a 24px variant of `.tool` that uses `--accent-soft` when pressed.
`.output-body`: `flex: 1; min-height: 0; overflow: auto; padding: 6px 0; font: 13px/20px var(--font-code); tab-size: 4; color: var(--text-code)`.
Each line: `display: grid; grid-template-columns: 4ch 1fr; column-gap: 12px; padding: 0 12px`; `.ln` right-aligned in `var(--faint)` with `user-select: none`.
`.text`: `white-space: pre` by default, and `white-space: pre-wrap; overflow-wrap: anywhere` under `.wrap`, so wrapped continuation lines stay in the text column; without wrapping, the `<ol>` gets `width: max-content; min-width: 100%` so the body scrolls horizontally.
`mark.fresh`: `background: rgb(53 116 240 / 0.22); box-shadow: 0 0 0 1px rgb(53 116 240 / 0.35); color: var(--text); border-radius: 2px`, with a 0.6s `fresh-in` animation starting from `rgb(53 116 240 / 0.55)`.
`.fresh-break`: `color: var(--accent); margin-left: 2px`.
`.caret`: `display: inline-block; width: 7px; height: 15px; vertical-align: -2px; background: var(--accent)`, blinking with a 1s `steps(1)` animation.
Under `prefers-reduced-motion: reduce`, disable `fresh-in` and the blink.

- [ ] **Step 3: Wire it into `App`**

Add `outputWrap?: boolean` to `Saved` (default `true` in `load`, persisted by `save`), held in `useState`.
Render `OutputDock` between `.canvas` and `.canvas-status` when `run?.stdout && shown`, passing `shown.printed`, `before`, `run.stdoutTruncated`, the `stepKey`, and the wrap state.
Pass `printed={shown?.printed ?? 0}` to `ConsolePanel`.

- [ ] **Step 4: Sync the Console**

In `ConsolePanel`, show `run.stdout.slice(0, printed)` instead of `run.stdout`, and use that slice in the "No output yet." condition.

- [ ] **Step 5: Lint, type-check and test**

Run: `cd web && npm run lint && npm run build && npm test`
Expected: no lint findings, build succeeds, 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "feat: show print output step by step in the visualizer"
```

---

### Task 4: End-to-end check in the real app

**Files:** none expected; fix whatever this finds in the files of Tasks 1 to 3.

- [ ] **Step 1: Start the app**

Run: `./dsaviz` (rebuilds the tracer and web app because their sources are newer), then open `http://localhost:8765` with `chrome-devtools-axi` at about 1920x1056.

- [ ] **Step 2: Step through Pranav's pattern code**

Paste the `reverseList(int n)` star code from the screenshot, input `n = 3`, Run.
Expected at step 1: the dock is visible, 4 rows tall (3 output lines plus the caret line), showing only the caret.
Step past line 6: two spaces appear highlighted on line 1 with the caret after them.
Step past line 7: `* ` appears highlighted on the same line.
Step past line 10: a highlighted `↵` ends the line and the caret moves to line 2.
Step back: the highlighted text disappears again; the Console panel shows the same text as the dock at every step.
Screenshot each of these and inspect them closely: alignment of gutter and text, highlight padding, caret baseline, no layout shift of the video between steps.

- [ ] **Step 3: Long lines and big output**

Run `System.out.println("word ".repeat(200));` once: with "Wrap lines" on it wraps under the text column; with it off the dock scrolls sideways and the page never scrolls horizontally; reload and the toggle state persists.
Run the 100,000 `x` case from Task 1: the "64 KB" note shows and stepping stays responsive.
Run a program with 1,500 `println` calls: "501 earlier lines not shown" appears at the end and scrolling stays smooth.

- [ ] **Step 4: Runs that do not print**

Run the default `reverseList(ListNode head)` example: no dock, and the canvas looks the same as before this change.

- [ ] **Step 5: Final checks**

Run: `cd engine && uv run pytest && cd ../web && npm run lint && npm test`, then `graphify update .` from the repo root.
Expected: everything passes.

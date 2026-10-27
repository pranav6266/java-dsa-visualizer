export interface OutputLine {
  /** 1-based line number in the whole output. */
  number: number
  /** Without the trailing newline or a "\r" before it. */
  text: string
  /** The part of `text` the line that just ran printed, or null when it printed none of it. */
  fresh: { from: number; to: number } | null
  /** The newline ending this line was just printed. */
  freshBreak: boolean
  /** Part of `text` printed after the last step there is to show, for example when a run hit the step limit. */
  late: { from: number; to: number } | null
}

export interface OutputView {
  /** The last line is where the next print continues, and may be "". */
  lines: OutputLine[]
  /** Lines dropped above the window. */
  hiddenLines: number
}

/**
 * Splits the output printed so far into lines. `before` is how much had been printed one step earlier, so the
 * text between `before` and `printed` is what the line the user just stepped over printed. Text between `printed`
 * and `end` was printed after the last step that can be shown.
 */
export function outputView(stdout: string, printed: number, before: number, maxLines = 1000, end = printed): OutputView {
  const raw = stdout.slice(0, end).split('\n')
  let start = 0
  const lines = raw.map((line, i) => {
    const stop = start + line.length
    const hasBreak = i < raw.length - 1
    const text = hasBreak && line.endsWith('\r') ? line.slice(0, -1) : line
    const range = (a: number, b: number) => {
      const from = Math.max(a, start) - start
      const to = Math.min(b, stop, start + text.length) - start
      return from < to ? { from, to } : null
    }
    const out: OutputLine = {
      number: i + 1,
      text,
      fresh: range(before, printed),
      freshBreak: hasBreak && stop >= before && stop < printed,
      late: range(printed, end),
    }
    start = stop + 1
    return out
  })
  const hiddenLines = Math.max(0, lines.length - maxLines)
  return { lines: lines.slice(hiddenLines), hiddenLines }
}

/** How many rows the output dock shows: the whole run's output plus the caret line, between 3 and 10. */
export function outputRows(stdout: string): number {
  const lines = stdout.split('\n').length
  return Math.min(10, Math.max(3, lines))
}

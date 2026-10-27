import { useLayoutEffect, useMemo, useRef, type CSSProperties } from 'react'
import { outputRows, outputView, type OutputLine } from './output'

interface Props {
  stdout: string
  /** How much of `stdout` was printed before the shown step. */
  printed: number
  /** The same for the step before it; the text in between is what the line just stepped over printed. */
  before: number
  /** How much to show: past `printed` only at the last step, when output came after the last recorded one. */
  end: number
  truncated: boolean
  /** Changes on every step so the highlight animation replays. */
  stepKey: string
  wrap: boolean
  onWrapChange: (wrap: boolean) => void
}

/** What System.out has printed so far, under the animation, with the latest print highlighted. */
export default function OutputDock({ stdout, printed, before, end, truncated, stepKey, wrap, onWrapChange }: Props) {
  const body = useRef<HTMLDivElement>(null)
  const caret = useRef<HTMLSpanElement>(null)
  const stuck = useRef(true)
  const view = useMemo(() => outputView(stdout, printed, before, 1000, end), [stdout, printed, before, end])
  const last = view.lines[view.lines.length - 1]
  const count = last.text === '' ? last.number - 1 : last.number
  // Sized for the whole run so the gutter never changes width while stepping.
  const style = useMemo(
    () => ({ '--output-rows': outputRows(stdout), '--output-gutter': `${Math.max(4, String(stdout.split('\n').length).length)}ch` }) as CSSProperties,
    [stdout],
  )

  // Follow new output unless the user scrolled up to read something.
  useLayoutEffect(() => {
    const el = body.current
    if (!el || !stuck.current) return
    el.scrollTop = el.scrollHeight
    const c = caret.current
    if (!c || wrap) return
    const x = c.offsetLeft
    if (x > el.scrollLeft + el.clientWidth - 24) el.scrollLeft = x - el.clientWidth + 48
    else if (x < el.scrollLeft) el.scrollLeft = Math.max(0, x - 48)
  }, [end, stepKey, wrap])

  const onScroll = () => {
    const el = body.current
    if (el) stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  const renderLine = (line: OutputLine, isLast: boolean) => {
    const { text, fresh, late } = line
    // Fresh text always comes before late text on a line.
    const cuts = [0, fresh?.from ?? 0, fresh?.to ?? 0, late?.from ?? text.length, late?.to ?? text.length, text.length]
    return (
      <li key={line.number} className="output-line">
        <span className="ln">{isLast && text === '' ? '' : line.number}</span>
        <span className="text">
          {text.slice(cuts[0], cuts[1])}
          {fresh && (
            <mark key={stepKey} className="fresh">
              {text.slice(cuts[1], cuts[2])}
            </mark>
          )}
          {text.slice(cuts[2], cuts[3])}
          {late && <span className="late">{text.slice(cuts[3], cuts[4])}</span>}
          {text.slice(cuts[4])}
          {line.freshBreak && (
            <span key={stepKey} className="fresh-break" title="New line">
              ↵
            </span>
          )}
          {isLast && <span ref={caret} className="caret" aria-hidden="true" />}
        </span>
      </li>
    )
  }

  return (
    <section className={wrap ? 'output-dock' : 'output-dock nowrap'} aria-labelledby="output-title" style={style}>
      <header className="output-head">
        <h2 id="output-title" className="output-title">
          Output
        </h2>
        {count > 0 && (
          <span className="output-count">
            {count.toLocaleString()} {count === 1 ? 'line' : 'lines'}
          </span>
        )}
        <button
          className={wrap ? 'output-toggle on' : 'output-toggle'}
          aria-pressed={wrap}
          onClick={() => onWrapChange(!wrap)}
          title={wrap ? 'Long lines wrap. Click to scroll sideways instead.' : 'Long lines scroll sideways. Click to wrap them.'}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <path
              d="M2 3.5h10M2 7h8.25a1.75 1.75 0 0 1 0 3.5H7.5m1.25-1.25L7.5 10.5l1.25 1.25M2 10.5h3"
              stroke="currentColor"
              strokeWidth="1.3"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Wrap lines
        </button>
      </header>
      <div ref={body} className={wrap ? 'output-body wrap' : 'output-body'} role="log" onScroll={onScroll}>
        <ol className="output-lines">
          {view.hiddenLines > 0 && (
            <li className="output-note">
              {view.hiddenLines.toLocaleString()} earlier {view.hiddenLines === 1 ? 'line' : 'lines'} not shown
            </li>
          )}
          {view.lines.map((line, i) => renderLine(line, i === view.lines.length - 1))}
          {end > printed && <li className="output-note">The muted text was printed after the last step shown.</li>}
          {truncated && end >= stdout.length && (
            <li className="output-note">Output stopped being recorded after 64 KB.</li>
          )}
        </ol>
      </div>
    </section>
  )
}

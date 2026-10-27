import { shortType } from './format'
import type { Frame, RunInfo, Step } from './types'

interface VariablesProps {
  step: Step | null
  overrides: Record<string, string>
  onOverride: (name: string, kind: string) => void
}

export function VariablesPanel({ step, overrides, onOverride }: VariablesProps) {
  const frame = step?.frames[0]
  return (
    <section className="panel" aria-labelledby="vars-title">
      <h2 id="vars-title" className="panel-title">Variables</h2>
      <div className="panel-body">
        {!frame ? (
          <p className="panel-empty">Run your code to see its variables here.</p>
        ) : frame.locals.length === 0 ? (
          <p className="panel-empty">No variables in {frame.method}() yet.</p>
        ) : (
          <table className="vars">
            <tbody>
              {frame.locals.map((local) => (
                <tr key={local.name} className={local.changed ? 'changed' : undefined}>
                  <td className="var-name">{local.name}</td>
                  <td className="var-value" title={local.value}>
                    {local.value}
                  </td>
                  <td className="var-type">
                    {local.kindOptions.length > 0 ? (
                      <select
                        className="kind-select"
                        aria-label={`Draw ${local.name} as`}
                        value={overrides[local.name] ?? local.kind ?? ''}
                        onChange={(e) => onOverride(local.name, e.target.value)}
                      >
                        {local.kindOptions.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      local.type
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

export function CallStackPanel({ frames }: { frames: Frame[] }) {
  return (
    <section className="panel" aria-labelledby="stack-title">
      <h2 id="stack-title" className="panel-title">Call stack</h2>
      <div className="panel-body">
        {frames.length === 0 ? (
          <p className="panel-empty">Calls show up here while your code runs.</p>
        ) : (
          <ol className="stack">
            {frames.map((f, i) => (
              <li key={`${f.callId}-${i}`} className={i === 0 ? 'top' : undefined}>
                <span className="frame-method">{f.method}</span>
                <span className="frame-line">line {f.line}</span>
              </li>
            ))}
            <li className="harness">
              <span className="frame-method">main</span>
              <span className="frame-line">your input</span>
            </li>
          </ol>
        )}
      </div>
    </section>
  )
}

interface ConsoleProps {
  run: RunInfo | null
  atEnd: boolean
  /** How much of the output was printed before the shown step. */
  printed: number
}

export function ConsolePanel({ run, atEnd, printed }: ConsoleProps) {
  const error = run?.error
  // At the last step, also show anything printed after the last recorded step (step limit, timeout).
  const stdout = (atEnd ? run?.stdout : run?.stdout.slice(0, printed)) ?? ''
  return (
    <section className="panel" aria-labelledby="console-title">
      <h2 id="console-title" className="panel-title">Console</h2>
      <div className="panel-body console">
        {!run ? (
          <p className="panel-empty">Output from System.out appears here.</p>
        ) : (
          <>
            {stdout && <pre className="stdout">{stdout}</pre>}
            {atEnd && error && (
              <p className="console-error">
                {shortType(error.type)}
                {error.message ? `: ${error.message}` : ''}
                {error.line > 0 && <span className="console-where"> at line {error.line}</span>}
              </p>
            )}
            {atEnd && !error && (
              <p className="console-result">
                {run.returned !== null ? (
                  <>
                    Returned <code>{run.returned}</code>
                  </>
                ) : (
                  'Finished'
                )}
              </p>
            )}
            {!stdout && !atEnd && <p className="panel-empty">No output yet.</p>}
            {run.truncated && <p className="panel-note">Only the first 1,500 steps are animated.</p>}
          </>
        )}
      </div>
    </section>
  )
}

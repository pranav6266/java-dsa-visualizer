import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { analyze, renderStatus, setOverrides, startRun } from './api'
import CodeEditor from './CodeEditor'
import { shortType } from './format'
import OutputDock from './OutputDock'
import { CallStackPanel, ConsolePanel, VariablesPanel } from './Panels'
import Player from './Player'
import type { Diagnostic, InputError, MethodInfo, RenderStatus, RunInfo } from './types'

const EXAMPLE = `class Solution {
    public ListNode reverseList(ListNode head) {
        ListNode prev = null;
        ListNode curr = head;
        while (curr != null) {
            ListNode next = curr.next;
            curr.next = prev;
            prev = curr;
            curr = next;
        }
        return prev;
    }
}
`

const STORAGE_KEY = 'dsaviz:v1'

interface Saved {
  code: string
  inputs: Record<string, Record<string, string>>
  method: string | null
  /** Whether long lines in the output dock wrap instead of scrolling sideways. */
  outputWrap?: boolean
}

function load(): Saved {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as Saved
  } catch {
    // Private mode or corrupt storage: start fresh.
  }
  return { code: EXAMPLE, inputs: { 'Solution.reverseList': { head: '[1,2,3,4,5]' } }, method: 'Solution.reverseList' }
}

function save(s: Saved) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
  } catch {
    // Storage is a convenience only.
  }
}

const methodKey = (m: MethodInfo) => `${m.cls}.${m.name}`

function placeholderFor(type: string): string {
  const t = type.replace(/\s/g, '')
  if (t === 'ListNode') return '[1,2,3,4,5]'
  if (t === 'TreeNode') return '[3,9,20,null,null,15,7]'
  if (t === 'String') return '"abcde"'
  if (t === 'char') return '"a"'
  if (t === 'boolean') return 'true'
  if (t.endsWith('[][]')) return '[[1,2],[3,4]]'
  if (t.endsWith('[]') || t.startsWith('List<')) return '[1,2,3]'
  if (t.startsWith('Map<') || t.startsWith('HashMap<')) return '{"a": 1}'
  return '5'
}

export default function App() {
  const [initial] = useState(load)
  const [code, setCode] = useState(initial.code)
  const [inputs, setInputs] = useState(initial.inputs)
  const [selected, setSelected] = useState<string | null>(initial.method)
  const [methods, setMethods] = useState<MethodInfo[]>([])
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([])
  const [inputError, setInputError] = useState<InputError | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [run, setRun] = useState<RunInfo | null>(null)
  const [runCode, setRunCode] = useState<string | null>(null)
  const [status, setStatus] = useState<RenderStatus | null>(null)
  const [target, setTarget] = useState(0)
  const [display, setDisplay] = useState<number | null>(null)
  const [overrides, setOverridesState] = useState<Record<string, string>>({})
  const [outputWrap, setOutputWrap] = useState(initial.outputWrap ?? true)

  const method = methods.find((m) => methodKey(m) === selected) ?? methods[0] ?? null
  const methodInputs = useMemo(() => (method ? (inputs[methodKey(method)] ?? {}) : {}), [method, inputs])

  useEffect(() => {
    save({ code, inputs, method: selected, outputWrap })
  }, [code, inputs, selected, outputWrap])

  // Re-check the code shortly after each edit: refreshes the method list and the red compile-error underlines.
  useEffect(() => {
    const timer = setTimeout(() => {
      analyze(code)
        .then((a) => {
          if (!a.ok) return
          // While the code doesn't parse, keep the last method list so the inputs don't vanish mid-edit.
          if (a.methods.length > 0 || a.diagnostics.length === 0) setMethods(a.methods)
          setDiagnostics(a.diagnostics)
        })
        .catch(() => setRequestError('The visualizer server is not responding. Is it still running?'))
    }, 450)
    return () => clearTimeout(timer)
  }, [code])

  // Heartbeat: when launched as an app, the server stops a few minutes after the last window closes.
  useEffect(() => {
    const ping = () => void fetch('/api/ping').catch(() => undefined)
    const timer = setInterval(ping, 30_000)
    return () => clearInterval(timer)
  }, [])

  // Poll render progress until every clip exists.
  useEffect(() => {
    if (!run) return
    let stop = false
    const tick = async () => {
      while (!stop) {
        try {
          const s = await renderStatus(run.id)
          if (stop) return
          setStatus(s)
          if (s.version === run.version && s.state !== 'rendering') return
        } catch {
          // Transient; try again.
        }
        await new Promise((r) => setTimeout(r, 400))
      }
    }
    void tick()
    return () => {
      stop = true
    }
  }, [run])

  const ready = useMemo(
    () => new Set(status && run && status.version === run.version ? status.ready : []),
    [status, run],
  )

  const doRun = useCallback(async () => {
    if (!method || running) return
    setRunning(true)
    setInputError(null)
    setRequestError(null)
    try {
      const res = await startRun({
        code,
        method: method.name,
        cls: method.cls,
        inputs: methodInputs,
        overrides,
      })
      setDiagnostics(res.diagnostics ?? [])
      if (res.methods?.length) setMethods(res.methods)
      if (!res.ok) {
        setRequestError(res.message ?? 'The run failed.')
      } else if (res.inputError) {
        setInputError(res.inputError)
      } else if (res.diagnostics.length > 0) {
        setRequestError(null)
      } else if (res.id) {
        const info = res as RunInfo
        setRun(info)
        setRunCode(code)
        setStatus(null)
        setTarget(0)
        setDisplay(null)
      }
    } catch {
      setRequestError('Could not reach the visualizer server. Is it still running?')
    } finally {
      setRunning(false)
    }
  }, [code, method, methodInputs, overrides, running])

  const steps = useMemo(() => run?.steps ?? [], [run])
  const shown = display !== null ? steps[display] : null
  const last = steps.length - 1
  const stale = run !== null && runCode !== code
  const atEnd = display !== null && display === last
  // The dock stays up while a clip loads (or re-renders) so the video never resizes under it.
  const outputIndex = display ?? target
  const outputStep = steps[outputIndex] ?? null
  const errorLine = shown?.event === 'exception' && run?.error ? run.error.line : null

  const stepLine = useCallback(() => setTarget((t) => Math.min(last, t + 1)), [last])
  const stepBack = useCallback(() => setTarget((t) => Math.max(0, t - 1)), [])
  const nextIteration = useCallback(() => {
    setTarget((t) => {
      const s = steps[t]
      return s ? Math.max(Math.min(last, s.nextIteration), Math.min(last, t + 1)) : t
    })
  }, [steps, last])
  const restart = useCallback(() => setTarget(0), [])

  const changeOverride = useCallback(
    async (name: string, kind: string) => {
      if (!run) return
      const next = { ...overrides, [name]: kind }
      setOverridesState(next)
      try {
        const info = await setOverrides(run.id, next)
        setRun((r) => (r ? { ...r, ...info } : r))
        setStatus(null)
        setDisplay(null)
      } catch {
        setRequestError('Could not re-render the animation.')
      }
    },
    [overrides, run],
  )

  // IntelliJ-like keys: F7 steps a line, F8 jumps to the next iteration. Arrow keys work outside text fields.
  const keys = useRef({ stepLine, stepBack, nextIteration, restart })
  useEffect(() => {
    keys.current = { stepLine, stepBack, nextIteration, restart }
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      const typing = el.closest('input, textarea, select, .monaco-editor') !== null
      if (e.key === 'F7') keys.current.stepLine()
      else if (e.key === 'F8') keys.current.nextIteration()
      else if (typing) return
      else if (e.key === 'ArrowRight' && e.shiftKey) keys.current.nextIteration()
      else if (e.key === 'ArrowRight') keys.current.stepLine()
      else if (e.key === 'ArrowLeft') keys.current.stepBack()
      else if (e.key === 'Home') keys.current.restart()
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const renderProgress =
    run && status && status.version === run.version && status.state === 'rendering'
      ? `Rendering ${status.ready.length} of ${status.total} steps`
      : null

  const it = shown?.iteration
  const compileErrors = diagnostics.filter((d) => d.line > 0)
  const generalErrors = diagnostics.filter((d) => d.line <= 0)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={20} height={20} />
          <span>DSA Visualizer</span>
        </div>
        <div className="run-controls">
          <label className="sr-only" htmlFor="method">
            Method to run
          </label>
          <select
            id="method"
            className="method-select"
            value={method ? methodKey(method) : ''}
            onChange={(e) => setSelected(e.target.value)}
            disabled={methods.length === 0}
          >
            {methods.length === 0 && <option value="">No method found</option>}
            {methods.map((m) => (
              <option key={methodKey(m)} value={methodKey(m)}>
                {m.name}({m.params.map((p) => `${p.type} ${p.name}`).join(', ')})
              </option>
            ))}
          </select>
          <button className="run-button" onClick={doRun} disabled={!method || running} title="Run (Ctrl+Enter)">
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M2.5 1.5v9l8-4.5z" fill="currentColor" />
            </svg>
            {running ? 'Running' : 'Run'}
          </button>
        </div>
        <div className="mode" role="group" aria-label="Mode">
          <button className="mode-option active" aria-pressed="true">
            Single iteration
          </button>
          <button className="mode-option" disabled title="Plays the whole run as one animation. Coming in a later version.">
            Full run
          </button>
        </div>
      </header>

      <main className="workspace">
        <section className="code-pane" aria-label="Code">
          <div className="inputs" hidden={!method}>
            {method && method.params.length === 0 && <span className="inputs-none">This method takes no input.</span>}
            {method?.params.map((p) => (
              <label key={p.name} className={inputError?.param === p.name ? 'input-field invalid' : 'input-field'}>
                <span className="input-name">{p.name}</span>
                <input
                  value={methodInputs[p.name] ?? ''}
                  placeholder={placeholderFor(p.type)}
                  spellCheck={false}
                  onChange={(e) =>
                    setInputs((all) => ({
                      ...all,
                      [methodKey(method)]: { ...(all[methodKey(method)] ?? {}), [p.name]: e.target.value },
                    }))
                  }
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void doRun()
                  }}
                />
                <span className="input-type">{p.type}</span>
              </label>
            ))}
          </div>
          {inputError && <p className="inline-error">{inputError.message}</p>}
          <div className="editor">
            <CodeEditor
              code={code}
              onChange={setCode}
              currentLine={stale ? null : (shown?.line ?? null)}
              errorLine={stale ? null : errorLine}
              diagnostics={diagnostics}
              onRun={doRun}
            />
          </div>
          {(compileErrors.length > 0 || generalErrors.length > 0) && (
            <ul className="problems" aria-label="Compile errors">
              {compileErrors.map((d, i) => (
                <li key={i}>
                  <span className="problem-line">Line {d.line}</span>
                  {d.message}
                </li>
              ))}
              {generalErrors.map((d, i) => (
                <li key={`g${i}`}>{d.message}</li>
              ))}
            </ul>
          )}
        </section>

        <section className="canvas-pane" aria-label="Animation">
          <div className="toolbar">
            <button className="tool" onClick={restart} disabled={!run || target === 0} title="Back to the start (Home)">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <path d="M3 2.5v9M11 2.5 5 7l6 4.5z" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinejoin="round" />
              </svg>
              <span className="sr-only">Restart</span>
            </button>
            <button className="tool" onClick={stepBack} disabled={!run || target === 0} title="Back one line (←)">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <path d="M9 2.5 4 7l5 4.5" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back
            </button>
            <button className="tool primary" onClick={stepLine} disabled={!run || target >= last} title="Run the highlighted line (F7 or →)">
              Step line
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <path d="M5 2.5 10 7l-5 4.5" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <button className="tool" onClick={nextIteration} disabled={!run || target >= last} title="Jump to the next loop iteration (F8 or Shift+→)">
              Next iteration
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <path d="M3 2.5 7.5 7 3 11.5M7 2.5 11.5 7 7 11.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <div className="position" aria-live="polite">
              {shown && (
                <>
                  {it && (
                    <span>
                      Iteration <b>{it.iteration}</b> of {it.total}
                    </span>
                  )}
                  <span>
                    Line <b>{shown.line}</b>
                  </span>
                  <span className="muted">
                    Step {(display ?? 0) + 1} of {steps.length}
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="canvas">
            {run ? (
              <Player runId={run.id} version={run.version} target={target} ready={ready} onShow={setDisplay} />
            ) : (
              <div className="canvas-empty">
                {running ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    Running your code
                  </>
                ) : (
                  <p>
                    Enter an input and press <b>Run</b>.
                    <br />
                    Each line of your code will animate here.
                  </p>
                )}
              </div>
            )}
            {run && running && (
              <div className="canvas-busy">
                <span className="spinner" aria-hidden="true" />
                Running your code
              </div>
            )}
          </div>
          {run?.stdout && outputStep && (
            <OutputDock
              key={run.id}
              stdout={run.stdout}
              printed={outputStep.printed}
              before={steps[outputIndex - 1]?.printed ?? outputStep.printed}
              end={outputIndex === last ? run.stdout.length : outputStep.printed}
              truncated={run.stdoutTruncated}
              stepKey={`${run.id}/${outputIndex}`}
              wrap={outputWrap}
              onWrapChange={setOutputWrap}
            />
          )}
          <div className="canvas-status">
            {renderProgress && (
              <div className="progress" aria-label={renderProgress}>
                <div className="progress-bar" style={{ width: `${(100 * (status?.ready.length ?? 0)) / Math.max(1, status?.total ?? 1)}%` }} />
              </div>
            )}
            {stale && <p className="notice">You edited the code. Press Run to animate the new version.</p>}
            {!stale && shown?.event === 'exception' && run?.error && (
              <p className="notice error">
                {shortType(run.error.type)} on line {run.error.line}
                {run.error.message ? `: ${run.error.message}` : ''}
              </p>
            )}
            {!stale && run?.error && run.error.kind !== 'runtime' && atEnd && (
              <p className="notice error">{run.error.message}</p>
            )}
            {status?.state === 'error' && <p className="notice error">The animation failed to render: {status.error}</p>}
            {requestError && <p className="notice error">{requestError}</p>}
            {renderProgress && !stale && <p className="notice muted">{renderProgress}</p>}
          </div>
        </section>
      </main>

      <footer className="panels">
        <VariablesPanel step={shown} overrides={overrides} onOverride={changeOverride} />
        <CallStackPanel frames={shown?.frames ?? []} />
        <ConsolePanel run={run} atEnd={atEnd} printed={shown?.printed ?? 0} />
      </footer>
    </div>
  )
}

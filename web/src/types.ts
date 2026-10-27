export interface Param {
  name: string
  type: string
}

export interface MethodInfo {
  cls: string
  name: string
  params: Param[]
  returnType: string
  static: boolean
  startLine: number
}

export interface Diagnostic {
  message: string
  line: number
  column: number
  endColumn: number
}

export interface KindOption {
  value: string
  label: string
}

export interface Local {
  name: string
  type: string
  value: string
  changed: boolean
  kind: string | null
  kindOptions: KindOption[]
}

export interface Frame {
  callId: number
  method: string
  line: number
  locals: Local[]
}

export interface Iteration {
  loop: number
  header: number
  iteration: number
  total: number
}

export interface Step {
  line: number
  event: 'step' | 'return' | 'exception'
  frames: Frame[]
  iteration: Iteration | null
  nextIteration: number
  returns: { method: string; value: string | null }[]
  /** UTF-16 length of `RunInfo.stdout` printed before this step ran. */
  printed: number
}

export interface RuntimeError {
  kind: 'runtime' | 'limit' | 'timeout' | 'internal'
  type: string
  message: string | null
  line: number
  step: number
}

export interface InputError {
  param: string | null
  message: string
}

export interface Analysis {
  ok: boolean
  message?: string
  methods: MethodInfo[]
  diagnostics: Diagnostic[]
}

export interface RunInfo {
  id: string
  version: number
  steps: Step[]
  total: number
  truncated: boolean
  error: RuntimeError | null
  returned: string | null
  stdout: string
  stdoutTruncated: boolean
  overrides: Record<string, string>
}

export type RunResponse = Analysis & { inputError?: InputError | null } & Partial<RunInfo>

export interface RenderStatus {
  version: number
  total: number
  ready: number[]
  state: 'rendering' | 'ready' | 'error'
  error: string | null
}

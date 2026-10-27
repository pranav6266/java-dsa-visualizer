import Editor, { loader, type OnMount } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/editor/editor.api'
import 'monaco-editor/languages/definitions/java/register'
import editorWorker from 'monaco-editor/editor/editor.worker?worker'
import { useEffect, useRef } from 'react'
import type { Diagnostic } from './types'

self.MonacoEnvironment = { getWorker: () => new editorWorker() }
loader.config({ monaco })

monaco.editor.defineTheme('intellij-dark', {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'keyword', foreground: 'CF8E6D' },
    { token: 'type', foreground: 'BCBEC4' },
    { token: 'string', foreground: '6AAB73' },
    { token: 'number', foreground: '2AACB8' },
    { token: 'comment', foreground: '7A7E85', fontStyle: 'italic' },
    { token: 'annotation', foreground: 'B3AE60' },
    { token: 'identifier', foreground: 'BCBEC4' },
    { token: 'delimiter', foreground: 'BCBEC4' },
  ],
  colors: {
    'editor.background': '#1E1F22',
    'editor.foreground': '#BCBEC4',
    'editorLineNumber.foreground': '#4B5059',
    'editorLineNumber.activeForeground': '#A1A3AB',
    'editor.lineHighlightBackground': '#26282E',
    'editor.selectionBackground': '#214283',
    'editorCursor.foreground': '#CED0D6',
    'editorIndentGuide.background1': '#2B2D30',
    'editorGutter.background': '#1E1F22',
    'editorWidget.background': '#2B2D30',
    'editorWidget.border': '#43454A',
    'scrollbarSlider.background': '#4E515766',
    'scrollbarSlider.hoverBackground': '#5A5D6388',
  },
})

interface Props {
  code: string
  onChange: (code: string) => void
  currentLine: number | null
  errorLine: number | null
  diagnostics: Diagnostic[]
  onRun: () => void
}

export default function CodeEditor({ code, onChange, currentLine, errorLine, diagnostics, onRun }: Props) {
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
  const decorations = useRef<monaco.editor.IEditorDecorationsCollection | null>(null)
  const runRef = useRef(onRun)
  useEffect(() => {
    runRef.current = onRun
  })

  const onMount: OnMount = (editor) => {
    editorRef.current = editor
    decorations.current = editor.createDecorationsCollection()
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => runRef.current())
  }

  useEffect(() => {
    const editor = editorRef.current
    if (!editor || !decorations.current) return
    const items: monaco.editor.IModelDeltaDecoration[] = []
    if (errorLine) {
      items.push({
        range: new monaco.Range(errorLine, 1, errorLine, 1),
        options: { isWholeLine: true, className: 'line-error', glyphMarginClassName: 'glyph-error' },
      })
    } else if (currentLine) {
      items.push({
        range: new monaco.Range(currentLine, 1, currentLine, 1),
        options: { isWholeLine: true, className: 'line-current', glyphMarginClassName: 'glyph-current' },
      })
    }
    decorations.current.set(items)
    const line = errorLine ?? currentLine
    if (line) editor.revealLineInCenterIfOutsideViewport(line, monaco.editor.ScrollType.Smooth)
  }, [currentLine, errorLine])

  useEffect(() => {
    const model = editorRef.current?.getModel()
    if (!model) return
    monaco.editor.setModelMarkers(
      model,
      'javac',
      diagnostics
        .filter((d) => d.line > 0)
        .map((d) => ({
          severity: monaco.MarkerSeverity.Error,
          message: d.message,
          startLineNumber: d.line,
          endLineNumber: d.line,
          startColumn: d.column,
          endColumn: Math.max(d.endColumn, d.column + 1),
        })),
    )
  }, [diagnostics, code])

  return (
    <Editor
      language="java"
      theme="intellij-dark"
      value={code}
      onChange={(v) => onChange(v ?? '')}
      onMount={onMount}
      options={{
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 14,
        lineHeight: 22,
        fontLigatures: false,
        minimap: { enabled: false },
        glyphMargin: true,
        lineNumbersMinChars: 3,
        lineDecorationsWidth: 6,
        scrollBeyondLastLine: false,
        renderLineHighlight: 'line',
        overviewRulerLanes: 0,
        hideCursorInOverviewRuler: true,
        padding: { top: 12, bottom: 12 },
        tabSize: 4,
        automaticLayout: true,
        scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
      }}
    />
  )
}

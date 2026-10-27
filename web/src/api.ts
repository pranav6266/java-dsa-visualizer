import type { Analysis, RenderStatus, RunInfo, RunResponse } from './types'

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

export function analyze(code: string): Promise<Analysis> {
  return post('/api/analyze', { code })
}

export function startRun(body: {
  code: string
  method: string
  cls: string
  inputs: Record<string, string>
  overrides: Record<string, string>
}): Promise<RunResponse> {
  return post('/api/runs', body)
}

export function setOverrides(id: string, overrides: Record<string, string>): Promise<RunInfo> {
  return post(`/api/runs/${id}/overrides`, { overrides })
}

export async function renderStatus(id: string): Promise<RenderStatus> {
  const res = await fetch(`/api/runs/${id}/status`)
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json() as Promise<RenderStatus>
}

export function clipUrl(id: string, version: number, index: number): string {
  return `/api/runs/${id}/clips/${version}/${index}.mp4`
}

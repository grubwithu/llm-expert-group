import type { CouncilEvent, CouncilSession, RoundRun } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(data?.detail || `Request failed: ${response.status}`)
  }
  return response.json()
}

export const api = {
  sessions: () => request<CouncilSession[]>('/api/sessions'),
  session: (id: string) => request<CouncilSession>(`/api/sessions/${id}`),
  createSession: (payload: { title: string; topic: string; repo_path: string }) =>
    request<CouncilSession>('/api/sessions', { method: 'POST', body: JSON.stringify(payload) }),
  startRound: (id: string) => request<RoundRun>(`/api/sessions/${id}/rounds`, { method: 'POST' }),
  stopRound: (id: string) => request<RoundRun | null>(`/api/sessions/${id}/rounds/stop`, { method: 'POST' }),
  latestRoundRun: (id: string) => request<RoundRun | null>(`/api/sessions/${id}/round-runs/latest`),
  action: (id: string, payload: { action: string; note?: string }) =>
    request<CouncilSession>(`/api/sessions/${id}/action`, { method: 'POST', body: JSON.stringify(payload) }),
}

export function subscribeRoundEvents(runId: string, onEvent: (event: CouncilEvent) => void, onError?: () => void) {
  const source = new EventSource(`/api/round-runs/${runId}/events`)
  source.addEventListener('council', event => {
    try {
      onEvent(JSON.parse((event as MessageEvent<string>).data) as CouncilEvent)
    } catch {
      // Ignore malformed events and leave the durable session state intact.
    }
  })
  source.onerror = () => onError?.()
  return source
}

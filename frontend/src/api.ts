import type { CouncilSession } from './types'

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
  runRound: (id: string) => request<CouncilSession>(`/api/sessions/${id}/rounds/run`, { method: 'POST' }),
  action: (id: string, payload: { action: string; note?: string }) =>
    request<CouncilSession>(`/api/sessions/${id}/action`, { method: 'POST', body: JSON.stringify(payload) }),
}

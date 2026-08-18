export type SecretaryStatus = 'VERIFIED' | 'PARTIALLY_VERIFIED' | 'NOT_FOUND' | 'CONFLICTING_EVIDENCE' | 'UNSTRUCTURED'

export type SecretaryEvidence = {
  path: string
  start_line: number
  end_line: number
  reason: string
  excerpt?: string | null
}

export type SecretaryInteraction = {
  id: string
  requester_role: 'chairman' | 'expert'
  requester_id?: string | null
  phase: 'opening' | 'expert' | 'synthesis'
  sequence: number
  question: string
  answer: string
  status: SecretaryStatus
  evidence: SecretaryEvidence[]
  limitations: string[]
  tool_trace: string[]
  repo_commit?: string | null
}

export type ExpertResponse = {
  model_id: string
  display_name: string
  content: string
  error?: string | null
  secretary_queries: SecretaryInteraction[]
  protocol_warnings: string[]
}

export type CouncilRound = {
  id: string
  number: number
  kind: string
  graph_thread_id?: string | null
  opening_statement: string
  expert_responses: ExpertResponse[]
  chairman_summary: string
  chairman_opening_secretary_queries: SecretaryInteraction[]
  chairman_synthesis_secretary_queries: SecretaryInteraction[]
  human_action?: string | null
  human_note?: string | null
  created_at: string
  completed_at: string
}

export type CouncilSession = {
  id: string
  title: string
  topic: string
  repo_path: string
  repo_commit?: string | null
  repo_context_truncated: boolean
  status: string
  current_round: number
  created_at: string
  updated_at: string
  rounds: CouncilRound[]
}

export type RoundRun = {
  id: string
  session_id: string
  number: number
  kind: string
  status: string
  opening_statement: string
  expert_responses: ExpertResponse[]
  chairman_summary: string
  error?: string | null
  created_at: string
  updated_at: string
  completed_at?: string | null
}

export type CouncilEvent = {
  type: string
  payload: Record<string, unknown>
}

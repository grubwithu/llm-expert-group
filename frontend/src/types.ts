export type ExpertResponse = {
  model_id: string
  display_name: string
  content: string
  error?: string | null
}

export type CouncilRound = {
  id: string
  number: number
  kind: string
  opening_statement: string
  expert_responses: ExpertResponse[]
  chairman_summary: string
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

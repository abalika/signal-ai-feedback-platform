export type Project = {
  id: number
  name: string
  description: string
  created_at: string
}

export type Document = {
  id: number
  project_id: number
  title: string
  content: string
  created_at: string
}

export type Feedback = {
  id: number
  project_id: number
  source: string
  content: string
  status: string
  created_at: string
}

export type Evidence = {
  document_id: number
  title: string
  excerpt: string
}

export type Analysis = {
  feedback_id: number
  category: string
  summary: string
  suggested_reply: string
  proposed_task: string
  evidence: Evidence[]
  needs_review: boolean
  model_mode: 'ai' | 'unavailable' | string
}

export type Ticket = {
  id: number
  feedback_id: number
  project_id: number
  title: string
  original_proposed_task?: string
  reviewer_note?: string
  resolution_note?: string
  updated_at?: string
  status: string
  created_at: string
}

export type Trace = {
  id: number
  feedback_id: number
  step: string
  detail: string
  created_at: string
}

export type Health = {
  status: string
  demo_mode?: boolean
  ai_configured: boolean
}

export type Metrics = {
  project_id: number | null
  documents: number
  feedback: number
  analyses: number
  ai_analyses: number
  unavailable_analyses: number
  tickets: number
  completed_tickets: number
  traces: number
  model_calls: number
  total_tokens: number
  model_latency_p50_ms: number | null
  model_latency_p95_ms: number | null
  ai_to_ticket_rate: number
}

export type NavKey = 'overview' | 'documents' | 'feedback' | 'tickets' | 'evaluations'
export type ModalKey = 'project' | 'document' | 'feedback' | null

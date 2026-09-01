import { requestJson } from './client'

export type AnalyticsResponseKind = 'verified' | 'clarification' | 'refusal'
export type DocumentResponseKind = 'verified' | 'no_results' | 'analytics_required'

export interface AnalyticsEvidence {
  tool_name: string
  arguments: Record<string, unknown>
  result: Record<string, unknown>
}

export interface AnalyticsQuestionResponse {
  kind: AnalyticsResponseKind
  answer: string
  verified: boolean
  model: string | null
  evidence: AnalyticsEvidence[]
}

export interface DocumentCitation {
  citation_id: string
  document_id: string
  chunk_id: string
  original_filename: string
  page_number: number
  section_number: number
  start_offset: number
  end_offset: number
  document_sha256: string
  chunk_sha256: string
  excerpt: string
}

export interface DocumentQuestionResponse {
  kind: DocumentResponseKind
  answer: string
  verified: boolean
  evidence_status: 'supported' | 'conflicting' | 'none'
  model: string | null
  retrieval_terms: string[]
  citations: DocumentCitation[]
}

export function askAnalyticsQuestion(question: string, signal?: AbortSignal): Promise<AnalyticsQuestionResponse> {
  return requestJson('/ai/questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: question.trim() }),
    signal,
  })
}

export function askDocumentQuestion(question: string, signal?: AbortSignal, documentId?: string): Promise<DocumentQuestionResponse> {
  return requestJson('/ai/document-questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: question.trim(), ...(documentId ? { document_id: documentId } : {}) }),
    signal,
  })
}

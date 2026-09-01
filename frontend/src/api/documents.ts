import { ApiRequestError, buildApiUrl, fetchJson, requestJson, requestNoContent } from './client'
import { maxDocumentSizeBytes } from './config'
import { formatBytes } from './imports'

export type DocumentStatus = 'stored' | 'failed'
export type ExtractionStatus = 'processing' | 'completed' | 'failed'
export type DocumentFactType = 'expiration_date' | 'document_date' | 'issuer' | 'reference_number' | 'document_subtype'

export interface DocumentFact {
  fact_type: DocumentFactType
  value_text: string | null
  value_date: string | null
  is_cleared: boolean
  source: 'automatic' | 'user'
  confidence: string | null
  source_page_number: number | null
  inference_name: string
  inference_version: string
  evidence_code: string
}

export interface DocumentExpirationReminder {
  enabled: boolean
  channel: 'in_app'
  lead_time_days: number
  acknowledged_expiration_date: string | null
  snoozed_until: string | null
  updated_at: string
}

export interface DocumentReminderItem {
  document_id: string
  display_name: string
  expiration_date: string
  days_until_expiration: number
  status: 'expired' | 'expires_today' | 'upcoming'
  lead_time_days: number
  channel: 'in_app'
}

export interface DocumentReminderListResponse {
  as_of: string
  household_timezone: string
  items: DocumentReminderItem[]
}

export interface PaginationMetadata {
  total: number
  offset: number
  limit: number
  returned: number
  has_more: boolean
}

export interface DocumentLibraryItem {
  id: string
  status: DocumentStatus
  original_filename: string
  media_type: string
  size_bytes: number
  sha256: string
  source: string
  title: string | null
  title_source: 'automatic' | 'user' | null
  document_type: string | null
  document_type_source: 'automatic' | 'user' | null
  notes: string | null
  collection_name?: string | null
  tags?: string[]
  metadata_inference: {
    classifier_name: string
    classifier_version: string
    suggested_title: string
    title_evidence_code: string
    suggested_document_type: string | null
    document_type_confidence: string | null
    evidence_codes: string[]
  } | null
  facts: DocumentFact[]
  expiration_reminder: DocumentExpirationReminder | null
  created_at: string
  updated_at: string
  latest_extraction_status: ExtractionStatus | null
  latest_extraction_updated_at: string | null
  chunk_count: number
  is_searchable: boolean
}

export interface DocumentListResponse {
  items: DocumentLibraryItem[]
  pagination: PaginationMetadata
}

export interface DocumentRead {
  id: string
  status: DocumentStatus
  original_filename: string
  media_type: string
  size_bytes: number
  sha256: string
  storage_backend: string
  source: string
  title: string | null
  title_source: 'automatic' | 'user' | null
  document_type: string | null
  document_type_source: 'automatic' | 'user' | null
  notes: string | null
  collection_name?: string | null
  tags?: string[]
  created_at: string
  updated_at: string
}

export interface DocumentExtractionRead {
  id: string
  document_id: string
  status: ExtractionStatus
  spans: Array<{ id: string; page_number: number; text: string }>
}

export interface DocumentChunkBuildResponse {
  document_id: string
  chunk_count: number
}

export interface DocumentSearchResult {
  id: string
  document_id: string
  original_filename: string
  page_number: number
  section_number: number
  text: string
  relevance_score: string
}

export interface DocumentSearchResponse {
  query: string
  result_count: number
  limit: number
  results: DocumentSearchResult[]
}

export class DuplicateDocumentUploadError extends Error {
  readonly existingDocumentId: string

  constructor(existingDocumentId: string) {
    super('This PDF is already stored in your document library.')
    this.name = 'DuplicateDocumentUploadError'
    this.existingDocumentId = existingDocumentId
  }
}

export interface DocumentFilters {
  documentType?: string
  name?: string
  collectionName?: string
}

export interface DocumentMetadataUpdate {
  title?: string | null
  document_type?: string | null
  notes?: string | null
  collection_name?: string | null
  tags?: string[]
}

export type DocumentFactUpdate =
  | { value_text: string; value_date?: never; is_cleared?: false }
  | { value_date: string; value_text?: never; is_cleared?: false }
  | { is_cleared: true; value_text?: never; value_date?: never }

export function listDocuments(
  offset = 0,
  limit = 10,
  signal?: AbortSignal,
  filters: DocumentFilters = {},
): Promise<DocumentListResponse> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (filters.documentType) params.set('document_type', filters.documentType)
  if (filters.name) params.set('name', filters.name)
  if (filters.collectionName) params.set('collection_name', filters.collectionName)
  return fetchJson('/documents', params, signal)
}

export function validateDocumentFile(file: File, sizeLimitBytes = maxDocumentSizeBytes): string | null {
  const filename = file.name.trim()
  if (!filename.toLowerCase().endsWith('.pdf')) return 'Choose a file with a .pdf extension.'
  if (filename.length > 255) return 'The PDF filename must be 255 characters or fewer.'
  if (file.type && file.type.toLowerCase() !== 'application/pdf') return 'Choose a PDF file, not another document type.'
  if (file.size === 0) return 'Choose a PDF that is not empty.'
  if (file.size > sizeLimitBytes) return `The PDF exceeds the ${formatBytes(sizeLimitBytes)} upload limit.`
  return null
}

export async function uploadDocument(file: File, signal?: AbortSignal): Promise<DocumentRead> {
  const validation = validateDocumentFile(file)
  if (validation) return Promise.reject(new Error(validation))
  const formData = new FormData()
  formData.append('file', file.type ? file : new File([file], file.name, { type: 'application/pdf' }))
  try {
    return await requestJson('/documents', { method: 'POST', body: formData, signal })
  } catch (error: unknown) {
    if (
      error instanceof ApiRequestError &&
      error.status === 409 &&
      isRecord(error.detail) &&
      typeof error.detail.existing_document_id === 'string'
    ) {
      throw new DuplicateDocumentUploadError(error.detail.existing_document_id)
    }
    throw error
  }
}

export function getDocument(documentId: string): Promise<DocumentRead> {
  return requestJson(`/documents/${documentId}`)
}

export function updateDocumentMetadata(
  documentId: string,
  metadata: DocumentMetadataUpdate,
): Promise<DocumentRead> {
  return requestJson(`/documents/${documentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(metadata),
  })
}

export function updateDocumentFact(
  documentId: string,
  factType: DocumentFactType,
  fact: DocumentFactUpdate,
): Promise<DocumentFact> {
  return requestJson(`/documents/${documentId}/facts/${factType}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fact),
  })
}

export function configureExpirationReminder(
  documentId: string,
  enabled: boolean,
  leadTimeDays: number,
): Promise<DocumentExpirationReminder> {
  return requestJson(`/documents/${documentId}/expiration-reminder`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled, lead_time_days: leadTimeDays }),
  })
}

export function listExpirationReminders(signal?: AbortSignal): Promise<DocumentReminderListResponse> {
  return fetchJson('/documents/expiration-reminders', undefined, signal)
}

export function acknowledgeExpirationReminder(documentId: string): Promise<void> {
  return requestJson(`/documents/${documentId}/expiration-reminder/acknowledge`, { method: 'POST' })
}

export function snoozeExpirationReminder(documentId: string, until: string): Promise<void> {
  return requestJson(`/documents/${documentId}/expiration-reminder/snooze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ until }),
  })
}

export function documentContentUrl(documentId: string): string {
  return buildApiUrl(`/documents/${documentId}/content`)
}

export function extractDocument(documentId: string): Promise<DocumentExtractionRead> {
  return requestJson(`/documents/${documentId}/extraction`, { method: 'PUT' })
}

export function buildDocumentChunks(documentId: string): Promise<DocumentChunkBuildResponse> {
  return requestJson(`/documents/${documentId}/chunks`, { method: 'PUT' })
}

export function searchDocuments(query: string, limit = 10, signal?: AbortSignal): Promise<DocumentSearchResponse> {
  return fetchJson('/documents/search', new URLSearchParams({ q: query.trim(), limit: String(limit) }), signal)
}

export function deleteDocument(documentId: string): Promise<void> {
  return requestNoContent(`/documents/${documentId}`, { method: 'DELETE' })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

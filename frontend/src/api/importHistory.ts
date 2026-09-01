import { fetchJson, requestNoContent } from './client'
import type { ImportStatus } from './imports'
import type { PaginationMetadata } from './transactions'

export interface ImportBatch {
  id: string
  filename: string
  adapter_name: string
  adapter_version: string
  account_label: string | null
  status: ImportStatus
  row_count: number
  imported_count: number
  rejected_count: number
  created_at: string
  updated_at: string
}

export interface ImportBatchListResponse {
  items: ImportBatch[]
  pagination: PaginationMetadata
}

export interface ImportBatchDetail extends ImportBatch {
  transaction_count: number
  duplicate_candidate_count: number
  transactions_url: string
  duplicate_candidates_url: string
  row_errors_persisted: false
}

export interface ImportHistoryFilters {
  status?: ImportStatus
  offset?: number
  limit?: number
}

export function serializeImportHistoryFilters(filters: ImportHistoryFilters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  params.set('offset', String(filters.offset ?? 0))
  params.set('limit', String(filters.limit ?? 10))
  return params
}

export function fetchImportHistory(
  filters: ImportHistoryFilters,
  signal?: AbortSignal,
): Promise<ImportBatchListResponse> {
  return fetchJson('/imports', serializeImportHistoryFilters(filters), signal)
}

export function fetchImportBatchDetail(
  batchId: string,
  signal?: AbortSignal,
): Promise<ImportBatchDetail> {
  return fetchJson(`/imports/${encodeURIComponent(batchId)}`, undefined, signal)
}

export function deleteImportBatch(batchId: string, signal?: AbortSignal): Promise<void> {
  return requestNoContent(`/imports/${encodeURIComponent(batchId)}`, {
    method: 'DELETE',
    signal,
  })
}

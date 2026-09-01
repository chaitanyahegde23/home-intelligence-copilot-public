import { apiFetch } from './client'
import { maxUploadSizeBytes } from './config'

export type ImportStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'completed_with_errors'
  | 'failed'

export interface RowValidationError {
  row_number: number | null
  field: string | null
  message: string
}

export interface TransactionImportResponse {
  import_batch_id: string
  filename: string
  adapter_name: string
  adapter_version: string
  account_label: string | null
  status: ImportStatus
  total_rows: number
  imported_rows: number
  rejected_rows: number
  duplicate_candidates_created: number
  errors: RowValidationError[]
}

export type ImportErrorCode =
  | 'unsupported_file'
  | 'oversized_file'
  | 'invalid_csv'
  | 'server_error'
  | 'network_error'
  | 'invalid_response'

export class ImportRequestError extends Error {
  readonly code: ImportErrorCode
  readonly status: number | undefined

  constructor(message: string, code: ImportErrorCode, status?: number) {
    super(message)
    this.name = 'ImportRequestError'
    this.code = code
    this.status = status
  }
}

const allowedContentTypes = new Set([
  '',
  'application/csv',
  'application/vnd.ms-excel',
  'text/csv',
])

export function validateTransactionFile(
  file: File,
  sizeLimitBytes = maxUploadSizeBytes,
): string | null {
  const filename = file.name.trim()
  if (!filename.toLowerCase().endsWith('.csv')) {
    return 'Choose a file with a .csv extension.'
  }
  if (filename.length > 512) {
    return 'The CSV filename must be 512 characters or fewer.'
  }
  if (!allowedContentTypes.has(file.type.toLowerCase())) {
    return 'Choose a CSV file, not another document type.'
  }
  if (file.size > sizeLimitBytes) {
    return `The CSV exceeds the ${formatBytes(sizeLimitBytes)} upload limit.`
  }
  return null
}

export async function uploadTransactions(
  file: File,
  accountLabel?: string,
  signal?: AbortSignal,
): Promise<TransactionImportResponse> {
  const validationMessage = validateTransactionFile(file)
  if (validationMessage) {
    throw new ImportRequestError(
      validationMessage,
      file.size > maxUploadSizeBytes ? 'oversized_file' : 'unsupported_file',
    )
  }

  const formData = new FormData()
  const uploadFile = file.type
    ? file
    : new File([file], file.name, { type: 'text/csv', lastModified: file.lastModified })
  formData.append('file', uploadFile)
  if (accountLabel) {
    formData.append('account_label', accountLabel)
  }

  let response: Response
  try {
    response = await apiFetch('/imports/transactions', {
      method: 'POST',
      body: formData,
      signal,
    })
  } catch (error: unknown) {
    throw new ImportRequestError(
      error instanceof Error ? `Could not reach the API: ${error.message}` : 'Could not reach the API.',
      'network_error',
    )
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response)
    throw new ImportRequestError(
      detail ?? defaultErrorMessage(response.status),
      errorCodeForStatus(response.status),
      response.status,
    )
  }

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new ImportRequestError('The API returned an unreadable import result.', 'invalid_response')
  }
  if (!isTransactionImportResponse(payload)) {
    throw new ImportRequestError('The API returned an unrecognized import result.', 'invalid_response')
  }
  return payload
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KiB`
  return `${(bytes / (1024 * 1024)).toFixed(bytes % (1024 * 1024) === 0 ? 0 : 1)} MiB`
}

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const payload: unknown = await response.json()
    return isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()
      ? payload.detail
      : null
  } catch {
    return null
  }
}

function defaultErrorMessage(status: number): string {
  if (status === 413) return 'The CSV is larger than the API upload limit.'
  if (status === 415) return 'The API accepts CSV files only.'
  if (status === 422) return 'The CSV format or contents could not be validated.'
  return `The import request failed (${status}).`
}

function errorCodeForStatus(status: number): ImportErrorCode {
  if (status === 413) return 'oversized_file'
  if (status === 415) return 'unsupported_file'
  if (status === 422) return 'invalid_csv'
  return 'server_error'
}

function isTransactionImportResponse(payload: unknown): payload is TransactionImportResponse {
  if (!isRecord(payload)) return false
  const status = payload.status
  const errors = payload.errors
  return (
    typeof payload.import_batch_id === 'string' &&
    payload.import_batch_id.length > 0 &&
    typeof payload.filename === 'string' &&
    typeof payload.adapter_name === 'string' &&
    typeof payload.adapter_version === 'string' &&
    (payload.account_label === null || typeof payload.account_label === 'string') &&
    typeof status === 'string' &&
    ['pending', 'processing', 'completed', 'completed_with_errors', 'failed'].includes(status) &&
    isNonNegativeInteger(payload.total_rows) &&
    isNonNegativeInteger(payload.imported_rows) &&
    isNonNegativeInteger(payload.rejected_rows) &&
    payload.imported_rows + payload.rejected_rows === payload.total_rows &&
    isNonNegativeInteger(payload.duplicate_candidates_created) &&
    Array.isArray(errors) &&
    errors.every(isRowValidationError)
  )
}

function isRowValidationError(value: unknown): value is RowValidationError {
  return (
    isRecord(value) &&
    (value.row_number === null || isNonNegativeInteger(value.row_number)) &&
    (value.field === null || typeof value.field === 'string') &&
    typeof value.message === 'string' &&
    value.message.length > 0
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL ?? '/api'

export const apiBaseUrl = configuredBaseUrl.replace(/\/$/, '')

const DEFAULT_MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024
const configuredMaxUploadSize = Number(import.meta.env.VITE_MAX_UPLOAD_SIZE_BYTES)

export const maxUploadSizeBytes =
  Number.isSafeInteger(configuredMaxUploadSize) && configuredMaxUploadSize > 0
    ? configuredMaxUploadSize
    : DEFAULT_MAX_UPLOAD_SIZE_BYTES

const DEFAULT_MAX_DOCUMENT_SIZE_BYTES = 20 * 1024 * 1024
const configuredMaxDocumentSize = Number(import.meta.env.VITE_MAX_DOCUMENT_SIZE_BYTES)

export const maxDocumentSizeBytes =
  Number.isSafeInteger(configuredMaxDocumentSize) && configuredMaxDocumentSize > 0
    ? configuredMaxDocumentSize
    : DEFAULT_MAX_DOCUMENT_SIZE_BYTES

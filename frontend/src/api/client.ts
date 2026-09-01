import { apiBaseUrl } from './config'

let csrfToken: string | null = null

export function setCsrfToken(value: string | null): void {
  csrfToken = value
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }
  return fetch(buildApiUrl(path), {
    ...init,
    method,
    headers,
    credentials: 'same-origin',
  })
}

export class ApiRequestError extends Error {
  readonly status: number | undefined
  readonly detail: unknown

  constructor(message: string, status?: number, detail?: unknown) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.detail = detail
  }
}

export function buildApiUrl(path: string, params?: URLSearchParams): string {
  const query = params?.toString()
  return `${apiBaseUrl}${path}${query ? `?${query}` : ''}`
}

export async function fetchJson<T>(
  path: string,
  params?: URLSearchParams,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response
  try {
    response = await apiFetch(`${path}${params?.toString() ? `?${params.toString()}` : ''}`, { signal })
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiRequestError(
      error instanceof Error ? `Could not reach the API: ${error.message}` : 'Could not reach the API.',
    )
  }

  if (!response.ok) {
    throw await buildResponseError(response)
  }

  try {
    return (await response.json()) as T
  } catch {
    throw new ApiRequestError('The API returned an unreadable response.', response.status)
  }
}

export async function requestNoContent(
  path: string,
  init: RequestInit = {},
): Promise<void> {
  let response: Response
  try {
    response = await apiFetch(path, init)
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiRequestError(
      error instanceof Error ? `Could not reach the API: ${error.message}` : 'Could not reach the API.',
    )
  }

  if (!response.ok) {
    throw await buildResponseError(response)
  }
}

export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await apiFetch(path, init)
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiRequestError(
      error instanceof Error ? `Could not reach the API: ${error.message}` : 'Could not reach the API.',
    )
  }
  if (!response.ok) {
    throw await buildResponseError(response)
  }
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiRequestError('The API returned an unreadable response.', response.status)
  }
}

async function buildResponseError(response: Response): Promise<ApiRequestError> {
  const detail = await readErrorDetail(response)
  const message = typeof detail === 'string' && detail.trim()
    ? detail
    : `API request failed (${response.status}).`
  return new ApiRequestError(message, response.status, detail)
}

async function readErrorDetail(response: Response): Promise<unknown> {
  try {
    const payload: unknown = await response.json()
    return isRecord(payload) ? payload.detail : null
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

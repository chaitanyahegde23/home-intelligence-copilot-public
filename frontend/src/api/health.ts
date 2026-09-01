import { apiBaseUrl } from './config'

export interface HealthResponse {
  status: 'ok'
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/health`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    throw new Error(`Health request failed (${response.status})`)
  }

  const payload: unknown = await response.json()
  if (!isHealthResponse(payload)) {
    throw new Error('Health response was not recognized')
  }
  return payload
}

function isHealthResponse(payload: unknown): payload is HealthResponse {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    'status' in payload &&
    payload.status === 'ok'
  )
}
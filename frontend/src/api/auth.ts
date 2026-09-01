import { ApiRequestError, apiFetch, fetchJson, setCsrfToken } from './client'

export interface AuthSession {
  mode: 'local' | 'secure'
  authenticated: true
  login: string | null
  role: string
  csrf_token: string | null
}

export async function fetchAuthSession(signal?: AbortSignal): Promise<AuthSession> {
  const session = await fetchJson<AuthSession>('/auth/session', undefined, signal)
  setCsrfToken(session.csrf_token)
  return session
}

export async function login(login: string, password: string): Promise<AuthSession> {
  const response = await apiFetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login, password }),
  })
  if (!response.ok) {
    throw new ApiRequestError(
      response.status === 429 ? 'Too many login attempts. Please wait and try again.' : 'Invalid login or password.',
      response.status,
    )
  }
  const session = (await response.json()) as AuthSession
  setCsrfToken(session.csrf_token)
  return session
}

export async function logout(): Promise<void> {
  const response = await apiFetch('/auth/logout', { method: 'POST' })
  if (!response.ok && response.status !== 401) {
    throw new ApiRequestError('Could not end the session.', response.status)
  }
  setCsrfToken(null)
}

import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { ApiRequestError } from '../api/client'
import { fetchAuthSession, login, logout, type AuthSession } from '../api/auth'

interface AuthGateProps {
  children: ReactNode
}

export function AuthGate({ children }: AuthGateProps) {
  const [session, setSession] = useState<AuthSession | null>(null)
  const [needsLogin, setNeedsLogin] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)

  async function loadSession(signal?: AbortSignal) {
    setBusy(true)
    setError(null)
    try {
      setSession(await fetchAuthSession(signal))
      setNeedsLogin(false)
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      if (reason instanceof ApiRequestError && reason.status === 401) {
        setNeedsLogin(true)
      } else {
        setError(reason instanceof Error ? reason.message : 'Could not verify the session.')
      }
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void fetchAuthSession(controller.signal)
      .then((authenticatedSession) => {
        setSession(authenticatedSession)
        setNeedsLogin(false)
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        if (reason instanceof ApiRequestError && reason.status === 401) {
          setNeedsLogin(true)
        } else {
          setError(reason instanceof Error ? reason.message : 'Could not verify the session.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false)
      })
    return () => controller.abort()
  }, [])

  if (busy) return <main className="auth-screen"><p>Verifying your private workspace…</p></main>
  if (needsLogin) {
    return <LoginScreen onAuthenticated={(authenticatedSession) => {
      setSession(authenticatedSession)
      setNeedsLogin(false)
    }} />
  }
  if (!session) {
    return (
      <main className="auth-screen">
        <div className="auth-card" role="alert">
          <h1>Workspace unavailable</h1>
          <p>{error}</p>
          <button type="button" onClick={() => void loadSession()}>Retry</button>
        </div>
      </main>
    )
  }

  return (
    <>
      {session.mode === 'secure' && (
        <div className="session-bar" aria-label="Signed-in session">
          <span>Signed in as {session.login}</span>
          <button
            type="button"
            onClick={() => void logout().finally(() => {
              setSession(null)
              setNeedsLogin(true)
            })}
          >
            Sign out
          </button>
        </div>
      )}
      {children}
    </>
  )
}

function LoginScreen({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const form = new FormData(event.currentTarget)
    try {
      onAuthenticated(await login(String(form.get('login')), String(form.get('password'))))
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'Login failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-screen">
      <form className="auth-card" onSubmit={(event) => void submit(event)}>
        <p className="eyebrow">Home Intelligence Copilot</p>
        <h1>Open your private workspace</h1>
        <label>Login<input name="login" autoComplete="username" required /></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </main>
  )
}

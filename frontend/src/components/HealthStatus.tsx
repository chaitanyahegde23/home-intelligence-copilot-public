import { useEffect, useState } from 'react'
import { fetchHealth } from '../api/health'

type HealthState =
  | { kind: 'loading' }
  | { kind: 'connected' }
  | { kind: 'error'; message: string }

export function HealthStatus() {
  const [health, setHealth] = useState<HealthState>({ kind: 'loading' })
  const [requestNumber, setRequestNumber] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
      .then(() => setHealth({ kind: 'connected' }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHealth({
            kind: 'error',
            message: error instanceof Error ? error.message : 'API connection failed',
          })
        }
      })
    return () => controller.abort()
  }, [requestNumber])

  const retry = () => {
    setHealth({ kind: 'loading' })
    setRequestNumber((value) => value + 1)
  }

  return (
    <aside className="health-card" aria-labelledby="health-title">
      <div className="health-card-heading">
        <span className={`health-dot health-dot--${health.kind}`} aria-hidden="true" />
        <div>
          <p className="health-label">Local API</p>
          <h2 id="health-title">
            {health.kind === 'loading' && 'Checking API...'}
            {health.kind === 'connected' && 'API connected'}
            {health.kind === 'error' && 'API unavailable'}
          </h2>
        </div>
      </div>
      {health.kind === 'loading' && (
        <p className="health-detail" role="status" aria-live="polite">
          Checking the local service.
        </p>
      )}
      {health.kind === 'connected' && (
        <span className="visually-hidden" role="status" aria-live="polite">
          The deterministic backend is ready.
        </span>
      )}
      {health.kind === 'error' && (
        <div role="alert">
          <p className="health-detail">{health.message}</p>
          <button type="button" onClick={retry}>
            Retry connection
          </button>
        </div>
      )}
    </aside>
  )
}

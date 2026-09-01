import { Component, type ReactNode } from 'react'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  hasError: boolean
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="fatal-error">
          <p className="eyebrow">Application error</p>
          <h1>The interface could not be displayed.</h1>
          <p>Your backend data was not changed. Reload the page to try again.</p>
          <button type="button" onClick={() => window.location.reload()}>
            Reload application
          </button>
        </main>
      )
    }
    return this.props.children
  }
}
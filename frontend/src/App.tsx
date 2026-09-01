import './App.css'
import './Workspace.css'
import { useEffect, useState } from 'react'
import { fetchCapabilities, type ApplicationCapabilities } from './api/capabilities'
import { AuthGate } from './components/AuthGate'
import { CopilotWorkspace } from './components/CopilotWorkspace'
import { DocumentWorkspace } from './components/DocumentWorkspace'
import { HealthStatus } from './components/HealthStatus'
import { ImportHistoryView } from './components/ImportHistoryView'
import { TransactionExplorer } from './components/TransactionExplorer'
import { TransactionImport } from './components/TransactionImport'

function App() {
  return (
    <AuthGate>
      <Workspace />
    </AuthGate>
  )
}

function Workspace() {
  const [capabilities, setCapabilities] = useState<ApplicationCapabilities | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchCapabilities(controller.signal)
      .then(setCapabilities)
      .catch(() => setCapabilities({ documents: true, document_copilot: false, financial_features: false }))
    return () => controller.abort()
  }, [])

  const financeEnabled = capabilities?.financial_features ?? false
  return (
    <div className="app-shell document-first-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="site-topbar">
        <a className="brand" href="#documents" aria-label="Home Intelligence Copilot home">
          <span className="brand-mark" aria-hidden="true">
            HI
          </span>
          <span>
            <strong>Home Intelligence</strong>
            <small>Household archive</small>
          </span>
        </a>
        {financeEnabled && <nav aria-label="Optional financial navigation" className="topbar-nav">
          <a href="#copilot"><span aria-hidden="true">✦</span> Copilot</a>
          <a href="#imports"><span aria-hidden="true">↥</span> Imports</a>
          <a href="#transactions"><span aria-hidden="true">≡</span> Transactions</a>
        </nav>}
        <div className="topbar-status"><HealthStatus /></div>
      </header>

      <main id="main-content" tabIndex={-1}>
        <DocumentWorkspace />
        {financeEnabled && <CopilotWorkspace />}
        {financeEnabled && <div className="import-workspace"><TransactionImport /><ImportHistoryView /></div>}
        {financeEnabled && <TransactionExplorer />}
      </main>
    </div>
  )
}

export default App

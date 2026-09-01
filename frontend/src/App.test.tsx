import { axe } from 'jest-axe'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { fetchAuthSession } from './api/auth'
import { fetchCapabilities } from './api/capabilities'
import { fetchHealth } from './api/health'

vi.mock('./api/auth', () => ({ fetchAuthSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('./api/health', () => ({ fetchHealth: vi.fn() }))
vi.mock('./api/capabilities', () => ({ fetchCapabilities: vi.fn() }))
vi.mock('./components/AnalyticsDashboard', () => ({ AnalyticsDashboard: () => <section /> }))
vi.mock('./components/CopilotWorkspace', () => ({ CopilotWorkspace: () => <section /> }))
vi.mock('./components/DocumentWorkspace', () => ({ DocumentWorkspace: () => <section><h1>Document archive</h1></section> }))
vi.mock('./components/ImportHistoryView', () => ({ ImportHistoryView: () => <section /> }))
vi.mock('./components/TransactionExplorer', () => ({ TransactionExplorer: () => <section /> }))
const mockedFetchAuthSession = vi.mocked(fetchAuthSession)
const mockedFetchHealth = vi.mocked(fetchHealth)
const mockedFetchCapabilities = vi.mocked(fetchCapabilities)

beforeEach(() => {
  mockedFetchAuthSession.mockResolvedValue({ mode: 'local', authenticated: true, login: null, role: 'owner', csrf_token: null })
  mockedFetchHealth.mockResolvedValue({ status: 'ok' })
  mockedFetchCapabilities.mockResolvedValue({ documents: true, document_copilot: true, financial_features: false })
})

describe('App', () => {
  it('renders the compact top bar and connected health state', async () => {
    const { container } = render(<App />)

    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Document archive')
    expect(screen.getByRole('banner')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute(
      'href',
      '#main-content',
    )
    expect(screen.getByRole('link', { name: 'Home Intelligence Copilot home' })).toBeVisible()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^Copilot$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Imports/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Transactions/ })).not.toBeInTheDocument()
    expect(await screen.findByText('API connected')).toBeVisible()
    expect((await axe(container)).violations).toEqual([])
  })

  it('shows financial navigation only when the runtime capability is enabled', async () => {
    mockedFetchCapabilities.mockResolvedValueOnce({ documents: true, document_copilot: true, financial_features: true })
    render(<App />)

    expect(await screen.findByRole('link', { name: /Imports/ })).toBeVisible()
    expect(screen.getByRole('link', { name: /Transactions/ })).toBeVisible()
    expect(screen.getByRole('link', { name: /^Copilot$/ })).toBeVisible()
    expect(screen.getByRole('navigation', { name: 'Optional financial navigation' })).toBeVisible()
  })

  it('shows a health failure and retries without crashing the shell', async () => {
    mockedFetchHealth
      .mockRejectedValueOnce(new Error('Health request failed (503)'))
      .mockResolvedValueOnce({ status: 'ok' })
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Health request failed (503)')
    await user.click(screen.getByRole('button', { name: 'Retry connection' }))
    expect(await screen.findByText('API connected')).toBeVisible()
    expect(mockedFetchHealth).toHaveBeenCalledTimes(2)
  })
})

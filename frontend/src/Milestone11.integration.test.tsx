import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'jest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { fetchAuthSession } from './api/auth'
import { fetchCapabilities } from './api/capabilities'
import { askDocumentQuestion } from './api/copilot'
import { buildDocumentChunks, deleteDocument, extractDocument, listDocuments, listExpirationReminders, searchDocuments, uploadDocument } from './api/documents'
import { fetchHealth } from './api/health'

vi.mock('./api/auth', () => ({ fetchAuthSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('./api/health', () => ({ fetchHealth: vi.fn() }))
vi.mock('./api/capabilities', () => ({ fetchCapabilities: vi.fn() }))
vi.mock('./api/copilot', () => ({ askAnalyticsQuestion: vi.fn(), askDocumentQuestion: vi.fn() }))
vi.mock('./api/documents', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api/documents')>()
  return { ...actual, listDocuments: vi.fn(), listExpirationReminders: vi.fn(), uploadDocument: vi.fn(), extractDocument: vi.fn(), buildDocumentChunks: vi.fn(), searchDocuments: vi.fn(), deleteDocument: vi.fn() }
})
vi.mock('./components/AnalyticsDashboard', () => ({ AnalyticsDashboard: () => <section /> }))
vi.mock('./components/ImportHistoryView', () => ({ ImportHistoryView: () => <section /> }))
vi.mock('./components/TransactionExplorer', () => ({ TransactionExplorer: () => <section /> }))

type DocumentStage = 'empty' | 'stored' | 'extracted' | 'searchable'
let documentStage: DocumentStage
const document = { id: 'doc-synthetic', status: 'stored' as const, original_filename: 'synthetic-household-document.pdf', media_type: 'application/pdf', size_bytes: 2048, sha256: 'a'.repeat(64), source: 'user_upload', title: null, title_source: null, document_type: null, document_type_source: null, notes: null, metadata_inference: null, facts: [], expiration_reminder: null, created_at: '2026-08-15T00:00:00Z', updated_at: '2026-08-15T00:00:00Z' }

function libraryPage() {
  const items = documentStage === 'empty' ? [] : [{ ...document, latest_extraction_status: documentStage === 'stored' ? null : 'completed' as const, latest_extraction_updated_at: documentStage === 'stored' ? null : '2026-08-15T00:01:00Z', chunk_count: documentStage === 'searchable' ? 1 : 0, is_searchable: documentStage === 'searchable' }]
  return { items, pagination: { total: items.length, offset: 0, limit: 10, returned: items.length, has_more: false } }
}

beforeEach(() => {
  documentStage = 'empty'
  vi.mocked(fetchAuthSession).mockResolvedValue({ mode: 'local', authenticated: true, login: null, role: 'owner', csrf_token: null })
  vi.mocked(fetchHealth).mockResolvedValue({ status: 'ok' })
  vi.mocked(fetchCapabilities).mockResolvedValue({ documents: true, document_copilot: true, financial_features: false })
  vi.mocked(listDocuments).mockImplementation(async () => libraryPage())
  vi.mocked(listExpirationReminders).mockResolvedValue({ as_of: '2026-08-20', household_timezone: 'America/Los_Angeles', items: [] })
  vi.mocked(uploadDocument).mockImplementation(async () => { documentStage = 'stored'; return { ...document, storage_backend: 'local_private' } })
  vi.mocked(extractDocument).mockImplementation(async () => { documentStage = 'extracted'; return { id: 'extraction-synthetic', document_id: document.id, status: 'completed', spans: [] } })
  vi.mocked(buildDocumentChunks).mockImplementation(async () => { documentStage = 'searchable'; return { document_id: document.id, chunk_count: 1 } })
  vi.mocked(searchDocuments).mockResolvedValue({ query: 'warranty', result_count: 1, limit: 10, results: [{ id: 'chunk-synthetic', document_id: document.id, original_filename: document.original_filename, page_number: 1, section_number: 1, text: 'The synthetic warranty expires on 2028-06-30.', relevance_score: '1.000000' }] })
  vi.mocked(askDocumentQuestion).mockResolvedValue({ kind: 'verified', answer: 'The synthetic warranty expires on 2028-06-30.', verified: true, evidence_status: 'supported', model: 'synthetic-model', retrieval_terms: ['warranty', 'expire'], citations: [{ citation_id: 'C1', document_id: document.id, chunk_id: 'chunk-synthetic', original_filename: document.original_filename, page_number: 1, section_number: 1, start_offset: 0, end_offset: 48, document_sha256: document.sha256, chunk_sha256: 'b'.repeat(64), excerpt: 'The synthetic warranty expires on 2028-06-30.' }] })
  vi.mocked(deleteDocument).mockImplementation(async () => { documentStage = 'empty' })
})

describe('Milestone 11 integrated workspace', () => {
  it('completes the synthetic document-to-cited-answer-to-deletion flow', async () => {
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByText('No documents have been uploaded.', undefined, { timeout: 5_000 })).toBeVisible()
    await user.upload(screen.getByLabelText('PDF documents'), new File(['%PDF synthetic'], document.original_filename, { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
    expect(await screen.findByRole('button', { name: new RegExp(document.original_filename) })).toBeVisible()
    expect(extractDocument).toHaveBeenCalledWith(document.id)
    expect(buildDocumentChunks).toHaveBeenCalledWith(document.id)
    expect(await screen.findByText('searchable')).toBeVisible()
    await user.type(screen.getByLabelText('Search documents'), 'warranty')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findAllByText('The synthetic warranty expires on 2028-06-30.')).not.toHaveLength(0)
    await user.type(screen.getByLabelText('Question about selected document'), 'When does the synthetic warranty expire?')
    await user.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByRole('link', { name: 'C1 · page 1' })).toHaveAttribute('href', `/api/documents/${document.id}/content`)
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await user.click(screen.getByRole('button', { name: 'Confirm deletion' }))
    expect(await screen.findByText('No documents have been uploaded.', undefined, { timeout: 5_000 })).toBeVisible()
  }, 15_000)

  it('has no detectable accessibility violations across the integrated empty workspace', async () => {
    const { container } = render(<App />)
    await screen.findByText('No documents have been uploaded.', undefined, { timeout: 5_000 })
    expect((await axe(container)).violations).toEqual([])
  })
})

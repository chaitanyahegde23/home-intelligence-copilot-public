import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildDocumentChunks,
  acknowledgeExpirationReminder,
  configureExpirationReminder,
  deleteDocument,
  DuplicateDocumentUploadError,
  extractDocument,
  getDocument,
  listDocuments,
  listExpirationReminders,
  searchDocuments,
  snoozeExpirationReminder,
  uploadDocument,
  updateDocumentMetadata,
  updateDocumentFact,
  type DocumentLibraryItem,
} from '../api/documents'
import { DocumentWorkspace } from './DocumentWorkspace'

vi.mock('../api/documents', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/documents')>()
  return { ...actual, listDocuments: vi.fn(), listExpirationReminders: vi.fn(), uploadDocument: vi.fn(), extractDocument: vi.fn(), buildDocumentChunks: vi.fn(), getDocument: vi.fn(), searchDocuments: vi.fn(), updateDocumentMetadata: vi.fn(), updateDocumentFact: vi.fn(), configureExpirationReminder: vi.fn(), acknowledgeExpirationReminder: vi.fn(), snoozeExpirationReminder: vi.fn(), deleteDocument: vi.fn() }
})

const stored: DocumentLibraryItem = {
  id: 'doc-1', status: 'stored' as const, original_filename: 'sample-household-guide.pdf', media_type: 'application/pdf', size_bytes: 2048, sha256: 'a'.repeat(64), source: 'user_upload', title: null, title_source: null, document_type: null, document_type_source: null, notes: null, metadata_inference: null, facts: [], expiration_reminder: null, created_at: '2026-08-15T00:00:00Z', updated_at: '2026-08-15T00:00:00Z', latest_extraction_status: null, latest_extraction_updated_at: null, chunk_count: 0, is_searchable: false,
}
const page = (items = [stored]) => ({ items, pagination: { total: items.length, offset: 0, limit: 10, returned: items.length, has_more: false } })

beforeEach(() => {
  vi.mocked(listDocuments).mockReset().mockResolvedValue(page())
  vi.mocked(listExpirationReminders).mockReset().mockResolvedValue({ as_of: '2026-08-20', household_timezone: 'America/Los_Angeles', items: [] })
  vi.mocked(uploadDocument).mockReset().mockResolvedValue({ ...stored, storage_backend: 'local_private' })
  vi.mocked(extractDocument).mockReset().mockResolvedValue({ id: 'extract-1', document_id: stored.id, status: 'completed', spans: [] })
  vi.mocked(buildDocumentChunks).mockReset().mockResolvedValue({ document_id: stored.id, chunk_count: 2 })
  vi.mocked(getDocument).mockReset().mockResolvedValue({ ...stored, storage_backend: 'local_private' })
  vi.mocked(searchDocuments).mockReset().mockResolvedValue({ query: 'policy', result_count: 1, limit: 10, results: [{ id: 'chunk-1', document_id: stored.id, original_filename: stored.original_filename, page_number: 2, section_number: 1, text: 'Synthetic policy details.', relevance_score: '1.250000' }] })
  vi.mocked(updateDocumentMetadata).mockReset().mockResolvedValue({ ...stored, storage_backend: 'local_private', title: 'Home guide', document_type: 'warranty', notes: 'Synthetic note' })
  vi.mocked(updateDocumentFact).mockReset()
  vi.mocked(configureExpirationReminder).mockReset()
  vi.mocked(acknowledgeExpirationReminder).mockReset()
  vi.mocked(snoozeExpirationReminder).mockReset()
  vi.mocked(deleteDocument).mockReset().mockResolvedValue()
})

describe('DocumentWorkspace', () => {
  it('loads the library and runs explicit extraction', async () => {
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    expect(await screen.findByRole('button', { name: new RegExp(stored.original_filename) })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Extract text' }))
    expect(extractDocument).toHaveBeenCalledWith(stored.id)
    expect(await screen.findByRole('status')).toHaveTextContent('text extraction completed')
  })

  it('uploads, extracts, indexes, clears the file control, and refreshes the library', async () => {
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    await screen.findByRole('button', { name: new RegExp(stored.original_filename) })
    const input = screen.getByLabelText('PDF documents')
    await user.upload(input, new File(['pdf'], 'guide.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'Upload PDF' }))
    expect(uploadDocument).toHaveBeenCalledWith(expect.objectContaining({ name: 'guide.pdf' }))
    expect(extractDocument).toHaveBeenCalledWith(stored.id)
    expect(buildDocumentChunks).toHaveBeenCalledWith(stored.id)
    expect(await screen.findByRole('status')).toHaveTextContent('was stored and is searchable in 2 text chunks')
    expect(input).toHaveValue('')
    expect(screen.getByText('Upload').closest('details')).not.toHaveAttribute('open')
  })

  it('uploads and processes multiple PDFs in one selection', async () => {
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    await screen.findByRole('button', { name: new RegExp(stored.original_filename) })
    await user.click(screen.getByText('Upload'))
    const input = screen.getByLabelText('PDF documents')
    await user.upload(input, [
      new File(['pdf-one'], 'one.pdf', { type: 'application/pdf' }),
      new File(['pdf-two'], 'two.pdf', { type: 'application/pdf' }),
    ])

    expect(screen.getByText('2 PDFs selected')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Upload 2 PDFs' }))
    expect(uploadDocument).toHaveBeenCalledTimes(2)
    expect(extractDocument).toHaveBeenCalledTimes(2)
    expect(buildDocumentChunks).toHaveBeenCalledTimes(2)
    expect(await screen.findByRole('status')).toHaveTextContent('2 documents stored; 2 searchable')
    expect(input).toHaveValue('')
  })

  it('explains a duplicate and links to the existing document', async () => {
    vi.mocked(uploadDocument).mockRejectedValueOnce(new DuplicateDocumentUploadError(stored.id))
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    await screen.findByRole('button', { name: new RegExp(stored.original_filename) })
    await user.upload(screen.getByLabelText('PDF documents'), new File(['pdf'], 'duplicate.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'Upload PDF' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('already stored')
    expect(screen.getByRole('button', { name: `View ${stored.original_filename}` })).toBeVisible()
  })

  it('keeps a stored document retryable when automatic processing fails', async () => {
    vi.mocked(extractDocument).mockRejectedValueOnce(new Error('Extraction unavailable'))
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    await screen.findByRole('button', { name: new RegExp(stored.original_filename) })
    await user.upload(screen.getByLabelText('PDF documents'), new File(['pdf'], 'retry.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'Upload PDF' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('was stored but processing failed')
    expect(screen.getByRole('button', { name: 'Extract text' })).toBeVisible()
  })

  it('searches document text and renders concise linked provenance', async () => {
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    await screen.findByRole('button', { name: new RegExp(stored.original_filename) })
    expect(screen.queryByText('Synthetic policy details.')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Search documents'), ' policy ')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(searchDocuments).toHaveBeenCalledWith('policy')
    expect(await screen.findByText('Synthetic policy details.')).toBeVisible()
    expect(screen.getByText('Page 2')).toBeVisible()
    expect(screen.getByRole('button', { name: stored.original_filename })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open PDF' })).toHaveAttribute('href', `/api/documents/${stored.id}/content`)
  })

  it('supports filename-only search, immediate type filtering, and metadata editing', async () => {
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    await screen.findByRole('button', { name: new RegExp(stored.original_filename) })
    expect(screen.getByRole('option', { name: 'Employment' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Immigration' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Receipt / invoice' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Search documents'), 'guide')
    await user.click(screen.getByRole('checkbox', { name: 'Filename only' }))
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(searchDocuments).not.toHaveBeenCalled()
    await user.selectOptions(screen.getByLabelText('Document type filter'), 'warranty')
    await waitFor(() => expect(listDocuments).toHaveBeenLastCalledWith(0, 10, expect.any(AbortSignal), { name: 'guide', documentType: 'warranty', collectionName: '' }))

    expect(screen.getByRole('link', { name: 'Open original' })).toHaveAttribute('href', `/api/documents/${stored.id}/content`)
    await user.click(screen.getByRole('button', { name: 'Edit details' }))
    await user.type(screen.getByLabelText('Display title'), 'Home guide')
    await user.selectOptions(screen.getAllByLabelText('Document type')[1]!, 'warranty')
    await user.type(screen.getByLabelText('Notes'), 'Synthetic note')
    await user.click(screen.getByRole('button', { name: 'Save details' }))
    expect(updateDocumentMetadata).toHaveBeenCalledWith(stored.id, {
      title: 'Home guide',
      document_type: 'warranty',
      notes: 'Synthetic note',
      collection_name: null,
      tags: [],
    })
  })

  it('shows extracted facts and saves user corrections', async () => {
    vi.mocked(listDocuments).mockResolvedValueOnce(page([{ ...stored, facts: [{ fact_type: 'expiration_date', value_text: null, value_date: '2030-06-30', is_cleared: false, source: 'automatic', confidence: '0.950', source_page_number: 2, inference_name: 'household_document_facts', inference_version: '1', evidence_code: 'label:expires' }] }]))
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    expect(await screen.findAllByText('2030-06-30')).not.toHaveLength(0)
    expect(screen.getByText('Detected on page 2')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Edit details' }))
    await user.clear(screen.getByLabelText('Expiration date'))
    await user.type(screen.getByLabelText('Expiration date'), '2031-07-01')
    await user.type(screen.getByLabelText('Issuer'), 'Synthetic Authority')
    await user.click(screen.getByRole('button', { name: 'Save details' }))
    expect(updateDocumentFact).toHaveBeenCalledWith(stored.id, 'expiration_date', { value_date: '2031-07-01' })
    expect(updateDocumentFact).toHaveBeenCalledWith(stored.id, 'issuer', { value_text: 'Synthetic Authority' })
  })

  it('organizes a document with a collection and normalized tags', async () => {
    vi.mocked(listDocuments).mockResolvedValue(page([{ ...stored, collection_name: 'Identity', tags: ['family'] }]))
    const user = userEvent.setup()
    render(<DocumentWorkspace />)

    expect(await screen.findByRole('button', { name: 'Identity' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Edit details' }))
    await user.clear(screen.getByLabelText('Collection'))
    await user.type(screen.getByLabelText('Collection'), 'Important records')
    await user.clear(screen.getByLabelText('Tags'))
    await user.type(screen.getByLabelText('Tags'), 'Travel, Family')
    await user.click(screen.getByRole('button', { name: 'Save details' }))

    expect(updateDocumentMetadata).toHaveBeenCalledWith(stored.id, expect.objectContaining({
      collection_name: 'Important records',
      tags: ['travel', 'family'],
    }))
  })

  it('organizes and deletes multiple selected documents', async () => {
    const second = { ...stored, id: 'doc-2', original_filename: 'second-document.pdf' }
    vi.mocked(listDocuments).mockResolvedValue(page([stored, second]))
    const user = userEvent.setup()
    render(<DocumentWorkspace />)

    await screen.findByRole('button', { name: new RegExp(stored.original_filename) })
    await user.click(screen.getByRole('checkbox', { name: 'Select all documents on this page' }))
    expect(screen.getByText('2 selected')).toBeVisible()
    await user.type(screen.getByLabelText('Collection for selected documents'), 'Travel records')
    await user.click(screen.getByRole('button', { name: 'Add to collection' }))
    await waitFor(() => expect(updateDocumentMetadata).toHaveBeenCalledWith(stored.id, { collection_name: 'Travel records' }))
    expect(updateDocumentMetadata).toHaveBeenCalledWith(second.id, { collection_name: 'Travel records' })

    await user.click(screen.getByRole('checkbox', { name: 'Select all documents on this page' }))
    await user.click(screen.getByRole('button', { name: 'Delete selected' }))
    expect(deleteDocument).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }))
    await waitFor(() => expect(deleteDocument).toHaveBeenCalledWith(stored.id))
    expect(deleteDocument).toHaveBeenCalledWith(second.id)
  })

  it('collapses collections and keeps key dates date-only', async () => {
    vi.mocked(listDocuments).mockResolvedValue(page([{ ...stored, is_searchable: true }]))
    const user = userEvent.setup()
    render(<DocumentWorkspace />)

    expect(await screen.findByTitle('No key date')).toHaveTextContent('—')
    expect(screen.queryByText('Searchable')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Collapse collections' }))
    expect(screen.getByRole('button', { name: 'Expand collections' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('configures and acts on an expiration reminder', async () => {
    vi.mocked(listExpirationReminders).mockResolvedValueOnce({ as_of: '2030-06-15', household_timezone: 'America/Los_Angeles', items: [{ document_id: stored.id, display_name: stored.original_filename, expiration_date: '2030-07-01', days_until_expiration: 16, status: 'upcoming', lead_time_days: 30, channel: 'in_app' }] })
    const user = userEvent.setup()
    render(<DocumentWorkspace />)
    expect(await screen.findByRole('button', { name: '1 reminder notification' })).toHaveTextContent('1')
    expect(screen.queryByRole('heading', { name: 'Document reminders' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '1 reminder notification' }))
    expect(await screen.findByRole('heading', { name: 'Document reminders' })).toBeVisible()
    expect(screen.getByText('Expires in 16 days · 2030-07-01')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Snooze 7 days' }))
    expect(snoozeExpirationReminder).toHaveBeenCalledWith(stored.id, '2030-06-22')

    await user.click(screen.getByRole('button', { name: '← Documents' }))
    await user.click(screen.getByRole('button', { name: 'Edit details' }))
    await user.selectOptions(screen.getByLabelText('Reminder'), 'enabled')
    await user.selectOptions(screen.getByLabelText('Remind me before'), '30')
    await user.click(screen.getByRole('button', { name: 'Save details' }))
    expect(configureExpirationReminder).toHaveBeenCalledWith(stored.id, true, 30)
  })

  it('opens an empty notification page without showing a reminder banner', async () => {
    const user = userEvent.setup()
    render(<DocumentWorkspace />)

    expect(await screen.findByRole('button', { name: '0 reminder notifications' })).toBeVisible()
    expect(screen.queryByText(/need attention/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '0 reminder notifications' }))
    expect(screen.getByText('No document reminders need attention.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '← Documents' }))
    expect(screen.getByRole('heading', { name: 'Document archive' })).toBeVisible()
  })

  it('shows automatic metadata provenance and confidence', async () => {
    vi.mocked(listDocuments).mockResolvedValueOnce(page([{
      ...stored,
      title: 'Synthetic Passport Record',
      title_source: 'automatic',
      document_type: 'identity',
      document_type_source: 'automatic',
      metadata_inference: {
        classifier_name: 'household_document_rules', classifier_version: '1',
        suggested_title: 'Synthetic Passport Record', title_evidence_code: 'text:first_heading',
        suggested_document_type: 'identity', document_type_confidence: '0.920',
        evidence_codes: ['text:passport'],
      },
    }]))
    render(<DocumentWorkspace />)

    expect(await screen.findByRole('heading', { name: 'Synthetic Passport Record' })).toBeVisible()
    expect(screen.getByText('Automatically named')).toBeVisible()
    expect(screen.getAllByText('Identity')).not.toHaveLength(0)
    expect(screen.getByText('Automatically detected · 92% confidence')).toBeVisible()
  })

  it('shows Gmail provenance for emailed documents', async () => {
    vi.mocked(listDocuments).mockResolvedValueOnce(page([{
      ...stored,
      source: 'gmail_attachment',
    }]))

    render(<DocumentWorkspace />)

    expect(await screen.findByText('Imported from Gmail')).toBeVisible()
  })

  it('requires inline confirmation before deletion', async () => {
    const user = userEvent.setup()
    vi.mocked(listDocuments).mockResolvedValueOnce(page()).mockResolvedValueOnce(page([]))
    render(<DocumentWorkspace />)
    await screen.findByRole('button', { name: new RegExp(stored.original_filename) })
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(deleteDocument).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Confirm deletion' }))
    expect(deleteDocument).toHaveBeenCalledWith(stored.id)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('was deleted'))
  })

  it('shows empty and error states', async () => {
    vi.mocked(listDocuments).mockResolvedValueOnce(page([]))
    const { unmount } = render(<DocumentWorkspace />)
    expect(await screen.findByText('No documents have been uploaded.')).toBeVisible()
    unmount()
    vi.mocked(listDocuments).mockRejectedValueOnce(new Error('Library unavailable'))
    render(<DocumentWorkspace />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Library unavailable')
  })
})

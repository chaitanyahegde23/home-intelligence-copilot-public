import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  deleteDocument,
  acknowledgeExpirationReminder,
  configureExpirationReminder,
  DuplicateDocumentUploadError,
  listDocuments,
  listExpirationReminders,
  documentContentUrl,
  updateDocumentMetadata,
  updateDocumentFact,
  snoozeExpirationReminder,
  uploadDocument,
  validateDocumentFile,
} from './documents'

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('document API', () => {
  it('validates PDF type, emptiness, filename, and size', () => {
    expect(validateDocumentFile(new File(['x'], 'notes.txt', { type: 'text/plain' }))).toMatch(/\.pdf/)
    expect(validateDocumentFile(new File([], 'notes.pdf', { type: 'application/pdf' }))).toMatch(/not empty/)
    expect(validateDocumentFile(new File(['12'], 'notes.pdf', { type: 'application/pdf' }), 1)).toMatch(/upload limit/)
    expect(validateDocumentFile(new File(['pdf'], 'notes.pdf', { type: 'application/pdf' }))).toBeNull()
  })

  it('lists documents with pagination parameters', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ items: [], pagination: { total: 0, offset: 10, limit: 10, returned: 0, has_more: false } }), { status: 200 }))
    await listDocuments(10, 10)
    expect(fetchMock).toHaveBeenCalledWith('/api/documents?offset=10&limit=10', expect.objectContaining({ method: 'GET' }))
  })

  it('lists with archive filters and builds a private content URL', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ items: [], pagination: { total: 0, offset: 0, limit: 10, returned: 0, has_more: false } }), { status: 200 }))
    await listDocuments(0, 10, undefined, { name: 'warranty', documentType: 'home', collectionName: 'Home records' })
    expect(fetchMock).toHaveBeenCalledWith('/api/documents?offset=0&limit=10&document_type=home&name=warranty&collection_name=Home+records', expect.objectContaining({ method: 'GET' }))
    expect(documentContentUrl('doc-1')).toBe('/api/documents/doc-1/content')
  })

  it('updates document metadata', async () => {
    const payload = { id: 'doc-1', title: 'Home warranty' }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }))
    await updateDocumentMetadata('doc-1', { title: 'Home warranty', document_type: 'warranty', notes: null, collection_name: 'Home records', tags: ['appliance'] })
    expect(fetchMock).toHaveBeenCalledWith('/api/documents/doc-1', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ title: 'Home warranty', document_type: 'warranty', notes: null, collection_name: 'Home records', tags: ['appliance'] }) }))
  })

  it('updates a structured document fact', async () => {
    const payload = { fact_type: 'expiration_date', value_date: '2030-06-30' }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }))
    await updateDocumentFact('doc-1', 'expiration_date', { value_date: '2030-06-30' })
    expect(fetchMock).toHaveBeenCalledWith('/api/documents/doc-1/facts/expiration_date', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ value_date: '2030-06-30' }) }))
  })

  it('lists, configures, acknowledges, and snoozes expiration reminders', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      new Response(JSON.stringify({ items: [] }), { status: 200 }),
    )
    await listExpirationReminders()
    await configureExpirationReminder('doc-1', true, 30)
    await acknowledgeExpirationReminder('doc-1')
    await snoozeExpirationReminder('doc-1', '2030-06-22')
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/documents/expiration-reminders',
      '/api/documents/doc-1/expiration-reminder',
      '/api/documents/doc-1/expiration-reminder/acknowledge',
      '/api/documents/doc-1/expiration-reminder/snooze',
    ])
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ method: 'PUT', body: JSON.stringify({ enabled: true, lead_time_days: 30 }) }))
  })

  it('uploads a PDF and deletes by document id', async () => {
    const payload = { id: 'doc-1', status: 'stored', original_filename: 'sample.pdf', media_type: 'application/pdf', size_bytes: 3, sha256: 'a'.repeat(64), storage_backend: 'local_private', source: 'user_upload', title: null, title_source: null, document_type: null, document_type_source: null, notes: null, created_at: '2026-08-15T00:00:00Z', updated_at: '2026-08-15T00:00:00Z' }
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify(payload), { status: 201 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(uploadDocument(new File(['pdf'], 'sample.pdf', { type: 'application/pdf' }))).resolves.toEqual(payload)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/documents')
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ method: 'POST', body: expect.any(FormData) }))
    await deleteDocument('doc-1')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/documents/doc-1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('turns duplicate upload details into an actionable typed error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: { existing_document_id: 'doc-existing' } }), {
        status: 409,
      }),
    )

    await expect(
      uploadDocument(new File(['pdf'], 'duplicate.pdf', { type: 'application/pdf' })),
    ).rejects.toEqual(expect.objectContaining<Partial<DuplicateDocumentUploadError>>({
      existingDocumentId: 'doc-existing',
    }))
  })
})

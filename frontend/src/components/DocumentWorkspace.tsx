import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { askDocumentQuestion, type DocumentQuestionResponse } from '../api/copilot'
import {
  buildDocumentChunks,
  acknowledgeExpirationReminder,
  configureExpirationReminder,
  deleteDocument,
  documentContentUrl,
  DuplicateDocumentUploadError,
  extractDocument,
  getDocument,
  listDocuments,
  listExpirationReminders,
  searchDocuments,
  snoozeExpirationReminder,
  updateDocumentMetadata,
  updateDocumentFact,
  uploadDocument,
  validateDocumentFile,
  type DocumentLibraryItem,
  type DocumentFactType,
  type DocumentListResponse,
  type DocumentReminderListResponse,
  type DocumentSearchResponse,
} from '../api/documents'
import { maxDocumentSizeBytes } from '../api/config'
import { formatBytes } from '../api/imports'
import { displayTimestamp } from './presentation'

const pageSize = 10
const documentTypeOptions = [
  ['identity', 'Identity'],
  ['tax', 'Tax'],
  ['financial', 'Financial'],
  ['insurance', 'Insurance'],
  ['warranty', 'Warranty'],
  ['home', 'Home'],
  ['employment', 'Employment'],
  ['immigration', 'Immigration'],
  ['legal', 'Legal'],
  ['medical', 'Medical'],
  ['education', 'Education'],
  ['correspondence', 'Correspondence'],
  ['receipt', 'Receipt / invoice'],
  ['other', 'Other'],
] as const

const documentTypeLabel = (value: string | null) =>
  documentTypeOptions.find(([type]) => type === value)?.[1] ?? value ?? 'Unclassified'

const searchExcerpt = (text: string, query: string, limit = 220) => {
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (normalized.length <= limit) return normalized
  const matchIndex = normalized.toLowerCase().indexOf(query.toLowerCase())
  const start = Math.max(0, (matchIndex < 0 ? 0 : matchIndex) - Math.floor(limit / 3))
  const excerpt = normalized.slice(start, start + limit).trim()
  return `${start > 0 ? '…' : ''}${excerpt}${start + limit < normalized.length ? '…' : ''}`
}

const reminderStatusLabel = (status: 'expired' | 'expires_today' | 'upcoming', daysUntilExpiration: number) => {
  if (status === 'expired') return `Expired ${Math.abs(daysUntilExpiration)} days ago`
  if (status === 'expires_today') return 'Expires today'
  return `Expires in ${daysUntilExpiration} days`
}

export function DocumentWorkspace() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadPopoverRef = useRef<HTMLDetailsElement>(null)
  const [offset, setOffset] = useState(0)
  const [library, setLibrary] = useState<DocumentListResponse | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [reminders, setReminders] = useState<DocumentReminderListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [duplicateDocument, setDuplicateDocument] = useState<{ id: string; filename: string } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [, setWorkingId] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchResponse, setSearchResponse] = useState<DocumentSearchResponse | null>(null)
  const [filenameOnly, setFilenameOnly] = useState(false)
  const [typeFilter, setTypeFilter] = useState('')
  const [appliedFilters, setAppliedFilters] = useState({ name: '', documentType: '', collectionName: '' })
  const [collectionsCollapsed, setCollectionsCollapsed] = useState(false)
  const [showReminders, setShowReminders] = useState(false)
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [bulkCollection, setBulkCollection] = useState('')
  const [bulkWorking, setBulkWorking] = useState(false)
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const [editingId, setEditingId] = useState('')
  const [metadata, setMetadata] = useState({ title: '', documentType: '', notes: '', collectionName: '', tags: '', expirationDate: '', documentDate: '', issuer: '', referenceNumber: '', documentSubtype: '', reminderEnabled: false, reminderDays: '90' })
  const [detailQuestion, setDetailQuestion] = useState('')
  const [detailAnswer, setDetailAnswer] = useState<DocumentQuestionResponse | null>(null)
  const [askingDetail, setAskingDetail] = useState(false)

  const loadLibrary = useCallback(async (nextOffset: number, signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const [documents, dueReminders] = await Promise.all([
        listDocuments(nextOffset, pageSize, signal, appliedFilters),
        listExpirationReminders(signal),
      ])
      setLibrary(documents)
      setSelectedId((current) => documents.items.some((item) => item.id === current) ? current : documents.items[0]?.id ?? '')
      setReminders(dueReminders)
    } catch (requestError: unknown) {
      if (!signal?.aborted) setError(requestError instanceof Error ? requestError.message : 'Documents could not be loaded.')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [appliedFilters])

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      listDocuments(offset, pageSize, controller.signal, appliedFilters),
      listExpirationReminders(controller.signal),
    ])
      .then(([documents, dueReminders]) => {
        setLibrary(documents)
        setSelectedId((current) => documents.items.some((item) => item.id === current) ? current : documents.items[0]?.id ?? '')
        setReminders(dueReminders)
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setError(requestError instanceof Error ? requestError.message : 'Documents could not be loaded.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [appliedFilters, offset])

  const goToOffset = (nextOffset: number) => {
    setLoading(true)
    setError('')
    setSelectedDocumentIds([])
    setConfirmBulkDelete(false)
    setOffset(nextOffset)
  }

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (files.length === 0) {
      setError('Choose one or more PDFs to upload.')
      return
    }
    const invalidFile = files.map((selectedFile) => ({ selectedFile, error: validateDocumentFile(selectedFile) })).find((item) => item.error)
    if (invalidFile) {
      setError(`${invalidFile.selectedFile.name}: ${invalidFile.error}`)
      return
    }
    setUploading(true)
    setError('')
    setMessage('')
    setDuplicateDocument(null)
    let storedCount = 0
    let searchableCount = 0
    let singleChunkCount = 0
    const failures: string[] = []
    for (const selectedFile of files) {
      try {
        const uploaded = await uploadDocument(selectedFile)
        storedCount += 1
        try {
          await extractDocument(uploaded.id)
          const indexed = await buildDocumentChunks(uploaded.id)
          searchableCount += 1
          singleChunkCount = indexed.chunk_count
        } catch (processingError: unknown) {
          failures.push(`${uploaded.original_filename} was stored but processing failed: ${processingError instanceof Error ? processingError.message : 'retry from its details'}.`)
        }
      } catch (requestError: unknown) {
        if (requestError instanceof DuplicateDocumentUploadError) {
          try {
            const existing = await getDocument(requestError.existingDocumentId)
            setDuplicateDocument({ id: existing.id, filename: existing.original_filename })
            failures.push(`${selectedFile.name} is already stored.`)
          } catch {
            failures.push(`${selectedFile.name} is already stored as document ${requestError.existingDocumentId}.`)
          }
        } else {
          failures.push(`${selectedFile.name} could not be uploaded: ${requestError instanceof Error ? requestError.message : 'unknown error'}.`)
        }
      }
    }
    setFiles([])
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (uploadPopoverRef.current) uploadPopoverRef.current.open = false
    setOffset(0)
    await loadLibrary(0)
    if (files.length === 1 && searchableCount === 1) setMessage(`${files[0]!.name} was stored and is searchable in ${singleChunkCount} text chunks.`)
    else if (storedCount > 0) setMessage(`${storedCount} document${storedCount === 1 ? '' : 's'} stored; ${searchableCount} searchable.`)
    if (failures.length > 0) setError(failures.join(' '))
    setUploading(false)
  }

  const runAction = async (document: DocumentLibraryItem, action: 'extract' | 'index' | 'delete') => {
    setWorkingId(document.id)
    setError('')
    setMessage('')
    try {
      if (action === 'extract') {
        await extractDocument(document.id)
        setMessage(`${document.original_filename} text extraction completed.`)
      } else if (action === 'index') {
        const result = await buildDocumentChunks(document.id)
        setMessage(`${document.original_filename} is searchable in ${result.chunk_count} text chunks.`)
      } else {
        await deleteDocument(document.id)
        setConfirmDeleteId('')
        setSearchResponse(null)
        setMessage(`${document.original_filename} was deleted.`)
      }
      const nextOffset = action === 'delete' && library?.items.length === 1 ? Math.max(0, offset - pageSize) : offset
      if (nextOffset !== offset) goToOffset(nextOffset)
      else await loadLibrary(nextOffset)
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'The document action failed.')
    } finally {
      setWorkingId('')
    }
  }

  const handleSearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const query = searchQuery.trim()
    if (!query) {
      setError('Enter words to search for.')
      return
    }
    if (filenameOnly) {
      setOffset(0)
      setSearchResponse(null)
      setSelectedDocumentIds([])
      setAppliedFilters((current) => ({ ...current, name: query }))
      return
    }
    setSearching(true)
    setError('')
    try {
      setSearchResponse(await searchDocuments(query))
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'Document search failed.')
    } finally {
      setSearching(false)
    }
  }

  const applyTypeFilter = (documentType: string) => {
    setTypeFilter(documentType)
    setOffset(0)
    setSelectedDocumentIds([])
    setAppliedFilters((current) => ({ ...current, documentType }))
  }

  const clearLibraryFilters = () => {
    setSearchQuery('')
    setFilenameOnly(false)
    setTypeFilter('')
    setSearchResponse(null)
    setSelectedDocumentIds([])
    setOffset(0)
    setAppliedFilters({ name: '', documentType: '', collectionName: '' })
  }

  const beginMetadataEdit = (document: DocumentLibraryItem) => {
    const factValue = (type: DocumentFactType) => {
      const fact = document.facts.find((item) => item.fact_type === type && !item.is_cleared)
      return fact?.value_date ?? fact?.value_text ?? ''
    }
    setEditingId(document.id)
    setMetadata({
      title: document.title ?? '',
      documentType: document.document_type ?? '',
      notes: document.notes ?? '',
      collectionName: document.collection_name ?? '',
      tags: (document.tags ?? []).join(', '),
      expirationDate: factValue('expiration_date'),
      documentDate: factValue('document_date'),
      issuer: factValue('issuer'),
      referenceNumber: factValue('reference_number'),
      documentSubtype: factValue('document_subtype'),
      reminderEnabled: document.expiration_reminder?.enabled ?? false,
      reminderDays: String(document.expiration_reminder?.lead_time_days ?? 90),
    })
  }

  const saveMetadata = async (event: FormEvent<HTMLFormElement>, document: DocumentLibraryItem) => {
    event.preventDefault()
    setWorkingId(document.id)
    setError('')
    setMessage('')
    try {
      await updateDocumentMetadata(document.id, {
        title: metadata.title.trim() || null,
        document_type: metadata.documentType || null,
        notes: metadata.notes.trim() || null,
        collection_name: metadata.collectionName.trim() || null,
        tags: metadata.tags.split(',').map((tag) => tag.trim().toLowerCase()).filter(Boolean),
      })
      const updates: Array<[DocumentFactType, string, 'date' | 'text']> = [
        ['expiration_date', metadata.expirationDate, 'date'],
        ['document_date', metadata.documentDate, 'date'],
        ['issuer', metadata.issuer.trim(), 'text'],
        ['reference_number', metadata.referenceNumber.trim(), 'text'],
        ['document_subtype', metadata.documentSubtype.trim(), 'text'],
      ]
      const currentValue = (type: DocumentFactType) => {
        const fact = document.facts.find((item) => item.fact_type === type && !item.is_cleared)
        return fact?.value_date ?? fact?.value_text ?? ''
      }
      await Promise.all(updates.filter(([type, value]) => value !== currentValue(type)).map(([type, value, kind]) =>
        updateDocumentFact(document.id, type, value ? (kind === 'date' ? { value_date: value } : { value_text: value }) : { is_cleared: true }),
      ))
      const reminderDays = Number(metadata.reminderDays)
      if (
        metadata.reminderEnabled !== (document.expiration_reminder?.enabled ?? false) ||
        reminderDays !== (document.expiration_reminder?.lead_time_days ?? 90)
      ) {
        await configureExpirationReminder(document.id, metadata.reminderEnabled, reminderDays)
      }
      setEditingId('')
      setMessage(`${document.original_filename} metadata was updated.`)
      await loadLibrary(offset)
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'Document metadata could not be updated.')
    } finally {
      setWorkingId('')
    }
  }

  const handleReminderAction = async (documentId: string, action: 'acknowledge' | 'snooze') => {
    setWorkingId(documentId)
    setError('')
    try {
      if (action === 'acknowledge') await acknowledgeExpirationReminder(documentId)
      else {
        const until = new Date(`${reminders?.as_of ?? new Date().toISOString().slice(0, 10)}T00:00:00Z`)
        until.setUTCDate(until.getUTCDate() + 7)
        await snoozeExpirationReminder(documentId, until.toISOString().slice(0, 10))
      }
      await loadLibrary(offset)
      setMessage(action === 'acknowledge' ? 'Reminder acknowledged.' : 'Reminder snoozed for 7 days.')
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'Reminder action failed.')
    } finally {
      setWorkingId('')
    }
  }

  const selectedDocument = library?.items.find((document) => document.id === selectedId) ?? library?.items[0] ?? null
  const collections = Array.from(new Set(library?.items.map((document) => document.collection_name).filter((value): value is string => Boolean(value)) ?? [])).sort()
  const reminderCount = reminders?.items.length ?? 0
  const pageDocumentIds = library?.items.map((document) => document.id) ?? []
  const visibleSelectedDocumentIds = selectedDocumentIds.filter((id) => pageDocumentIds.includes(id))
  const allPageDocumentsSelected = pageDocumentIds.length > 0 && pageDocumentIds.every((id) => visibleSelectedDocumentIds.includes(id))

  const toggleDocumentSelection = (documentId: string) => {
    setConfirmBulkDelete(false)
    setSelectedDocumentIds((current) => current.includes(documentId) ? current.filter((id) => id !== documentId) : [...current, documentId])
  }

  const togglePageSelection = () => {
    setConfirmBulkDelete(false)
    setSelectedDocumentIds(allPageDocumentsSelected ? [] : pageDocumentIds)
  }

  const organizeSelectedDocuments = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const collectionName = bulkCollection.trim()
    if (!collectionName || visibleSelectedDocumentIds.length === 0) return
    setBulkWorking(true)
    setError('')
    setMessage('')
    const selectedIds = [...visibleSelectedDocumentIds]
    const results = await Promise.allSettled(selectedIds.map((documentId) => updateDocumentMetadata(documentId, { collection_name: collectionName })))
    const failedIds = selectedIds.filter((_, index) => results[index]?.status === 'rejected')
    const organizedCount = selectedIds.length - failedIds.length
    await loadLibrary(offset)
    setSelectedDocumentIds(failedIds)
    setBulkCollection('')
    if (organizedCount > 0) setMessage(`${organizedCount} document${organizedCount === 1 ? '' : 's'} organized in ${collectionName}.`)
    if (failedIds.length > 0) setError(`${failedIds.length} document${failedIds.length === 1 ? '' : 's'} could not be organized and remain selected.`)
    setBulkWorking(false)
  }

  const deleteSelectedDocuments = async () => {
    const selectedIds = [...visibleSelectedDocumentIds]
    if (selectedIds.length === 0) return
    setBulkWorking(true)
    setError('')
    setMessage('')
    const results = await Promise.allSettled(selectedIds.map((documentId) => deleteDocument(documentId)))
    const failedIds = selectedIds.filter((_, index) => results[index]?.status === 'rejected')
    const deletedCount = selectedIds.length - failedIds.length
    const nextOffset = deletedCount === library?.items.length ? Math.max(0, offset - pageSize) : offset
    setConfirmBulkDelete(false)
    setSelectedDocumentIds(failedIds)
    setSearchResponse(null)
    if (nextOffset !== offset) goToOffset(nextOffset)
    else await loadLibrary(nextOffset)
    if (deletedCount > 0) setMessage(`${deletedCount} document${deletedCount === 1 ? '' : 's'} deleted.`)
    if (failedIds.length > 0) setError(`${failedIds.length} document${failedIds.length === 1 ? '' : 's'} could not be deleted and remain selected.`)
    setBulkWorking(false)
  }

  const askAboutSelectedDocument = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedDocument || !detailQuestion.trim()) return
    setAskingDetail(true)
    setError('')
    try {
      setDetailAnswer(await askDocumentQuestion(detailQuestion, undefined, selectedDocument.id))
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'The document question failed.')
    } finally {
      setAskingDetail(false)
    }
  }

  return (
    <section className="archive-workspace" id="documents" aria-label="Household documents">
      {showReminders ? <section className="notification-page" id="reminders" aria-labelledby="notification-page-title"><header><button className="button-link" type="button" onClick={() => setShowReminders(false)}>← Documents</button><div><p className="eyebrow">Notifications</p><h1 id="notification-page-title">Document reminders</h1><p>{reminders?.items.length ?? 0} active · household date {reminders?.as_of ?? 'loading'}</p></div></header>{message && <p className="workspace-state workspace-state--success" role="status">{message}</p>}{error && <div className="workspace-state workspace-state--error" role="alert"><p>{error}</p></div>}{reminders && reminders.items.length > 0 ? <div className="notification-list">{reminders.items.map((reminder) => <article key={reminder.document_id}><button className="notification-document" type="button" onClick={() => { setSelectedId(reminder.document_id); setShowReminders(false) }}><strong>{reminder.display_name}</strong><span>{reminderStatusLabel(reminder.status, reminder.days_until_expiration)} · {reminder.expiration_date}</span></button><div className="document-actions"><button type="button" onClick={() => void handleReminderAction(reminder.document_id, 'acknowledge')}>Acknowledge</button><button className="button-secondary" type="button" onClick={() => void handleReminderAction(reminder.document_id, 'snooze')}>Snooze 7 days</button></div></article>)}</div> : <p className="notification-empty">No document reminders need attention.</p>}</section> : <>
      <header className="archive-header"><div><p className="eyebrow">Private household records</p><h1 id="documents-title">Document archive</h1></div><div className="archive-header__actions"><button className="notification-bell" type="button" aria-label={`${reminderCount} reminder notification${reminderCount === 1 ? '' : 's'}`} onClick={() => setShowReminders(true)}><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></svg>{reminderCount > 0 && <span>{reminderCount > 99 ? '99+' : reminderCount}</span>}</button><details ref={uploadPopoverRef} className="upload-popover"><summary className="button-anchor">Upload</summary><form className="document-upload" onSubmit={(event) => void handleUpload(event)}><label htmlFor="document-file">PDF documents</label><input ref={fileInputRef} id="document-file" type="file" accept="application/pdf,.pdf" multiple onChange={(event) => setFiles(Array.from(event.currentTarget.files ?? []))} /><small>Choose one or more PDFs, each up to {formatBytes(maxDocumentSizeBytes)}. Processing is automatic.</small>{files.length > 0 && <p className="upload-selection">{files.length} PDF{files.length === 1 ? '' : 's'} selected</p>}<button type="submit" disabled={uploading}>{uploading ? `Processing ${files.length}…` : `Upload ${files.length > 1 ? `${files.length} PDFs` : 'PDF'}`}</button></form></details></div></header>
      {message && <p className="workspace-state workspace-state--success" role="status">{message}</p>}
      {error && <div className="workspace-state workspace-state--error" role="alert"><p>{error}</p>{duplicateDocument && <button type="button" onClick={() => setSelectedId(duplicateDocument.id)}>View {duplicateDocument.filename}</button>}</div>}
      <div className="archive-commandbar">
        <form className="archive-search" onSubmit={(event) => void handleSearch(event)}><label className="archive-search__query"><span className="sr-only">Search documents</span><input value={searchQuery} placeholder={filenameOnly ? 'Search filenames' : 'Search document text'} maxLength={200} onChange={(event) => setSearchQuery(event.currentTarget.value)} /></label><label className="search-mode"><input type="checkbox" checked={filenameOnly} onChange={(event) => setFilenameOnly(event.currentTarget.checked)} />Filename only</label><button type="submit" disabled={searching}>{searching ? 'Searching…' : 'Search'}</button></form>
        <div className="archive-filter"><label><span className="sr-only">Document type</span><select aria-label="Document type filter" value={typeFilter} onChange={(event) => applyTypeFilter(event.currentTarget.value)}><option value="">All types</option>{documentTypeOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><button className="button-link archive-clear" type="button" onClick={clearLibraryFilters}>Clear</button></div>
      </div>
      {searchResponse && <section className="compact-search-results" aria-live="polite" aria-label="Document search results"><header><strong>{searchResponse.result_count} result{searchResponse.result_count === 1 ? '' : 's'}</strong><span>for “{searchResponse.query}”</span><button className="button-link" type="button" onClick={() => setSearchResponse(null)}>Close</button></header>{searchResponse.results.map((result) => <article key={result.id}><div className="search-result__heading"><button className="search-result__select" type="button" onClick={() => { setSelectedId(result.document_id); setSearchResponse(null) }}>{result.original_filename}</button><span>Page {result.page_number}</span></div><p>{searchExcerpt(result.text, searchResponse.query)}</p><a href={documentContentUrl(result.document_id)} target="_blank" rel="noreferrer">Open PDF</a></article>)}</section>}
      {visibleSelectedDocumentIds.length > 0 && <form className="bulk-action-bar" onSubmit={(event) => void organizeSelectedDocuments(event)}><strong>{visibleSelectedDocumentIds.length} selected</strong><label><span className="sr-only">Collection for selected documents</span><input value={bulkCollection} list="document-collections" maxLength={100} placeholder="Create or choose collection" onChange={(event) => setBulkCollection(event.currentTarget.value)} /></label><datalist id="document-collections">{collections.map((collection) => <option key={collection} value={collection} />)}</datalist><button type="submit" disabled={bulkWorking || !bulkCollection.trim()}>Add to collection</button>{confirmBulkDelete ? <span className="bulk-delete-confirmation"><span>Delete {visibleSelectedDocumentIds.length} permanently?</span><button className="button-danger" type="button" disabled={bulkWorking} onClick={() => void deleteSelectedDocuments()}>Confirm delete</button><button className="button-secondary" type="button" onClick={() => setConfirmBulkDelete(false)}>Cancel</button></span> : <button className="button-danger" type="button" disabled={bulkWorking} onClick={() => setConfirmBulkDelete(true)}>Delete selected</button>}<button className="button-link" type="button" onClick={() => setSelectedDocumentIds([])}>Clear selection</button></form>}
      {loading && <p className="workspace-state" role="status">Loading document library...</p>}
      {!loading && library && library.items.length === 0 && <p className="workspace-state">No documents have been uploaded.</p>}
      {!loading && library && library.items.length > 0 && <div className={`archive-three-pane${collectionsCollapsed ? ' archive-three-pane--collections-collapsed' : ''}`}>
        <nav className={`collection-rail${collectionsCollapsed ? ' collection-rail--collapsed' : ''}`} id="collections" aria-label="Document collections"><div className="collection-rail__header"><strong>Collections</strong><button type="button" aria-label={collectionsCollapsed ? 'Expand collections' : 'Collapse collections'} aria-expanded={!collectionsCollapsed} onClick={() => setCollectionsCollapsed((current) => !current)}><span aria-hidden="true">{collectionsCollapsed ? '›' : '‹'}</span></button></div><div className="collection-rail__links"><button className={!appliedFilters.collectionName ? 'is-active' : ''} type="button" onClick={() => { setSelectedDocumentIds([]); setAppliedFilters((current) => ({ ...current, collectionName: '' })) }}>All documents</button>{collections.map((collection) => <button className={appliedFilters.collectionName === collection ? 'is-active' : ''} type="button" key={collection} onClick={() => { setOffset(0); setSelectedDocumentIds([]); setAppliedFilters((current) => ({ ...current, collectionName: collection })) }}>{collection}</button>)}</div></nav>
        <section className="archive-list" aria-label="Documents"><div className="archive-list-heading"><label className="archive-select-all"><input type="checkbox" checked={allPageDocumentsSelected} onChange={togglePageSelection} /><span className="sr-only">Select all documents on this page</span></label><span>Name</span><span>Type</span><span>Key date</span></div>{library.items.map((document) => { const expiration = document.facts.find((fact) => fact.fact_type === 'expiration_date' && !fact.is_cleared)?.value_date; const documentDate = document.facts.find((fact) => fact.fact_type === 'document_date' && !fact.is_cleared)?.value_date; const keyDate = expiration ?? documentDate; return <div className="archive-row-shell" key={document.id}><label className="archive-select"><input type="checkbox" checked={selectedDocumentIds.includes(document.id)} onChange={() => toggleDocumentSelection(document.id)} /><span className="sr-only">Select {document.title ?? document.original_filename}</span></label><button className={`archive-row${selectedDocument?.id === document.id ? ' archive-row--selected' : ''}`} id={`document-${document.id}`} type="button" onClick={() => { setSelectedId(document.id); setDetailAnswer(null) }}><span className="pdf-icon" aria-hidden="true">PDF</span><span className="archive-row__name"><strong>{document.title ?? document.original_filename}</strong><small>{document.title ? document.original_filename : `${formatBytes(document.size_bytes)} · ${displayTimestamp(document.created_at)}`}</small></span><span className="document-type-chip">{documentTypeLabel(document.document_type)}</span><span className={expiration ? 'key-date key-date--expiration' : 'key-date'} title={expiration ? 'Expiration date' : documentDate ? 'Document date' : 'No key date'}>{keyDate ?? '—'}</span></button></div>})}<div className="pagination" aria-label="Document library pages"><button className="button-secondary" type="button" disabled={offset === 0} onClick={() => goToOffset(Math.max(0, offset - pageSize))}>Previous</button><span>{library.pagination.returned} of {library.pagination.total}</span><button type="button" disabled={!library.pagination.has_more} onClick={() => goToOffset(offset + pageSize)}>Next</button></div></section>
        <aside className="document-detail" aria-label="Selected document details">{selectedDocument && <><iframe className="document-preview" title={`Preview ${selectedDocument.original_filename}`} src={documentContentUrl(selectedDocument.id)} /><div className="detail-heading"><div><h2>{selectedDocument.title ?? selectedDocument.original_filename}</h2><p>{selectedDocument.original_filename}</p></div><span className={`status-chip status-chip--${selectedDocument.latest_extraction_status ?? selectedDocument.status}`}>{selectedDocument.is_searchable ? 'searchable' : selectedDocument.latest_extraction_status ?? selectedDocument.status}</span></div><div className="detail-chips"><span>{documentTypeLabel(selectedDocument.document_type)}</span>{selectedDocument.source === 'gmail_attachment' && <span>Imported from Gmail</span>}{selectedDocument.collection_name && <span>{selectedDocument.collection_name}</span>}{(selectedDocument.tags ?? []).map((tag) => <span key={tag}>#{tag}</span>)}{selectedDocument.is_searchable && <span>OCR / text ready</span>}{selectedDocument.title_source === 'automatic' && <span>Automatically named</span>}{selectedDocument.document_type_source === 'user' && <span>User confirmed</span>}{selectedDocument.document_type_source === 'automatic' && selectedDocument.metadata_inference?.document_type_confidence && <span>Automatically detected · {Math.round(Number(selectedDocument.metadata_inference.document_type_confidence) * 100)}% confidence</span>}</div><dl className="detail-facts"><div><dt>Uploaded</dt><dd>{displayTimestamp(selectedDocument.created_at)}</dd></div>{selectedDocument.facts.filter((fact) => !fact.is_cleared).map((fact) => <div key={fact.fact_type}><dt>{fact.fact_type.replaceAll('_', ' ')}</dt><dd>{fact.value_date ?? fact.value_text}<small>{fact.source === 'automatic' ? `Detected${fact.source_page_number ? ` on page ${fact.source_page_number}` : ''}` : 'User confirmed'}</small></dd></div>)}</dl>{selectedDocument.notes && <p className="document-notes">{selectedDocument.notes}</p>}
          {editingId === selectedDocument.id && <form className="metadata-form detail-edit-form" onSubmit={(event) => void saveMetadata(event, selectedDocument)}><label>Display title<input value={metadata.title} maxLength={255} onChange={(event) => setMetadata((current) => ({ ...current, title: event.target.value }))} /></label><label>Document type<select value={metadata.documentType} onChange={(event) => setMetadata((current) => ({ ...current, documentType: event.target.value }))}><option value="">Unclassified</option>{documentTypeOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Collection<input value={metadata.collectionName} maxLength={100} placeholder="Family identity" onChange={(event) => setMetadata((current) => ({ ...current, collectionName: event.target.value }))} /></label><label>Tags<input value={metadata.tags} maxLength={500} placeholder="tax, 2026, urgent" onChange={(event) => setMetadata((current) => ({ ...current, tags: event.target.value }))} /></label><label>Expiration date<input type="date" value={metadata.expirationDate} onChange={(event) => setMetadata((current) => ({ ...current, expirationDate: event.target.value }))} /></label><label>Document date<input type="date" value={metadata.documentDate} onChange={(event) => setMetadata((current) => ({ ...current, documentDate: event.target.value }))} /></label><label>Issuer<input value={metadata.issuer} onChange={(event) => setMetadata((current) => ({ ...current, issuer: event.target.value }))} /></label><label>Reference number<input value={metadata.referenceNumber} onChange={(event) => setMetadata((current) => ({ ...current, referenceNumber: event.target.value }))} /></label><label>Document subtype<input value={metadata.documentSubtype} onChange={(event) => setMetadata((current) => ({ ...current, documentSubtype: event.target.value }))} /></label><label>Reminder<select value={metadata.reminderEnabled ? 'enabled' : 'disabled'} onChange={(event) => setMetadata((current) => ({ ...current, reminderEnabled: event.target.value === 'enabled' }))}><option value="disabled">Off</option><option value="enabled">On</option></select></label><label>Remind me before<select value={metadata.reminderDays} disabled={!metadata.reminderEnabled} onChange={(event) => setMetadata((current) => ({ ...current, reminderDays: event.target.value }))}><option value="30">30 days</option><option value="60">60 days</option><option value="90">90 days</option><option value="180">180 days</option></select></label><label className="metadata-form__notes">Notes<textarea value={metadata.notes} rows={3} onChange={(event) => setMetadata((current) => ({ ...current, notes: event.target.value }))} /></label><div className="metadata-form__actions"><button type="submit">Save details</button><button className="button-secondary" type="button" onClick={() => setEditingId('')}>Cancel</button></div></form>}
          <div className="document-actions"><a className="button-anchor document-open-link" href={documentContentUrl(selectedDocument.id)} target="_blank" rel="noreferrer">Open original</a><button className="button-secondary" type="button" onClick={() => beginMetadataEdit(selectedDocument)}>Edit details</button>{!selectedDocument.is_searchable && selectedDocument.latest_extraction_status !== 'completed' && <button type="button" onClick={() => void runAction(selectedDocument, 'extract')}>Extract text</button>}{!selectedDocument.is_searchable && selectedDocument.latest_extraction_status === 'completed' && <button type="button" onClick={() => void runAction(selectedDocument, 'index')}>Build search index</button>}{confirmDeleteId !== selectedDocument.id ? <button className="button-danger" type="button" onClick={() => setConfirmDeleteId(selectedDocument.id)}>Delete</button> : <span className="delete-confirmation"><span>Delete permanently?</span><button className="button-danger" type="button" onClick={() => void runAction(selectedDocument, 'delete')}>Confirm deletion</button><button className="button-secondary" type="button" onClick={() => setConfirmDeleteId('')}>Cancel</button></span>}</div>
          <section className="document-question">{detailAnswer && <article aria-live="polite"><p>{detailAnswer.answer}</p>{detailAnswer.citations.map((citation) => <a key={citation.citation_id} href={documentContentUrl(citation.document_id)} target="_blank" rel="noreferrer">{citation.citation_id} · page {citation.page_number}</a>)}</article>}<form onSubmit={(event) => void askAboutSelectedDocument(event)}><label><span className="sr-only">Question about selected document</span><input value={detailQuestion} maxLength={200} placeholder="Ask about this document…" onChange={(event) => setDetailQuestion(event.currentTarget.value)} /></label><button type="submit" disabled={askingDetail || !detailQuestion.trim()}>{askingDetail ? 'Checking…' : 'Ask'}</button></form></section></>}</aside>
      </div>}
      </>}
    </section>
  )
}

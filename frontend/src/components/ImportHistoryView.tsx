import { type FormEvent, useEffect, useState } from 'react'
import {
  deleteImportBatch,
  fetchImportBatchDetail,
  fetchImportHistory,
  type ImportBatchDetail,
  type ImportBatchListResponse,
  type ImportHistoryFilters,
} from '../api/importHistory'
import type { ImportStatus } from '../api/imports'
import {
  buildWorkspaceHref,
  readUrlOffset,
  readUrlParam,
  updateUrlParams,
} from '../api/urlState'
import { displayImportStatus, displayTimestamp } from './presentation'

const pageSize = 10
const statuses: ImportStatus[] = [
  'pending',
  'processing',
  'completed',
  'completed_with_errors',
  'failed',
]

function initialFilters(): ImportHistoryFilters {
  const status = readUrlParam('imports_status')
  return {
    status: statuses.includes(status as ImportStatus) ? (status as ImportStatus) : undefined,
    offset: readUrlOffset('imports_offset'),
    limit: pageSize,
  }
}

export function ImportHistoryView() {
  const [initialDetailId] = useState(() => readUrlParam('import_batch'))
  const [draftStatus, setDraftStatus] = useState<ImportStatus | ''>(initialFilters().status ?? '')
  const [query, setQuery] = useState<ImportHistoryFilters>(initialFilters)
  const [response, setResponse] = useState<ImportBatchListResponse | null>(null)
  const [detail, setDetail] = useState<ImportBatchDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(Boolean(initialDetailId))
  const [error, setError] = useState('')
  const [detailError, setDetailError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [deleteMessage, setDeleteMessage] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    fetchImportHistory(query, controller.signal)
      .then((result) => {
        setResponse(result)
        setLoading(false)
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setError(requestError instanceof Error ? requestError.message : 'Import history could not be loaded.')
          setLoading(false)
        }
      })
    return () => controller.abort()
  }, [query])

  useEffect(() => {
    if (!initialDetailId) return
    const controller = new AbortController()
    fetchImportBatchDetail(initialDetailId, controller.signal)
      .then((result) => setDetail(result))
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setDetailError(
            requestError instanceof Error ? requestError.message : 'Import detail could not be loaded.',
          )
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false)
      })
    return () => controller.abort()
  }, [initialDetailId])

  const applyStatus = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const next = { status: draftStatus || undefined, offset: 0, limit: pageSize }
    setLoading(true)
    setError('')
    updateUrlParams({ imports_status: draftStatus || null, imports_offset: 0 })
    setQuery(next)
  }

  const goToOffset = (offset: number) => {
    const next = { ...query, offset, limit: pageSize }
    setLoading(true)
    setError('')
    updateUrlParams({ imports_offset: offset })
    setQuery(next)
  }

  const loadDetail = async (batchId: string) => {
    setDetailLoading(true)
    setDetailError('')
    updateUrlParams({ import_batch: batchId })
    try {
      setDetail(await fetchImportBatchDetail(batchId))
    } catch (requestError: unknown) {
      setDetail(null)
      setDetailError(requestError instanceof Error ? requestError.message : 'Import detail could not be loaded.')
    } finally {
      setDetailLoading(false)
    }
  }

  const removeDetail = async () => {
    if (!detail) return
    const transactionLabel = detail.transaction_count === 1 ? 'transaction' : 'transactions'
    const confirmed = window.confirm(
      `Delete ${detail.filename} and its ${detail.transaction_count} ${transactionLabel}? This cannot be undone.`,
    )
    if (!confirmed) return

    setDeleting(true)
    setDeleteError('')
    setDeleteMessage('')
    try {
      await deleteImportBatch(detail.id)
      const deletedFilename = detail.filename
      setDetail(null)
      updateUrlParams({ import_batch: null })
      setDeleteMessage(`${deletedFilename} and its imported transactions were deleted.`)

      const nextOffset = response?.items.length === 1 && (query.offset ?? 0) > 0
        ? Math.max(0, (query.offset ?? 0) - pageSize)
        : query.offset ?? 0
      const nextQuery = { ...query, offset: nextOffset, limit: pageSize }
      if (nextOffset !== query.offset) {
        updateUrlParams({ imports_offset: nextOffset })
        setQuery(nextQuery)
      } else {
        setLoading(true)
        try {
          setResponse(await fetchImportHistory(nextQuery))
        } catch (requestError: unknown) {
          setError(
            requestError instanceof Error
              ? `The import was deleted, but history could not be refreshed: ${requestError.message}`
              : 'The import was deleted, but history could not be refreshed.',
          )
        } finally {
          setLoading(false)
        }
      }
    } catch (requestError: unknown) {
      setDeleteError(requestError instanceof Error ? requestError.message : 'The import could not be deleted.')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <section className="workspace-panel" id="history" aria-labelledby="history-title">
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">Import provenance</p>
          <h2 id="history-title">Import history</h2>
        </div>
        <p>Review every batch, its reconciled counts, and the normalized records it created.</p>
      </div>

      <div className="history-layout">
        <div className="history-list">
          <form className="inline-filter" onSubmit={applyStatus}>
        <label>
          Import status
          <select
            value={draftStatus}
            onChange={(event) => setDraftStatus(event.currentTarget.value as ImportStatus | '')}
          >
            <option value="">All statuses</option>
            {statuses.map((status) => (
              <option key={status} value={status}>{displayImportStatus(status)}</option>
            ))}
          </select>
        </label>
        <button type="submit">Apply status</button>
          </form>

          {loading && <p className="workspace-state" role="status">Loading import history...</p>}
          {error && <p className="workspace-state workspace-state--error" role="alert">{error}</p>}
          {!loading && response && (
            <>
          <p className="result-summary">Showing {response.pagination.returned} of {response.pagination.total} imports</p>
          {response.items.length === 0 ? (
            <p className="workspace-state">No imports match this status.</p>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Created</th>
                    <th scope="col">Filename</th>
                    <th scope="col">Status</th>
                    <th scope="col">Rows</th>
                    <th scope="col">Format</th>
                    <th scope="col"><span className="visually-hidden">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {response.items.map((batch) => (
                    <tr key={batch.id}>
                      <td>{displayTimestamp(batch.created_at)}</td>
                      <td><strong>{batch.filename}</strong><small>{batch.account_label ?? 'No account label'}</small></td>
                      <td><span className={`status-chip status-chip--${batch.status}`}>{displayImportStatus(batch.status)}</span></td>
                      <td>{batch.imported_count} imported / {batch.rejected_count} rejected</td>
                      <td>{batch.adapter_name} v{batch.adapter_version}</td>
                      <td><button className="button-link" type="button" onClick={() => void loadDetail(batch.id)}>Details</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="pagination" aria-label="Import history pages">
            <button className="button-secondary" type="button" disabled={response.pagination.offset === 0} onClick={() => goToOffset(Math.max(0, response.pagination.offset - pageSize))}>Previous</button>
            <span>Offset {response.pagination.offset}</span>
            <button type="button" disabled={!response.pagination.has_more} onClick={() => goToOffset(response.pagination.offset + pageSize)}>Next</button>
          </div>
            </>
          )}
        </div>

        <aside className="detail-panel" aria-labelledby="batch-detail-title">
        <h3 id="batch-detail-title">Import batch detail</h3>
        {deleteMessage && <p role="status">{deleteMessage}</p>}
        {deleteError && <p role="alert">{deleteError}</p>}
        {detailLoading && <p role="status">Loading batch detail...</p>}
        {detailError && <p role="alert">{detailError}</p>}
        {!detailLoading && !detail && !detailError && <p>Select an import to inspect its provenance and counts.</p>}
        {detail && !detailLoading && (
          <>
            <p><strong>{detail.filename}</strong></p>
            <dl className="detail-grid">
              <div><dt>Status</dt><dd>{displayImportStatus(detail.status)}</dd></div>
              <div><dt>Total rows</dt><dd>{detail.row_count}</dd></div>
              <div><dt>Transactions</dt><dd>{detail.transaction_count}</dd></div>
              <div><dt>Duplicate candidates</dt><dd>{detail.duplicate_candidate_count}</dd></div>
              <div><dt>Format</dt><dd>{detail.adapter_name} v{detail.adapter_version}</dd></div>
              <div><dt>Batch ID</dt><dd className="id-cell">{detail.id}</dd></div>
            </dl>
            <p className="detail-note">
              Row-level validation errors are returned during upload and are not retained in history.
            </p>
            <a
              className="button-anchor"
              href={buildWorkspaceHref({ tx_batch: detail.id, tx_offset: 0 }, 'transactions')}
            >
              View this batch's transactions
            </a>
            <button
              className="button-danger"
              type="button"
              disabled={deleting}
              onClick={() => void removeDetail()}
            >
              {deleting
                ? 'Deleting import...'
                : `Delete import and ${detail.transaction_count} ${detail.transaction_count === 1 ? 'transaction' : 'transactions'}`}
            </button>
          </>
        )}
        </aside>
      </div>
    </section>
  )
}

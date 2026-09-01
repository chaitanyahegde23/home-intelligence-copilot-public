import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  serializeAnalyticsFilters,
  serializePeriodComparisonFilters,
} from './analytics'
import { buildApiUrl, fetchJson } from './client'
import { deleteImportBatch, serializeImportHistoryFilters } from './importHistory'
import { serializeTransactionFilters } from './transactions'
import { buildWorkspaceHref, updateUrlParams } from './urlState'

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

describe('workspace query serialization', () => {
  it('serializes bounded transaction and import-history filters', () => {
    expect(
      serializeTransactionFilters({
        startDate: '2026-06-01',
        endDate: '2026-06-30',
        accountName: ' Sample Checking ',
        category: 'Groceries',
        merchantName: 'Example Market',
        importBatchId: 'batch-id',
        offset: 20,
        limit: 20,
      }).toString(),
    ).toBe(
      'start_date=2026-06-01&end_date=2026-06-30&account_name=Sample+Checking&category=Groceries&merchant_name=Example+Market&import_batch_id=batch-id&offset=20&limit=20',
    )
    expect(
      serializeImportHistoryFilters({ status: 'completed_with_errors', offset: 10, limit: 10 }).toString(),
    ).toBe('status=completed_with_errors&offset=10&limit=10')
  })

  it('serializes overview and period-comparison filters without client calculations', () => {
    expect(
      serializeAnalyticsFilters({
        startDate: '2026-06-01',
        endDate: '2026-06-30',
        accountName: 'Sample Checking',
      }).toString(),
    ).toBe('start_date=2026-06-01&end_date=2026-06-30&account_name=Sample+Checking')
    expect(
      serializePeriodComparisonFilters({
        currentStartDate: '2026-06-01',
        currentEndDate: '2026-06-30',
        comparisonStartDate: '2026-05-01',
        comparisonEndDate: '2026-05-31',
      }).toString(),
    ).toBe(
      'current_start_date=2026-06-01&current_end_date=2026-06-30&comparison_start_date=2026-05-01&comparison_end_date=2026-05-31',
    )
  })
})

describe('workspace request and URL state', () => {
  it('preserves recoverable filters and builds batch navigation links', () => {
    window.history.replaceState(null, '', '/?analytics_start=2026-06-01#analytics')
    updateUrlParams({ tx_batch: 'batch-id', tx_offset: 0 })
    expect(window.location.search).toContain('analytics_start=2026-06-01')
    expect(window.location.search).toContain('tx_batch=batch-id')
    expect(buildWorkspaceHref({ tx_batch: 'next-batch' }, 'transactions')).toContain(
      'tx_batch=next-batch',
    )
    expect(
      buildWorkspaceHref({ tx_batch: 'next-batch' }, 'transactions').endsWith('#transactions'),
    ).toBe(true)
  })

  it('returns API details for failed requests', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'start_date must be on or before end_date' }), {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    await expect(fetchJson('/transactions')).rejects.toMatchObject({
      status: 422,
      message: 'start_date must be on or before end_date',
    })
    expect(buildApiUrl('/transactions', new URLSearchParams({ limit: '20' }))).toBe(
      '/api/transactions?limit=20',
    )
  })

  it('deletes an encoded import batch through the protected API', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(deleteImportBatch('batch/id')).resolves.toBeUndefined()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/imports/batch%2Fid',
      expect.objectContaining({ method: 'DELETE', credentials: 'same-origin' }),
    )
  })
})

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  deleteImportBatch,
  fetchImportBatchDetail,
  fetchImportHistory,
} from '../api/importHistory'
import { ImportHistoryView } from './ImportHistoryView'

vi.mock('../api/importHistory', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/importHistory')>()
  return {
    ...actual,
    deleteImportBatch: vi.fn(),
    fetchImportHistory: vi.fn(),
    fetchImportBatchDetail: vi.fn(),
  }
})

const mockedFetchHistory = vi.mocked(fetchImportHistory)
const mockedFetchDetail = vi.mocked(fetchImportBatchDetail)
const mockedDeleteImport = vi.mocked(deleteImportBatch)
const batch = {
  id: '18bf35a1-9436-4f36-a97e-a286ab6b3344',
  filename: 'synthetic-transactions.csv',
  adapter_name: 'canonical_csv',
  adapter_version: '1',
  account_label: 'Sample Checking',
  status: 'completed' as const,
  row_count: 2,
  imported_count: 2,
  rejected_count: 0,
  created_at: '2026-06-04T00:00:00Z',
  updated_at: '2026-06-04T00:00:00Z',
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  mockedFetchHistory.mockReset().mockResolvedValue({
    items: [batch],
    pagination: { total: 1, offset: 0, limit: 10, returned: 1, has_more: false },
  })
  mockedFetchDetail.mockReset().mockResolvedValue({
    ...batch,
    transaction_count: 2,
    duplicate_candidate_count: 0,
    transactions_url: `/transactions?import_batch_id=${batch.id}`,
    duplicate_candidates_url: `/duplicate-candidates?import_batch_id=${batch.id}`,
    row_errors_persisted: false,
  })
  mockedDeleteImport.mockReset().mockResolvedValue()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

describe('ImportHistoryView', () => {
  it('lists imports, loads detail, and links to batch transactions', async () => {
    const user = userEvent.setup()
    render(<ImportHistoryView />)
    expect(await screen.findByText('synthetic-transactions.csv')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Details' }))
    const link = screen.getByRole('link', { name: "View this batch's transactions" })
    expect(link).toHaveAttribute('href', expect.stringContaining(`tx_batch=${batch.id}`))
    expect(window.location.search).toContain(`import_batch=${batch.id}`)
  })

  it('applies a status filter and exposes loading failures', async () => {
    mockedFetchHistory.mockResolvedValueOnce({
      items: [batch],
      pagination: { total: 1, offset: 0, limit: 10, returned: 1, has_more: false },
    }).mockRejectedValueOnce(new Error('Import history unavailable'))
    const user = userEvent.setup()
    render(<ImportHistoryView />)
    await screen.findByText('synthetic-transactions.csv')
    await user.selectOptions(screen.getByLabelText('Import status'), 'failed')
    await user.click(screen.getByRole('button', { name: 'Apply status' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Import history unavailable')
    expect(window.location.search).toContain('imports_status=failed')
  })

  it('confirms deletion, removes detail state, and refreshes history', async () => {
    mockedFetchHistory
      .mockResolvedValueOnce({
        items: [batch],
        pagination: { total: 1, offset: 0, limit: 10, returned: 1, has_more: false },
      })
      .mockResolvedValueOnce({
        items: [],
        pagination: { total: 0, offset: 0, limit: 10, returned: 0, has_more: false },
      })
    const user = userEvent.setup()
    render(<ImportHistoryView />)
    await screen.findByText('synthetic-transactions.csv')
    await user.click(screen.getByRole('button', { name: 'Details' }))

    await user.click(screen.getByRole('button', { name: 'Delete import and 2 transactions' }))

    expect(window.confirm).toHaveBeenCalledWith(
      'Delete synthetic-transactions.csv and its 2 transactions? This cannot be undone.',
    )
    expect(mockedDeleteImport).toHaveBeenCalledWith(batch.id)
    expect(await screen.findByRole('status')).toHaveTextContent(
      'synthetic-transactions.csv and its imported transactions were deleted.',
    )
    expect(window.location.search).not.toContain('import_batch=')
  })

  it('keeps the import when confirmation is cancelled and reports delete failures', async () => {
    const user = userEvent.setup()
    render(<ImportHistoryView />)
    await screen.findByText('synthetic-transactions.csv')
    await user.click(screen.getByRole('button', { name: 'Details' }))
    vi.mocked(window.confirm).mockReturnValueOnce(false)

    await user.click(screen.getByRole('button', { name: 'Delete import and 2 transactions' }))
    expect(mockedDeleteImport).not.toHaveBeenCalled()

    mockedDeleteImport.mockRejectedValueOnce(new Error('Delete unavailable'))
    vi.mocked(window.confirm).mockReturnValueOnce(true)
    await user.click(screen.getByRole('button', { name: 'Delete import and 2 transactions' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Delete unavailable')
    expect(screen.getAllByText('synthetic-transactions.csv')[0]).toBeVisible()
  })
})

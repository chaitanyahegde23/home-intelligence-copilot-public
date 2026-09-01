import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { assignTransactionCategory, createCategory, fetchCategories } from '../api/categorization'
import { fetchTransactions } from '../api/transactions'
import { TransactionExplorer } from './TransactionExplorer'

vi.mock('../api/transactions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/transactions')>()
  return { ...actual, fetchTransactions: vi.fn() }
})
vi.mock('../api/categorization', () => ({
  fetchCategories: vi.fn(),
  createCategory: vi.fn(),
  assignTransactionCategory: vi.fn(),
}))

const mockedFetchTransactions = vi.mocked(fetchTransactions)
const transaction = {
  id: 'transaction-id',
  import_batch_id: 'batch-id',
  account_name: 'Sample Checking',
  transaction_date: '2026-06-03',
  posted_date: '2026-06-04',
  description: 'Example Grocery Store',
  merchant_name: 'Example Grocery',
  amount: '-82.45',
  transaction_type: null,
  category: 'Groceries',
  source_file: 'synthetic.csv',
  created_at: '2026-06-04T00:00:00Z',
  updated_at: '2026-06-04T00:00:00Z',
  category_assignment: null,
}

const summary = {
  currency: 'USD' as const,
  transaction_count: 1,
  gross_amount: '82.45',
  spending_amount: '82.45',
  income_amount: '0.00',
  net_amount: '-82.45',
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  mockedFetchTransactions.mockReset()
  vi.mocked(fetchCategories).mockReset().mockResolvedValue([
    { id: 'category-grocery', name: 'Groceries', description: null, is_active: true },
    { id: 'category-home', name: 'Home', description: null, is_active: true },
  ])
  vi.mocked(assignTransactionCategory).mockReset().mockResolvedValue({
    id: 'assignment-id', transaction_id: transaction.id, category_id: 'category-home',
    source: 'manual', rule_id: null, note: null,
    created_at: transaction.created_at, updated_at: transaction.updated_at,
  })
  vi.mocked(createCategory).mockReset().mockResolvedValue({
    id: 'category-utilities', name: 'Utilities', description: null, is_active: true,
  })
})

describe('TransactionExplorer', () => {
  it('renders API rows and paginates with recoverable URL state', async () => {
    mockedFetchTransactions.mockResolvedValue({
      items: [transaction],
      pagination: { total: 21, offset: 0, limit: 20, returned: 1, has_more: true },
      summary: { ...summary, transaction_count: 21 },
    })
    const user = userEvent.setup()
    render(<TransactionExplorer />)

    expect(await screen.findByText('Example Grocery')).toBeVisible()
    expect(screen.getAllByText('-$82.45')).not.toHaveLength(0)
    expect(screen.getByLabelText('Filtered transaction totals')).toHaveTextContent('Gross activity$82.45')
    expect(screen.getByText('imported label')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(mockedFetchTransactions).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 20, limit: 20 }),
      expect.any(AbortSignal),
    ))
    expect(window.location.search).toContain('tx_offset=20')
  })

  it('applies filters and renders API errors', async () => {
    mockedFetchTransactions
      .mockResolvedValueOnce({
        items: [],
        pagination: { total: 0, offset: 0, limit: 20, returned: 0, has_more: false },
        summary: { currency: 'USD', transaction_count: 0, gross_amount: '0.00', spending_amount: '0.00', income_amount: '0.00', net_amount: '0.00' },
      })
      .mockRejectedValueOnce(new Error('start_date must be on or before end_date'))
    const user = userEvent.setup()
    render(<TransactionExplorer />)
    expect(await screen.findByText('No transactions match these filters.')).toBeVisible()

    await user.type(screen.getByLabelText('Account'), 'Sample Checking')
    await user.click(screen.getByRole('button', { name: 'Apply filters' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('start_date must be on or before end_date')
    expect(window.location.search).toContain('tx_account=Sample+Checking')
  })

  it('assigns a category and refreshes current provenance', async () => {
    mockedFetchTransactions
      .mockResolvedValueOnce({
        items: [transaction],
        pagination: { total: 1, offset: 0, limit: 20, returned: 1, has_more: false },
        summary,
      })
      .mockResolvedValueOnce({
        items: [{ ...transaction, category: 'Home', category_assignment: { id: 'assignment-id', category_id: 'category-home', source: 'manual', note: null } }],
        pagination: { total: 1, offset: 0, limit: 20, returned: 1, has_more: false },
        summary,
      })
    const user = userEvent.setup()
    render(<TransactionExplorer />)
    await screen.findByText('Example Grocery')

    await user.selectOptions(screen.getByLabelText('Category for Example Grocery'), 'category-home')

    expect(assignTransactionCategory).toHaveBeenCalledWith(transaction.id, 'category-home')
    expect(await screen.findByText('manual assignment')).toBeVisible()
  })

  it('creates a category for a fresh household', async () => {
    mockedFetchTransactions.mockResolvedValue({
      items: [],
      pagination: { total: 0, offset: 0, limit: 20, returned: 0, has_more: false },
      summary: { currency: 'USD', transaction_count: 0, gross_amount: '0.00', spending_amount: '0.00', income_amount: '0.00', net_amount: '0.00' },
    })
    const user = userEvent.setup()
    render(<TransactionExplorer />)
    await screen.findByText('No transactions match these filters.')

    await user.type(screen.getByLabelText('New category'), 'Utilities')
    await user.click(screen.getByRole('button', { name: 'Create category' }))

    expect(createCategory).toHaveBeenCalledWith('Utilities')
    await waitFor(() => expect(screen.getByLabelText('New category')).toHaveValue(''))
  })
})

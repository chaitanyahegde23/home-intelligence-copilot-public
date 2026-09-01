import { type FormEvent, useEffect, useState } from 'react'
import {
  assignTransactionCategory,
  createCategory,
  fetchCategories,
  type Category,
} from '../api/categorization'
import {
  fetchTransactions,
  type TransactionFilters,
  type TransactionListResponse,
} from '../api/transactions'
import { readUrlOffset, readUrlParam, updateUrlParams } from '../api/urlState'
import { displayMoney } from './presentation'

type LoadState = 'loading' | 'ready' | 'error'

const pageSize = 20

function initialFilters(): TransactionFilters {
  return {
    startDate: readUrlParam('tx_start'),
    endDate: readUrlParam('tx_end'),
    accountName: readUrlParam('tx_account'),
    category: readUrlParam('tx_category'),
    merchantName: readUrlParam('tx_merchant'),
    importBatchId: readUrlParam('tx_batch'),
    offset: readUrlOffset('tx_offset'),
    limit: pageSize,
  }
}

export function TransactionExplorer() {
  const [draft, setDraft] = useState<TransactionFilters>(initialFilters)
  const [query, setQuery] = useState<TransactionFilters>(initialFilters)
  const [response, setResponse] = useState<TransactionListResponse | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [error, setError] = useState('')
  const [categories, setCategories] = useState<Category[]>([])
  const [categoryError, setCategoryError] = useState('')
  const [updatingId, setUpdatingId] = useState('')
  const [newCategoryName, setNewCategoryName] = useState('')
  const [creatingCategory, setCreatingCategory] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetchCategories(controller.signal)
      .then(setCategories)
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setCategoryError(
            requestError instanceof Error ? requestError.message : 'Categories could not be loaded.',
          )
        }
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchTransactions(query, controller.signal)
      .then((result) => {
        setResponse(result)
        setLoadState('ready')
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setError(requestError instanceof Error ? requestError.message : 'Transactions could not be loaded.')
          setLoadState('error')
        }
      })
    return () => controller.abort()
  }, [query])

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const next = { ...draft, offset: 0, limit: pageSize }
    setLoadState('loading')
    setError('')
    writeTransactionUrl(next)
    setQuery(next)
  }

  const clearFilters = () => {
    const next: TransactionFilters = { offset: 0, limit: pageSize }
    setDraft(next)
    setLoadState('loading')
    setError('')
    writeTransactionUrl(next)
    setQuery(next)
  }

  const goToOffset = (offset: number) => {
    const next = { ...query, offset, limit: pageSize }
    setDraft(next)
    setLoadState('loading')
    setError('')
    writeTransactionUrl(next)
    setQuery(next)
  }

  const updateCategory = async (transactionId: string, categoryId: string) => {
    if (!categoryId) return
    setUpdatingId(transactionId)
    setCategoryError('')
    try {
      await assignTransactionCategory(transactionId, categoryId)
      setResponse(await fetchTransactions(query))
    } catch (requestError: unknown) {
      setCategoryError(
        requestError instanceof Error ? requestError.message : 'The category could not be updated.',
      )
    } finally {
      setUpdatingId('')
    }
  }

  const addCategory = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const name = newCategoryName.trim()
    if (!name) return
    setCreatingCategory(true)
    setCategoryError('')
    try {
      const category = await createCategory(name)
      setCategories((current) => [...current, category].sort((left, right) => left.name.localeCompare(right.name)))
      setNewCategoryName('')
    } catch (requestError: unknown) {
      setCategoryError(
        requestError instanceof Error ? requestError.message : 'The category could not be created.',
      )
    } finally {
      setCreatingCategory(false)
    }
  }

  return (
    <section className="workspace-panel" id="transactions" aria-labelledby="transactions-title">
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">Normalized records</p>
          <h2 id="transactions-title">Transactions</h2>
        </div>
        <p>Filter persisted transactions and trace every row back to its import batch.</p>
      </div>

      <form className="filter-grid" onSubmit={applyFilters}>
        <label>
          Start date
          <input
            type="date"
            value={draft.startDate ?? ''}
            onChange={(event) => setDraft({ ...draft, startDate: event.currentTarget.value })}
          />
        </label>
        <label>
          End date
          <input
            type="date"
            value={draft.endDate ?? ''}
            onChange={(event) => setDraft({ ...draft, endDate: event.currentTarget.value })}
          />
        </label>
        <label>
          Account
          <input
            type="text"
            value={draft.accountName ?? ''}
            onChange={(event) => setDraft({ ...draft, accountName: event.currentTarget.value })}
          />
        </label>
        <label>
          Category
          <input
            type="text"
            value={draft.category ?? ''}
            onChange={(event) => setDraft({ ...draft, category: event.currentTarget.value })}
          />
        </label>
        <label>
          Merchant
          <input
            type="text"
            value={draft.merchantName ?? ''}
            onChange={(event) => setDraft({ ...draft, merchantName: event.currentTarget.value })}
          />
        </label>
        <label>
          Import batch ID
          <input
            type="text"
            value={draft.importBatchId ?? ''}
            onChange={(event) => setDraft({ ...draft, importBatchId: event.currentTarget.value })}
          />
        </label>
        <div className="filter-actions">
          <button type="submit">Apply filters</button>
          <button className="button-secondary" type="button" onClick={clearFilters}>
            Clear
          </button>
        </div>
      </form>

      <form className="category-manager" onSubmit={(event) => void addCategory(event)}>
        <label htmlFor="new-category">New category</label>
        <input
          id="new-category"
          type="text"
          maxLength={255}
          placeholder="e.g. Groceries"
          value={newCategoryName}
          onChange={(event) => setNewCategoryName(event.currentTarget.value)}
        />
        <button type="submit" disabled={creatingCategory || !newCategoryName.trim()}>
          {creatingCategory ? 'Creating...' : 'Create category'}
        </button>
        <small>Create a category once, then assign it directly from any transaction row.</small>
      </form>

      {loadState === 'loading' && <p className="workspace-state" role="status">Loading transactions...</p>}
      {loadState === 'error' && <p className="workspace-state workspace-state--error" role="alert">{error}</p>}
      {categoryError && <p className="workspace-state workspace-state--error" role="alert">{categoryError}</p>}
      {loadState === 'ready' && response && (
        <>
          <div className="transaction-summary" aria-label="Filtered transaction totals">
            <article><span>Spending</span><strong>{displayMoney(response.summary.spending_amount, response.summary.currency)}</strong></article>
            <article><span>Income</span><strong>{displayMoney(response.summary.income_amount, response.summary.currency)}</strong></article>
            <article><span>Net</span><strong>{displayMoney(response.summary.net_amount, response.summary.currency)}</strong></article>
            <article><span>Gross activity</span><strong>{displayMoney(response.summary.gross_amount, response.summary.currency)}</strong></article>
          </div>
          <p className="result-summary">
            Showing {response.pagination.returned} of {response.pagination.total} transactions · totals include all {response.summary.transaction_count} matches
          </p>
          {response.items.length === 0 ? (
            <p className="workspace-state">No transactions match these filters.</p>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Description</th>
                    <th scope="col">Account</th>
                    <th scope="col">Category</th>
                    <th scope="col">Amount</th>
                    <th scope="col">Import batch</th>
                  </tr>
                </thead>
                <tbody>
                  {response.items.map((transaction) => (
                    <tr key={transaction.id}>
                      <td>{transaction.transaction_date}</td>
                      <td>
                        <strong>{transaction.merchant_name ?? transaction.description}</strong>
                        {transaction.merchant_name && <small>{transaction.description}</small>}
                      </td>
                      <td>{transaction.account_name ?? 'Not provided'}</td>
                      <td>
                        <label className="visually-hidden" htmlFor={`category-${transaction.id}`}>Category for {transaction.merchant_name ?? transaction.description}</label>
                        <select
                          className="category-select"
                          id={`category-${transaction.id}`}
                          value={categories.find((category) => category.name === transaction.category)?.id ?? ''}
                          disabled={updatingId === transaction.id || categories.length === 0}
                          onChange={({ currentTarget: { value } }) => void updateCategory(transaction.id, value)}
                        >
                          <option value="">{categories.some((category) => category.name === transaction.category) ? 'Choose category' : transaction.category ?? 'Uncategorized'}</option>
                          {categories.map((category) => <option value={category.id} key={category.id}>{category.name}</option>)}
                        </select>
                        <small className="category-provenance">{updatingId === transaction.id ? 'Saving...' : transaction.category_assignment ? `${transaction.category_assignment.source} assignment` : transaction.category ? 'imported label' : 'no assignment'}</small>
                      </td>
                      <td className="money-cell">{displayMoney(transaction.amount)}</td>
                      <td className="id-cell">{transaction.import_batch_id}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot><tr><th scope="row" colSpan={6}>Filtered gross activity {displayMoney(response.summary.gross_amount, response.summary.currency)} · net {displayMoney(response.summary.net_amount, response.summary.currency)}</th></tr></tfoot>
              </table>
            </div>
          )}
          <div className="pagination" aria-label="Transaction pages">
            <button
              className="button-secondary"
              type="button"
              disabled={response.pagination.offset === 0}
              onClick={() => goToOffset(Math.max(0, response.pagination.offset - pageSize))}
            >
              Previous
            </button>
            <span>Offset {response.pagination.offset}</span>
            <button
              type="button"
              disabled={!response.pagination.has_more}
              onClick={() => goToOffset(response.pagination.offset + pageSize)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  )
}

function writeTransactionUrl(filters: TransactionFilters) {
  updateUrlParams({
    tx_start: filters.startDate ?? null,
    tx_end: filters.endDate ?? null,
    tx_account: filters.accountName?.trim() ?? null,
    tx_category: filters.category?.trim() ?? null,
    tx_merchant: filters.merchantName?.trim() ?? null,
    tx_batch: filters.importBatchId?.trim() ?? null,
    tx_offset: filters.offset ?? 0,
  })
}

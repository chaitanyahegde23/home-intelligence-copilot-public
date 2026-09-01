import { fetchJson } from './client'

export interface Transaction {
  id: string
  import_batch_id: string
  account_name: string | null
  transaction_date: string
  posted_date: string | null
  description: string
  merchant_name: string | null
  amount: string
  transaction_type: string | null
  category: string | null
  source_file: string
  created_at: string
  updated_at: string
  category_assignment: {
    id: string
    category_id: string
    source: 'imported' | 'rule' | 'manual'
    note: string | null
  } | null
}

export interface PaginationMetadata {
  total: number
  offset: number
  limit: number
  returned: number
  has_more: boolean
}

export interface TransactionListResponse {
  items: Transaction[]
  pagination: PaginationMetadata
  summary: {
    currency: 'USD'
    transaction_count: number
    gross_amount: string
    spending_amount: string
    income_amount: string
    net_amount: string
  }
}

export interface TransactionFilters {
  startDate?: string
  endDate?: string
  accountName?: string
  category?: string
  merchantName?: string
  importBatchId?: string
  offset?: number
  limit?: number
}

export function serializeTransactionFilters(filters: TransactionFilters): URLSearchParams {
  const params = new URLSearchParams()
  appendText(params, 'start_date', filters.startDate)
  appendText(params, 'end_date', filters.endDate)
  appendText(params, 'account_name', filters.accountName)
  appendText(params, 'category', filters.category)
  appendText(params, 'merchant_name', filters.merchantName)
  appendText(params, 'import_batch_id', filters.importBatchId)
  params.set('offset', String(filters.offset ?? 0))
  params.set('limit', String(filters.limit ?? 20))
  return params
}

export function fetchTransactions(
  filters: TransactionFilters,
  signal?: AbortSignal,
): Promise<TransactionListResponse> {
  return fetchJson('/transactions', serializeTransactionFilters(filters), signal)
}

function appendText(params: URLSearchParams, name: string, value?: string) {
  const normalized = value?.trim()
  if (normalized) params.set(name, normalized)
}

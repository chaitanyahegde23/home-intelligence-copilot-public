import { fetchJson, requestJson } from './client'

export interface Category {
  id: string
  name: string
  description: string | null
  is_active: boolean
}

export interface CategoryAssignment {
  id: string
  transaction_id: string
  category_id: string
  source: 'imported' | 'rule' | 'manual'
  rule_id: string | null
  note: string | null
  created_at: string
  updated_at: string
}

export function fetchCategories(signal?: AbortSignal): Promise<Category[]> {
  return fetchJson('/categories', undefined, signal)
}

export function createCategory(name: string): Promise<Category> {
  return requestJson('/categories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description: null, is_active: true }),
  })
}

export function assignTransactionCategory(
  transactionId: string,
  categoryId: string,
): Promise<CategoryAssignment> {
  return requestJson(`/transactions/${encodeURIComponent(transactionId)}/category-assignment`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category_id: categoryId, note: null }),
  })
}

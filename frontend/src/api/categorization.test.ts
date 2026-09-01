import { beforeEach, describe, expect, it, vi } from 'vitest'
import { assignTransactionCategory, createCategory, fetchCategories } from './categorization'

beforeEach(() => vi.restoreAllMocks())

describe('categorization API', () => {
  it('lists, creates, and manually assigns categories', async () => {
    const category = { id: 'category-1', name: 'Groceries', description: null, is_active: true }
    const assignment = {
      id: 'assignment-1', transaction_id: 'transaction/1', category_id: category.id,
      source: 'manual', rule_id: null, note: null,
      created_at: '2026-08-15T00:00:00Z', updated_at: '2026-08-15T00:00:00Z',
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify([category]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(category), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(assignment), { status: 200 }))

    await expect(fetchCategories()).resolves.toEqual([category])
    await expect(createCategory(category.name)).resolves.toEqual(category)
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/categories', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ name: category.name, description: null, is_active: true }),
    }))
    await expect(assignTransactionCategory('transaction/1', category.id)).resolves.toEqual(assignment)
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/transactions/transaction%2F1/category-assignment',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ category_id: category.id, note: null }),
      }),
    )
  })
})

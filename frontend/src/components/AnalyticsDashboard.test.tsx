import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchCategorySpending,
  fetchPeriodComparison,
  fetchSpendingSummary,
} from '../api/analytics'
import { AnalyticsDashboard } from './AnalyticsDashboard'

vi.mock('../api/analytics', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/analytics')>()
  return {
    ...actual,
    fetchSpendingSummary: vi.fn(),
    fetchCategorySpending: vi.fn(),
    fetchPeriodComparison: vi.fn(),
  }
})

const mockedSummary = vi.mocked(fetchSpendingSummary)
const mockedCategories = vi.mocked(fetchCategorySpending)
const mockedComparison = vi.mocked(fetchPeriodComparison)

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  mockedSummary.mockReset().mockResolvedValue({
    semantics_version: '1.0',
    metric: 'gross_spending',
    currency: 'USD',
    total_spending: '125.45',
    transaction_count: 2,
  })
  mockedCategories.mockReset().mockResolvedValue({
    semantics_version: '1.0',
    metric: 'gross_spending_by_category',
    currency: 'USD',
    total_spending: '125.45',
    transaction_count: 2,
    groups: [
      {
        category: 'Groceries',
        bucket: 'category',
        total_spending: '125.45',
        transaction_count: 2,
        percentage: '100.00',
      },
    ],
  })
  mockedComparison.mockReset().mockResolvedValue({
    semantics_version: '1.0',
    metric: 'gross_spending_period_comparison',
    currency: 'USD',
    current_period: {
      start_date: '2026-06-01',
      end_date: '2026-06-30',
      total_spending: '125.45',
      transaction_count: 2,
    },
    comparison_period: {
      start_date: '2026-05-01',
      end_date: '2026-05-31',
      total_spending: '100.00',
      transaction_count: 1,
    },
    absolute_change: '25.45',
    percentage_change: '25.45',
    category_deltas: [],
  })
})

describe('AnalyticsDashboard', () => {
  it('renders summary and category values returned by the API', async () => {
    const user = userEvent.setup()
    render(<AnalyticsDashboard />)
    const overview = screen.getByRole('article', { name: 'Spending overview' })
    await user.type(within(overview).getByLabelText('Start date'), '2026-06-01')
    await user.type(within(overview).getByLabelText('End date'), '2026-06-30')
    await user.click(within(overview).getByRole('button', { name: 'View spending' }))

    expect(await within(overview).findByText('$125.45', { selector: 'strong' })).toBeVisible()
    expect(within(overview).getByText('Groceries')).toBeVisible()
    expect(within(overview).getByText('100.00%')).toBeVisible()
    expect(window.location.search).toContain('analytics_start=2026-06-01')
  })

  it('renders period comparison values and an API error state', async () => {
    const user = userEvent.setup()
    render(<AnalyticsDashboard />)
    const comparison = screen.getByRole('article', { name: 'Compare periods' })
    const current = within(comparison).getByRole('group', { name: 'Current period' })
    const baseline = within(comparison).getByRole('group', { name: 'Comparison period' })
    await user.type(within(current).getByLabelText('Start date'), '2026-06-01')
    await user.type(within(current).getByLabelText('End date'), '2026-06-30')
    await user.type(within(baseline).getByLabelText('Start date'), '2026-05-01')
    await user.type(within(baseline).getByLabelText('End date'), '2026-05-31')
    await user.click(within(comparison).getByRole('button', { name: 'Compare periods' }))
    expect(await within(comparison).findByText('$25.45')).toBeVisible()

    mockedComparison.mockRejectedValueOnce(new Error('Comparison unavailable'))
    await user.click(within(comparison).getByRole('button', { name: 'Compare periods' }))
    expect(await within(comparison).findByRole('alert')).toHaveTextContent('Comparison unavailable')
  })

  it('restores shared analytics URLs and loads their verified results', async () => {
    window.history.replaceState(null, '', '/?analytics_start=2026-06-01&analytics_end=2026-06-30&compare_current_start=2026-06-01&compare_current_end=2026-06-30&compare_baseline_start=2026-05-01&compare_baseline_end=2026-05-31#analytics')
    render(<AnalyticsDashboard />)
    expect(await screen.findAllByText('$125.45', { selector: 'strong' })).toHaveLength(2)
    expect(await screen.findByText('$25.45')).toBeVisible()
    expect(mockedSummary).toHaveBeenCalledWith(expect.objectContaining({ startDate: '2026-06-01' }), expect.any(AbortSignal))
    expect(mockedComparison).toHaveBeenCalledWith(expect.objectContaining({ comparisonStartDate: '2026-05-01' }), expect.any(AbortSignal))
  })
})

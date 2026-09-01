import { fetchJson } from './client'

export interface AnalyticsFilters {
  startDate: string
  endDate: string
  accountName?: string
}

export interface SpendingSummary {
  semantics_version: '1.0'
  metric: 'gross_spending'
  currency: 'USD'
  total_spending: string
  transaction_count: number
}

export interface CategorySpendingGroup {
  category: string | null
  bucket: 'category' | 'uncategorized'
  total_spending: string
  transaction_count: number
  percentage: string
}

export interface CategorySpending {
  semantics_version: '1.0'
  metric: 'gross_spending_by_category'
  currency: 'USD'
  total_spending: string
  transaction_count: number
  groups: CategorySpendingGroup[]
}

export interface PeriodComparisonFilters {
  currentStartDate: string
  currentEndDate: string
  comparisonStartDate: string
  comparisonEndDate: string
  accountName?: string
}

export interface ComparedPeriod {
  start_date: string
  end_date: string
  total_spending: string
  transaction_count: number
}

export interface CategorySpendingDelta {
  category: string | null
  bucket: 'category' | 'uncategorized'
  current_spending: string
  comparison_spending: string
  absolute_change: string
  current_transaction_count: number
  comparison_transaction_count: number
  transaction_count_change: number
}

export interface PeriodComparison {
  semantics_version: '1.0'
  metric: 'gross_spending_period_comparison'
  currency: 'USD'
  current_period: ComparedPeriod
  comparison_period: ComparedPeriod
  absolute_change: string
  percentage_change: string | null
  category_deltas: CategorySpendingDelta[]
}

export function serializeAnalyticsFilters(filters: AnalyticsFilters): URLSearchParams {
  const params = new URLSearchParams({
    start_date: filters.startDate,
    end_date: filters.endDate,
  })
  if (filters.accountName?.trim()) params.set('account_name', filters.accountName.trim())
  return params
}

export function serializePeriodComparisonFilters(
  filters: PeriodComparisonFilters,
): URLSearchParams {
  const params = new URLSearchParams({
    current_start_date: filters.currentStartDate,
    current_end_date: filters.currentEndDate,
    comparison_start_date: filters.comparisonStartDate,
    comparison_end_date: filters.comparisonEndDate,
  })
  if (filters.accountName?.trim()) params.set('account_name', filters.accountName.trim())
  return params
}

export function fetchSpendingSummary(
  filters: AnalyticsFilters,
  signal?: AbortSignal,
): Promise<SpendingSummary> {
  return fetchJson('/analytics/spending/summary', serializeAnalyticsFilters(filters), signal)
}

export function fetchCategorySpending(
  filters: AnalyticsFilters,
  signal?: AbortSignal,
): Promise<CategorySpending> {
  return fetchJson('/analytics/spending/by-category', serializeAnalyticsFilters(filters), signal)
}

export function fetchPeriodComparison(
  filters: PeriodComparisonFilters,
  signal?: AbortSignal,
): Promise<PeriodComparison> {
  return fetchJson(
    '/analytics/spending/compare',
    serializePeriodComparisonFilters(filters),
    signal,
  )
}

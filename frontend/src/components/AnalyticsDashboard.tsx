import { type FormEvent, useEffect, useState } from 'react'
import {
  fetchCategorySpending,
  fetchPeriodComparison,
  fetchSpendingSummary,
  type AnalyticsFilters,
  type CategorySpending,
  type PeriodComparison,
  type PeriodComparisonFilters,
  type SpendingSummary,
} from '../api/analytics'
import { readUrlParam, updateUrlParams } from '../api/urlState'
import { displayMoney } from './presentation'

function initialAnalyticsFilters(): AnalyticsFilters {
  return {
    startDate: readUrlParam('analytics_start'),
    endDate: readUrlParam('analytics_end'),
    accountName: readUrlParam('analytics_account'),
  }
}

function initialComparisonFilters(): PeriodComparisonFilters {
  return {
    currentStartDate: readUrlParam('compare_current_start'),
    currentEndDate: readUrlParam('compare_current_end'),
    comparisonStartDate: readUrlParam('compare_baseline_start'),
    comparisonEndDate: readUrlParam('compare_baseline_end'),
    accountName: readUrlParam('compare_account'),
  }
}

export function AnalyticsDashboard() {
  const [initialOverview] = useState(initialAnalyticsFilters)
  const hasInitialOverview = Boolean(
    initialOverview.startDate && initialOverview.endDate,
  )
  const [filters, setFilters] = useState<AnalyticsFilters>(initialOverview)
  const [summary, setSummary] = useState<SpendingSummary | null>(null)
  const [categories, setCategories] = useState<CategorySpending | null>(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(hasInitialOverview)
  const [analyticsError, setAnalyticsError] = useState('')
  const [initialComparison] = useState(initialComparisonFilters)
  const hasInitialComparison = Boolean(
    initialComparison.currentStartDate &&
    initialComparison.currentEndDate &&
    initialComparison.comparisonStartDate &&
    initialComparison.comparisonEndDate,
  )
  const [comparisonFilters, setComparisonFilters] =
    useState<PeriodComparisonFilters>(initialComparison)
  const [comparison, setComparison] = useState<PeriodComparison | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(hasInitialComparison)
  const [comparisonError, setComparisonError] = useState('')

  useEffect(() => {
    if (!hasInitialOverview) return
    const controller = new AbortController()
    Promise.all([
      fetchSpendingSummary(initialOverview, controller.signal),
      fetchCategorySpending(initialOverview, controller.signal),
    ])
      .then(([nextSummary, nextCategories]) => {
        setSummary(nextSummary)
        setCategories(nextCategories)
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setAnalyticsError(
            requestError instanceof Error
              ? requestError.message
              : 'Spending analytics could not be loaded.',
          )
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setAnalyticsLoading(false)
      })
    return () => controller.abort()
  }, [hasInitialOverview, initialOverview])

  useEffect(() => {
    if (!hasInitialComparison) return
    const controller = new AbortController()
    fetchPeriodComparison(initialComparison, controller.signal)
      .then((result) => setComparison(result))
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setComparisonError(
            requestError instanceof Error
              ? requestError.message
              : 'Period comparison could not be loaded.',
          )
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setComparisonLoading(false)
      })
    return () => controller.abort()
  }, [hasInitialComparison, initialComparison])

  const loadAnalytics = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setAnalyticsLoading(true)
    setAnalyticsError('')
    setSummary(null)
    setCategories(null)
    updateUrlParams({
      analytics_start: filters.startDate,
      analytics_end: filters.endDate,
      analytics_account: filters.accountName?.trim() ?? null,
    })
    try {
      const [nextSummary, nextCategories] = await Promise.all([
        fetchSpendingSummary(filters),
        fetchCategorySpending(filters),
      ])
      setSummary(nextSummary)
      setCategories(nextCategories)
    } catch (requestError: unknown) {
      setAnalyticsError(requestError instanceof Error ? requestError.message : 'Spending analytics could not be loaded.')
    } finally {
      setAnalyticsLoading(false)
    }
  }

  const loadComparison = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setComparisonLoading(true)
    setComparisonError('')
    setComparison(null)
    updateUrlParams({
      compare_current_start: comparisonFilters.currentStartDate,
      compare_current_end: comparisonFilters.currentEndDate,
      compare_baseline_start: comparisonFilters.comparisonStartDate,
      compare_baseline_end: comparisonFilters.comparisonEndDate,
      compare_account: comparisonFilters.accountName?.trim() ?? null,
    })
    try {
      setComparison(await fetchPeriodComparison(comparisonFilters))
    } catch (requestError: unknown) {
      setComparisonError(requestError instanceof Error ? requestError.message : 'Period comparison could not be loaded.')
    } finally {
      setComparisonLoading(false)
    }
  }

  return (
    <section className="workspace-panel analytics-panel" id="analytics" aria-labelledby="analytics-title">
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">Verified calculations</p>
          <h2 id="analytics-title">Spending analytics</h2>
        </div>
        <p>Every total below comes from deterministic backend services using analytics semantics v1.0.</p>
      </div>

      <div className="analytics-layout">
        <article className="analytics-card" aria-labelledby="spending-overview-title">
          <h3 id="spending-overview-title">Spending overview</h3>
          <form className="analytics-form" onSubmit={(event) => void loadAnalytics(event)}>
            <label>
              Start date
              <input type="date" required value={filters.startDate} onChange={(event) => setFilters({ ...filters, startDate: event.currentTarget.value })} />
            </label>
            <label>
              End date
              <input type="date" required value={filters.endDate} onChange={(event) => setFilters({ ...filters, endDate: event.currentTarget.value })} />
            </label>
            <label>
              Account <span>Optional</span>
              <input type="text" value={filters.accountName ?? ''} onChange={(event) => setFilters({ ...filters, accountName: event.currentTarget.value })} />
            </label>
            <button type="submit" disabled={analyticsLoading}>{analyticsLoading ? 'Calculating...' : 'View spending'}</button>
          </form>

          {analyticsLoading && <p className="workspace-state" role="status">Loading verified spending totals...</p>}
          {analyticsError && <p className="workspace-state workspace-state--error" role="alert">{analyticsError}</p>}
          {!analyticsLoading && !analyticsError && !summary && (
            <p className="workspace-state">Choose a date range to view exact spending totals and categories.</p>
          )}
          {summary && categories && (
            <div className="analytics-results">
              <div className="metric-card">
                <span>Gross spending</span>
                <strong>{displayMoney(summary.total_spending, summary.currency)}</strong>
                <small>{summary.transaction_count} spending transactions · semantics {summary.semantics_version}</small>
              </div>
              <h4>By category</h4>
              {categories.groups.length === 0 ? (
                <p>No spending transactions were found in this range.</p>
              ) : (
                <div className="data-table-wrap">
                  <table className="data-table compact-table">
                    <thead><tr><th scope="col">Category</th><th scope="col">Transactions</th><th scope="col">Share</th><th scope="col">Spending</th></tr></thead>
                    <tbody>
                      {categories.groups.map((group) => (
                        <tr key={`${group.bucket}-${group.category ?? 'uncategorized'}`}>
                          <td>{group.category ?? 'Uncategorized'}</td>
                          <td>{group.transaction_count}</td>
                          <td>{group.percentage}%</td>
                          <td className="money-cell">{displayMoney(group.total_spending, categories.currency)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </article>

        <article className="analytics-card" aria-labelledby="period-comparison-title">
          <h3 id="period-comparison-title">Compare periods</h3>
          <form className="analytics-form comparison-form" onSubmit={(event) => void loadComparison(event)}>
            <fieldset>
              <legend>Current period</legend>
              <label>Start date<input type="date" required value={comparisonFilters.currentStartDate} onChange={(event) => setComparisonFilters({ ...comparisonFilters, currentStartDate: event.currentTarget.value })} /></label>
              <label>End date<input type="date" required value={comparisonFilters.currentEndDate} onChange={(event) => setComparisonFilters({ ...comparisonFilters, currentEndDate: event.currentTarget.value })} /></label>
            </fieldset>
            <fieldset>
              <legend>Comparison period</legend>
              <label>Start date<input type="date" required value={comparisonFilters.comparisonStartDate} onChange={(event) => setComparisonFilters({ ...comparisonFilters, comparisonStartDate: event.currentTarget.value })} /></label>
              <label>End date<input type="date" required value={comparisonFilters.comparisonEndDate} onChange={(event) => setComparisonFilters({ ...comparisonFilters, comparisonEndDate: event.currentTarget.value })} /></label>
            </fieldset>
            <label>Account <span>Optional</span><input type="text" value={comparisonFilters.accountName ?? ''} onChange={(event) => setComparisonFilters({ ...comparisonFilters, accountName: event.currentTarget.value })} /></label>
            <button type="submit" disabled={comparisonLoading}>{comparisonLoading ? 'Comparing...' : 'Compare periods'}</button>
          </form>

          {comparisonLoading && <p className="workspace-state" role="status">Loading verified period comparison...</p>}
          {comparisonError && <p className="workspace-state workspace-state--error" role="alert">{comparisonError}</p>}
          {!comparisonLoading && !comparisonError && !comparison && <p className="workspace-state">Choose two explicit periods to compare exact spending.</p>}
          {comparison && (
            <div className="analytics-results">
              <div className="comparison-metrics">
                <div><span>Current</span><strong>{displayMoney(comparison.current_period.total_spending, comparison.currency)}</strong><small>{comparison.current_period.transaction_count} transactions</small></div>
                <div><span>Comparison</span><strong>{displayMoney(comparison.comparison_period.total_spending, comparison.currency)}</strong><small>{comparison.comparison_period.transaction_count} transactions</small></div>
                <div><span>Change</span><strong>{displayMoney(comparison.absolute_change, comparison.currency)}</strong><small>{comparison.percentage_change === null ? 'No percentage for a zero baseline' : `${comparison.percentage_change}%`}</small></div>
              </div>
              <h4>Category changes</h4>
              {comparison.category_deltas.length === 0 ? <p>No category changes were found.</p> : (
                <div className="data-table-wrap">
                  <table className="data-table compact-table">
                    <thead><tr><th scope="col">Category</th><th scope="col">Current</th><th scope="col">Comparison</th><th scope="col">Change</th></tr></thead>
                    <tbody>{comparison.category_deltas.map((delta) => (
                      <tr key={`${delta.bucket}-${delta.category ?? 'uncategorized'}`}>
                        <td>{delta.category ?? 'Uncategorized'}</td>
                        <td className="money-cell">{displayMoney(delta.current_spending, comparison.currency)}</td>
                        <td className="money-cell">{displayMoney(delta.comparison_spending, comparison.currency)}</td>
                        <td className="money-cell">{displayMoney(delta.absolute_change, comparison.currency)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </article>
      </div>
    </section>
  )
}

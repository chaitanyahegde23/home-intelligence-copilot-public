import { render, screen } from '@testing-library/react'
import { axe } from 'jest-axe'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { askAnalyticsQuestion, askDocumentQuestion } from '../api/copilot'
import { CopilotWorkspace } from './CopilotWorkspace'

vi.mock('../api/copilot', () => ({ askAnalyticsQuestion: vi.fn(), askDocumentQuestion: vi.fn() }))

const verifiedAnalytics = {
  kind: 'verified' as const,
  answer: 'You spent **$350.45 USD** across **2 transactions**.',
  verified: true,
  model: 'synthetic-model',
  evidence: [{ tool_name: 'get_spending_summary', arguments: { start_date: '2026-01-01', end_date: '2026-01-31' }, result: { total_spending: '350.45', transaction_count: 2 } }],
}

const citation = {
  citation_id: 'C1', document_id: 'doc-1', chunk_id: 'chunk-1', original_filename: 'synthetic-warranty.pdf', page_number: 2, section_number: 1, start_offset: 0, end_offset: 28, document_sha256: 'a'.repeat(64), chunk_sha256: 'b'.repeat(64), excerpt: 'The warranty expires in 2028.',
}

beforeEach(() => {
  vi.mocked(askAnalyticsQuestion).mockReset().mockResolvedValue(verifiedAnalytics)
  vi.mocked(askDocumentQuestion).mockReset().mockResolvedValue({ kind: 'verified', answer: 'The warranty expires in 2028.', verified: true, evidence_status: 'supported', model: 'synthetic-model', retrieval_terms: ['warranty', 'expires'], citations: [citation] })
})

async function submitQuestion(question: string) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Your question'), question)
  await user.click(screen.getByRole('button', { name: 'Ask Copilot' }))
  return user
}

describe('CopilotWorkspace', () => {
  it('has no detectable accessibility violations in its initial state', async () => {
    const { container } = render(<CopilotWorkspace />)
    expect((await axe(container)).violations).toEqual([])
  })

  it('renders verified analytics evidence from an allowlisted tool', async () => {
    render(<CopilotWorkspace />)
    await submitQuestion('How much did I spend from 2026-01-01 through 2026-01-31?')
    expect(await screen.findByText('$350.45 USD')).toHaveProperty('tagName', 'STRONG')
    expect(screen.getByText('2 transactions')).toHaveProperty('tagName', 'STRONG')
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByText('Deterministic evidence'))
    await userEvent.click(screen.getByText('get_spending_summary'))
    expect(screen.getByText('350.45')).toBeVisible()
    expect(screen.getByText('Evidence verified')).toBeVisible()
  })

  it('renders malformed emphasis and HTML-like model text as safe text', async () => {
    vi.mocked(askAnalyticsQuestion).mockResolvedValueOnce({
      ...verifiedAnalytics,
      answer: '<img src=x onerror=alert(1)> You spent ** $350.45 USD ** from ** **2026-01-01.',
    })
    render(<CopilotWorkspace />)
    await submitQuestion('Synthetic safe rendering question')

    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeVisible()
    expect(document.querySelector('img')).toBeNull()
    expect(screen.getByText('$350.45 USD')).toHaveProperty('tagName', 'STRONG')
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument()
  })

  it.each([
    ['clarification', 'What exact start and end dates should I use?', 'Provide the missing period'],
    ['refusal', 'I cannot perform that request.', 'blocked before any household analytics tool'],
  ] as const)('renders the analytics %s state', async (kind, answer, guidance) => {
    vi.mocked(askAnalyticsQuestion).mockResolvedValueOnce({ kind, answer, verified: false, model: kind === 'clarification' ? 'synthetic-model' : null, evidence: [] })
    render(<CopilotWorkspace />)
    await submitQuestion('Synthetic bounded question')
    expect(await screen.findByText(answer)).toBeVisible()
    expect(screen.getByText(new RegExp(guidance))).toBeVisible()
    expect(screen.getByText('Not verified')).toBeVisible()
  })

  it('renders an exact document citation and technical provenance', async () => {
    const user = userEvent.setup()
    render(<CopilotWorkspace />)
    await user.click(screen.getByLabelText('Household documents'))
    await submitQuestion('When does the synthetic warranty expire?')
    expect(await screen.findAllByText(citation.excerpt)).toHaveLength(2)
    expect(screen.getByText((_, element) => element?.tagName === 'FIGCAPTION' && element.textContent?.includes('synthetic-warranty.pdf · page 2, section 1') === true)).toBeVisible()
    expect(screen.getByRole('link', { name: citation.original_filename })).toHaveAttribute(
      'href',
      `/api/documents/${citation.document_id}/content`,
    )
    await user.click(screen.getByText('Technical provenance'))
    expect(screen.getByText(citation.document_sha256)).toBeVisible()
  })

  it.each([
    ['no_results', 'No relevant indexed passages were found.', 'Extract and index a relevant PDF'],
    ['analytics_required', 'Use deterministic analytics for transaction totals.', 'Switch to Spending analytics'],
  ] as const)('renders the document %s state', async (kind, answer, guidance) => {
    vi.mocked(askDocumentQuestion).mockResolvedValueOnce({ kind, answer, verified: false, evidence_status: 'none', model: null, retrieval_terms: [], citations: [] })
    const user = userEvent.setup()
    render(<CopilotWorkspace />)
    await user.click(screen.getByLabelText('Household documents'))
    await submitQuestion('Synthetic question')
    expect(await screen.findByText(answer)).toBeVisible()
    expect(screen.getByText(new RegExp(guidance))).toBeVisible()
  })

  it('warns when cited documents conflict', async () => {
    vi.mocked(askDocumentQuestion).mockResolvedValueOnce({ kind: 'verified', answer: 'The indexed sources disagree.', verified: true, evidence_status: 'conflicting', model: 'synthetic-model', retrieval_terms: ['warranty'], citations: [citation, { ...citation, citation_id: 'C2', chunk_id: 'chunk-2', document_id: 'doc-2', original_filename: 'synthetic-warranty-2.pdf' }] })
    const user = userEvent.setup()
    render(<CopilotWorkspace />)
    await user.click(screen.getByLabelText('Household documents'))
    await submitQuestion('Which warranty date is correct?')
    expect(await screen.findByText(/indexed documents disagree/)).toBeVisible()
    expect(screen.getByText(/Review every cited passage/)).toBeVisible()
    expect(screen.getAllByRole('figure')).toHaveLength(2)
  })

  it('shows disabled-provider errors without losing the selected mode', async () => {
    vi.mocked(askAnalyticsQuestion).mockRejectedValueOnce(new Error('AI explanations are disabled'))
    render(<CopilotWorkspace />)
    await submitQuestion('Synthetic question')
    expect(await screen.findByRole('alert')).toHaveTextContent('AI explanations are disabled')
    expect(screen.getByLabelText('Spending analytics')).toBeChecked()
  })
})

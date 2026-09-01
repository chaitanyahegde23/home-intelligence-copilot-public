import { beforeEach, describe, expect, it, vi } from 'vitest'
import { askAnalyticsQuestion, askDocumentQuestion } from './copilot'

beforeEach(() => vi.restoreAllMocks())

describe('Copilot API', () => {
  it('posts trimmed analytics questions as JSON', async () => {
    const response = { kind: 'clarification', answer: 'Which dates?', verified: false, model: 'synthetic-model', evidence: [] }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }))
    await expect(askAnalyticsQuestion('  How much?  ')).resolves.toEqual(response)
    expect(fetchMock).toHaveBeenCalledWith('/api/ai/questions', expect.objectContaining({ method: 'POST', body: JSON.stringify({ question: 'How much?' }) }))
  })

  it('posts document questions and exposes privacy-safe disabled errors', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'AI explanations are disabled' }), { status: 503 }))
    await expect(askDocumentQuestion('Warranty?')).rejects.toThrow('AI explanations are disabled')
    expect(fetchMock).toHaveBeenCalledWith('/api/ai/document-questions', expect.objectContaining({ method: 'POST' }))
  })

  it('can scope a document question to one document', async () => {
    const response = { kind: 'no_results', answer: 'No evidence.', verified: false, evidence_status: 'none', model: null, retrieval_terms: [], citations: [] }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }))

    await askDocumentQuestion(' When does it expire? ', undefined, 'doc-1')

    expect(fetchMock).toHaveBeenCalledWith('/api/ai/document-questions', expect.objectContaining({
      body: JSON.stringify({ question: 'When does it expire?', document_id: 'doc-1' }),
    }))
  })
})

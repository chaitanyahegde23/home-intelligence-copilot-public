import { type FormEvent, useState } from 'react'
import {
  askAnalyticsQuestion,
  askDocumentQuestion,
  type AnalyticsQuestionResponse,
  type DocumentQuestionResponse,
} from '../api/copilot'
import { documentContentUrl } from '../api/documents'

type CopilotMode = 'analytics' | 'documents'

export function CopilotWorkspace({ documentOnly = false }: { documentOnly?: boolean }) {
  const [mode, setMode] = useState<CopilotMode>(documentOnly ? 'documents' : 'analytics')
  const [question, setQuestion] = useState('')
  const [analyticsResponse, setAnalyticsResponse] = useState<AnalyticsQuestionResponse | null>(null)
  const [documentResponse, setDocumentResponse] = useState<DocumentQuestionResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const selectMode = (nextMode: CopilotMode) => {
    setMode(nextMode)
    setQuestion('')
    setError('')
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedQuestion = question.trim()
    if (!normalizedQuestion) {
      setError('Enter a question before asking the Copilot.')
      return
    }
    setLoading(true)
    setError('')
    try {
      if (mode === 'analytics') {
        setAnalyticsResponse(await askAnalyticsQuestion(normalizedQuestion))
      } else {
        setDocumentResponse(await askDocumentQuestion(normalizedQuestion))
      }
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'The Copilot request failed.')
    } finally {
      setLoading(false)
    }
  }

  const response = mode === 'analytics' ? analyticsResponse : documentResponse

  return (
    <section className="workspace-panel" id="copilot" aria-labelledby="copilot-title">
      <div className="workspace-heading">
        <div><p className="eyebrow">Controlled explanations</p><h2 id="copilot-title">Household Copilot</h2></div>
        <p>Ask one bounded question at a time. Financial answers use tested analytics tools; document answers require exact stored citations.</p>
      </div>

      <div className="copilot-layout">
        <form className="copilot-form" onSubmit={(event) => void submit(event)}>
          {!documentOnly && <fieldset className="mode-picker">
            <legend>Question source</legend>
            <label><input type="radio" name="copilot-mode" value="analytics" checked={mode === 'analytics'} onChange={() => selectMode('analytics')} /> Spending analytics</label>
            <label><input type="radio" name="copilot-mode" value="documents" checked={mode === 'documents'} onChange={() => selectMode('documents')} /> Household documents</label>
          </fieldset>}
          <label htmlFor="copilot-question">Your question</label>
          <textarea
            id="copilot-question"
            value={question}
            maxLength={mode === 'analytics' ? 1000 : 200}
            rows={4}
            placeholder={mode === 'analytics' ? 'How much did I spend from 2026-06-01 through 2026-06-30?' : 'When does the synthetic warranty expire?'}
            onChange={(event) => setQuestion(event.currentTarget.value)}
          />
          <p className="copilot-guidance">
            {mode === 'analytics'
              ? 'Use exact YYYY-MM-DD dates or “last month.” Relative periods are resolved by the server before allowlisted, read-only analytics tools run.'
              : 'Searchable PDFs are retrieved lexically. Financial totals are redirected to Spending analytics and are never calculated from document text.'}
          </p>
          <button type="submit" disabled={loading}>{loading ? 'Checking evidence...' : 'Ask Copilot'}</button>
          <p className="privacy-note">Your question may be sent to the configured OpenAI project. The app does not save question history, and every request may consume API credit.</p>
        </form>

        <div className="copilot-response" aria-live="polite">
          {error && <p className="workspace-state workspace-state--error" role="alert">{error}</p>}
          {loading && <p className="workspace-state" role="status">Checking deterministic evidence...</p>}
          {!loading && !error && !response && <div className="copilot-placeholder"><span aria-hidden="true">?</span><h3>No question asked yet</h3><p>Choose the correct source so the Copilot cannot silently mix financial calculations with document retrieval.</p></div>}
          {!loading && !error && mode === 'analytics' && analyticsResponse && <AnalyticsAnswer response={analyticsResponse} />}
          {!loading && !error && mode === 'documents' && documentResponse && <DocumentAnswer response={documentResponse} />}
        </div>
      </div>
    </section>
  )
}

function AnalyticsAnswer({ response }: { response: AnalyticsQuestionResponse }) {
  return (
    <article className={`answer-card answer-card--${response.kind}`}>
      <p className="answer-kicker">{response.kind === 'verified' ? 'Verified analytics answer' : response.kind}</p>
      <h3><SafeAnswerText text={response.answer} /></h3>
      {response.kind === 'clarification' && <p>Provide the missing period or filters, then ask again.</p>}
      {response.kind === 'refusal' && <p>The request was blocked before any household analytics tool was called.</p>}
      {response.evidence.length > 0 && <details className="evidence-disclosure"><summary>Deterministic evidence</summary><div className="evidence-list">{response.evidence.map((item, index) => <details key={`${item.tool_name}-${index}`}><summary>{item.tool_name}</summary><EvidenceTable title="Arguments" value={item.arguments} /><EvidenceTable title="Result" value={item.result} /></details>)}</div></details>}
      <AnswerMetadata verified={response.verified} model={response.model} />
    </article>
  )
}

function DocumentAnswer({ response }: { response: DocumentQuestionResponse }) {
  return (
    <article className={`answer-card answer-card--${response.kind}`}>
      <p className="answer-kicker">{response.kind === 'verified' ? `${response.evidence_status} document answer` : response.kind.replaceAll('_', ' ')}</p>
      <h3><SafeAnswerText text={response.answer} /></h3>
      {response.kind === 'no_results' && <p>Extract and index a relevant PDF, or try more specific words.</p>}
      {response.kind === 'analytics_required' && <p>Switch to Spending analytics and include exact dates for a deterministic calculation.</p>}
      {response.evidence_status === 'conflicting' && <p className="conflict-note">The indexed documents disagree. Review every cited passage before relying on this answer.</p>}
      {response.citations.length > 0 && <div className="citation-list"><h4>Exact citations</h4>{response.citations.map((citation) => <figure key={citation.citation_id}><blockquote>{citation.excerpt}</blockquote><figcaption><strong>{citation.citation_id}</strong> · <a href={documentContentUrl(citation.document_id)} target="_blank" rel="noreferrer">{citation.original_filename}</a> · page {citation.page_number}, section {citation.section_number}</figcaption><details><summary>Technical provenance</summary><dl><div><dt>Document ID</dt><dd>{citation.document_id}</dd></div><div><dt>Chunk ID</dt><dd>{citation.chunk_id}</dd></div><div><dt>Offsets</dt><dd>{citation.start_offset}–{citation.end_offset}</dd></div><div><dt>Document SHA-256</dt><dd>{citation.document_sha256}</dd></div><div><dt>Chunk SHA-256</dt><dd>{citation.chunk_sha256}</dd></div></dl></details></figure>)}</div>}
      {response.retrieval_terms.length > 0 && <p className="retrieval-terms"><strong>Retrieval terms:</strong> {response.retrieval_terms.join(', ')}</p>}
      <AnswerMetadata verified={response.verified} model={response.model} />
    </article>
  )
}

function EvidenceTable({ title, value }: { title: string; value: Record<string, unknown> }) {
  return <div className="evidence-table"><h5>{title}</h5><dl>{Object.entries(value).map(([key, item]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{formatEvidenceValue(item)}</dd></div>)}</dl></div>
}

function formatEvidenceValue(value: unknown): string {
  if (value === null) return 'None'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

export function SafeAnswerText({ text }: { text: string }) {
  const normalized = text.replaceAll('\\*', '*')
  const segments = normalized.split('**')
  return segments.map((segment, index) => {
    if (index % 2 === 1 && segment.trim()) {
      return <strong key={index}>{segment.trim()}</strong>
    }
    return segment
  })
}

function AnswerMetadata({ verified, model }: { verified: boolean; model: string | null }) {
  return <p className="answer-metadata"><span className={`status-chip status-chip--${verified ? 'completed' : 'pending'}`}>{verified ? 'Evidence verified' : 'Not verified'}</span><span>{model ? `Explained by ${model}` : 'No model response used'}</span></p>
}

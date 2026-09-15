import { type FormEvent, useState } from 'react'

import { api } from '@/services/api'
import type { RagResponse } from '@/types'

import { Card } from './ui'

/**
 * Module 8 — ASHA/CHW knowledge RAG. Educational reference only: a worker
 * asks a plain question, the backend retrieves curated guidance scoped to
 * a single fixed topic it cannot change (see knowledge/queries.py::
 * chw_knowledge). Never a diagnosis, never a treatment instruction.
 */
export function ChwKnowledgeCard() {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<RagResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function ask(event: FormEvent) {
    event.preventDefault()
    if (!question.trim()) return
    setBusy(true)
    setError(null)
    try {
      const response = await api.post<RagResponse>('/rag/chw/', { question })
      setResult(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not fetch guidance.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Health knowledge">
      <p className="text-xs text-ink-600 -mt-1 mb-2">
        Ask a general question — e.g. "What should I check for a child with
        diarrhoea?" Educational reference only, not a diagnosis or
        instruction to prescribe.
      </p>
      <form onSubmit={ask} className="flex gap-2">
        <input
          className="input flex-1"
          placeholder="What should I check when..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button className="btn-care" disabled={busy || !question.trim()}>
          {busy ? 'Asking…' : 'Ask'}
        </button>
      </form>

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      {result && result.status === 'grounded' && (
        <div className="mt-3 rounded-md border border-care-200 bg-care-50/40 p-3">
          <p className="whitespace-pre-line text-sm text-ink-700">{result.answer}</p>
          {result.sources.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-ink-500">
              {result.sources.map((source) => (
                <li key={`${source.document_id}-${source.section}`}>
                  {source.title} · {source.organization} · {source.authority_label}
                  {source.section ? ` · ${source.section}` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {result && result.status === 'no_grounding' && (
        <p className="mt-2 text-xs text-ink-400">
          No sufficiently relevant guidance was found for that question.
        </p>
      )}
    </Card>
  )
}

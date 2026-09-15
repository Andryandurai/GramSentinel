import { useAsync } from '@/hooks/useAsync'
import type { RagResponse, RagSource } from '@/types'

/**
 * Renders retrieved, cited guidance underneath a result the deterministic
 * system already computed. Never the result itself — this panel has no
 * prop through which it could show a triage level, referral, or safety
 * verdict of its own; it only ever displays `answer` + `sources` from the
 * backend's RAG response.
 *
 * Loading / grounded / no-results / failure states per the task's own
 * spec — the panel simply doesn't render when RAG is disabled/unavailable/
 * has nothing relevant, so the page around it never looks broken.
 */
function SourceCitation({ source }: { source: RagSource }) {
  return (
    <li className="rounded-md border border-ink-200 bg-white px-3 py-2 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-ink-800">{source.title}</span>
        <span className="text-ink-400">· {source.organization}</span>
        <span
          className={`pill ml-auto ${
            source.authority === 'INTERNAL'
              ? 'bg-ink-100 text-ink-600'
              : 'bg-sentinel-100 text-sentinel-700'
          }`}
        >
          {source.authority_label}
        </span>
      </div>
      <div className="mt-1 text-ink-500">
        {[
          source.section,
          source.page ? `p. ${source.page}` : null,
          `v${source.version}`,
        ]
          .filter(Boolean)
          .join(' · ')}
      </div>
      {source.source_url && (
        <a
          href={source.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-block text-sentinel-700 hover:underline"
        >
          View source ↗
        </a>
      )}
    </li>
  )
}

export function RagGuidancePanel({
  title = 'Relevant Guidance',
  fetcher,
  deps,
}: {
  title?: string
  fetcher: () => Promise<RagResponse>
  deps: unknown[]
}) {
  const { data, loading, error } = useAsync<RagResponse>(fetcher, deps)

  if (loading) {
    return <p className="mt-3 text-xs text-ink-400">Finding relevant guidance…</p>
  }
  if (error || !data || data.status === 'disabled' || data.status === 'unavailable') {
    // Deliberately silent, not an error banner — the application result
    // above this panel is already complete and correct on its own; a RAG
    // outage must never look like the assessment/alert itself failed.
    return null
  }
  if (data.status === 'no_grounding') {
    return (
      <p className="mt-3 text-xs text-ink-400">
        No sufficiently relevant approved guidance was found for this result.
      </p>
    )
  }

  return (
    <div className="mt-4 rounded-lg border border-sentinel-200 bg-sentinel-50/40 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-sentinel-700">
        {title}
      </div>
      <p className="mt-1.5 whitespace-pre-line text-sm text-ink-700">{data.answer}</p>
      {data.sources.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {data.sources.map((source) => (
            <SourceCitation key={`${source.document_id}-${source.section}`} source={source} />
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] text-ink-400">
        Retrieved from curated reference material. Not medical advice, and it
        does not change the result above.
      </p>
    </div>
  )
}

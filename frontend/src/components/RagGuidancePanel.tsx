import { useTranslation } from 'react-i18next'

import { useAsync } from '@/hooks/useAsync'
import type { RagResponse, RagSource } from '@/types'

/**
 * Renders a grounded, cited explanation underneath a result the
 * deterministic system already computed — never the result itself. This
 * panel has no prop through which it could show a triage level, referral,
 * or safety verdict of its own.
 *
 * Health-worker-facing only: it never shows raw retrieved reference text,
 * retrieval/embedding scores, model names, or backend status words. When
 * a grounded explanation genuinely isn't available (no LLM configured, the
 * call failed, or the response came back empty), the panel shows one calm,
 * short line and nothing else — the assessment/alert result above it is
 * unaffected either way.
 *
 * `source.authority`/`authority_label` describe how authoritative a cited
 * document genuinely is (task §9/§30: never present reference material as
 * verbatim official guidance) — `rag.authorityShort`/`authorityFull` below
 * translate that same true meaning, never inventing a different claim
 * about the source's authority in another language.
 *
 * `answer` itself (the RAG-generated explanation) is not translated here —
 * it is real generated content the backend currently only produces in
 * English regardless of the selected UI language (a known limitation, not
 * addressed by this component).
 */

function FallbackNote({ title, message }: { title: string; message: string }) {
  return (
    <div className="mt-3 rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2.5">
      <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">
        {title}
      </div>
      <p className="mt-1 text-xs text-ink-600">{message}</p>
    </div>
  )
}

function SourceLine({ source }: { source: RagSource }) {
  const { t } = useTranslation('common')
  const authority = t(`rag.authorityShort.${source.authority}`, { defaultValue: source.authority_label })
  const authorityFull = t(`rag.authorityFull.${source.authority}`, { defaultValue: source.authority_label })
  return (
    <li className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-ink-600">
      <span className="font-medium text-ink-700">{source.title}</span>
      <span>·</span>
      <span>{source.organization}</span>
      <span
        className="pill bg-ink-100 text-ink-500"
        title={authorityFull}
      >
        {authority}
      </span>
      {source.source_url && (
        <a
          href={source.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sentinel-700 hover:underline"
        >
          {t('rag.viewSource')}
        </a>
      )}
    </li>
  )
}

export function RagGuidancePanel({
  title,
  fetcher,
  deps,
}: {
  title?: string
  fetcher: () => Promise<RagResponse>
  deps: unknown[]
}) {
  const { t } = useTranslation('common')
  const resolvedTitle = title ?? t('rag.defaultTitle')
  const { data, loading, error } = useAsync<RagResponse>(fetcher, deps)

  if (loading) {
    return <p className="mt-3 text-xs text-ink-400">{t('rag.finding')}</p>
  }

  // RAG disabled by configuration — no section at all, nothing to explain
  // and nothing to say about it to a Health Worker.
  if (data?.status === 'disabled') {
    return null
  }

  // Any failure to reach or parse the RAG response, or the backend saying
  // it has nothing usable to show, all read the same way to a Health
  // Worker: guidance isn't available right now, and that's fine — the
  // assessment result above stands on its own regardless.
  if (error || !data || data.status === 'unavailable') {
    return <FallbackNote title={resolvedTitle} message={t('rag.unavailable')} />
  }

  if (data.status === 'no_grounding') {
    return <FallbackNote title={resolvedTitle} message={t('rag.noGrounding')} />
  }

  // Grounded: a real explanation was generated. Guard defensively against
  // a malformed answer/sources shape so a backend inconsistency can never
  // crash this panel — the worst case is showing nothing extra, never an
  // error screen over the assessment result.
  const answer = typeof data.answer === 'string' ? data.answer.trim() : ''
  const sources = Array.isArray(data.sources) ? data.sources : []
  if (!answer) {
    return <FallbackNote title={resolvedTitle} message={t('rag.unavailable')} />
  }

  return (
    <div className="mt-3 rounded-lg border border-sentinel-200 bg-sentinel-50/40 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-sentinel-700">
        {resolvedTitle}
      </div>
      <p className="mt-1.5 text-sm text-ink-700 leading-relaxed">{answer}</p>

      {sources.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer select-none font-medium text-sentinel-700">
            {t('rag.sourcesCount', { count: sources.length })}
          </summary>
          <ul className="mt-1.5 space-y-1">
            {sources.map((source, index) => (
              <SourceLine key={`${source.document_id ?? index}-${source.section ?? ''}`} source={source} />
            ))}
          </ul>
        </details>
      )}

      <p className="mt-2 text-[11px] text-ink-400">
        Reference material only — does not change the result above.
      </p>
    </div>
  )
}

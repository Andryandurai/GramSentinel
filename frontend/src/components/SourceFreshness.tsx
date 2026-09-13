/**
 * Source freshness, for the Health Officer Portal.
 *
 * The purpose is narrow: stop an officer from reading a four-day-old
 * laboratory feed and a twenty-minute-old CHW report as equally current
 * evidence.
 *
 * Two things this must never do, and the styling follows from both:
 *
 *   - Never show a missing source as zero, or as a small number, or as
 *     anything that could be skimmed as a measurement. A missing source shows
 *     "No report this period" as text.
 *   - Never imply the platform has downgraded anything. Freshness does not
 *     touch alert severity or the Safety Engine; it informs the human, and the
 *     panel says so rather than leaving it to be assumed.
 */

import type { FreshnessStatus, SourceFreshness } from '@/types'

const STATUS_STYLE: Record<FreshnessStatus, { pill: string; row: string }> = {
  FRESH: { pill: 'bg-care-100 text-care-800', row: 'border-ink-200' },
  AGING: { pill: 'bg-amber-100 text-amber-800', row: 'border-amber-200' },
  STALE: { pill: 'bg-orange-100 text-orange-800', row: 'border-orange-200' },
  // Deliberately the most distinct treatment. Missing is not "very stale" —
  // it is the absence of information, and it is the state most likely to be
  // misread as "nothing is happening there".
  MISSING: { pill: 'bg-ink-200 text-ink-700', row: 'border-ink-300 bg-ink-50' },
}

export function FreshnessPill({ status }: { status: FreshnessStatus }) {
  const label =
    status.charAt(0) + status.slice(1).toLowerCase() // FRESH -> Fresh
  return (
    <span className={`pill ${STATUS_STYLE[status].pill}`}>{label}</span>
  )
}

/** Compact freshness line for an alert evidence card. */
export function EvidenceFreshness({ freshness }: { freshness: SourceFreshness }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
      <FreshnessPill status={freshness.status} />
      <span className="text-ink-600">
        {freshness.status === 'MISSING'
          ? freshness.reported_this_period
            ? 'No data received'
            : 'No report this period'
          : `Updated ${freshness.age_text}`}
      </span>
    </div>
  )
}

function FreshnessRow({ source }: { source: SourceFreshness }) {
  const style = STATUS_STYLE[source.status]
  return (
    <li className={`rounded-md border px-3 py-2 ${style.row}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{source.source_kind_display}</span>
        <FreshnessPill status={source.status} />
        <span className="ml-auto text-xs text-ink-600">
          {source.status === 'MISSING' && !source.reported_this_period
            ? 'No report this period'
            : source.age_text
              ? `Updated ${source.age_text}`
              : 'Never updated'}
        </span>
      </div>
      <p className="mt-1 text-xs text-ink-500">
        {source.source_name}
        {source.village_name ? ` · ${source.village_name}` : ''}
      </p>
      <p className="mt-1 text-xs text-ink-600">{source.explanation}</p>
    </li>
  )
}

export function SourceFreshnessPanel({
  sources,
  note,
}: {
  sources: SourceFreshness[]
  note?: string
}) {
  if (sources.length === 0) {
    return (
      <p className="text-sm text-ink-500">
        No data sources are registered for your area yet.
      </p>
    )
  }

  const attention = sources.filter(
    (s) => s.status === 'STALE' || s.status === 'MISSING',
  ).length

  return (
    <div className="space-y-3">
      {attention > 0 && (
        <p className="text-xs text-ink-700">
          {attention} of {sources.length} sources{' '}
          {attention === 1 ? 'is' : 'are'} out of date or missing for this
          period. Evidence from{' '}
          {attention === 1 ? 'that source' : 'those sources'} is older than it
          appears.
        </p>
      )}

      {/* Backend returns worst-first, so the sources an officer most needs to
          notice are already at the top. */}
      <ul className="space-y-2">
        {sources.map((source) => (
          <FreshnessRow key={source.source_code} source={source} />
        ))}
      </ul>

      <p className="text-xs text-ink-400 leading-relaxed">
        {note ??
          'A missing source has reported nothing for this period. That is not ' +
            'the same as reporting zero cases and is never counted as zero.'}{' '}
        Freshness is shown for your judgement — it does not change alert
        severity, confidence, or any safety rule.
      </p>
    </div>
  )
}

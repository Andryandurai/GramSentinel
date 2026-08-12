import type { TriageLevel, TriageSupport as Support } from '@/types'

const LEVEL_PRESENTATION: Record<
  TriageLevel,
  { label: string; band: string; dot: string; text: string }
> = {
  ROUTINE: {
    label: 'Routine',
    band: 'border-care-200 bg-care-50',
    dot: 'bg-care-500',
    text: 'text-care-700',
  },
  CONCERNING: {
    label: 'Medium priority',
    band: 'border-amber-300 bg-amber-50',
    dot: 'bg-amber-500',
    text: 'text-amber-800',
  },
  URGENT: {
    label: 'Urgent',
    band: 'border-red-300 bg-red-50',
    dot: 'bg-red-500',
    text: 'text-red-700',
  },
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-400">
        {title}
      </h3>
      <div className="mt-1 text-sm text-ink-800">{children}</div>
    </div>
  )
}

/**
 * The worker-facing result, arranged so it can be read at a glance:
 * level → why → what to consider → safety → disclaimer.
 *
 * All wording comes from the existing triage and referral logic. Nothing here
 * invents a recommendation; the component only decides how the produced text
 * is laid out.
 */
export function TriageSupportPanel({ support }: { support: Support }) {
  const level = LEVEL_PRESENTATION[support.triage_level]
  const escalated = support.escalation_forced
  const hasFlags = support.red_flags.length > 0

  return (
    <div className="space-y-5">
      {/* 1. Risk level */}
      <div className={`rounded-lg border px-4 py-3 ${level.band}`}>
        <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Risk level
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${level.dot}`} />
          <span className={`text-lg font-semibold ${level.text}`}>
            {level.label}
          </span>
        </div>
        {escalated && (
          <p className="mt-1.5 text-xs text-red-700">
            Raised from{' '}
            {LEVEL_PRESENTATION[support.model_triage_level]?.label.toLowerCase() ??
              support.model_triage_level.toLowerCase()}{' '}
            by a safety rule.
          </p>
        )}
      </div>

      {/* 2. Why */}
      <Section title="Why">{support.reasoning_summary}</Section>

      {/* 3. Suggested next step */}
      <Section title="Suggested next step">
        {support.referral_recommendation}
        {support.followup_interval_days ? (
          <p className="mt-1 text-ink-600">
            Suggested follow-up in {support.followup_interval_days} day
            {support.followup_interval_days === 1 ? '' : 's'}.
          </p>
        ) : null}
      </Section>

      {/* 4. Safety — visually separated from the AI-assisted reasoning above */}
      <div
        className={`rounded-lg border px-4 py-3 ${
          hasFlags
            ? 'border-red-300 bg-red-50'
            : 'border-ink-200 bg-ink-50'
        }`}
      >
        <div className="flex items-center gap-2">
          <span
            className={`text-xs font-semibold uppercase tracking-wide ${
              hasFlags ? 'text-red-700' : 'text-ink-500'
            }`}
          >
            Safety check
          </span>
          <span className="pill bg-white text-ink-600 border border-ink-200">
            rule-based, not AI
          </span>
        </div>

        {hasFlags ? (
          <>
            <p className="mt-1.5 text-sm font-medium text-red-800">
              ⚠ Human review required
            </p>
            <ul className="mt-1.5 space-y-1">
              {support.red_flags.map((flag) => (
                <li key={flag.code} className="text-sm text-red-800">
                  <span className="font-medium">{flag.label}</span> —{' '}
                  {flag.rationale}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-red-700">
              This escalation is applied by a fixed rule and cannot be
              overridden by the AI.
            </p>
          </>
        ) : (
          <p className="mt-1.5 text-sm text-ink-700">
            No automatic high-risk escalation triggered. The suggested level
            above stands.
          </p>
        )}
      </div>

      {/* Recording gaps, when the worker left something out */}
      {support.completeness.notes.length > 0 && (
        <div className="rounded-md border border-ink-200 bg-white px-3 py-2">
          <div className="text-xs font-medium text-ink-600">
            Not recorded
          </div>
          <ul className="mt-1 space-y-0.5">
            {support.completeness.notes.map((note) => (
              <li key={note} className="text-xs text-ink-600">
                • {note}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 5. Disclaimer */}
      <p className="border-t border-ink-200 pt-3 text-xs text-ink-500">
        <span className="font-semibold text-ink-600">Important:</span> This is
        decision-support only and does not replace professional medical care.
        You make the final decision.
      </p>
    </div>
  )
}

import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'

import { AgentTrace } from '@/components/AgentTrace'
import type { TriageLevel, TriageSupport as Support } from '@/types'

/** The six vital-sign fields as the New Assessment form holds them — plain
 *  strings, empty meaning "not entered" (never the same as an entered "0"). */
export interface VitalsInput {
  temperature_c: string
  pulse_bpm: string
  respiratory_rate: string
  systolic_bp: string
  diastolic_bp: string
  spo2: string
}

const PRIORITY_STYLE: Record<TriageLevel, { icon: string; band: string; text: string }> = {
  ROUTINE: { icon: '🟢', band: 'border-care-300 bg-care-50', text: 'text-care-700' },
  CONCERNING: { icon: '🟠', band: 'border-amber-300 bg-amber-50', text: 'text-amber-800' },
  URGENT: { icon: '🔴', band: 'border-red-300 bg-red-50', text: 'text-red-700' },
}

/** Which recorded-factor sentence (from the real triage result) corresponds
 *  to each vital, so a value can be marked as having influenced the
 *  priority — without introducing any new threshold of our own. Diastolic
 *  blood pressure is never itself scored, so it has no prefix to match.
 *  `factorPrefix` matches against `contributing_factors`, which is
 *  backend-generated English narrative text (not yet multilingual — a
 *  known, documented limitation) — this match is on the raw English
 *  sentence regardless of UI language, so it is unaffected by `label`
 *  being translated below. */
const VITAL_FIELDS: {
  key: keyof VitalsInput
  unit: string
  factorPrefix: string
}[] = [
  { key: 'temperature_c', unit: '°C', factorPrefix: 'recorded temperature ' },
  { key: 'pulse_bpm', unit: '/min', factorPrefix: 'pulse ' },
  { key: 'respiratory_rate', unit: '/min', factorPrefix: 'respiratory rate ' },
  { key: 'systolic_bp', unit: ' mmHg', factorPrefix: 'systolic blood pressure ' },
  { key: 'diastolic_bp', unit: ' mmHg', factorPrefix: '' },
  { key: 'spo2', unit: '%', factorPrefix: 'oxygen saturation ' },
]

function vitalFieldLabel(key: keyof VitalsInput, t: TFunction<'assessments'>): string {
  return t(`triageSupport.vitalLabels.${key}`)
}

function capitalise(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text
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
      <div className="mt-1.5 text-sm text-ink-800">{children}</div>
    </div>
  )
}

/** The current priority, made as visually unmistakable as possible — a new
 *  worker should not have to interpret what "concerning" means. */
function PriorityBanner({ support }: { support: Support }) {
  const { t } = useTranslation('assessments')
  const style = PRIORITY_STYLE[support.triage_level]
  const escalated = support.escalation_forced

  return (
    <div className={`rounded-xl border-2 px-5 py-4 ${style.band}`}>
      <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">
        {t('triageSupport.currentPriority')}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2.5">
        <span className="text-2xl" aria-hidden="true">
          {style.icon}
        </span>
        <span className={`text-2xl font-bold tracking-tight ${style.text}`}>
          {t(`triageSupport.priorityLevel.${support.triage_level}`).toUpperCase()}
        </span>
        {escalated && (
          <span className="pill border border-red-300 bg-white text-red-700 text-[11px]">
            {t('triageSupport.escalatedBySafetyRule')}
          </span>
        )}
      </div>
      <p className="mt-2 text-sm text-ink-700">
        <span className="font-medium text-ink-800">{t('triageSupport.whatThisMeans')} </span>
        {t(`triageSupport.meaning.${support.triage_level}`)}
      </p>
    </div>
  )
}

/** Every bullet here is one of the system's own recorded factors — nothing
 *  is added, reworded into a diagnosis, or scored again on the frontend.
 *  `factors` is backend-generated English narrative text (not yet
 *  multilingual — a known, documented limitation). */
function WhyThisPriority({ support }: { support: Support }) {
  const { t } = useTranslation('assessments')
  const factors = support.contributing_factors
  return (
    <Section title={t('triageSupport.whyThisPriority')}>
      {factors.length > 0 ? (
        <ul className="space-y-1 list-disc pl-4">
          {factors.map((factor) => (
            <li key={factor}>{capitalise(factor)}</li>
          ))}
        </ul>
      ) : (
        <p className="text-ink-600">{t('triageSupport.noConcerningFeatures')}</p>
      )}
    </Section>
  )
}

function WhatToDoNext({ support }: { support: Support }) {
  const { t } = useTranslation('assessments')
  return (
    <Section title={t('triageSupport.whatToDoNext')}>
      <p className="font-medium text-ink-900">
        {t(`triageSupport.referralRecommendation.${support.referral_pathway}`, {
          defaultValue: support.referral_recommendation,
        })}
      </p>
      {support.followup_interval_days ? (
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-ink-400">
            {t('triageSupport.suggestedFollowUp')}
          </span>
          <span className="font-medium text-ink-800">
            {t('triageSupport.followUpDayCount', { count: support.followup_interval_days })}
          </span>
        </div>
      ) : null}
    </Section>
  )
}

/** Recorded vitals, shown as entered — flagged only where they are one of
 *  the system's own recorded contributing factors. A value left blank is
 *  never shown as if it were zero. */
function VitalSignCheck({
  vitals,
  factors,
}: {
  vitals: VitalsInput
  factors: string[]
}) {
  const { t } = useTranslation('assessments')
  const rows = VITAL_FIELDS.map((field) => {
    const raw = (vitals[field.key] ?? '').trim()
    return {
      ...field,
      value: raw === '' ? null : raw,
      flagged:
        raw !== '' &&
        field.factorPrefix !== '' &&
        factors.some((factor) => factor.startsWith(field.factorPrefix)),
    }
  })
  const recorded = rows.filter((row) => row.value !== null)

  return (
    <Section title={t('triageSupport.vitalSignCheck')}>
      {recorded.length > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-3">
          {recorded.map((row) => (
            <div key={row.key}>
              <div className="text-xs text-ink-400">{vitalFieldLabel(row.key, t)}</div>
              <div
                className={`font-medium ${row.flagged ? 'text-amber-700' : 'text-ink-800'}`}
              >
                {row.value}
                {row.unit}
                {row.flagged && (
                  <span className="ml-1.5 pill bg-amber-100 text-amber-800 text-[10px] align-middle">
                    {t('triageSupport.flagged')}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-ink-400">{t('triageSupport.vitalsNotRecorded')}</p>
      )}
    </Section>
  )
}

/** The backend's own "Vitals not recorded: temperature_c, ..." note names
 *  its internal field keys — swapped here for the same translated labels
 *  the Vital Sign Check section uses, built from the same `missing_vitals`
 *  list, so nothing here is invented. */
function InformationToCheck({ support }: { support: Support }) {
  const { t } = useTranslation('assessments')
  const missingVitals = support.completeness.missing_vitals
  const notes = [
    ...support.completeness.notes.filter(
      (note) => !note.startsWith('Vitals not recorded'),
    ),
    ...(missingVitals.length > 0
      ? [
          t('triageSupport.vitalsNotRecordedNote', {
            list: missingVitals.map((key) => vitalFieldLabel(key as keyof VitalsInput, t)).join(', '),
          }),
        ]
      : []),
  ]
  return (
    <Section title={t('triageSupport.informationToCheck')}>
      {notes.length > 0 ? (
        <ul className="space-y-1">
          {notes.map((note) => (
            <li key={note} className="flex items-start gap-1.5 text-amber-800">
              <span aria-hidden="true">⚠</span>
              <span>{note}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="flex items-center gap-1.5 text-care-700">
          <span aria-hidden="true">✓</span>
          {t('triageSupport.noAdditionalInfo')}
        </p>
      )}
    </Section>
  )
}

/** Rule-based and separate from the recommendation above it — the point a
 *  new worker most needs to take away is that this check can raise the
 *  priority but nothing here decided it on its own. `flag.label`/
 *  `.rationale` are backend-generated red-flag text (not yet multilingual
 *  — a known, documented limitation). */
function SafetyCheck({ support }: { support: Support }) {
  const { t } = useTranslation('assessments')
  const flags = support.red_flags
  const hasFlags = flags.length > 0

  return (
    <div
      className={`rounded-lg border px-4 py-3 ${
        hasFlags ? 'border-red-300 bg-red-50' : 'border-ink-200 bg-ink-50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`text-xs font-semibold uppercase tracking-wide ${
            hasFlags ? 'text-red-700' : 'text-ink-500'
          }`}
        >
          {t('triageSupport.safetyCheck')}
        </span>
        <span className="pill bg-white text-ink-600 border border-ink-200">
          {t('triageSupport.ruleBasedSafetyReview')}
        </span>
      </div>

      {hasFlags ? (
        <>
          <p className="mt-1.5 text-sm font-medium text-red-800">
            {t('triageSupport.humanReviewRequired')}
          </p>
          <ul className="mt-1.5 space-y-1">
            {flags.map((flag) => (
              <li key={flag.code} className="text-sm text-red-800">
                <span className="font-medium">{flag.label}</span> — {flag.rationale}
              </li>
            ))}
          </ul>
          {support.escalation_forced && (
            <p className="mt-1.5 text-xs text-red-700">
              {t('triageSupport.raisedFrom', {
                level: t(`triageSupport.priorityLevel.${support.model_triage_level}`, {
                  defaultValue: support.model_triage_level,
                }).toLowerCase(),
              })}
            </p>
          )}
        </>
      ) : (
        <p className="mt-1.5 text-sm text-ink-700">
          {t('triageSupport.noAutomaticEscalation')}
        </p>
      )}
    </div>
  )
}

/** Collapsed by default — a new worker gets the result first, and can open
 *  this to see the real stages that produced it. Reuses `AgentTrace`, which
 *  already renders each agent's own name, purpose and result in plain
 *  language, so nothing here duplicates that work. */
function HowThisWasProcessed({ support }: { support: Support }) {
  const { t } = useTranslation('assessments')
  return (
    <details className="group rounded-lg border border-ink-200">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500">
        {t('triageSupport.howThisWasProcessed')}
        <span
          className="text-ink-400 transition-transform group-open:rotate-90"
          aria-hidden="true"
        >
          ▸
        </span>
      </summary>
      <div className="border-t border-ink-200 px-4 py-3">
        <AgentTrace trace={support.agent_trace} />
      </div>
    </details>
  )
}

export function TriageSupportPanel({
  support,
  vitals,
}: {
  support: Support
  vitals: VitalsInput
}) {
  const { t } = useTranslation('assessments')
  const supplementary = support.supplementary_context

  return (
    <div className="space-y-5">
      <PriorityBanner support={support} />
      <WhyThisPriority support={support} />
      <WhatToDoNext support={support} />
      <VitalSignCheck vitals={vitals} factors={support.contributing_factors} />
      <InformationToCheck support={support} />
      <SafetyCheck support={support} />

      {/* Optional free-text detail, shown so the worker can see it was kept —
          and told plainly that it did not drive the priority above. */}
      {supplementary?.has_supplementary_detail && (
        <div className="rounded-md border border-ink-200 bg-white px-3 py-2">
          <div className="text-xs font-medium text-ink-600">
            {t('triageSupport.additionalDetailRecorded')}
          </div>
          {supplementary.other_symptom_text && (
            <p className="mt-1.5 text-sm text-ink-800">
              <span className="text-xs font-medium text-ink-500">{t('triageSupport.otherLabel')} </span>
              {supplementary.other_symptom_text}
            </p>
          )}
          {supplementary.symptom_timeline.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {supplementary.symptom_timeline.map((entry) => (
                <li key={entry.day} className="text-sm text-ink-800">
                  <span className="text-xs font-medium text-ink-500">
                    {t('triageSupport.dayPrefix', { day: entry.day })}{' '}
                  </span>
                  {entry.detail}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-ink-500">{supplementary.note}</p>
        </div>
      )}

      <HowThisWasProcessed support={support} />
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'

import { Card, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type {
  PicmeRchStatus,
  PregnancyAiGuidance,
  PregnancyProfile,
  PregnancyQuestion,
  PregnancyVisitNumber,
} from '@/types'

/**
 * Pregnancy assessment pathway — Phase 1-3/23-25.
 *
 * Rendered inside the existing New Assessment workflow (`NewAssessment.tsx`)
 * once a worker chooses "Pregnancy" as the assessment type for the selected
 * patient. Not a separate portal or route: this is the one place the
 * pregnancy questionnaire, PICME/RCH recording, and visit history live.
 *
 * Every question shown here comes from `GET /pregnancy/questions/<visit>/`
 * — nothing is hardcoded twice. `PregnancyProfile.visit_status` is entirely
 * backend-derived (completed count, target, overdue/urgent flags); this
 * component never computes those itself.
 */

const VISIT_OPTIONS: PregnancyVisitNumber[] = [1, 2, 3, 4]

/** Machine PICME/RCH status -> translation key (under `picme`), so the same
 *  set of options is never translated twice. */
const PICME_STATUS_KEYS: Record<PicmeRchStatus, string> = {
  AVAILABLE: 'statusAvailable',
  REGISTRATION_PENDING: 'statusPending',
  NOT_AVAILABLE: 'statusNotAvailable',
}
const PICME_OPTIONS: PicmeRchStatus[] = ['AVAILABLE', 'REGISTRATION_PENDING', 'NOT_AVAILABLE']

function picmeStatusLabel(t: TFunction, status: PicmeRchStatus): string {
  return t(`picme.${PICME_STATUS_KEYS[status]}`)
}

const RULE_STYLES: Record<string, string> = {
  URGENT_CLINICAL_REVIEW: 'bg-red-100 text-red-700 border-red-200',
  FOLLOW_UP_OVERDUE: 'bg-amber-100 text-amber-800 border-amber-200',
  MISSING_NEXT_CHECKUP: 'bg-ink-100 text-ink-600 border-ink-200',
  LOW_VISIT_COMPLETION_FOR_STAGE: 'bg-amber-100 text-amber-800 border-amber-200',
  ANC_4PLUS_TARGET_NOT_YET_REACHED: 'bg-ink-100 text-ink-600 border-ink-200',
  MISSING_PICME: 'bg-ink-100 text-ink-600 border-ink-200',
}

function formatDate(value: string | null, t: TFunction): string {
  if (!value) return t('profile.notRecorded')
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}

/** A rule flag's own `label`/`detail` text comes from the backend in
 *  English only. `flag.rule` is the stable structural key (matches
 *  `pregnancy.json`'s `rules` object exactly), so that — not the backend
 *  text — drives the localized label; `flag.detail` (the hover tooltip)
 *  has no translation key and is shown as returned. */
function RuleFlagList({
  flags,
  t,
}: {
  flags: PregnancyProfile['visit_status']['rule_flags']
  t: TFunction
}) {
  if (flags.length === 0) {
    return <p className="text-xs text-care-700">{t('profile.noFlags')}</p>
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {flags.map((flag) => (
        <span
          key={flag.rule}
          title={flag.detail}
          className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
            RULE_STYLES[flag.rule] ?? 'bg-ink-100 text-ink-600 border-ink-200'
          }`}
        >
          {t(`rules.${flag.rule}`, { defaultValue: flag.label })}
        </span>
      ))}
    </div>
  )
}

function ProfileOverview({ profile, t }: { profile: PregnancyProfile; t: TFunction }) {
  const { visit_status: status } = profile
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div>
          <div className="text-xs text-ink-400">{t('profile.visitsCompleted')}</div>
          <div className="text-lg font-semibold text-ink-800">
            {status.completed_visit_count} / {status.target_visit_count}
          </div>
        </div>
        <div>
          <div className="text-xs text-ink-400">{t('profile.nextCheckup')}</div>
          <div className="text-sm font-medium text-ink-800">
            {formatDate(status.next_checkup_date, t)}
          </div>
        </div>
        <div>
          <div className="text-xs text-ink-400">{t('profile.picmeRchId')}</div>
          <div className="text-sm font-medium text-ink-800">
            {profile.picme_rch_status === 'AVAILABLE'
              ? profile.picme_rch_id || picmeStatusLabel(t, 'AVAILABLE')
              : picmeStatusLabel(t, profile.picme_rch_status)}
          </div>
        </div>
        <div>
          <div className="text-xs text-ink-400">{t('profile.lmp')}</div>
          <div className="text-sm text-ink-700">{formatDate(profile.lmp, t)}</div>
        </div>
        <div>
          <div className="text-xs text-ink-400">{t('profile.expectedDeliveryDate')}</div>
          <div className="text-sm text-ink-700">{formatDate(profile.expected_delivery_date, t)}</div>
        </div>
        <div>
          <div className="text-xs text-ink-400">{t('profile.status')}</div>
          <div className="text-sm text-ink-700">
            {t(`common:status.${profile.status}`, { defaultValue: profile.status })}
          </div>
        </div>
      </div>
      <RuleFlagList flags={status.rule_flags} t={t} />
    </div>
  )
}

function VisitHistory({ profile, t }: { profile: PregnancyProfile; t: TFunction }) {
  if (profile.visits.length === 0) {
    return <Empty>{t('history.noVisits')}</Empty>
  }
  return (
    <ul className="space-y-2">
      {profile.visits.map((visit) => (
        <li key={visit.id} className="rounded-md border border-ink-200 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-medium text-ink-800">
              {t(`visitLabels.${visit.visit_number}`, { defaultValue: visit.visit_label })}
            </span>
            <span className="text-xs text-ink-400">{formatDate(visit.visit_date, t)}</span>
          </div>
          {visit.warning_signs.length > 0 ? (
            <p className="mt-1 text-xs text-red-600">
              {t('history.warningSignsLabel')}{' '}
              {visit.warning_signs
                .map((sign) => t(`questions.${sign}`, { defaultValue: sign.replace(/_/g, ' ') }))
                .join(', ')}
            </p>
          ) : (
            <p className="mt-1 text-xs text-care-700">{t('history.noWarningSigns')}</p>
          )}
          <p className="mt-1 text-xs text-ink-500">
            {t('history.nextCheckupLabel')} {formatDate(visit.next_checkup_date, t)}
          </p>
        </li>
      ))}
    </ul>
  )
}

function VisitSummaryCard({
  profile,
  guidance,
  t,
}: {
  profile: PregnancyProfile
  guidance: PregnancyAiGuidance
  t: TFunction
}) {
  return (
    <Card title={t('summary.title')}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <div className="text-xs text-ink-400">{t('profile.visitsCompleted')}</div>
            <div className="text-lg font-semibold text-ink-800">
              {profile.visit_status.completed_visit_count} / {profile.visit_status.target_visit_count}
            </div>
          </div>
          <div>
            <div className="text-xs text-ink-400">{t('profile.picmeRchId')}</div>
            <div className="text-sm font-medium text-ink-800">
              {picmeStatusLabel(t, profile.picme_rch_status)}
            </div>
          </div>
          <div>
            <div className="text-xs text-ink-400">{t('profile.nextCheckup')}</div>
            <div className="text-sm font-medium text-ink-800">
              {formatDate(guidance.next_checkup ?? profile.next_checkup_date, t)}
            </div>
          </div>
          <div>
            <div className="text-xs text-ink-400">{t('summary.followUpStatus')}</div>
            <div className="text-sm font-medium text-ink-800">
              {t(`followUpStatus.${guidance.follow_up_status}`, {
                defaultValue: guidance.follow_up_status.replace(/_/g, ' '),
              })}
            </div>
          </div>
        </div>

        {guidance.warning_signs.length > 0 && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {guidance.suggested_action}
          </div>
        )}

        <div>
          <div className="text-xs font-medium text-ink-500 mb-1">{t('summary.aiGuidanceLabel')}</div>
          <p className="text-sm text-ink-700">{guidance.visit_summary}</p>
        </div>

        {guidance.missing_information.length > 0 && (
          <p className="text-xs text-ink-500">
            {t('summary.missingLabel')} {guidance.missing_information.join(', ')}
          </p>
        )}

        <p className="text-xs text-ink-400">
          {t('common:disclaimer.medical')}
        </p>
      </div>
    </Card>
  )
}

function QuestionnaireForm({
  profile,
  onSaved,
}: {
  profile: PregnancyProfile
  onSaved: (profile: PregnancyProfile, guidance: PregnancyAiGuidance) => void
}) {
  const { t } = useTranslation('pregnancy')
  const [visitNumber, setVisitNumber] = useState<PregnancyVisitNumber | null>(null)
  const [responses, setResponses] = useState<Record<string, string>>({})
  const [lmpDate, setLmpDate] = useState('')
  const [nextCheckup, setNextCheckup] = useState('')
  const [picmeId, setPicmeId] = useState(profile.picme_rch_id)
  const [picmeStatus, setPicmeStatus] = useState<PicmeRchStatus>(profile.picme_rch_status)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const questions = useAsync<{ questions: PregnancyQuestion[] }>(
    () =>
      visitNumber
        ? api.get(`/pregnancy/questions/${visitNumber}/`)
        : Promise.resolve({ questions: [] }),
    [visitNumber],
  )

  useEffect(() => {
    setResponses({})
    setLmpDate('')
  }, [visitNumber])

  function setAnswer(key: string, value: string) {
    setResponses((prev) => ({ ...prev, [key]: value }))
  }

  async function save() {
    if (!visitNumber) return
    setSaving(true)
    setError(null)
    try {
      const payload: Record<string, unknown> = {
        visit_number: visitNumber,
        responses: lmpDate ? { ...responses, lmp_date: lmpDate } : responses,
        next_checkup_date: nextCheckup || null,
      }
      if (picmeId.trim() || picmeStatus !== profile.picme_rch_status) {
        payload.picme_rch_id = picmeId.trim()
        payload.picme_rch_status = picmeStatus
      }
      const response = await api.post<{ profile: PregnancyProfile; visit: { ai_guidance: PregnancyAiGuidance } }>(
        `/pregnancy/profiles/${profile.id}/visits/`,
        payload,
      )
      onSaved(response.profile, response.visit.ai_guidance)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('form.couldNotSave'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title={t('form.title')}>
      <div className="space-y-5">
        <div>
          <span className="label">{t('form.whichVisit')}</span>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {VISIT_OPTIONS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setVisitNumber(n)}
                className={`rounded-md border px-3 py-2 text-left text-xs font-medium transition-colors ${
                  visitNumber === n
                    ? 'border-care-600 bg-care-50 text-care-800'
                    : 'border-ink-200 text-ink-600 hover:border-care-400'
                }`}
              >
                {t(`visitLabels.${n}`)}
              </button>
            ))}
          </div>
        </div>

        {visitNumber && questions.loading && <Loading label={t('form.loadingQuestions')} />}
        {visitNumber && questions.error && (
          <ErrorNote message={questions.error} onRetry={questions.reload} />
        )}

        {visitNumber && questions.data && (
          <div className="space-y-4">
            {questions.data.questions.map((question) => (
              <div key={question.key}>
                <label className="label" htmlFor={question.key}>
                  {t(`questions.${question.key}`, { defaultValue: question.text })}
                  {question.warning_sign && (
                    <span className="ml-1.5 text-[10px] font-medium uppercase text-amber-600">
                      {t('warningSignBadge')}
                    </span>
                  )}
                </label>
                {question.type === 'DATE' ? (
                  <input
                    id={question.key}
                    type="date"
                    className="input max-w-[12rem]"
                    value={lmpDate}
                    onChange={(e) => setLmpDate(e.target.value)}
                  />
                ) : (
                  <div className="flex gap-3">
                    {(['YES', 'NO', 'UNKNOWN'] as const).map((option) => (
                      <label key={option} className="flex items-center gap-1.5 text-xs text-ink-700">
                        <input
                          type="radio"
                          name={question.key}
                          checked={responses[question.key] === option}
                          onChange={() => setAnswer(question.key, option)}
                        />
                        {t(`answers.${option}`)}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            ))}

            <fieldset className="rounded-md border border-ink-200 p-3">
              <legend className="label px-1">{t('picme.label')}</legend>
              <input
                className="input"
                placeholder={t('picme.placeholder')}
                value={picmeId}
                onChange={(e) => setPicmeId(e.target.value)}
              />
              <div className="mt-2 flex flex-wrap gap-3">
                {PICME_OPTIONS.map((option) => (
                  <label key={option} className="flex items-center gap-1.5 text-xs text-ink-700">
                    <input
                      type="radio"
                      name="picme_rch_status"
                      checked={picmeStatus === option}
                      onChange={() => setPicmeStatus(option)}
                    />
                    {picmeStatusLabel(t, option)}
                  </label>
                ))}
              </div>
              <p className="mt-2 text-xs text-ink-400">
                {t('picme.helperNote')}
              </p>
            </fieldset>

            <div>
              <label className="label" htmlFor="next_checkup">
                {t('form.nextCheckupDate')}
              </label>
              <input
                id="next_checkup"
                type="date"
                className="input max-w-[12rem]"
                value={nextCheckup}
                onChange={(e) => setNextCheckup(e.target.value)}
              />
            </div>

            {error && <ErrorNote message={error} />}

            <button className="btn-care w-full" onClick={save} disabled={saving}>
              {saving ? t('form.saving') : t('form.save')}
            </button>
          </div>
        )}
      </div>
    </Card>
  )
}

export function PregnancyAssessmentFlow({ patientId }: { patientId: number }) {
  const { t } = useTranslation('pregnancy')
  const [profile, setProfile] = useState<PregnancyProfile | null>(null)
  const [savedGuidance, setSavedGuidance] = useState<PregnancyAiGuidance | null>(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  const profiles = useAsync<PregnancyProfile[]>(
    () => api.get(`/pregnancy/profiles/?patient=${patientId}`),
    [patientId],
  )

  useEffect(() => {
    if (!profiles.data) return
    const active = profiles.data.find((p) => p.status === 'ACTIVE') ?? profiles.data[0] ?? null
    setProfile(active)
  }, [profiles.data])

  async function startProfile() {
    setStarting(true)
    setStartError(null)
    try {
      const created = await api.post<PregnancyProfile>('/pregnancy/profiles/', { patient: patientId })
      setProfile(created)
    } catch (err) {
      setStartError(err instanceof Error ? err.message : t('profile.couldNotStart'))
    } finally {
      setStarting(false)
    }
  }

  if (profiles.loading) return <Loading label={t('profile.loadingRecord')} />
  if (profiles.error) return <ErrorNote message={profiles.error} onRetry={profiles.reload} />

  if (!profile) {
    return (
      <Card title={t('profile.notFoundTitle')}>
        <p className="text-sm text-ink-600">
          {t('profile.noProfile')}
        </p>
        {startError && <ErrorNote message={startError} />}
        <button className="btn-care mt-3" onClick={startProfile} disabled={starting}>
          {starting ? t('profile.starting') : t('profile.startAssessment')}
        </button>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <Card title={t('profile.title')}>
        <ProfileOverview profile={profile} t={t} />
      </Card>

      {savedGuidance ? (
        <VisitSummaryCard profile={profile} guidance={savedGuidance} t={t} />
      ) : (
        <QuestionnaireForm
          profile={profile}
          onSaved={(updated, guidance) => {
            setProfile(updated)
            setSavedGuidance(guidance)
            profiles.reload()
          }}
        />
      )}

      {savedGuidance && (
        <button className="btn-ghost" onClick={() => setSavedGuidance(null)}>
          {t('summary.recordAnother')}
        </button>
      )}

      <Card title={t('history.title')}>
        <VisitHistory profile={profile} t={t} />
      </Card>
    </div>
  )
}

import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Card, Empty, ErrorNote, Loading, Stat } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { OfficerPregnancyListItem, OfficerPregnancySummary } from '@/types'

/**
 * Pregnancy Follow-up — Phase 15/16/18. Embedded directly inside the Health
 * Officer Dashboard, the same pattern `FieldOperationsSection` already
 * established: no separate top-level route, one implementation.
 *
 * Never shows a patient name — only `patient_code`, matching the existing
 * Health Officer permission model (no other officer-facing view in this
 * codebase exposes an individual patient's name either).
 */

const RULE_STYLES: Record<string, string> = {
  URGENT_CLINICAL_REVIEW: 'bg-red-100 text-red-700',
  FOLLOW_UP_OVERDUE: 'bg-amber-100 text-amber-800',
  MISSING_NEXT_CHECKUP: 'bg-ink-100 text-ink-600',
  LOW_VISIT_COMPLETION_FOR_STAGE: 'bg-amber-100 text-amber-800',
  ANC_4PLUS_TARGET_NOT_YET_REACHED: 'bg-ink-100 text-ink-600',
  MISSING_PICME: 'bg-ink-100 text-ink-600',
}

function formatDate(value: string | null, notRecordedLabel: string): string {
  if (!value) return notRecordedLabel
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}

function needsFollowUp(item: OfficerPregnancyListItem): boolean {
  return item.visit_status.rule_flags.some(
    (f) => f.rule === 'FOLLOW_UP_OVERDUE' || f.rule === 'URGENT_CLINICAL_REVIEW',
  )
}

function RequestFollowUpForm({ profileId, onDone }: { profileId: number; onDone: () => void }) {
  const { t } = useTranslation('pregnancy')
  const { t: tc } = useTranslation('common')
  const [priority, setPriority] = useState<'NORMAL' | 'HIGH' | 'URGENT'>('HIGH')
  const [dueDate, setDueDate] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!dueDate) return
    setSaving(true)
    setError(null)
    try {
      await api.post(`/pregnancy/officer/profiles/${profileId}/request-followup/`, {
        priority,
        due_date: dueDate,
        reason,
      })
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('officer.couldNotRequest'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-2 space-y-2 rounded-md border border-ink-200 bg-ink-50/60 p-3">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="label text-xs" htmlFor={`due-${profileId}`}>
            {t('officer.requestFormDueDate')}
          </label>
          <input
            id={`due-${profileId}`}
            type="date"
            className="input py-1 text-xs"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="label text-xs" htmlFor={`priority-${profileId}`}>
            {t('officer.requestFormPriority')}
          </label>
          <select
            id={`priority-${profileId}`}
            className="input py-1 text-xs"
            value={priority}
            onChange={(e) => setPriority(e.target.value as typeof priority)}
          >
            <option value="NORMAL">{tc('status.NORMAL')}</option>
            <option value="HIGH">{tc('status.HIGH')}</option>
            <option value="URGENT">{tc('status.URGENT')}</option>
          </select>
        </div>
        <button type="submit" className="btn-sentinel py-1 text-xs" disabled={saving || !dueDate}>
          {saving ? t('officer.sending') : t('officer.sendRequest')}
        </button>
      </div>
      <input
        className="input py-1 text-xs"
        placeholder={t('officer.requestFormReasonPlaceholder')}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      {error && <ErrorNote message={error} />}
    </form>
  )
}

function PregnancyRow({ item, onRequested }: { item: OfficerPregnancyListItem; onRequested: () => void }) {
  const { t } = useTranslation('pregnancy')
  const { t: tc } = useTranslation('common')
  const [requesting, setRequesting] = useState(false)
  const flagged = needsFollowUp(item)

  return (
    <li className={`rounded-md border p-3 ${flagged ? 'border-amber-300 bg-amber-50/40' : 'border-ink-200'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-ink-800">{item.patient_code}</div>
          <div className="text-xs text-ink-400">{item.village_name}</div>
        </div>
        <div className="text-right text-xs text-ink-600">
          <div>{t('officer.visitsLabel')} {item.visit_status.completed_visit_count} / {item.visit_status.target_visit_count}</div>
          <div>{t('history.nextCheckupLabel')} {formatDate(item.next_checkup_date, t('profile.notRecorded'))}</div>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-500">
        <span>{t('officer.picmeRchLabel')} {tc(`status.${item.picme_rch_status}`, { defaultValue: item.picme_rch_status.replace(/_/g, ' ') })}</span>
        <span>· {t('officer.worker')} {item.assigned_health_worker_name || t('officer.unassigned')}</span>
        <span>· {t('officer.lastVisit')} {formatDate(item.last_visit_date, t('profile.notRecorded'))}</span>
      </div>

      {item.visit_status.rule_flags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.visit_status.rule_flags.map((flag) => (
            <span
              key={flag.rule}
              title={flag.detail}
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${RULE_STYLES[flag.rule] ?? 'bg-ink-100 text-ink-600'}`}
            >
              {t(`rules.${flag.rule}`, { defaultValue: flag.label })}
            </span>
          ))}
        </div>
      )}

      {flagged && !requesting && (
        <button className="btn-ghost mt-2 py-1 text-xs" onClick={() => setRequesting(true)}>
          {t('officer.requestVisit')}
        </button>
      )}
      {requesting && (
        <RequestFollowUpForm
          profileId={item.id}
          onDone={() => {
            setRequesting(false)
            onRequested()
          }}
        />
      )}
    </li>
  )
}

export function PregnancyFollowUpSection() {
  const { t } = useTranslation('pregnancy')
  const [showList, setShowList] = useState(false)

  const summary = useAsync<OfficerPregnancySummary>(() => api.get('/pregnancy/officer/summary/'))
  const list = useAsync<OfficerPregnancyListItem[]>(
    () => (showList ? api.get('/pregnancy/officer/list/') : Promise.resolve([])),
    [showList],
  )

  return (
    <Card
      title={t('officer.sectionTitle')}
      action={
        <button className="btn-ghost py-1 text-xs" onClick={() => setShowList((v) => !v)}>
          {showList ? t('officer.hideList') : t('officer.viewList')}
        </button>
      }
    >
      {summary.loading && <Loading label={t('officer.loadingSummary')} />}
      {summary.error && <ErrorNote message={summary.error} onRetry={summary.reload} />}
      {summary.data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat value={summary.data.active_pregnancies} label={t('officer.activePregnancies')} />
          <Stat value={summary.data.completed_anc_visits} label={t('officer.completedAncVisits')} />
          <Stat value={summary.data.due_followups} label={t('officer.dueFollowups')} />
          <Stat value={summary.data.overdue_followups} label={t('officer.overdueFollowups')} tone="red" />
          <Stat value={summary.data.below_visit_target} label={t('officer.belowVisitTarget')} tone="amber" />
          <Stat value={summary.data.picme_registration_pending} label={t('officer.picmePending')} />
        </div>
      )}

      {showList && (
        <div className="mt-4 border-t border-ink-200 pt-4">
          {list.loading && <Loading label={t('officer.loadingList')} />}
          {list.error && <ErrorNote message={list.error} onRetry={list.reload} />}
          {list.data && list.data.length === 0 && <Empty>{t('officer.noRecords')}</Empty>}
          {list.data && list.data.length > 0 && (
            <ul className="space-y-2">
              {list.data.map((item) => (
                <PregnancyRow
                  key={item.id}
                  item={item}
                  onRequested={() => {
                    list.reload()
                    summary.reload()
                  }}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  )
}

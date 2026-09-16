import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Card, Empty, ErrorNote, Loading, Stat } from '@/components/ui'
import { useFieldOperationsStore } from '@/store/fieldOperations'
import type {
  ActionPlan,
  ChecklistItemStatus,
  FieldOpsPriority,
  FieldVisit,
  Inspection,
  InspectionType,
} from '@/types'

/**
 * Field Operations — Field Visit Planner, Inspection Checklist System, and
 * Action Plan Management. An operational workflow module, deliberately
 * separate from Community Intelligence: nothing here is derived from a
 * detected signal — every visit, inspection, and action plan exists only
 * because a Health Officer explicitly created it.
 *
 * Embedded directly inside the Health Officer Dashboard (`pages/officer/
 * Dashboard.tsx`) rather than its own top-level portal page — there is
 * deliberately no separate `/officer/field-operations` route rendering a
 * second copy of this UI; this component is the single implementation
 * either place would otherwise have duplicated.
 */

function readFileAsDataUri(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('Could not read that file.'))
    reader.readAsDataURL(file)
  })
}

const PRIORITY_STYLES: Record<FieldOpsPriority, string> = {
  NORMAL: 'bg-ink-100 text-ink-600',
  HIGH: 'bg-amber-100 text-amber-800',
  URGENT: 'bg-red-100 text-red-700',
}
function PriorityPill({ priority, label }: { priority: FieldOpsPriority; label: string }) {
  const { t: tc } = useTranslation('common')
  return <span className={`pill ${PRIORITY_STYLES[priority]}`}>{tc(`status.${priority}`, { defaultValue: label })}</span>
}

const VISIT_STATUS_STYLES: Record<string, string> = {
  SCHEDULED: 'bg-ink-100 text-ink-600',
  IN_PROGRESS: 'bg-amber-100 text-amber-800',
  COMPLETED: 'bg-care-100 text-care-700',
  CANCELLED: 'bg-ink-100 text-ink-400',
}
const INSPECTION_STATUS_STYLES: Record<string, string> = {
  DRAFT: 'bg-ink-100 text-ink-600',
  IN_PROGRESS: 'bg-amber-100 text-amber-800',
  COMPLETED: 'bg-care-100 text-care-700',
}
const ACTION_STATUS_STYLES: Record<string, string> = {
  PENDING: 'bg-ink-100 text-ink-600',
  IN_PROGRESS: 'bg-amber-100 text-amber-800',
  COMPLETED: 'bg-care-100 text-care-700',
}
const CHECKLIST_STATUS_STYLES: Record<string, string> = {
  PASSED: 'bg-care-100 text-care-700',
  FAILED: 'bg-red-100 text-red-700',
  NEEDS_ACTION: 'bg-amber-100 text-amber-800',
}

function StatusPill({ value, label, styles }: { value: string; label: string; styles: Record<string, string> }) {
  const { t: tc } = useTranslation('common')
  return (
    <span className={`pill ${styles[value] ?? 'bg-ink-100 text-ink-600'}`}>
      {tc(`status.${value}`, { defaultValue: label })}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Field Visits
// ---------------------------------------------------------------------------
function ScheduleVisitForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { meta, loadMeta, createVisit } = useFieldOperationsStore()
  const [form, setForm] = useState({
    visit_date: '', start_time: '', end_time: '', assigned_officer: '', objective: '', priority: 'NORMAL', notes: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!meta) void loadMeta()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!form.visit_date || !form.assigned_officer || !form.objective) return
    setSaving(true)
    setError(null)
    try {
      await createVisit({
        village: meta?.village_id,
        assigned_officer: Number(form.assigned_officer),
        visit_date: form.visit_date,
        start_time: form.start_time || null,
        end_time: form.end_time || null,
        objective: form.objective,
        priority: form.priority,
        notes: form.notes,
      })
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('visits.scheduleError'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-ink-200 p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">{t('visits.visitDate')}</label>
          <input type="date" className="input w-full" value={form.visit_date} onChange={(e) => setForm({ ...form, visit_date: e.target.value })} />
        </div>
        <div>
          <label className="label">{t('visits.assignedOfficer')}</label>
          <select className="input w-full" value={form.assigned_officer} onChange={(e) => setForm({ ...form, assigned_officer: e.target.value })}>
            <option value="">{t('visits.selectOfficer')}</option>
            {meta?.officers.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">{t('visits.startTime')}</label>
          <input type="time" className="input w-full" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} />
        </div>
        <div>
          <label className="label">{t('visits.endTime')}</label>
          <input type="time" className="input w-full" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} />
        </div>
        <div>
          <label className="label">{t('visits.priority')}</label>
          <select className="input w-full" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
            {meta?.priorities.map((p) => (
              <option key={p.value} value={p.value}>{tc(`status.${p.value}`, { defaultValue: p.label })}</option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className="label">{t('visits.visitObjectiveLabel')}</label>
        <input
          className="input w-full mb-1.5"
          list="visit-objective-templates"
          placeholder={t('visits.objectivePlaceholder')}
          value={form.objective}
          onChange={(e) => setForm({ ...form, objective: e.target.value })}
        />
        <datalist id="visit-objective-templates">
          {meta?.visit_objective_templates.map((template) => <option key={template} value={template} />)}
        </datalist>
      </div>
      <div>
        <label className="label">{t('visits.notes')}</label>
        <textarea className="input w-full" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </div>
      {error && <p className="text-xs text-red-700">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className="btn-sentinel" disabled={saving}>
          {saving ? t('visits.scheduling') : t('visits.submit')}
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>{tc('actions.cancel')}</button>
      </div>
    </form>
  )
}

function VisitOutcomeForm({ visit, onDone }: { visit: FieldVisit; onDone: () => void }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { completeVisit } = useFieldOperationsStore()
  const [form, setForm] = useState({ outcome_summary: '', observations: '', issues_identified: '', follow_up_required: false })
  const [saving, setSaving] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    try {
      await completeVisit(visit.id, form)
      onDone()
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-2 rounded-md border border-ink-100 bg-ink-50 p-3">
      <div className="text-sm font-medium text-ink-700">{t('visits.visitOutcome')}</div>
      <textarea className="input w-full" rows={2} placeholder={t('visits.outcomeSummary')} value={form.outcome_summary} onChange={(e) => setForm({ ...form, outcome_summary: e.target.value })} />
      <textarea className="input w-full" rows={2} placeholder={t('visits.observations')} value={form.observations} onChange={(e) => setForm({ ...form, observations: e.target.value })} />
      <textarea className="input w-full" rows={2} placeholder={t('visits.issuesIdentified')} value={form.issues_identified} onChange={(e) => setForm({ ...form, issues_identified: e.target.value })} />
      <label className="flex items-center gap-1.5 text-xs text-ink-600">
        <input type="checkbox" checked={form.follow_up_required} onChange={(e) => setForm({ ...form, follow_up_required: e.target.checked })} />
        {t('visits.followUpRequired')}
      </label>
      <button type="submit" className="btn-care py-1.5 text-xs" disabled={saving}>
        {saving ? tc('actions.saving') : t('visits.completeVisit')}
      </button>
    </form>
  )
}

function VisitDetail({ visit, onOpenActionPlan }: { visit: FieldVisit; onOpenActionPlan: (prefill: ActionPlanPrefill) => void }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { startVisit, cancelVisit, clearSelectedVisit } = useFieldOperationsStore()
  const [recordingOutcome, setRecordingOutcome] = useState(false)

  return (
    <div className="rounded-lg border border-sentinel-200 bg-sentinel-50/40 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium text-ink-800">{visit.objective}</div>
          <div className="text-xs text-ink-500">
            {visit.village_name} · {visit.visit_date}
            {visit.start_time ? ` · ${visit.start_time.slice(0, 5)}${visit.end_time ? `–${visit.end_time.slice(0, 5)}` : ''}` : ''} · {visit.assigned_officer_name}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <PriorityPill priority={visit.priority} label={visit.priority_label} />
          <StatusPill value={visit.status} label={visit.status_label} styles={VISIT_STATUS_STYLES} />
        </div>
      </div>
      {visit.notes && <p className="mt-2 text-sm text-ink-700">{visit.notes}</p>}

      {visit.status === 'SCHEDULED' && (
        <div className="mt-3 flex gap-2">
          <button className="btn-sentinel py-1.5 text-xs" onClick={() => void startVisit(visit.id)}>{t('visits.startVisit')}</button>
          <button className="btn-ghost py-1.5 text-xs" onClick={() => void cancelVisit(visit.id)}>{t('visits.cancelVisit')}</button>
        </div>
      )}

      {visit.status === 'IN_PROGRESS' && !recordingOutcome && (
        <button className="btn-care mt-3 py-1.5 text-xs" onClick={() => setRecordingOutcome(true)}>{t('visits.recordOutcomeComplete')}</button>
      )}
      {visit.status === 'IN_PROGRESS' && recordingOutcome && (
        <div className="mt-3">
          <VisitOutcomeForm visit={visit} onDone={() => setRecordingOutcome(false)} />
        </div>
      )}

      {visit.status === 'COMPLETED' && (
        <div className="mt-3 space-y-1 rounded-md border border-ink-100 bg-white p-3 text-sm">
          <div className="label">{t('visits.visitOutcome')}</div>
          <p><span className="font-medium">{t('visits.summaryLabel')} </span>{visit.outcome_summary || '—'}</p>
          <p><span className="font-medium">{t('visits.observationsLabel')} </span>{visit.observations || '—'}</p>
          <p><span className="font-medium">{t('visits.issuesIdentifiedLabel')} </span>{visit.issues_identified || t('visits.none')}</p>
          {visit.issues_identified && (
            <button
              className="btn-sentinel mt-2 py-1.5 text-xs"
              onClick={() =>
                onOpenActionPlan({
                  village: visit.village,
                  source_type: 'FIELD_VISIT',
                  source_field_visit: visit.id,
                  problem_finding: visit.issues_identified,
                  title: `Follow-up: ${visit.objective}`,
                })
              }
            >
              {t('actionPlans.create')}
            </button>
          )}
        </div>
      )}
      <button className="btn-ghost mt-3 py-1 text-xs" onClick={clearSelectedVisit}>{tc('actions.close')}</button>
    </div>
  )
}

function FieldVisitsSection({ onOpenActionPlan }: { onOpenActionPlan: (prefill: ActionPlanPrefill) => void }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { summary, visits, visitsLoading, visitsError, loadVisits, selectedVisit, selectVisit } = useFieldOperationsStore()
  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')

  useEffect(() => {
    void loadVisits(statusFilter ? { status: statusFilter } : undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  return (
    <div className="space-y-4">
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat value={summary.field_visits.upcoming} label={t('upcomingVisits')} tone="sentinel" />
          <Stat value={summary.field_visits.pending} label={t('visits.pendingVisits')} />
          <Stat value={summary.field_visits.completed} label={t('visits.completedVisits')} tone="care" />
          <Stat value={summary.field_visits.overdue} label={t('visits.overdueVisitsStat')} tone={summary.field_visits.overdue > 0 ? 'amber' : 'ink'} />
        </div>
      )}

      <Card
        title={t('visits.title')}
        action={!showForm && <button className="btn-sentinel py-1.5 text-xs" onClick={() => setShowForm(true)}>+ {t('visits.schedule')}</button>}
      >
        {showForm && (
          <div className="mb-4">
            <ScheduleVisitForm onDone={() => setShowForm(false)} />
          </div>
        )}

        {selectedVisit && (
          <div className="mb-4">
            <VisitDetail visit={selectedVisit} onOpenActionPlan={onOpenActionPlan} />
          </div>
        )}

        <div className="mb-3 flex flex-wrap gap-1.5">
          {['', 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'].map((value) => (
            <button
              key={value || 'ALL'}
              className={`pill ${statusFilter === value ? 'bg-sentinel-700 text-white' : 'bg-ink-100 text-ink-600'}`}
              onClick={() => setStatusFilter(value)}
            >
              {value ? tc(`status.${value}`) : t('visits.allStatuses')}
            </button>
          ))}
        </div>

        {visitsLoading ? (
          <Loading label={t('visits.loading')} />
        ) : visitsError ? (
          <ErrorNote message={visitsError} onRetry={() => loadVisits()} />
        ) : visits.length === 0 ? (
          <Empty>{t('visits.noVisits')}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-500">
                  <th className="py-1.5 pr-3">{t('visits.date')}</th>
                  <th className="py-1.5 pr-3">{t('visits.village')}</th>
                  <th className="py-1.5 pr-3">{t('visits.officer')}</th>
                  <th className="py-1.5 pr-3">{t('visits.objective')}</th>
                  <th className="py-1.5 pr-3">{t('visits.priority')}</th>
                  <th className="py-1.5 pr-3">{t('visits.status')}</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody>
                {visits.map((visit) => (
                  <tr key={visit.id} className="border-t border-ink-100">
                    <td className="py-2 pr-3">{visit.visit_date}{visit.is_overdue && <span className="ml-1 text-[10px] text-red-600">{tc('status.OVERDUE')}</span>}</td>
                    <td className="py-2 pr-3">{visit.village_name}</td>
                    <td className="py-2 pr-3">{visit.assigned_officer_name}</td>
                    <td className="py-2 pr-3">{visit.objective}</td>
                    <td className="py-2 pr-3"><PriorityPill priority={visit.priority} label={visit.priority_label} /></td>
                    <td className="py-2 pr-3"><StatusPill value={visit.status} label={visit.status_label} styles={VISIT_STATUS_STYLES} /></td>
                    <td className="py-2">
                      <button className="btn-ghost py-1 text-xs" onClick={() => void selectVisit(visit.id)}>{tc('actions.view')}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inspections
// ---------------------------------------------------------------------------
function StartInspectionForm({ onDone }: { onDone: (inspectionId: number) => void }) {
  const { t } = useTranslation('operations')
  const { meta, loadMeta, createInspection } = useFieldOperationsStore()
  const [inspectionType, setInspectionType] = useState<InspectionType | ''>('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!meta) void loadMeta()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!inspectionType || !meta?.village_id) return
    setSaving(true)
    try {
      const inspection = await createInspection(meta.village_id, inspectionType)
      onDone(inspection.id)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-ink-200 p-4">
      <label className="label">{t('inspections.type')}</label>
      <div className="grid gap-2 sm:grid-cols-2">
        {meta?.inspection_types.map((type) => (
          <label key={type.value} className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm cursor-pointer ${inspectionType === type.value ? 'border-sentinel-500 bg-sentinel-50' : 'border-ink-200'}`}>
            <input type="radio" name="inspection_type" checked={inspectionType === type.value} onChange={() => setInspectionType(type.value)} />
            {type.label}
          </label>
        ))}
      </div>
      <button type="submit" className="btn-sentinel" disabled={!inspectionType || saving}>
        {saving ? t('inspections.starting') : t('inspections.start')}
      </button>
    </form>
  )
}

function ChecklistItemRow({ inspection, item }: { inspection: Inspection; item: Inspection['responses'][number] }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { updateChecklistItem } = useFieldOperationsStore()
  const [remarks, setRemarks] = useState(item.remarks)
  const [saving, setSaving] = useState<ChecklistItemStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const locked = inspection.status === 'COMPLETED'

  async function mark(value: ChecklistItemStatus) {
    setSaving(value)
    setError(null)
    try {
      await updateChecklistItem(inspection.id, item.id, value, remarks)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('inspections.itemSaveError'))
    } finally {
      setSaving(null)
    }
  }

  return (
    <li className="rounded-md border border-ink-100 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-ink-800">{item.item_text}</span>
        <StatusPill value={item.status ?? 'NOT_REVIEWED'} label={item.status_label} styles={CHECKLIST_STATUS_STYLES} />
      </div>
      {!locked && (
        <div className="mt-2 space-y-1.5">
          <input
            className="input w-full text-xs"
            placeholder={t('inspections.remarksPlaceholder')}
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
          />
          <div className="flex gap-1.5">
            {(['PASSED', 'NEEDS_ACTION', 'FAILED'] as ChecklistItemStatus[]).map((value) => (
              <button
                key={value}
                className={`pill ${CHECKLIST_STATUS_STYLES[value]}`}
                disabled={saving !== null}
                onClick={() => void mark(value)}
              >
                {saving === value ? tc('actions.saving') : tc(`status.${value}`)}
              </button>
            ))}
          </div>
          {error && <p className="text-[11px] text-red-700">{error}</p>}
        </div>
      )}
      {locked && item.remarks && <p className="mt-1 text-xs text-ink-600">{item.remarks}</p>}
    </li>
  )
}

function InspectionDetail({ inspection, onOpenActionPlan }: { inspection: Inspection; onOpenActionPlan: (prefill: ActionPlanPrefill) => void }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { startInspection, completeInspection, uploadInspectionAttachment, clearSelectedInspection } = useFieldOperationsStore()
  const [summaryRemarks, setSummaryRemarks] = useState('')
  const [file, setFile] = useState<File | null>(null)

  async function handleUpload() {
    if (!file) return
    const dataUri = await readFileAsDataUri(file)
    await uploadInspectionAttachment(inspection.id, dataUri, file.name)
    setFile(null)
  }

  const actionableItems = inspection.responses.filter((r) => r.status === 'FAILED' || r.status === 'NEEDS_ACTION')

  return (
    <div className="rounded-lg border border-sentinel-200 bg-sentinel-50/40 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium text-ink-800">{inspection.inspection_type_label}</div>
          <div className="text-xs text-ink-500">{inspection.village_name} · {inspection.officer_name} · {inspection.inspection_date}</div>
        </div>
        <StatusPill value={inspection.status} label={inspection.status_label} styles={INSPECTION_STATUS_STYLES} />
      </div>

      {inspection.status === 'DRAFT' && (
        <button className="btn-sentinel mt-3 py-1.5 text-xs" onClick={() => void startInspection(inspection.id)}>{t('inspections.beginChecklist')}</button>
      )}

      {inspection.status !== 'DRAFT' && (
        <>
          <ul className="mt-3 space-y-2">
            {inspection.responses.map((item) => (
              <ChecklistItemRow key={item.id} inspection={inspection} item={item} />
            ))}
          </ul>

          <div className="mt-3 grid grid-cols-2 gap-2 rounded-md border border-ink-100 bg-white p-3 text-xs sm:grid-cols-4">
            <div>{t('inspections.total')}: <span className="font-semibold">{inspection.summary.total}</span></div>
            <div>{tc('status.PASSED')}: <span className="font-semibold text-care-700">{inspection.summary.passed}</span></div>
            <div>{tc('status.FAILED')}: <span className="font-semibold text-red-700">{inspection.summary.failed}</span></div>
            <div>{tc('status.NEEDS_ACTION')}: <span className="font-semibold text-amber-700">{inspection.summary.needs_action}</span></div>
          </div>

          <div className="mt-3">
            <div className="label">{t('inspections.supportingDocuments')}</div>
            {inspection.attachments.length === 0 && inspection.status !== 'COMPLETED' && (
              <p className="text-xs text-ink-400">{t('inspections.noDocuments')}</p>
            )}
            <ul className="text-xs text-ink-600">
              {inspection.attachments.map((a) => (
                <li key={a.id}>
                  <a
                    className="text-sentinel-700 hover:underline"
                    href={`${import.meta.env.VITE_API_BASE_URL ?? '/api'}/officer/inspections/${inspection.id}/attachments/${a.id}/`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    📎 {a.filename}
                  </a>
                </li>
              ))}
            </ul>
            {inspection.status !== 'COMPLETED' && (
              <div className="mt-1.5 flex items-center gap-2">
                <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
                <button className="btn-ghost py-1 text-xs" disabled={!file} onClick={() => void handleUpload()}>{t('inspections.upload')}</button>
              </div>
            )}
          </div>

          {inspection.status === 'IN_PROGRESS' && (
            <div className="mt-3 space-y-1.5">
              <textarea className="input w-full text-sm" rows={2} placeholder={t('inspections.summaryRemarksPlaceholder')} value={summaryRemarks} onChange={(e) => setSummaryRemarks(e.target.value)} />
              <button className="btn-care py-1.5 text-xs" onClick={() => void completeInspection(inspection.id, summaryRemarks)}>{t('inspections.complete')}</button>
            </div>
          )}

          {inspection.status === 'COMPLETED' && (
            <>
              {inspection.summary_remarks && <p className="mt-2 text-sm text-ink-700">{inspection.summary_remarks}</p>}
              {actionableItems.length > 0 && (
                <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3">
                  <div className="mb-1.5 text-xs font-medium text-amber-800">{t('inspections.itemsNeedingFollowUp')}</div>
                  <ul className="space-y-1.5">
                    {actionableItems.map((item) => (
                      <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span>{item.item_text} — {item.remarks}</span>
                        <button
                          className="btn-sentinel py-1 text-xs"
                          onClick={() =>
                            onOpenActionPlan({
                              village: inspection.village,
                              source_type: 'INSPECTION',
                              source_inspection: inspection.id,
                              source_checklist_item: item.id,
                              problem_finding: item.remarks,
                              title: `${inspection.inspection_type_label}: ${item.item_text}`,
                            })
                          }
                        >
                          {t('actionPlans.create')}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </>
      )}
      <button className="btn-ghost mt-3 py-1 text-xs" onClick={clearSelectedInspection}>{tc('actions.close')}</button>
    </div>
  )
}

function InspectionsSection({ onOpenActionPlan }: { onOpenActionPlan: (prefill: ActionPlanPrefill) => void }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { summary, inspections, inspectionsLoading, inspectionsError, loadInspections, selectedInspection, selectInspection } =
    useFieldOperationsStore()
  const [showForm, setShowForm] = useState(false)

  useEffect(() => {
    void loadInspections()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-4">
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat value={summary.inspections.draft} label={tc('status.DRAFT')} />
          <Stat value={summary.inspections.in_progress} label={tc('status.IN_PROGRESS')} tone="amber" />
          <Stat value={summary.inspections.completed} label={tc('status.COMPLETED')} tone="care" />
          <Stat value={summary.inspections.needs_action_items} label={tc('status.NEEDS_ACTION')} tone="amber" />
          <Stat value={summary.inspections.failed_items} label={t('inspections.failedItems')} tone="red" />
        </div>
      )}

      <Card
        title={t('inspections.title')}
        action={!showForm && <button className="btn-sentinel py-1.5 text-xs" onClick={() => setShowForm(true)}>+ {t('inspections.start')}</button>}
      >
        {showForm && (
          <div className="mb-4">
            <StartInspectionForm onDone={(id) => { setShowForm(false); void selectInspection(id) }} />
          </div>
        )}

        {selectedInspection && (
          <div className="mb-4">
            <InspectionDetail inspection={selectedInspection} onOpenActionPlan={onOpenActionPlan} />
          </div>
        )}

        {inspectionsLoading ? (
          <Loading label={t('inspections.loading')} />
        ) : inspectionsError ? (
          <ErrorNote message={inspectionsError} onRetry={() => loadInspections()} />
        ) : inspections.length === 0 ? (
          <Empty>{t('inspections.noInspections')}</Empty>
        ) : (
          <div className="space-y-2">
            {inspections.map((inspection) => (
              <div key={inspection.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-ink-100 p-3 text-sm">
                <div>
                  <div className="font-medium text-ink-800">{inspection.inspection_type_label}</div>
                  <div className="text-xs text-ink-500">{inspection.village_name} · {inspection.inspection_date}</div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill value={inspection.status} label={inspection.status_label} styles={INSPECTION_STATUS_STYLES} />
                  <button className="btn-ghost py-1 text-xs" onClick={() => void selectInspection(inspection.id)}>{tc('actions.view')}</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Action Plans
// ---------------------------------------------------------------------------
interface ActionPlanPrefill {
  village: number
  source_type: 'FIELD_VISIT' | 'INSPECTION' | 'OTHER'
  source_field_visit?: number
  source_inspection?: number
  source_checklist_item?: number
  problem_finding: string
  title: string
}

function ActionPlanForm({ prefill, onDone, onCancel }: { prefill: ActionPlanPrefill | null; onDone: () => void; onCancel: () => void }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { meta, loadMeta, createActionPlan } = useFieldOperationsStore()
  const [form, setForm] = useState({
    title: prefill?.title ?? '', problem_finding: prefill?.problem_finding ?? '',
    department: '', responsible_officer: '', deadline: '', required_resources: '', priority: 'NORMAL', notes: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!meta) void loadMeta()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!form.title || !form.problem_finding || !form.department || !form.deadline) return
    setSaving(true)
    setError(null)
    try {
      await createActionPlan({
        title: form.title,
        problem_finding: form.problem_finding,
        village: prefill?.village ?? meta?.village_id,
        source_type: prefill?.source_type ?? 'OTHER',
        source_field_visit: prefill?.source_field_visit,
        source_inspection: prefill?.source_inspection,
        source_checklist_item: prefill?.source_checklist_item,
        department: Number(form.department),
        responsible_officer: form.responsible_officer ? Number(form.responsible_officer) : null,
        deadline: form.deadline,
        required_resources: form.required_resources,
        priority: form.priority,
        progress_percentage: 0,
        notes: form.notes,
      })
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('actionPlans.createError'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-ink-200 p-4">
      {prefill && (
        <p className="rounded-md border border-sentinel-200 bg-sentinel-50 px-3 py-2 text-xs text-sentinel-800">
          {t('actionPlans.linkedNote', {
            source: t(prefill.source_type === 'FIELD_VISIT' ? 'actionPlans.sourceFieldVisit' : 'actionPlans.sourceInspection'),
          })}
        </p>
      )}
      <div>
        <label className="label">{t('actionPlans.actionTitle')}</label>
        <input className="input w-full" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
      </div>
      <div>
        <label className="label">{t('actionPlans.problemFinding')}</label>
        <textarea className="input w-full" rows={2} value={form.problem_finding} onChange={(e) => setForm({ ...form, problem_finding: e.target.value })} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">{t('actionPlans.responsibleDepartment')}</label>
          <select className="input w-full" value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })}>
            <option value="">{t('actionPlans.selectDepartment')}</option>
            {meta?.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">{t('actionPlans.responsiblePerson')}</label>
          <select className="input w-full" value={form.responsible_officer} onChange={(e) => setForm({ ...form, responsible_officer: e.target.value })}>
            <option value="">{t('actionPlans.unassigned')}</option>
            {meta?.staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">{t('actionPlans.deadline')}</label>
          <input type="date" className="input w-full" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} />
        </div>
        <div>
          <label className="label">{t('actionPlans.priority')}</label>
          <select className="input w-full" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
            {meta?.priorities.map((p) => <option key={p.value} value={p.value}>{tc(`status.${p.value}`, { defaultValue: p.label })}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="label">{t('actionPlans.requiredResources')}</label>
        <textarea className="input w-full" rows={2} placeholder={t('actionPlans.requiredResourcesPlaceholder')} value={form.required_resources} onChange={(e) => setForm({ ...form, required_resources: e.target.value })} />
      </div>
      <div>
        <label className="label">{t('actionPlans.notes')}</label>
        <textarea className="input w-full" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </div>
      {error && <p className="text-xs text-red-700">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className="btn-sentinel" disabled={saving}>{saving ? t('actionPlans.creating') : t('actionPlans.create')}</button>
        <button type="button" className="btn-ghost" onClick={onCancel}>{tc('actions.cancel')}</button>
      </div>
    </form>
  )
}

function ProgressBar({ value }: { value: number }) {
  const tone = value >= 100 ? 'bg-care-600' : value > 0 ? 'bg-amber-500' : 'bg-ink-300'
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-ink-100">
      <div className={`h-full ${tone}`} style={{ width: `${value}%` }} />
    </div>
  )
}

function ActionPlanCard({ plan }: { plan: ActionPlan }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { updateActionPlanProgress } = useFieldOperationsStore()
  const [expanded, setExpanded] = useState(false)
  const [progress, setProgress] = useState(plan.progress_percentage)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleUpdate() {
    setSaving(true)
    try {
      await updateActionPlanProgress(plan.id, progress, note)
      setNote('')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-ink-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium text-ink-800">{plan.title}{plan.is_overdue && <span className="ml-2 text-[10px] text-red-600">{tc('status.OVERDUE')}</span>}</div>
          <div className="text-xs text-ink-500">{plan.village_name} · {plan.department_name} · {t('actionPlans.due')} {plan.deadline}</div>
        </div>
        <div className="flex items-center gap-1.5">
          <PriorityPill priority={plan.priority} label={plan.priority_label} />
          <StatusPill value={plan.status} label={plan.status_label} styles={ACTION_STATUS_STYLES} />
        </div>
      </div>
      <p className="mt-2 text-sm text-ink-700">{plan.problem_finding}</p>
      {plan.required_resources && <p className="mt-1 text-xs text-ink-500">{t('actionPlans.resourcesLabel')} {plan.required_resources}</p>}

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-xs text-ink-500">
          <span>{t('actionPlans.progress')}</span>
          <span className="font-medium text-ink-700">{plan.progress_percentage}%</span>
        </div>
        <ProgressBar value={plan.progress_percentage} />
      </div>

      {plan.status !== 'COMPLETED' && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            type="range" min={0} max={100} value={progress}
            onChange={(e) => setProgress(Number(e.target.value))}
            className="flex-1"
          />
          <span className="w-10 text-right text-xs font-medium">{progress}%</span>
          <input className="input flex-1 text-xs" placeholder={t('actionPlans.updateNotePlaceholder')} value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn-sentinel py-1 text-xs" disabled={saving} onClick={() => void handleUpdate()}>
            {saving ? tc('actions.saving') : t('actionPlans.updateProgress')}
          </button>
        </div>
      )}

      <button className="btn-ghost mt-2 py-1 text-xs" onClick={() => setExpanded(!expanded)}>
        {expanded ? t('actionPlans.hideProgressHistory') : t('actionPlans.viewProgressHistory')}
      </button>
      {expanded && (
        <ol className="mt-2 space-y-1 border-t border-ink-100 pt-2 text-xs text-ink-600">
          {plan.progress_updates.length === 0 ? (
            <li className="text-ink-400">{t('actionPlans.noUpdates')}</li>
          ) : (
            plan.progress_updates.map((u, i) => (
              <li key={i}>
                {new Date(u.created_at).toLocaleDateString()} — {u.previous_percentage}% → {u.new_percentage}%
                {u.update_note && <span className="text-ink-500"> ({u.update_note})</span>}
              </li>
            ))
          )}
        </ol>
      )}
    </div>
  )
}

function ActionPlansSection({ prefill, onPrefillConsumed }: { prefill: ActionPlanPrefill | null; onPrefillConsumed: () => void }) {
  const { t } = useTranslation('operations')
  const { t: tc } = useTranslation('common')
  const { summary, actionPlans, actionPlansLoading, actionPlansError, loadActionPlans } = useFieldOperationsStore()
  const [showForm, setShowForm] = useState(false)

  useEffect(() => {
    void loadActionPlans()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (prefill) setShowForm(true)
  }, [prefill])

  return (
    <div className="space-y-4">
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat value={summary.action_plans.open} label={t('actionPlans.openStat')} />
          <Stat value={summary.action_plans.in_progress} label={tc('status.IN_PROGRESS')} tone="amber" />
          <Stat value={summary.action_plans.due_soon} label={t('actionPlans.dueSoon')} tone="amber" />
          <Stat value={summary.action_plans.overdue} label={tc('status.OVERDUE')} tone="red" />
          <Stat value={summary.action_plans.completed} label={tc('status.COMPLETED')} tone="care" />
        </div>
      )}

      <Card
        title={t('actionPlans.title')}
        action={!showForm && <button className="btn-sentinel py-1.5 text-xs" onClick={() => setShowForm(true)}>+ {t('actionPlans.create')}</button>}
      >
        {showForm && (
          <div className="mb-4">
            <ActionPlanForm
              prefill={prefill}
              onDone={() => { setShowForm(false); onPrefillConsumed() }}
              onCancel={() => { setShowForm(false); onPrefillConsumed() }}
            />
          </div>
        )}

        {actionPlansLoading ? (
          <Loading label={t('actionPlans.loading')} />
        ) : actionPlansError ? (
          <ErrorNote message={actionPlansError} onRetry={() => loadActionPlans()} />
        ) : actionPlans.length === 0 ? (
          <Empty>{t('actionPlans.noPlans')}</Empty>
        ) : (
          <div className="space-y-3">
            {actionPlans.map((plan) => <ActionPlanCard key={plan.id} plan={plan} />)}
          </div>
        )}
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section (embedded in the Health Officer Dashboard)
// ---------------------------------------------------------------------------
type Section = 'visits' | 'inspections' | 'actions'

export function FieldOperationsSection() {
  const { t } = useTranslation('operations')
  const { summary, loadSummary } = useFieldOperationsStore()
  const [section, setSection] = useState<Section>('visits')
  const [actionPlanPrefill, setActionPlanPrefill] = useState<ActionPlanPrefill | null>(null)

  useEffect(() => {
    void loadSummary()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openActionPlanFrom(prefill: ActionPlanPrefill) {
    setActionPlanPrefill(prefill)
    setSection('actions')
  }

  const tabs: Array<{ id: Section; label: string }> = [
    { id: 'visits', label: t('visits.title') },
    { id: 'inspections', label: t('inspections.title') },
    { id: 'actions', label: t('actionPlans.title') },
  ]

  return (
    <section className="overflow-hidden rounded-xl border border-ink-200 bg-white">
      <div className="border-b border-ink-200 bg-gradient-to-r from-sentinel-50 to-white px-5 py-4">
        <h2 className="text-lg font-semibold text-ink-900">{t('title')}</h2>
        <p className="text-sm text-ink-600 mt-0.5">
          {t('subtitle')}
        </p>
      </div>

      <div className="space-y-4 p-5">
        {summary && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat value={summary.field_visits.upcoming} label={t('upcomingVisits')} tone="sentinel" />
            <Stat value={summary.inspections.draft + summary.inspections.in_progress} label={t('pendingInspections')} tone="amber" />
            <Stat value={summary.action_plans.open + summary.action_plans.in_progress} label={t('openActionPlans')} />
            <Stat value={summary.action_plans.overdue} label={t('overdueActions')} tone={summary.action_plans.overdue > 0 ? 'red' : 'ink'} />
          </div>
        )}

        <div className="flex flex-wrap gap-2 border-b border-ink-200 pb-2">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`rounded-md px-3 py-2 text-sm font-medium ${
                section === tab.id ? 'bg-sentinel-700 text-white' : 'bg-white text-ink-600 hover:bg-ink-50'
              }`}
              onClick={() => setSection(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {section === 'visits' && <FieldVisitsSection onOpenActionPlan={openActionPlanFrom} />}
        {section === 'inspections' && <InspectionsSection onOpenActionPlan={openActionPlanFrom} />}
        {section === 'actions' && (
          <ActionPlansSection prefill={actionPlanPrefill} onPrefillConsumed={() => setActionPlanPrefill(null)} />
        )}
      </div>
    </section>
  )
}

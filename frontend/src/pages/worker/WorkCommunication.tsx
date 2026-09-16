import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { Card, Empty, ErrorNote, Loading } from '@/components/ui'
import { useWorkCommunicationStore } from '@/store/workCommunication'
import type { CorrectableRecord, WorkflowStatus } from '@/types'

/**
 * Work & Communication — one Worker Portal tab holding three related
 * capabilities: a private conversation with the assigned Health Officer,
 * a read-only tracker for submitted report approvals, and a controlled
 * workflow for requesting a correction to an already-submitted record.
 *
 * A completed New Assessment is never simply reopened for editing here —
 * see the Correction Requests section below, which is deliberately a
 * request-and-approve workflow, not an edit form.
 */

const STATUS_STYLES: Record<WorkflowStatus, string> = {
  SUBMITTED: 'bg-ink-100 text-ink-600',
  UNDER_REVIEW: 'bg-amber-100 text-amber-800',
  APPROVED: 'bg-care-100 text-care-700',
  RETURNED_FOR_CORRECTION: 'bg-amber-100 text-amber-800',
  RESUBMITTED: 'bg-ink-100 text-ink-600',
  REJECTED: 'bg-red-100 text-red-700',
}

function StatusPill({ status }: { status: WorkflowStatus }) {
  const { t: tc } = useTranslation('common')
  return <span className={`pill ${STATUS_STYLES[status]}`}>{tc(`status.${status}`)}</span>
}

function readFileAsDataUri(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('Could not read that file.'))
    reader.readAsDataURL(file)
  })
}

// ---------------------------------------------------------------------------
// Supervisor Communication
// ---------------------------------------------------------------------------
function SupervisorCommunicationSection() {
  const { t } = useTranslation('worker')
  const { t: tc } = useTranslation('common')
  const {
    officerName,
    messages,
    messagesLoading,
    messagesError,
    sendingMessage,
    sendMessageError,
    loadMyMessages,
    sendMyMessage,
  } = useWorkCommunicationStore()

  const [search, setSearch] = useState('')
  const [body, setBody] = useState('')
  const [subject, setSubject] = useState('')
  const [file, setFile] = useState<File | null>(null)

  useEffect(() => {
    void loadMyMessages()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleSearch(event: FormEvent) {
    event.preventDefault()
    void loadMyMessages(search)
  }

  async function handleSend(event: FormEvent) {
    event.preventDefault()
    if (!body.trim()) return

    let attachment: string | undefined
    if (file) {
      try {
        attachment = await readFileAsDataUri(file)
      } catch {
        return
      }
    }

    try {
      await sendMyMessage({
        subject: subject.trim(),
        body: body.trim(),
        attachment,
        attachment_filename: file?.name,
      })
      setBody('')
      setSubject('')
      setFile(null)
    } catch {
      // sendMessageError already reflects this in the store
    }
  }

  return (
    <Card title={t('workCommunication.tabs.communication')}>
      <p className="text-sm text-ink-600 -mt-1 mb-4">
        {officerName
          ? t('workCommunication.messages.privateConversationWith', { officerName })
          : t('workCommunication.messages.privateConversationGeneric')}
      </p>

      <form onSubmit={handleSearch} className="mb-3 flex gap-2">
        <input
          className="input flex-1"
          placeholder={t('workCommunication.messages.searchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button type="submit" className="btn-ghost">
          {tc('actions.search')}
        </button>
      </form>

      {messagesLoading ? (
        <Loading label={t('workCommunication.messages.loading')} />
      ) : messagesError ? (
        <ErrorNote message={messagesError} onRetry={() => loadMyMessages()} />
      ) : messages.length === 0 ? (
        <Empty>{t('workCommunication.messages.empty')}</Empty>
      ) : (
        <ul className="max-h-[420px] space-y-3 overflow-y-auto rounded-md border border-ink-100 p-3">
          {messages.map((message) => (
            <li
              key={message.id}
              className={`rounded-lg border p-3 text-sm ${
                message.is_from_officer
                  ? 'border-sentinel-200 bg-sentinel-50/60'
                  : 'border-care-200 bg-care-50/60 ml-6'
              }`}
            >
              <div className="flex items-center justify-between gap-2 text-xs text-ink-500">
                <span className="font-medium text-ink-700">
                  {message.is_from_officer ? tc('role.HEALTH_OFFICER') : t('workCommunication.messages.you')}
                </span>
                <span>{new Date(message.created_at).toLocaleString()}</span>
              </div>
              {message.subject && <div className="mt-1 font-medium text-ink-800">{message.subject}</div>}
              <p className="mt-1 whitespace-pre-line text-ink-800">{message.body}</p>
              {message.has_attachment && (
                <a
                  className="mt-2 inline-block text-xs text-sentinel-700 hover:underline"
                  href={`${import.meta.env.VITE_API_BASE_URL ?? '/api'}/work/messages/${message.id}/attachment/`}
                  target="_blank"
                  rel="noreferrer"
                >
                  📎 {message.attachment_filename || t('workCommunication.messages.attachmentFallback')}
                </a>
              )}
              {!message.is_from_officer && (
                <div className="mt-1 text-[11px] text-ink-400">
                  {message.is_read ? t('workCommunication.messages.read') : t('workCommunication.messages.sent')}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={handleSend} className="mt-4 space-y-2 border-t border-ink-100 pt-4">
        <input
          className="input w-full"
          placeholder={t('workCommunication.messages.subjectPlaceholder')}
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
        />
        <textarea
          className="input w-full"
          rows={3}
          placeholder={t('workCommunication.messages.bodyPlaceholder')}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <label className="btn-ghost cursor-pointer py-1.5 text-xs">
            {t('workCommunication.messages.attachDocument')}
            <input
              type="file"
              className="hidden"
              accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {file && <span className="text-xs text-ink-500">{file.name}</span>}
          <button type="submit" className="btn-care ml-auto" disabled={sendingMessage || !body.trim()}>
            {sendingMessage ? t('shared.sending') : tc('actions.send')}
          </button>
        </div>
        {sendMessageError && <p className="text-xs text-red-700">{sendMessageError}</p>}
      </form>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Report Approval Tracker
// ---------------------------------------------------------------------------
const REPORT_FILTERS: Array<WorkflowStatus | 'ALL'> = [
  'ALL', 'SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'RETURNED_FOR_CORRECTION', 'RESUBMITTED', 'REJECTED',
]

function ReportApprovalSection() {
  const { t } = useTranslation('worker')
  const { t: tc } = useTranslation('common')
  const { reportApprovals, reportApprovalsLoading, reportApprovalsError, loadMyReportApprovals } =
    useWorkCommunicationStore()
  const [filter, setFilter] = useState<WorkflowStatus | 'ALL'>('ALL')

  useEffect(() => {
    void loadMyReportApprovals(filter === 'ALL' ? undefined : filter)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  return (
    <Card title={t('workCommunication.approvals.cardTitle')}>
      <p className="text-sm text-ink-600 -mt-1 mb-4">
        {t('workCommunication.approvals.description')}
      </p>

      <div className="mb-4 flex flex-wrap gap-1.5">
        {REPORT_FILTERS.map((value) => (
          <button
            key={value}
            className={`pill ${filter === value ? 'bg-care-600 text-white' : 'bg-ink-100 text-ink-600'}`}
            onClick={() => setFilter(value)}
          >
            {value === 'ALL' ? t('workCommunication.approvals.allFilter') : tc(`status.${value}`)}
          </button>
        ))}
      </div>

      {reportApprovalsLoading ? (
        <Loading label={t('workCommunication.approvals.loading')} />
      ) : reportApprovalsError ? (
        <ErrorNote message={reportApprovalsError} onRetry={() => loadMyReportApprovals()} />
      ) : reportApprovals.length === 0 ? (
        <Empty>{t('workCommunication.approvals.empty')}</Empty>
      ) : (
        <div className="space-y-3">
          {reportApprovals.map((approval) => (
            <div key={approval.id} className="rounded-lg border border-ink-200 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-medium text-ink-800">
                    {t('workCommunication.approvals.communityReportWeek', { week: approval.week_label })}
                  </div>
                  <div className="text-xs text-ink-500">
                    {t('workCommunication.approvals.submittedUpdated', {
                      submittedDate: new Date(approval.created_at).toLocaleDateString(),
                      updatedDate: new Date(approval.updated_at).toLocaleDateString(),
                    })}
                  </div>
                </div>
                <StatusPill status={approval.status} />
              </div>
              {approval.supervisor_comment && (
                <p className="mt-2 rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-sm text-ink-700">
                  <span className="font-medium">{t('workCommunication.supervisorComment')} </span>
                  {approval.supervisor_comment}
                </p>
              )}
              {approval.status === 'RETURNED_FOR_CORRECTION' && (
                <Link to="/worker/community-report" className="btn-care mt-3 inline-block py-1.5 text-xs">
                  {t('workCommunication.approvals.resubmit')}
                </Link>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Correction Requests
// ---------------------------------------------------------------------------
function RequestCorrectionForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation('worker')
  const { t: tc } = useTranslation('common')
  const { correctableRecords, correctableRecordsLoading, loadCorrectableRecords, submittingCorrection, submitCorrection } =
    useWorkCommunicationStore()
  const [selected, setSelected] = useState<CorrectableRecord | null>(null)
  const [mistake, setMistake] = useState('')
  const [correction, setCorrection] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void loadCorrectableRecords()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!selected || !mistake.trim() || !correction.trim()) return
    setError(null)
    try {
      await submitCorrection({
        record_type: selected.record_type,
        record_id: selected.record_id,
        mistake_description: mistake.trim(),
        proposed_correction: correction.trim(),
      })
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('workCommunication.corrections.submitError'))
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-ink-200 p-4">
      <div>
        <label className="label">{t('workCommunication.corrections.recordLabel')}</label>
        {correctableRecordsLoading ? (
          <Loading label={t('workCommunication.corrections.loadingRecords')} />
        ) : (
          <select
            className="input w-full"
            value={selected ? `${selected.record_type}:${selected.record_id}` : ''}
            onChange={(e) => {
              const found = correctableRecords.find((r) => `${r.record_type}:${r.record_id}` === e.target.value)
              setSelected(found ?? null)
            }}
          >
            <option value="">{t('workCommunication.corrections.selectRecordPlaceholder')}</option>
            {correctableRecords.map((record) => (
              <option key={`${record.record_type}:${record.record_id}`} value={`${record.record_type}:${record.record_id}`}>
                {record.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {selected && Object.keys(selected.snapshot).length > 0 && (
        <div className="rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-xs text-ink-700">
          <div className="mb-1 font-medium text-ink-500">{t('workCommunication.corrections.currentInformation')}</div>
          {Object.entries(selected.snapshot).map(([field, value]) => (
            <div key={field}>
              {field}: <span className="font-medium">{value}</span>
            </div>
          ))}
        </div>
      )}

      <div>
        <label className="label">{t('workCommunication.corrections.whatIsWrong')}</label>
        <textarea className="input w-full" rows={2} value={mistake} onChange={(e) => setMistake(e.target.value)} />
      </div>
      <div>
        <label className="label">{t('workCommunication.corrections.correctInformation')}</label>
        <textarea className="input w-full" rows={2} value={correction} onChange={(e) => setCorrection(e.target.value)} />
      </div>

      {error && <p className="text-xs text-red-700">{error}</p>}

      <div className="flex gap-2">
        <button type="submit" className="btn-care" disabled={!selected || submittingCorrection}>
          {submittingCorrection ? t('workCommunication.corrections.submitting') : t('workCommunication.corrections.submitButton')}
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>
          {tc('actions.cancel')}
        </button>
      </div>
    </form>
  )
}

function CorrectionHistory({ correctionId }: { correctionId: number }) {
  const correction = useWorkCommunicationStore((state) => state.corrections.find((c) => c.id === correctionId))
  if (!correction) return null

  return (
    <ol className="mt-3 space-y-1.5 border-t border-ink-100 pt-3 text-xs text-ink-600">
      {correction.events.map((event, index) => (
        <li key={index} className="flex items-center gap-2">
          <span className="text-ink-400">{new Date(event.created_at).toLocaleDateString()}</span>
          <span className="font-medium">{event.to_status_label}</span>
          {event.comment && <span className="text-ink-500">— {event.comment}</span>}
        </li>
      ))}
    </ol>
  )
}

function CorrectionRequestsSection() {
  const { t } = useTranslation('worker')
  const { corrections, correctionsLoading, correctionsError, loadMyCorrections } = useWorkCommunicationStore()
  const [showForm, setShowForm] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    void loadMyCorrections()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Card title={t('workCommunication.tabs.corrections')}>
      <p className="text-sm text-ink-600 -mt-1 mb-4">
        {t('workCommunication.corrections.description')}
      </p>

      {!showForm && (
        <button className="btn-care mb-4" onClick={() => setShowForm(true)}>
          {t('workCommunication.corrections.requestButton')}
        </button>
      )}
      {showForm && (
        <div className="mb-4">
          <RequestCorrectionForm onDone={() => setShowForm(false)} />
        </div>
      )}

      {correctionsLoading ? (
        <Loading label={t('workCommunication.corrections.loading')} />
      ) : correctionsError ? (
        <ErrorNote message={correctionsError} onRetry={() => loadMyCorrections()} />
      ) : corrections.length === 0 ? (
        <Empty>{t('workCommunication.corrections.empty')}</Empty>
      ) : (
        <div className="space-y-3">
          {corrections.map((correction) => (
            <div key={correction.id} className="rounded-lg border border-ink-200 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-medium text-ink-800">{correction.record_label}</div>
                  <div className="text-xs text-ink-500">
                    {t('workCommunication.corrections.requestedDate', {
                      date: new Date(correction.created_at).toLocaleDateString(),
                    })}
                  </div>
                </div>
                <StatusPill status={correction.status} />
              </div>
              <p className="mt-2 text-sm text-ink-700">
                <span className="font-medium">{t('workCommunication.corrections.issueLabel')} </span>
                {correction.mistake_description}
              </p>
              <p className="mt-1 text-sm text-ink-700">
                <span className="font-medium">{t('workCommunication.corrections.proposedCorrectionLabel')} </span>
                {correction.proposed_correction}
              </p>
              {correction.supervisor_comment && (
                <p className="mt-2 rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-sm text-ink-700">
                  <span className="font-medium">{t('workCommunication.supervisorComment')} </span>
                  {correction.supervisor_comment}
                </p>
              )}
              <button
                className="btn-ghost mt-2 py-1 text-xs"
                onClick={() => setExpanded(expanded === correction.id ? null : correction.id)}
              >
                {expanded === correction.id
                  ? t('workCommunication.corrections.hideHistory')
                  : t('workCommunication.corrections.viewHistory')}
              </button>
              {expanded === correction.id && <CorrectionHistory correctionId={correction.id} />}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
type Section = 'communication' | 'reports' | 'corrections'

export default function WorkCommunicationPage() {
  const { t } = useTranslation('worker')
  const [section, setSection] = useState<Section>('communication')

  const tabs: Array<{ id: Section; label: string; avatar?: boolean }> = [
    { id: 'communication', label: t('workCommunication.tabs.communication') },
    { id: 'reports', label: t('workCommunication.tabs.reports') },
    { id: 'corrections', label: t('workCommunication.tabs.corrections') },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t('workCommunication.title')}</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {t('workCommunication.subtitle')}
        </p>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-ink-200 pb-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`rounded-md px-3 py-2 text-sm font-medium ${
              section === tab.id ? 'bg-care-600 text-white' : 'bg-white text-ink-600 hover:bg-ink-50'
            }`}
            onClick={() => setSection(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {section === 'communication' && <SupervisorCommunicationSection />}
      {section === 'reports' && <ReportApprovalSection />}
      {section === 'corrections' && <CorrectionRequestsSection />}
    </div>
  )
}

import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Card, Empty, ErrorNote, Loading } from '@/components/ui'
import { translateSnapshotField } from '@/i18n/snapshotFields'
import { openAttachment } from '@/services/api'
import { useWorkCommunicationStore } from '@/store/workCommunication'
import type { WorkflowStatus } from '@/types'

/**
 * Team Workspace — the Health Officer's side of Work & Communication:
 * reviewing worker messages, report approvals, and correction requests
 * for the officer's own village team. Every list here is already
 * village-scoped server-side (`scope_queryset`, same as every other
 * officer-facing view in this portal) — there is no village selector on
 * this page because there is nothing for one to do.
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

function readFileAsDataUri(file: File, errorMessage: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error(errorMessage))
    reader.readAsDataURL(file)
  })
}

// ---------------------------------------------------------------------------
// Communication
// ---------------------------------------------------------------------------
function CommunicationSection() {
  const { t } = useTranslation('officer')
  const { t: tc } = useTranslation('common')
  const {
    threads, threadsLoading, threadsError, loadThreads,
    selectedWorkerId, threadWorkerName, threadMessages, threadLoading, threadError, openThread, replyToThread,
  } = useWorkCommunicationStore()
  const [reply, setReply] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const [openingAttachmentId, setOpeningAttachmentId] = useState<number | null>(null)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)

  useEffect(() => {
    void loadThreads()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleOpenAttachment(messageId: number) {
    setOpeningAttachmentId(messageId)
    setAttachmentError(null)
    try {
      await openAttachment(`/work/messages/${messageId}/attachment/`)
    } catch (err) {
      setAttachmentError(
        err instanceof Error ? err.message : t('teamWorkspace.communication.attachmentError'),
      )
    } finally {
      setOpeningAttachmentId(null)
    }
  }

  async function handleReply(event: FormEvent) {
    event.preventDefault()
    if (!selectedWorkerId || !reply.trim()) return
    setSending(true)
    try {
      let attachment: string | undefined
      if (file) attachment = await readFileAsDataUri(file, t('teamWorkspace.communication.fileReadError'))
      await replyToThread(selectedWorkerId, { body: reply.trim(), attachment, attachment_filename: file?.name })
      setReply('')
      setFile(null)
    } finally {
      setSending(false)
    }
  }

  return (
    <Card title={t('teamWorkspace.communication.title')}>
      <div className="grid gap-4 md:grid-cols-[240px_minmax(0,1fr)]">
        <div>
          {threadsLoading ? (
            <Loading label={tc('states.loading')} />
          ) : threadsError ? (
            <ErrorNote message={threadsError} onRetry={loadThreads} />
          ) : threads.length === 0 ? (
            <Empty>{t('teamWorkspace.communication.noWorkers')}</Empty>
          ) : (
            <ul className="space-y-1">
              {threads.map((thread) => (
                <li key={thread.worker_id}>
                  <button
                    className={`w-full rounded-md px-3 py-2 text-left text-sm ${
                      selectedWorkerId === thread.worker_id ? 'bg-care-50 text-care-800' : 'hover:bg-ink-50'
                    }`}
                    onClick={() => void openThread(thread.worker_id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{thread.worker_name}</span>
                      {thread.unread_count > 0 && (
                        <span className="pill bg-care-600 text-white">{thread.unread_count}</span>
                      )}
                    </div>
                    <div className="truncate text-xs text-ink-500">
                      {thread.last_message_preview || t('teamWorkspace.communication.noMessages')}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          {!selectedWorkerId ? (
            <Empty>{t('teamWorkspace.communication.selectWorker')}</Empty>
          ) : threadLoading ? (
            <Loading label={tc('states.loading')} />
          ) : threadError ? (
            <ErrorNote message={threadError} onRetry={() => void openThread(selectedWorkerId)} />
          ) : (
            <>
              <div className="mb-2 text-sm font-medium text-ink-700">{threadWorkerName}</div>
              {attachmentError && (
                <div className="mb-2">
                  <ErrorNote message={attachmentError} />
                </div>
              )}
              <ul className="max-h-[360px] space-y-3 overflow-y-auto rounded-md border border-ink-100 p-3">
                {threadMessages.length === 0 ? (
                  <Empty>{t('teamWorkspace.communication.noMessages')}</Empty>
                ) : (
                  threadMessages.map((message) => (
                    <li
                      key={message.id}
                      className={`rounded-lg border p-3 text-sm ${
                        message.is_from_officer
                          ? 'border-sentinel-200 bg-sentinel-50/60 ml-6'
                          : 'border-care-200 bg-care-50/60'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 text-xs text-ink-500">
                        <span className="font-medium text-ink-700">
                          {message.is_from_officer ? t('teamWorkspace.communication.you') : threadWorkerName}
                        </span>
                        <span>{new Date(message.created_at).toLocaleString()}</span>
                      </div>
                      <p className="mt-1 whitespace-pre-line text-ink-800">{message.body}</p>
                      {message.has_attachment && (
                        <button
                          type="button"
                          className="mt-2 inline-block text-xs text-sentinel-700 hover:underline disabled:opacity-50"
                          onClick={() => void handleOpenAttachment(message.id)}
                          disabled={openingAttachmentId === message.id}
                        >
                          📎{' '}
                          {openingAttachmentId === message.id
                            ? t('teamWorkspace.communication.attachmentOpening')
                            : message.attachment_filename || t('teamWorkspace.communication.attachmentFallback')}
                        </button>
                      )}
                    </li>
                  ))
                )}
              </ul>

              <form onSubmit={handleReply} className="mt-3 space-y-2">
                <textarea
                  className="input w-full"
                  rows={2}
                  placeholder={t('teamWorkspace.communication.replyPlaceholder')}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                />
                <div className="flex items-center gap-2">
                  <label className="btn-ghost cursor-pointer py-1.5 text-xs">
                    {t('teamWorkspace.communication.attachDocument')}
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg"
                      onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    />
                  </label>
                  {file && <span className="text-xs text-ink-500">{file.name}</span>}
                  <button type="submit" className="btn-sentinel ml-auto" disabled={sending || !reply.trim()}>
                    {sending ? t('teamWorkspace.communication.sending') : tc('actions.send')}
                  </button>
                </div>
              </form>
            </>
          )}
        </div>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Report Approvals
// ---------------------------------------------------------------------------
function getNextActions(t: (key: string) => string): Record<string, { target: WorkflowStatus; label: string; tone: string }[]> {
  return {
    SUBMITTED: [{ target: 'UNDER_REVIEW', label: t('teamWorkspace.transition.actions.markUnderReview'), tone: 'btn-sentinel' }],
    RESUBMITTED: [{ target: 'UNDER_REVIEW', label: t('teamWorkspace.transition.actions.markUnderReview'), tone: 'btn-sentinel' }],
    UNDER_REVIEW: [
      { target: 'APPROVED', label: t('teamWorkspace.transition.actions.approve'), tone: 'btn-care' },
      { target: 'RETURNED_FOR_CORRECTION', label: t('teamWorkspace.transition.actions.returnForCorrection'), tone: 'btn-ghost' },
      { target: 'REJECTED', label: t('teamWorkspace.transition.actions.reject'), tone: 'btn-ghost' },
    ],
  }
}

function TransitionControls({
  currentStatus,
  onTransition,
}: {
  currentStatus: WorkflowStatus
  onTransition: (target: WorkflowStatus, comment: string) => Promise<void>
}) {
  const { t } = useTranslation('officer')
  const { t: tc } = useTranslation('common')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<WorkflowStatus | null>(null)
  const actions = getNextActions(t)[currentStatus] ?? []
  if (actions.length === 0) return null

  async function run(target: WorkflowStatus) {
    setBusy(target)
    try {
      await onTransition(target, comment)
      setComment('')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="mt-3 space-y-2 border-t border-ink-100 pt-3">
      <input
        className="input w-full text-sm"
        placeholder={t('teamWorkspace.transition.commentPlaceholder')}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        {actions.map((action) => (
          <button
            key={action.target}
            className={`${action.tone} py-1.5 text-xs`}
            disabled={busy !== null}
            onClick={() => void run(action.target)}
          >
            {busy === action.target ? tc('actions.saving') : action.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function ReportApprovalsSection() {
  const { t } = useTranslation('officer')
  const { reportApprovals, reportApprovalsLoading, reportApprovalsError, loadTeamReportApprovals, transitionReportApproval } =
    useWorkCommunicationStore()

  useEffect(() => {
    void loadTeamReportApprovals()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Card title={t('teamWorkspace.reports.title')}>
      {reportApprovalsLoading ? (
        <Loading label={t('teamWorkspace.reports.loading')} />
      ) : reportApprovalsError ? (
        <ErrorNote message={reportApprovalsError} onRetry={() => loadTeamReportApprovals()} />
      ) : reportApprovals.length === 0 ? (
        <Empty>{t('teamWorkspace.reports.empty')}</Empty>
      ) : (
        <div className="space-y-3">
          {reportApprovals.map((approval) => (
            <div key={approval.id} className="rounded-lg border border-ink-200 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-medium text-ink-800">
                    {approval.worker_name} — {approval.week_label}
                  </div>
                  <div className="text-xs text-ink-500">{approval.village_name}</div>
                </div>
                <StatusPill status={approval.status} />
              </div>
              <TransitionControls
                currentStatus={approval.status}
                onTransition={(target, comment) => transitionReportApproval(approval.id, target, comment)}
              />
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Corrections
// ---------------------------------------------------------------------------
function CorrectionsSection() {
  const { t } = useTranslation('officer')
  const { t: tc } = useTranslation('common')
  const { corrections, correctionsLoading, correctionsError, loadTeamCorrections, transitionCorrection } =
    useWorkCommunicationStore()

  useEffect(() => {
    void loadTeamCorrections()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Card title={t('teamWorkspace.corrections.title')}>
      {correctionsLoading ? (
        <Loading label={t('teamWorkspace.corrections.loading')} />
      ) : correctionsError ? (
        <ErrorNote message={correctionsError} onRetry={() => loadTeamCorrections()} />
      ) : corrections.length === 0 ? (
        <Empty>{t('teamWorkspace.corrections.empty')}</Empty>
      ) : (
        <div className="space-y-3">
          {corrections.map((correction) => (
            <div key={correction.id} className="rounded-lg border border-ink-200 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium text-ink-800">{correction.record_label}</div>
                <StatusPill status={correction.status} />
              </div>
              {Object.keys(correction.original_snapshot).length > 0 && (
                <div className="mt-2 rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-xs text-ink-700">
                  <div className="mb-1 font-medium text-ink-500">{t('teamWorkspace.corrections.original')}</div>
                  {Object.entries(correction.original_snapshot).map(([field, value]) => (
                    <div key={field}>
                      {translateSnapshotField(field, tc)}: <span className="font-medium">{value}</span>
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-2 text-sm text-ink-700">
                <span className="font-medium">{t('teamWorkspace.corrections.issueLabel')} </span>
                {correction.mistake_description}
              </p>
              <p className="mt-1 text-sm text-ink-700">
                <span className="font-medium">{t('teamWorkspace.corrections.proposedLabel')} </span>
                {correction.proposed_correction}
              </p>
              <TransitionControls
                currentStatus={correction.status}
                onTransition={(target, comment) => transitionCorrection(correction.id, target, comment)}
              />
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

export default function TeamWorkspacePage() {
  const { t } = useTranslation('officer')
  const [section, setSection] = useState<Section>('communication')
  const tabs: Array<{ id: Section; label: string }> = [
    { id: 'communication', label: t('teamWorkspace.communication.title') },
    { id: 'reports', label: t('teamWorkspace.reports.title') },
    { id: 'corrections', label: t('teamWorkspace.corrections.title') },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t('teamWorkspace.title')}</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {t('teamWorkspace.subtitle')}
        </p>
      </div>

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

      {section === 'communication' && <CommunicationSection />}
      {section === 'reports' && <ReportApprovalsSection />}
      {section === 'corrections' && <CorrectionsSection />}
    </div>
  )
}

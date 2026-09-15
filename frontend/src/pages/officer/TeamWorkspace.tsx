import { useEffect, useState, type FormEvent } from 'react'

import { Card, Empty, ErrorNote, Loading } from '@/components/ui'
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
const STATUS_LABELS: Record<WorkflowStatus, string> = {
  SUBMITTED: 'Submitted',
  UNDER_REVIEW: 'Under review',
  APPROVED: 'Approved',
  RETURNED_FOR_CORRECTION: 'Needs correction',
  RESUBMITTED: 'Resubmitted',
  REJECTED: 'Rejected',
}

function StatusPill({ status }: { status: WorkflowStatus }) {
  return <span className={`pill ${STATUS_STYLES[status]}`}>{STATUS_LABELS[status]}</span>
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
// Communication
// ---------------------------------------------------------------------------
function CommunicationSection() {
  const {
    threads, threadsLoading, threadsError, loadThreads,
    selectedWorkerId, threadWorkerName, threadMessages, threadLoading, threadError, openThread, replyToThread,
  } = useWorkCommunicationStore()
  const [reply, setReply] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)

  useEffect(() => {
    void loadThreads()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleReply(event: FormEvent) {
    event.preventDefault()
    if (!selectedWorkerId || !reply.trim()) return
    setSending(true)
    try {
      let attachment: string | undefined
      if (file) attachment = await readFileAsDataUri(file)
      await replyToThread(selectedWorkerId, { body: reply.trim(), attachment, attachment_filename: file?.name })
      setReply('')
      setFile(null)
    } finally {
      setSending(false)
    }
  }

  return (
    <Card title="Worker Messages">
      <div className="grid gap-4 md:grid-cols-[240px_minmax(0,1fr)]">
        <div>
          {threadsLoading ? (
            <Loading label="Loading…" />
          ) : threadsError ? (
            <ErrorNote message={threadsError} onRetry={loadThreads} />
          ) : threads.length === 0 ? (
            <Empty>No workers found.</Empty>
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
                      {thread.last_message_preview || 'No messages yet'}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          {!selectedWorkerId ? (
            <Empty>Select a worker to view the conversation.</Empty>
          ) : threadLoading ? (
            <Loading label="Loading conversation…" />
          ) : threadError ? (
            <ErrorNote message={threadError} onRetry={() => void openThread(selectedWorkerId)} />
          ) : (
            <>
              <div className="mb-2 text-sm font-medium text-ink-700">{threadWorkerName}</div>
              <ul className="max-h-[360px] space-y-3 overflow-y-auto rounded-md border border-ink-100 p-3">
                {threadMessages.length === 0 ? (
                  <Empty>No messages yet.</Empty>
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
                          {message.is_from_officer ? 'You' : threadWorkerName}
                        </span>
                        <span>{new Date(message.created_at).toLocaleString()}</span>
                      </div>
                      <p className="mt-1 whitespace-pre-line text-ink-800">{message.body}</p>
                      {message.has_attachment && (
                        <a
                          className="mt-2 inline-block text-xs text-sentinel-700 hover:underline"
                          href={`${import.meta.env.VITE_API_BASE_URL ?? '/api'}/work/messages/${message.id}/attachment/`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          📎 {message.attachment_filename || 'Attachment'}
                        </a>
                      )}
                    </li>
                  ))
                )}
              </ul>

              <form onSubmit={handleReply} className="mt-3 space-y-2">
                <textarea
                  className="input w-full"
                  rows={2}
                  placeholder="Reply…"
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                />
                <div className="flex items-center gap-2">
                  <label className="btn-ghost cursor-pointer py-1.5 text-xs">
                    Attach document
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg"
                      onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    />
                  </label>
                  {file && <span className="text-xs text-ink-500">{file.name}</span>}
                  <button type="submit" className="btn-sentinel ml-auto" disabled={sending || !reply.trim()}>
                    {sending ? 'Sending…' : 'Send'}
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
const NEXT_ACTIONS: Record<string, { target: WorkflowStatus; label: string; tone: string }[]> = {
  SUBMITTED: [{ target: 'UNDER_REVIEW', label: 'Mark Under Review', tone: 'btn-sentinel' }],
  RESUBMITTED: [{ target: 'UNDER_REVIEW', label: 'Mark Under Review', tone: 'btn-sentinel' }],
  UNDER_REVIEW: [
    { target: 'APPROVED', label: 'Approve', tone: 'btn-care' },
    { target: 'RETURNED_FOR_CORRECTION', label: 'Return for Correction', tone: 'btn-ghost' },
    { target: 'REJECTED', label: 'Reject', tone: 'btn-ghost' },
  ],
}

function TransitionControls({
  currentStatus,
  onTransition,
}: {
  currentStatus: WorkflowStatus
  onTransition: (target: WorkflowStatus, comment: string) => Promise<void>
}) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<WorkflowStatus | null>(null)
  const actions = NEXT_ACTIONS[currentStatus] ?? []
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
        placeholder="Comment (shown to the worker)"
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
            {busy === action.target ? 'Saving…' : action.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function ReportApprovalsSection() {
  const { reportApprovals, reportApprovalsLoading, reportApprovalsError, loadTeamReportApprovals, transitionReportApproval } =
    useWorkCommunicationStore()

  useEffect(() => {
    void loadTeamReportApprovals()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Card title="Report Approvals">
      {reportApprovalsLoading ? (
        <Loading label="Loading reports…" />
      ) : reportApprovalsError ? (
        <ErrorNote message={reportApprovalsError} onRetry={() => loadTeamReportApprovals()} />
      ) : reportApprovals.length === 0 ? (
        <Empty>No reports are currently awaiting approval.</Empty>
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
  const { corrections, correctionsLoading, correctionsError, loadTeamCorrections, transitionCorrection } =
    useWorkCommunicationStore()

  useEffect(() => {
    void loadTeamCorrections()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Card title="Correction Requests">
      {correctionsLoading ? (
        <Loading label="Loading correction requests…" />
      ) : correctionsError ? (
        <ErrorNote message={correctionsError} onRetry={() => loadTeamCorrections()} />
      ) : corrections.length === 0 ? (
        <Empty>No correction requests.</Empty>
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
                  <div className="mb-1 font-medium text-ink-500">Original</div>
                  {Object.entries(correction.original_snapshot).map(([field, value]) => (
                    <div key={field}>
                      {field}: <span className="font-medium">{value}</span>
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-2 text-sm text-ink-700">
                <span className="font-medium">Issue: </span>
                {correction.mistake_description}
              </p>
              <p className="mt-1 text-sm text-ink-700">
                <span className="font-medium">Proposed correction: </span>
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
  const [section, setSection] = useState<Section>('communication')
  const tabs: Array<{ id: Section; label: string }> = [
    { id: 'communication', label: 'Worker Messages' },
    { id: 'reports', label: 'Report Approvals' },
    { id: 'corrections', label: 'Correction Requests' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Team Workspace</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          Review messages, report approvals, and correction requests from your team.
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

import { create } from 'zustand'

import { api } from '@/services/api'
import type {
  CorrectableRecord,
  CorrectionRequest,
  MessageThreadResponse,
  OfficerWorkerThread,
  ReportApproval,
  SupervisorMessage,
  WorkflowStatus,
} from '@/types'

/**
 * Work & Communication client state — Supervisor Communication, Report
 * Approval Tracker, and Correction Requests, for both the worker's own
 * view and the Health Officer's review view. One store because these three
 * capabilities are one feature area on both sides of the relationship, not
 * three independent ones; every field here is populated only from a real
 * API response, never computed locally — the backend is the only place
 * that decides a status, derives an officer, or checks ownership.
 */
interface WorkCommunicationState {
  // --- Supervisor Communication (worker) --------------------------------
  officerName: string | null
  messages: SupervisorMessage[]
  messagesLoading: boolean
  messagesError: string | null
  messagesHasMore: boolean
  sendingMessage: boolean
  sendMessageError: string | null

  loadMyMessages: (search?: string) => Promise<void>
  sendMyMessage: (input: { subject?: string; body: string; attachment?: string; attachment_filename?: string }) => Promise<void>

  // --- Supervisor Communication (officer) --------------------------------
  threads: OfficerWorkerThread[]
  threadsLoading: boolean
  threadsError: string | null
  selectedWorkerId: number | null
  threadWorkerName: string | null
  threadMessages: SupervisorMessage[]
  threadLoading: boolean
  threadError: string | null

  loadThreads: () => Promise<void>
  openThread: (workerId: number, search?: string) => Promise<void>
  replyToThread: (workerId: number, input: { subject?: string; body: string; attachment?: string; attachment_filename?: string }) => Promise<void>

  // --- Report Approval Tracker --------------------------------------------
  reportApprovals: ReportApproval[]
  reportApprovalsLoading: boolean
  reportApprovalsError: string | null

  loadMyReportApprovals: (status?: WorkflowStatus) => Promise<void>
  loadTeamReportApprovals: (status?: WorkflowStatus) => Promise<void>
  transitionReportApproval: (id: number, targetStatus: WorkflowStatus, comment: string) => Promise<void>

  // --- Correction Requests -------------------------------------------------
  correctableRecords: CorrectableRecord[]
  correctableRecordsLoading: boolean
  corrections: CorrectionRequest[]
  correctionsLoading: boolean
  correctionsError: string | null
  submittingCorrection: boolean

  loadCorrectableRecords: () => Promise<void>
  loadMyCorrections: () => Promise<void>
  loadTeamCorrections: (status?: WorkflowStatus) => Promise<void>
  submitCorrection: (input: {
    record_type: string
    record_id: number
    mistake_description: string
    proposed_correction: string
  }) => Promise<CorrectionRequest>
  transitionCorrection: (id: number, targetStatus: WorkflowStatus, comment: string) => Promise<void>
}

export const useWorkCommunicationStore = create<WorkCommunicationState>((set, get) => ({
  officerName: null,
  messages: [],
  messagesLoading: false,
  messagesError: null,
  messagesHasMore: false,
  sendingMessage: false,
  sendMessageError: null,

  async loadMyMessages(search = '') {
    set({ messagesLoading: true, messagesError: null })
    try {
      const query = search ? `?q=${encodeURIComponent(search)}` : ''
      const result = await api.get<MessageThreadResponse>(`/work/messages/${query}`)
      set({
        officerName: result.officer_name ?? null,
        messages: result.messages,
        messagesHasMore: result.has_more,
        messagesLoading: false,
      })
    } catch (error) {
      set({
        messagesLoading: false,
        messagesError: error instanceof Error ? error.message : 'Unable to load messages.',
      })
    }
  },

  async sendMyMessage(input) {
    set({ sendingMessage: true, sendMessageError: null })
    try {
      await api.post('/work/messages/', input)
      set({ sendingMessage: false })
      await get().loadMyMessages()
    } catch (error) {
      set({
        sendingMessage: false,
        sendMessageError: error instanceof Error ? error.message : 'Unable to send this message.',
      })
      throw error
    }
  },

  threads: [],
  threadsLoading: false,
  threadsError: null,
  selectedWorkerId: null,
  threadWorkerName: null,
  threadMessages: [],
  threadLoading: false,
  threadError: null,

  async loadThreads() {
    set({ threadsLoading: true, threadsError: null })
    try {
      const result = await api.get<{ threads: OfficerWorkerThread[] }>('/officer/work/threads/')
      set({ threads: result.threads, threadsLoading: false })
    } catch (error) {
      set({
        threadsLoading: false,
        threadsError: error instanceof Error ? error.message : 'Unable to load conversations.',
      })
    }
  },

  async openThread(workerId, search = '') {
    set({ threadLoading: true, threadError: null, selectedWorkerId: workerId })
    try {
      const query = search ? `?q=${encodeURIComponent(search)}` : ''
      const result = await api.get<MessageThreadResponse>(`/officer/work/threads/${workerId}/messages/${query}`)
      set({
        threadWorkerName: result.worker_name ?? null,
        threadMessages: result.messages,
        threadLoading: false,
      })
      // The unread count on the overview list is now stale for this
      // worker (opening the thread just marked their messages read) —
      // refresh it rather than let the badge lie until the next visit.
      void get().loadThreads()
    } catch (error) {
      set({
        threadLoading: false,
        threadError: error instanceof Error ? error.message : 'Unable to load this conversation.',
      })
    }
  },

  async replyToThread(workerId, input) {
    await api.post(`/officer/work/threads/${workerId}/messages/`, input)
    await get().openThread(workerId)
  },

  reportApprovals: [],
  reportApprovalsLoading: false,
  reportApprovalsError: null,

  async loadMyReportApprovals(status) {
    set({ reportApprovalsLoading: true, reportApprovalsError: null })
    try {
      const query = status ? `?status=${status}` : ''
      const result = await api.get<{ approvals: ReportApproval[] }>(`/work/report-approvals/${query}`)
      set({ reportApprovals: result.approvals, reportApprovalsLoading: false })
    } catch (error) {
      set({
        reportApprovalsLoading: false,
        reportApprovalsError: error instanceof Error ? error.message : 'Unable to load reports.',
      })
    }
  },

  async loadTeamReportApprovals(status) {
    set({ reportApprovalsLoading: true, reportApprovalsError: null })
    try {
      const query = status ? `?status=${status}` : ''
      const result = await api.get<{ approvals: ReportApproval[] }>(`/officer/work/report-approvals/${query}`)
      set({ reportApprovals: result.approvals, reportApprovalsLoading: false })
    } catch (error) {
      set({
        reportApprovalsLoading: false,
        reportApprovalsError: error instanceof Error ? error.message : 'Unable to load reports.',
      })
    }
  },

  async transitionReportApproval(id, targetStatus, comment) {
    await api.post(`/officer/work/report-approvals/${id}/transition/`, { status: targetStatus, comment })
    await get().loadTeamReportApprovals()
  },

  correctableRecords: [],
  correctableRecordsLoading: false,
  corrections: [],
  correctionsLoading: false,
  correctionsError: null,
  submittingCorrection: false,

  async loadCorrectableRecords() {
    set({ correctableRecordsLoading: true })
    try {
      const result = await api.get<{ records: CorrectableRecord[] }>('/work/correctable-records/')
      set({ correctableRecords: result.records, correctableRecordsLoading: false })
    } catch {
      set({ correctableRecordsLoading: false })
    }
  },

  async loadMyCorrections() {
    set({ correctionsLoading: true, correctionsError: null })
    try {
      const result = await api.get<{ corrections: CorrectionRequest[] }>('/work/corrections/')
      set({ corrections: result.corrections, correctionsLoading: false })
    } catch (error) {
      set({
        correctionsLoading: false,
        correctionsError: error instanceof Error ? error.message : 'Unable to load correction requests.',
      })
    }
  },

  async loadTeamCorrections(status) {
    set({ correctionsLoading: true, correctionsError: null })
    try {
      const query = status ? `?status=${status}` : ''
      const result = await api.get<{ corrections: CorrectionRequest[] }>(`/officer/work/corrections/${query}`)
      set({ corrections: result.corrections, correctionsLoading: false })
    } catch (error) {
      set({
        correctionsLoading: false,
        correctionsError: error instanceof Error ? error.message : 'Unable to load correction requests.',
      })
    }
  },

  async submitCorrection(input) {
    set({ submittingCorrection: true })
    try {
      const created = await api.post<CorrectionRequest>('/work/corrections/', input)
      set({ submittingCorrection: false })
      await get().loadMyCorrections()
      return created
    } catch (error) {
      set({ submittingCorrection: false })
      throw error
    }
  },

  async transitionCorrection(id, targetStatus, comment) {
    await api.post(`/officer/work/corrections/${id}/transition/`, { status: targetStatus, comment })
    await get().loadTeamCorrections()
  },
}))

import { create } from 'zustand'

import { api } from '@/services/api'
import type {
  ActionPlan,
  FieldOpsMeta,
  FieldOpsSummary,
  FieldVisit,
  Inspection,
  InspectionChecklistResponse,
} from '@/types'

/**
 * Field Operations client state — Field Visits, Inspections, and Action
 * Plans. One store for the whole feature, matching this project's
 * established convention (see `store/workCommunication.ts`,
 * `store/simulation.ts`): every field is populated only from a real API
 * response, never computed client-side.
 */
interface FieldOperationsState {
  summary: FieldOpsSummary | null
  summaryLoading: boolean
  meta: FieldOpsMeta | null

  loadSummary: () => Promise<void>
  loadMeta: () => Promise<void>

  // --- Field Visits --------------------------------------------------------
  visits: FieldVisit[]
  visitsLoading: boolean
  visitsError: string | null
  selectedVisit: FieldVisit | null

  loadVisits: (filters?: Record<string, string>) => Promise<void>
  createVisit: (input: Record<string, unknown>) => Promise<FieldVisit>
  selectVisit: (id: number) => Promise<void>
  clearSelectedVisit: () => void
  startVisit: (id: number) => Promise<void>
  completeVisit: (id: number, outcome: Record<string, unknown>) => Promise<void>
  cancelVisit: (id: number) => Promise<void>

  // --- Inspections -----------------------------------------------------------
  inspections: Inspection[]
  inspectionsLoading: boolean
  inspectionsError: string | null
  selectedInspection: Inspection | null

  loadInspections: (filters?: Record<string, string>) => Promise<void>
  createInspection: (village: number, inspectionType: string) => Promise<Inspection>
  selectInspection: (id: number) => Promise<void>
  clearSelectedInspection: () => void
  startInspection: (id: number) => Promise<void>
  completeInspection: (id: number, summaryRemarks: string) => Promise<void>
  updateChecklistItem: (
    inspectionId: number,
    responseId: number,
    status: string,
    remarks: string,
  ) => Promise<InspectionChecklistResponse>
  uploadInspectionAttachment: (inspectionId: number, file: string, filename: string) => Promise<void>

  // --- Action Plans ----------------------------------------------------------
  actionPlans: ActionPlan[]
  actionPlansLoading: boolean
  actionPlansError: string | null

  loadActionPlans: (filters?: Record<string, string>) => Promise<void>
  createActionPlan: (input: Record<string, unknown>) => Promise<ActionPlan>
  updateActionPlanProgress: (id: number, newPercentage: number, note: string) => Promise<void>
}

function toQuery(filters?: Record<string, string>): string {
  if (!filters) return ''
  const entries = Object.entries(filters).filter(([, value]) => value)
  if (entries.length === 0) return ''
  return `?${new URLSearchParams(entries).toString()}`
}

export const useFieldOperationsStore = create<FieldOperationsState>((set, get) => ({
  summary: null,
  summaryLoading: false,
  meta: null,

  async loadSummary() {
    set({ summaryLoading: true })
    try {
      const summary = await api.get<FieldOpsSummary>('/officer/field-operations/summary/')
      set({ summary, summaryLoading: false })
    } catch {
      set({ summaryLoading: false })
    }
  },

  async loadMeta() {
    try {
      const meta = await api.get<FieldOpsMeta>('/officer/field-operations/meta/')
      set({ meta })
    } catch {
      // The relevant forms show their own "unable to load" state via meta === null.
    }
  },

  visits: [],
  visitsLoading: false,
  visitsError: null,
  selectedVisit: null,

  async loadVisits(filters) {
    set({ visitsLoading: true, visitsError: null })
    try {
      const visits = await api.get<FieldVisit[]>(`/officer/field-visits/${toQuery(filters)}`)
      set({ visits, visitsLoading: false })
    } catch (error) {
      set({ visitsLoading: false, visitsError: error instanceof Error ? error.message : 'Unable to load field visits.' })
    }
  },

  async createVisit(input) {
    const visit = await api.post<FieldVisit>('/officer/field-visits/', input)
    await get().loadVisits()
    void get().loadSummary()
    return visit
  },

  async selectVisit(id) {
    const visit = await api.get<FieldVisit>(`/officer/field-visits/${id}/`)
    set({ selectedVisit: visit })
  },

  clearSelectedVisit: () => set({ selectedVisit: null }),

  async startVisit(id) {
    const visit = await api.post<FieldVisit>(`/officer/field-visits/${id}/start/`)
    set({ selectedVisit: visit })
    await get().loadVisits()
  },

  async completeVisit(id, outcome) {
    const visit = await api.post<FieldVisit>(`/officer/field-visits/${id}/complete/`, outcome)
    set({ selectedVisit: visit })
    await get().loadVisits()
    void get().loadSummary()
  },

  async cancelVisit(id) {
    const visit = await api.post<FieldVisit>(`/officer/field-visits/${id}/cancel/`)
    set({ selectedVisit: visit })
    await get().loadVisits()
    void get().loadSummary()
  },

  inspections: [],
  inspectionsLoading: false,
  inspectionsError: null,
  selectedInspection: null,

  async loadInspections(filters) {
    set({ inspectionsLoading: true, inspectionsError: null })
    try {
      const inspections = await api.get<Inspection[]>(`/officer/inspections/${toQuery(filters)}`)
      set({ inspections, inspectionsLoading: false })
    } catch (error) {
      set({
        inspectionsLoading: false,
        inspectionsError: error instanceof Error ? error.message : 'Unable to load inspections.',
      })
    }
  },

  async createInspection(village, inspectionType) {
    const inspection = await api.post<Inspection>('/officer/inspections/', {
      village, inspection_type: inspectionType,
    })
    await get().loadInspections()
    void get().loadSummary()
    return inspection
  },

  async selectInspection(id) {
    const inspection = await api.get<Inspection>(`/officer/inspections/${id}/`)
    set({ selectedInspection: inspection })
  },

  clearSelectedInspection: () => set({ selectedInspection: null }),

  async startInspection(id) {
    const inspection = await api.post<Inspection>(`/officer/inspections/${id}/start/`)
    set({ selectedInspection: inspection })
    await get().loadInspections()
  },

  async completeInspection(id, summaryRemarks) {
    const inspection = await api.post<Inspection>(`/officer/inspections/${id}/complete/`, {
      summary_remarks: summaryRemarks,
    })
    set({ selectedInspection: inspection })
    await get().loadInspections()
    void get().loadSummary()
  },

  async updateChecklistItem(inspectionId, responseId, statusValue, remarks) {
    const response = await api.post<InspectionChecklistResponse>(
      `/officer/inspections/${inspectionId}/responses/${responseId}/`,
      { status: statusValue, remarks },
    )
    await get().selectInspection(inspectionId)
    return response
  },

  async uploadInspectionAttachment(inspectionId, file, filename) {
    await api.post(`/officer/inspections/${inspectionId}/attachments/`, { file, filename })
    await get().selectInspection(inspectionId)
  },

  actionPlans: [],
  actionPlansLoading: false,
  actionPlansError: null,

  async loadActionPlans(filters) {
    set({ actionPlansLoading: true, actionPlansError: null })
    try {
      const actionPlans = await api.get<ActionPlan[]>(`/officer/action-plans/${toQuery(filters)}`)
      set({ actionPlans, actionPlansLoading: false })
    } catch (error) {
      set({
        actionPlansLoading: false,
        actionPlansError: error instanceof Error ? error.message : 'Unable to load action plans.',
      })
    }
  },

  async createActionPlan(input) {
    const plan = await api.post<ActionPlan>('/officer/action-plans/', input)
    await get().loadActionPlans()
    void get().loadSummary()
    return plan
  },

  async updateActionPlanProgress(id, newPercentage, note) {
    await api.post(`/officer/action-plans/${id}/progress/`, { new_percentage: newPercentage, update_note: note })
    await get().loadActionPlans()
    void get().loadSummary()
  },
}))

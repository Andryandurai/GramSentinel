/**
 * Offline Community Reporting — connectivity + sync state.
 *
 * Kept as its own small store (mirrors `store/simulation.ts`'s pattern of
 * one dedicated store per self-contained feature) rather than folded into
 * `store/auth.ts`, since sync state has nothing to do with who is signed in.
 *
 * The queue processor here is deliberately the only one: `syncPendingReports`
 * is not re-entered while a sync is already running (`get().status ===
 * 'syncing'` guards it), so a manual "Sync now" click and the automatic
 * `online` event can never race each other into two competing loops.
 */

import { create } from 'zustand'

import { ApiError, api } from '@/services/api'
import {
  type QueuedReport,
  type QueuedReportPayload,
  enqueueReport,
  listReports,
  updateReport,
} from '@/services/offlineQueue'

interface CommunityReportApiResponse {
  report: { id: number }
}

type ConnectivityStatus = 'online' | 'offline' | 'syncing'

interface OfflineSyncState {
  status: ConnectivityStatus
  reports: QueuedReport[]
  initialised: boolean
  refresh: () => Promise<void>
  enqueue: (
    payload: QueuedReportPayload,
    villageName: string,
  ) => Promise<QueuedReport>
  syncNow: () => Promise<void>
  retry: (clientId: string) => Promise<void>
  init: () => void
}

/** A network-level failure (no response reached at all) is the only case
 *  that should keep a report queued rather than mark it failed — that is
 *  exactly `ApiError` with `status === 0`, the shape `services/api.ts`
 *  already throws when `fetch` itself throws. A real 4xx/5xx from the
 *  server (bad data, permission, etc.) is a genuine failure the worker
 *  should see, not something to retry forever unattended. */
function isConnectivityFailure(error: unknown): boolean {
  return error instanceof ApiError && error.status === 0
}

function humaneError(error: unknown): string {
  if (isConnectivityFailure(error)) {
    return 'Could not connect to the server. Your report is still saved on this device.'
  }
  if (error instanceof Error) return error.message
  return 'Could not sync this report.'
}

export const useOfflineSync = create<OfflineSyncState>((set, get) => ({
  status: typeof navigator !== 'undefined' && navigator.onLine === false ? 'offline' : 'online',
  reports: [],
  initialised: false,

  async refresh() {
    const reports = await listReports()
    set({ reports })
  },

  async enqueue(payload, villageName) {
    const record = await enqueueReport(payload, villageName)
    await get().refresh()
    // Best-effort: try to sync right away in case connectivity is actually
    // fine and the worker just hasn't been marked online yet.
    if (get().status !== 'offline') void get().syncNow()
    return record
  },

  async syncNow() {
    if (get().status === 'syncing') return
    const pending = get().reports.filter(
      (r) => r.status === 'pending' || r.status === 'failed',
    )
    if (pending.length === 0) return

    set({ status: 'syncing' })

    for (const report of pending) {
      await updateReport(report.client_id, {
        status: 'syncing',
        last_attempt_at: new Date().toISOString(),
      })
      await get().refresh()

      try {
        const response = await api.post<CommunityReportApiResponse>(
          '/community-reports/',
          {
            ...report.payload,
            idempotency_key: report.client_id,
            client_created_at: report.created_at,
          },
        )
        await updateReport(report.client_id, {
          status: 'synced',
          synced_at: new Date().toISOString(),
          server_report_id: response.report.id,
          last_error: null,
        })
      } catch (error) {
        if (isConnectivityFailure(error)) {
          // Still offline in practice — stop the whole batch rather than
          // burning through retries for every remaining report in a row.
          await updateReport(report.client_id, {
            status: 'pending',
            last_error: humaneError(error),
          })
          await get().refresh()
          set({ status: 'offline' })
          return
        }
        await updateReport(report.client_id, {
          status: 'failed',
          retry_count: report.retry_count + 1,
          last_error: humaneError(error),
        })
      }
      await get().refresh()
    }

    set({ status: typeof navigator !== 'undefined' && navigator.onLine === false ? 'offline' : 'online' })
  },

  async retry(clientId) {
    await updateReport(clientId, { status: 'pending', last_error: null })
    await get().refresh()
    void get().syncNow()
  },

  init() {
    if (get().initialised) return
    set({ initialised: true })
    void get().refresh().then(() => {
      if (get().status !== 'offline') void get().syncNow()
    })

    if (typeof window === 'undefined') return
    window.addEventListener('online', () => {
      set({ status: 'online' })
      void get().syncNow()
    })
    window.addEventListener('offline', () => {
      set({ status: 'offline' })
    })
  },
}))

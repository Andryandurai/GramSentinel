/**
 * Connectivity state and automatic synchronisation of queued reports.
 *
 * The guarantee this hook exists to provide: a report a worker completed
 * without connectivity reaches GramSentinel exactly once, and stays on the
 * device until it does.
 *
 * Three things it deliberately does not do:
 *
 *   - It never analyses a queued report. No triage, no severity, no alert is
 *     produced on the device. A queued report is inert text until the backend
 *     receives it and runs the existing pipeline over it.
 *   - It never deletes a report it failed to send. Failure moves a report back
 *     to pending with the error recorded, never out of the queue.
 *   - It never rewrites the original creation time. The worker's own record of
 *     when they observed something survives however long the sync takes.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, api } from '@/services/api'
import { offlineQueue } from '@/services/offlineQueue'
import type { QueuedReport, SyncPhase } from '@/types'

/** `navigator.onLine` is a weak signal — it reports whether an interface is up,
 *  not whether the server is reachable, which on a rural connection is exactly
 *  the distinction that matters. It is used to *trigger* a sync attempt; the
 *  attempt itself is what establishes reachability. */
function browserOnline(): boolean {
  return typeof navigator === 'undefined' ? true : navigator.onLine !== false
}

/** A failure that means "the request never arrived" — worth retrying as-is.
 *
 *  `ApiError` with status 0 is what the api layer raises when fetch itself
 *  rejected. A 5xx is the server failing to process a request that did arrive;
 *  also retryable, since nothing was stored. A 4xx is not: the report is
 *  malformed or unauthorised, and resending it unchanged will fail forever. */
function isRetryable(error: unknown): boolean {
  if (error instanceof ApiError) return error.status === 0 || error.status >= 500
  return true
}

export interface OfflineSyncState {
  online: boolean
  phase: SyncPhase
  pending: QueuedReport[]
  pendingCount: number
  /** Reports that failed for a reason retrying will not fix. Surfaced so a
   *  worker is told rather than left watching a counter that never falls. */
  blocked: QueuedReport[]
  lastSyncedAt: string | null
  lastError: string | null
  syncNow: () => Promise<void>
  enqueue: (report: QueuedReport) => void
  discard: (uid: string) => void
}

export function useOfflineSync(): OfflineSyncState {
  const [online, setOnline] = useState(browserOnline)
  const [pending, setPending] = useState<QueuedReport[]>(() => offlineQueue.all())
  const [phase, setPhase] = useState<SyncPhase>('IDLE')
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)

  // Guards a sync already in flight. Without it, the online event and the
  // interval below can both start a pass and deliver every report twice —
  // which the backend would deduplicate, but the point is not to rely on that
  // for something this side can simply not do.
  const syncing = useRef(false)

  const syncNow = useCallback(async () => {
    if (syncing.current) return

    const queued = offlineQueue.all()
    if (queued.length === 0) {
      setPending([])
      setPhase('IDLE')
      return
    }

    syncing.current = true
    setPhase('SYNCING')
    setLastError(null)

    let delivered = 0
    let failure: string | null = null

    // Oldest first: the report that has been waiting longest is the one the
    // officer is most overdue to see.
    for (const report of [...queued].sort((a, b) =>
      a.client_created_at.localeCompare(b.client_created_at),
    )) {
      try {
        await api.post('/community-reports/', {
          ...report.payload,
          client_report_uid: report.client_report_uid,
          client_created_at: report.client_created_at,
          captured_offline: report.captured_offline,
        })
        // Confirmed stored. A 200 carrying `duplicate: true` lands here too,
        // and should: the backend is telling us this report is already safely
        // stored, which is precisely when the device should stop holding it.
        setPending(offlineQueue.remove(report.client_report_uid))
        delivered += 1
      } catch (error) {
        const message =
          error instanceof Error ? error.message : 'Could not sync this report.'
        failure = message
        setPending(offlineQueue.markFailed(report.client_report_uid, message))

        if (!isRetryable(error)) {
          // Permanently rejected — leave it queued and visible, but stop
          // hammering the server with it. The remaining reports still go.
          continue
        }
        // The connection dropped again. Stop the pass and keep the rest
        // queued; the next online event or tick will resume.
        break
      }
    }

    syncing.current = false

    if (delivered > 0) setLastSyncedAt(new Date().toISOString())
    const remaining = offlineQueue.count()

    if (remaining === 0) {
      setPhase('SYNCED')
    } else {
      setPhase(failure ? 'ERROR' : 'IDLE')
      setLastError(failure)
    }
  }, [])

  // --- connectivity transitions -----------------------------------------
  useEffect(() => {
    function goOnline() {
      setOnline(true)
      void syncNow()
    }
    function goOffline() {
      setOnline(false)
      setPhase('IDLE')
    }

    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [syncNow])

  // A retry timer as well as the online event, because the event only fires on
  // an interface transition. A connection that was never reported as down but
  // is simply not working — the common rural case — produces no event at all,
  // and without this the queue would sit untouched until the worker reloaded.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (browserOnline() && offlineQueue.count() > 0) void syncNow()
    }, 30_000)
    return () => window.clearInterval(timer)
  }, [syncNow])

  // One attempt on mount, so reports queued in a previous session go as soon
  // as the worker opens the app with a connection.
  useEffect(() => {
    if (browserOnline() && offlineQueue.count() > 0) void syncNow()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const enqueue = useCallback(
    (report: QueuedReport) => {
      setPending(offlineQueue.enqueue(report))
      if (browserOnline()) void syncNow()
    },
    [syncNow],
  )

  /** Remove a report the worker has explicitly chosen to abandon. The only
   *  path by which an unsynced report leaves the device, and it requires a
   *  deliberate act by the person who wrote it. */
  const discard = useCallback((uid: string) => {
    setPending(offlineQueue.remove(uid))
  }, [])

  return {
    online,
    phase,
    pending,
    pendingCount: pending.length,
    blocked: pending.filter(
      (r) => r.attempts > 0 && r.last_error !== null && r.attempts >= 3,
    ),
    lastSyncedAt,
    lastError,
    syncNow,
    enqueue,
    discard,
  }
}

/**
 * Durable storage for community reports captured without connectivity.
 *
 * A queued report is the only copy of something a health worker observed in a
 * village. It is written to `localStorage` the moment the worker submits, and
 * it is removed at exactly one point: when the backend has confirmed it was
 * stored. Not when a request is sent, not when a response arrives with an
 * error — only on confirmation. Everything else here follows from that.
 *
 * Why `localStorage` rather than IndexedDB: a report is a few hundred bytes of
 * JSON and the queue is bounded (see MAX_QUEUED). Synchronous reads and writes
 * mean a report cannot be lost in an awaited write that never settled because
 * the worker closed the tab or the device slept — which is the realistic
 * failure on the hardware this runs on. IndexedDB would be the right answer if
 * reports carried photos.
 *
 * Every access is wrapped: Safari private mode throws on write, and a worker
 * losing the app to an exception while offline is worse than a degraded queue.
 */

import type { QueuedReport } from '@/types'

const QUEUE_KEY = 'gs.offline.reports.v1'

/** Bound the queue so a device that has been offline for weeks cannot fill its
 *  storage quota and start throwing on the write that matters. Oldest-first is
 *  deliberate: if something must be refused it should be the new report, while
 *  the worker is still present to be told, rather than silently dropping an
 *  older one they believe is safely stored. */
const MAX_QUEUED = 200

export class QueueFullError extends Error {
  constructor() {
    super(
      `This device is holding ${MAX_QUEUED} reports that have not reached ` +
        `GramSentinel yet. Connect to the internet to sync before adding more.`,
    )
    this.name = 'QueueFullError'
  }
}

function read(): QueuedReport[] {
  try {
    const raw = localStorage.getItem(QUEUE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as QueuedReport[]) : []
  } catch {
    // Corrupt or unreadable storage. Returning [] keeps the app usable; the
    // queue is not overwritten here, so a later successful read can still
    // recover the reports.
    return []
  }
}

function write(reports: QueuedReport[]): boolean {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(reports))
    return true
  } catch {
    return false
  }
}

export const offlineQueue = {
  all: read,

  count: () => read().length,

  /** Store a report. Throws if the queue is full, so the worker is told
   *  rather than believing an observation was saved when it was not. */
  enqueue(report: QueuedReport): QueuedReport[] {
    const existing = read()
    if (existing.length >= MAX_QUEUED) throw new QueueFullError()

    // Same uid twice means the same report — re-saving must not create a
    // second queue entry any more than it creates a second row server-side.
    const next = [
      ...existing.filter(
        (r) => r.client_report_uid !== report.client_report_uid,
      ),
      report,
    ]
    if (!write(next)) {
      throw new Error(
        'This device could not save the report locally. Check available ' +
          'storage before continuing.',
      )
    }
    return next
  },

  /** Remove a report. Called only once the backend has confirmed storage. */
  remove(uid: string): QueuedReport[] {
    const next = read().filter((r) => r.client_report_uid !== uid)
    write(next)
    return next
  },

  /** Record a failed attempt without discarding the report.
   *
   *  A failure is a reason to try again later, never a reason to delete — the
   *  observation still exists whether or not the network does. */
  markFailed(uid: string, error: string): QueuedReport[] {
    const next = read().map((r) =>
      r.client_report_uid === uid
        ? {
            ...r,
            attempts: r.attempts + 1,
            last_error: error,
            last_attempt_at: new Date().toISOString(),
          }
        : r,
    )
    write(next)
    return next
  },

  capacity: () => MAX_QUEUED,
}

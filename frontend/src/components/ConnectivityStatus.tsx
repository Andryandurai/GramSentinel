/**
 * Connectivity and sync state for the worker portal.
 *
 * A worker needs to answer one question at a glance: *is what I just recorded
 * safe?* So the pending count is always shown when it is non-zero — including
 * while online and syncing — rather than only in an offline state.
 */

import type { OfflineSyncState } from '@/hooks/useOfflineSync'

function Dot({ tone }: { tone: 'online' | 'offline' | 'busy' }) {
  const colour =
    tone === 'online'
      ? 'bg-care-600'
      : tone === 'busy'
        ? 'bg-amber-500 animate-pulse'
        : 'bg-ink-400'
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${colour}`}
      aria-hidden="true"
    />
  )
}

export function ConnectivityStatus({ sync }: { sync: OfflineSyncState }) {
  const { online, phase, pendingCount, lastError } = sync

  const syncing = phase === 'SYNCING'
  const tone = syncing ? 'busy' : online ? 'online' : 'offline'

  let headline: string
  if (syncing) {
    headline = `Syncing ${pendingCount} report${pendingCount === 1 ? '' : 's'}…`
  } else if (!online) {
    headline = 'Offline'
  } else {
    headline = 'Online'
  }

  let detail: string
  if (syncing) {
    detail = 'Sending to GramSentinel. Keep this page open.'
  } else if (pendingCount > 0) {
    detail = `${pendingCount} report${
      pendingCount === 1 ? '' : 's'
    } waiting to sync — saved on this device.`
  } else if (online) {
    detail = 'All reports synced.'
  } else {
    detail =
      'Reports you complete now are saved on this device and sent automatically ' +
      'when the connection returns.'
  }

  const frame = !online
    ? 'border-ink-300 bg-ink-50'
    : pendingCount > 0
      ? 'border-amber-300 bg-amber-50'
      : 'border-care-200 bg-care-50'

  return (
    <section
      className={`rounded-lg border px-4 py-3 ${frame}`}
      // Announced to screen readers when it changes: a worker who has just
      // submitted needs to hear that it was queued, not only see it.
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Dot tone={tone} />
        <span className="text-sm font-semibold">{headline}</span>

        {pendingCount === 0 && online && !syncing && (
          <span className="text-sm text-care-700">✓ All reports synced</span>
        )}

        {pendingCount > 0 && !syncing && online && (
          <button
            type="button"
            className="btn-ghost ml-auto text-xs"
            onClick={() => void sync.syncNow()}
          >
            Retry now
          </button>
        )}
      </div>

      <p className="mt-1 text-xs text-ink-600">{detail}</p>

      {lastError && pendingCount > 0 && (
        <p className="mt-1 text-xs text-ink-600">
          Last attempt failed: {lastError} Nothing was lost — these reports stay
          on this device and will be retried.
        </p>
      )}
    </section>
  )
}

/** The queue itself, so a worker can see exactly what is still on the device
 *  rather than trusting a number. */
export function PendingReports({ sync }: { sync: OfflineSyncState }) {
  if (sync.pendingCount === 0) return null

  return (
    <div className="rounded-lg border border-ink-200 bg-white px-4 py-3">
      <div className="text-sm font-semibold">
        Waiting to sync ({sync.pendingCount})
      </div>
      <ul className="mt-2 space-y-2">
        {sync.pending.map((report) => (
          <li
            key={report.client_report_uid}
            className="rounded-md border border-ink-200 px-3 py-2 text-xs"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{report.village_name}</span>
              <span className="font-mono text-ink-400">
                {report.week_label}
              </span>
              <span className="pill ml-auto bg-amber-100 text-amber-800">
                Pending sync
              </span>
            </div>
            <p className="mt-1 text-ink-600">
              Recorded {new Date(report.client_created_at).toLocaleString()}
              {report.attempts > 0 && ` · ${report.attempts} attempt(s)`}
            </p>
            {report.last_error && (
              <p className="mt-1 text-ink-500">{report.last_error}</p>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-400">
        These are stored on this device only. They have not been analysed and no
        alert has been raised — that happens after they reach GramSentinel.
      </p>
    </div>
  )
}

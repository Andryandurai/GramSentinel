import { useEffect } from 'react'

import { useOfflineSync } from '@/store/offlineSync'

/**
 * Compact connectivity/sync status for the Health Worker Portal header.
 * Plain, worker-facing language only — no mention of IndexedDB, HTTP
 * status codes, retries or any other implementation detail.
 */
export function SyncStatusIndicator() {
  const { status, reports, init } = useOfflineSync()

  useEffect(() => {
    init()
  }, [init])

  const pending = reports.filter((r) => r.status === 'pending' || r.status === 'failed')
  const failed = reports.filter((r) => r.status === 'failed')

  if (status === 'syncing') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs text-white">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-300" aria-hidden="true" />
        Syncing {pending.length} report{pending.length === 1 ? '' : 's'}…
      </span>
    )
  }

  if (status === 'offline') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs text-white">
        <span className="h-1.5 w-1.5 rounded-full bg-red-300" aria-hidden="true" />
        Offline
        {pending.length > 0 ? ` — ${pending.length} report${pending.length === 1 ? '' : 's'} waiting to sync` : ''}
      </span>
    )
  }

  if (failed.length > 0) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs text-white">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-300" aria-hidden="true" />
        {failed.length} report{failed.length === 1 ? '' : 's'} could not sync
      </span>
    )
  }

  if (pending.length > 0) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs text-white">
        <span className="h-1.5 w-1.5 rounded-full bg-care-300" aria-hidden="true" />
        {pending.length} report{pending.length === 1 ? '' : 's'} waiting to sync
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs text-white">
      <span className="h-1.5 w-1.5 rounded-full bg-care-300" aria-hidden="true" />
      Online
    </span>
  )
}

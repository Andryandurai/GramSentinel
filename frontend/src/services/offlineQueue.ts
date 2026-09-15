/**
 * Offline Community Reporting — local persistence layer.
 *
 * Plain IndexedDB, no added dependency: the project has no offline/PWA
 * infrastructure yet (checked — no Dexie/localForage/service worker in
 * package.json), and native IndexedDB is enough for one small queue of
 * structured records. `localStorage` was deliberately not used — a
 * community report is structured data or a worker could lose it on the
 * many `JSON.parse`/size-limit edges `localStorage` doesn't guard against.
 *
 * This module only ever stores a `CommunityReport` submission's own fields
 * (village, week, period, entries, notes) — the exact same shape the online
 * form already sends. It must never grow to carry patient-identifying
 * fields; there is no code path here that could, since it only wraps
 * whatever `CommunityReportPage` already builds for the online endpoint.
 */

export type QueuedReportStatus = 'pending' | 'syncing' | 'synced' | 'failed'

export interface QueuedReportPayload {
  village: number
  week_label: string
  period_start: string
  period_end: string
  unusual_observation: boolean
  notes: string
  entries: Array<{ category: string; case_count: number; description: string }>
}

export interface QueuedReport {
  client_id: string
  payload: QueuedReportPayload
  village_name: string
  /** When the worker actually filled this in — never overwritten by sync. */
  created_at: string
  queued_at: string
  status: QueuedReportStatus
  retry_count: number
  last_attempt_at: string | null
  last_error: string | null
  synced_at: string | null
  server_report_id: number | null
}

const DB_NAME = 'gramsentinel-offline'
const DB_VERSION = 1
const STORE = 'community_reports'

let dbPromise: Promise<IDBDatabase> | null = null

function openDB(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB is not available in this browser.'))
      return
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'client_id' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Could not open offline storage.'))
  })
  return dbPromise
}

function withStore<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return openDB().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(STORE, mode)
        const request = run(tx.objectStore(STORE))
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error ?? new Error('Offline storage error.'))
      }),
  )
}

function newClientId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  // Fallback for older WebViews some field devices may still run.
  return `offline-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/** Queue one report. Returns immediately — the caller shows "saved on this
 *  device" without waiting for any network activity. */
export async function enqueueReport(
  payload: QueuedReportPayload,
  villageName: string,
): Promise<QueuedReport> {
  const now = new Date().toISOString()
  const record: QueuedReport = {
    client_id: newClientId(),
    payload,
    village_name: villageName,
    created_at: now,
    queued_at: now,
    status: 'pending',
    retry_count: 0,
    last_attempt_at: null,
    last_error: null,
    synced_at: null,
    server_report_id: null,
  }
  await withStore('readwrite', (store) => store.add(record))
  return record
}

export async function listReports(): Promise<QueuedReport[]> {
  const all = await withStore<QueuedReport[]>('readonly', (store) => store.getAll())
  return all.sort((a, b) => a.created_at.localeCompare(b.created_at))
}

export async function updateReport(
  clientId: string,
  patch: Partial<QueuedReport>,
): Promise<void> {
  const db = await openDB()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    const store = tx.objectStore(STORE)
    const getRequest = store.get(clientId)
    getRequest.onsuccess = () => {
      const existing = getRequest.result as QueuedReport | undefined
      if (!existing) {
        resolve()
        return
      }
      const putRequest = store.put({ ...existing, ...patch })
      putRequest.onsuccess = () => resolve()
      putRequest.onerror = () => reject(putRequest.error ?? new Error('Offline storage error.'))
    }
    getRequest.onerror = () => reject(getRequest.error ?? new Error('Offline storage error.'))
  })
}

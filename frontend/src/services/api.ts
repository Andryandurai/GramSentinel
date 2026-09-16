/**
 * Thin fetch wrapper with JWT attachment and one-shot refresh on 401.
 *
 * Route protection in this app is a usability measure only — the backend
 * enforces every role check server-side.
 */

export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

const ACCESS_KEY = 'gs.access'
const REFRESH_KEY = 'gs.refresh'

export class ApiError extends Error {
  status: number
  payload: unknown

  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

export const tokens = {
  access: () => localStorage.getItem(ACCESS_KEY),
  refresh: () => localStorage.getItem(REFRESH_KEY),
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  },
  setAccess(access: string) {
    localStorage.setItem(ACCESS_KEY, access)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

function describe(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      const parts: string[] = []
      for (const [field, value] of Object.entries(detail)) {
        const text = Array.isArray(value) ? value.join(' ') : String(value)
        parts.push(field === 'detail' ? text : `${field}: ${text}`)
      }
      if (parts.length) return parts.join(' · ')
    }
  }
  if (status === 401) return 'Your session has expired. Please sign in again.'
  if (status === 403) return 'Your role does not have access to this.'
  if (status >= 500) return 'The server could not complete this request.'
  return `Request failed (${status}).`
}

async function attemptRefresh(): Promise<boolean> {
  const refresh = tokens.refresh()
  if (!refresh) return false
  try {
    const response = await fetch(`${BASE_URL}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
    if (!response.ok) return false
    const data = await response.json()
    tokens.setAccess(data.access)
    return true
  } catch {
    return false
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  const access = tokens.access()
  if (access) headers.set('Authorization', `Bearer ${access}`)

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(
      'Could not reach the GramSentinel server. Is the backend running?',
      0,
      null,
    )
  }

  if (response.status === 401 && retry && tokens.refresh()) {
    if (await attemptRefresh()) return request<T>(path, init, false)
    tokens.clear()
  }

  if (response.status === 204) return undefined as T

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(describe(payload, response.status), response.status, payload)
  }
  return payload as T
}

/**
 * Same JWT-attach + one-shot-refresh-on-401 behaviour as `request()`, for an
 * endpoint whose response is binary rather than JSON (a message attachment,
 * an exported report) — a plain `<a href>`/`window.open` to an authenticated
 * API route never carries the Authorization header, since that would be an
 * ordinary browser navigation, not a fetch. Callers turn the result into an
 * object URL with `URL.createObjectURL` and revoke it once done.
 */
async function requestBlob(path: string, retry = true): Promise<Blob> {
  const headers = new Headers()
  const access = tokens.access()
  if (access) headers.set('Authorization', `Bearer ${access}`)

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, { headers })
  } catch {
    throw new ApiError(
      'Could not reach the GramSentinel server. Is the backend running?',
      0,
      null,
    )
  }

  if (response.status === 401 && retry && tokens.refresh()) {
    if (await attemptRefresh()) return requestBlob(path, false)
    tokens.clear()
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(describe(payload, response.status), response.status, payload)
  }
  return response.blob()
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) }),
  getBlob: (path: string) => requestBlob(path),
}

/**
 * Phase 8 — the one place a WebSocket URL is derived from `BASE_URL`.
 *
 * A browser `WebSocket` cannot set an `Authorization` header, so the JWT
 * access token travels as a `?token=` query parameter instead — see
 * `backend/simulation/ws_auth.py`'s docstring for the server side of this.
 * `BASE_URL` already ends in `/api` (either the explicit
 * `VITE_API_BASE_URL` or the Vite dev-server's own `/api` proxy target) —
 * stripped here because WebSocket routes live under `/ws/`, not `/api/`,
 * on the same backend origin.
 */
export function buildSimulationSocketUrl(sessionId: number): string {
  const token = tokens.access() ?? ''
  const path = `/ws/simulation/sessions/${sessionId}/?token=${encodeURIComponent(token)}`

  if (import.meta.env.VITE_API_BASE_URL) {
    const wsBase = BASE_URL.replace(/^http/, 'ws').replace(/\/api\/?$/, '')
    return `${wsBase}${path}`
  }
  // No explicit API base — same convention the REST client falls back to
  // (a relative `/api`, resolved by the Vite dev proxy or same-origin
  // deployment). `vite.config.ts` already proxies `/ws` the same way.
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

/**
 * Fetches an authenticated binary resource (a message attachment) and opens
 * it in a new tab — the one place this project turns an authenticated blob
 * response into something a person can actually view, reused by every
 * attachment link instead of duplicated per page. A plain `<a href>` to the
 * same API path would be an unauthenticated browser navigation and 401;
 * this goes through `api.getBlob`, which carries the same JWT header (and
 * refresh-on-401 retry) as every other request. The browser renders
 * viewable types (PDF, PNG, JPEG — the endpoint marks these
 * `Content-Disposition: inline`) in that tab and falls back to its own
 * native download prompt for anything else.
 */
export async function openAttachment(path: string): Promise<void> {
  const blob = await api.getBlob(path)
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener')
  // Revoked on a delay, not immediately — the new tab needs time to load
  // the blob: URL before it stops resolving.
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export async function login(username: string, password: string) {
  const response = await fetch(`${BASE_URL}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(
      response.status === 401
        ? 'Incorrect username or password.'
        : describe(payload, response.status),
      response.status,
      payload,
    )
  }
  tokens.set(payload.access, payload.refresh)
  return payload
}

import { type FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { homeRouteFor, useAuth } from '@/store/auth'

/** Demonstration credentials, grouped by area. */
const AREAS = [
  {
    area: 'Village A',
    place: 'Kovilur',
    accounts: [
      { username: 'worker.a', role: 'CHW / PHC Worker' },
      { username: 'officer.a', role: 'Health Officer' },
    ],
  },
  {
    area: 'Village B',
    place: 'Ariyanur',
    accounts: [
      { username: 'worker.b', role: 'CHW / PHC Worker' },
      { username: 'officer.b', role: 'Health Officer' },
    ],
  },
  {
    area: 'Village C',
    place: 'Melur',
    accounts: [
      { username: 'worker.c', role: 'CHW / PHC Worker' },
      { username: 'officer.c', role: 'Health Officer' },
    ],
  },
]

const OTHER_ACCOUNTS = [
  { username: 'patient', role: 'Patient' },
  { username: 'admin', role: 'Administrator' },
]

const DEMO_PASSWORD = 'demo1234'

export default function Login() {
  const { signIn, error, clearError, status } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showAccounts, setShowAccounts] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    try {
      const user = await signIn(username.trim(), password)
      navigate(homeRouteFor(user), { replace: true })
    } catch {
      /* surfaced from the store */
    }
  }

  function fill(name: string) {
    clearError()
    setUsername(name)
    setPassword(DEMO_PASSWORD)
  }

  return (
    <div className="min-h-screen bg-ink-50 flex flex-col">
      <main className="flex-1 flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-md">
          {/* Identity */}
          <div className="text-center">
            <div className="inline-flex h-11 w-11 items-center justify-center rounded-lg bg-sentinel-700 text-white">
              <svg
                viewBox="0 0 24 24"
                className="h-6 w-6"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
              >
                <path
                  d="M12 3 5 6v5c0 4.2 2.9 8.1 7 9 4.1-.9 7-4.8 7-9V6l-7-3Z"
                  strokeLinejoin="round"
                />
                <path d="M12 9v5M9.5 11.5h5" strokeLinecap="round" />
              </svg>
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-ink-900">
              GramSentinel
            </h1>
            <p className="text-sm text-ink-600">Rural Healthcare Intelligence</p>
          </div>

          {/* Sign-in */}
          <div className="card mt-6">
            <div className="px-6 py-5">
              <h2 className="text-sm font-semibold text-ink-800">Secure login</h2>
              <p className="text-xs text-ink-400 mt-0.5">
                Your role determines which portal opens.
              </p>

              <form onSubmit={handleSubmit} className="mt-5 space-y-4">
                <div>
                  <label className="label" htmlFor="username">
                    Username
                  </label>
                  <input
                    id="username"
                    className="input"
                    value={username}
                    onChange={(e) => {
                      clearError()
                      setUsername(e.target.value)
                    }}
                    autoComplete="username"
                    autoFocus
                    required
                  />
                </div>

                <div>
                  <label className="label" htmlFor="password">
                    Password
                  </label>
                  <input
                    id="password"
                    type="password"
                    className="input"
                    value={password}
                    onChange={(e) => {
                      clearError()
                      setPassword(e.target.value)
                    }}
                    autoComplete="current-password"
                    required
                  />
                </div>

                {error && (
                  <div
                    role="alert"
                    className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
                  >
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  className="btn-sentinel w-full"
                  disabled={status === 'loading' || !username || !password}
                >
                  {status === 'loading' ? 'Signing in…' : 'Login'}
                </button>
              </form>
            </div>

            {/* Demonstration credentials — collapsed by default so the page
                stays an authentication screen rather than a listing. */}
            <div className="border-t border-ink-200">
              <button
                type="button"
                className="w-full flex items-center justify-between px-6 py-3 text-left hover:bg-ink-50"
                onClick={() => setShowAccounts((open) => !open)}
                aria-expanded={showAccounts}
              >
                <span className="text-xs font-medium text-ink-600">
                  Demonstration accounts
                </span>
                <span className="text-xs text-ink-400">
                  {showAccounts ? 'Hide' : 'Show'}
                </span>
              </button>

              {showAccounts && (
                <div className="px-6 pb-5 space-y-4">
                  {AREAS.map((group) => (
                    <div key={group.area}>
                      <div className="flex items-baseline gap-2">
                        <span className="text-xs font-semibold text-ink-800">
                          {group.area}
                        </span>
                        <span className="text-xs text-ink-400">
                          {group.place}
                        </span>
                      </div>
                      <div className="mt-1.5 grid grid-cols-2 gap-2">
                        {group.accounts.map((account) => (
                          <button
                            key={account.username}
                            type="button"
                            onClick={() => fill(account.username)}
                            className={`rounded-md border px-2.5 py-2 text-left transition-colors ${
                              username === account.username
                                ? 'border-sentinel-500 bg-sentinel-50'
                                : 'border-ink-200 hover:bg-ink-50'
                            }`}
                          >
                            <div className="font-mono text-xs font-semibold text-ink-800">
                              {account.username}
                            </div>
                            <div className="text-[11px] text-ink-400 mt-0.5">
                              {account.role}
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}

                  <div className="border-t border-ink-100 pt-3">
                    <div className="grid grid-cols-2 gap-2">
                      {OTHER_ACCOUNTS.map((account) => (
                        <button
                          key={account.username}
                          type="button"
                          onClick={() => fill(account.username)}
                          className={`rounded-md border px-2.5 py-2 text-left transition-colors ${
                            username === account.username
                              ? 'border-sentinel-500 bg-sentinel-50'
                              : 'border-ink-200 hover:bg-ink-50'
                          }`}
                        >
                          <div className="font-mono text-xs font-semibold text-ink-800">
                            {account.username}
                          </div>
                          <div className="text-[11px] text-ink-400 mt-0.5">
                            {account.role}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>

                  <p className="text-xs text-ink-400">
                    Password for all:{' '}
                    <code className="font-mono text-ink-600">
                      {DEMO_PASSWORD}
                    </code>{' '}
                    · Accounts are provisioned by an administrator.
                  </p>
                </div>
              )}
            </div>
          </div>

          <p className="mt-5 text-center text-xs text-ink-400 leading-relaxed">
            Decision-support and early-warning prototype. Synthetic data only —
            no real patient records.
          </p>
        </div>
      </main>
    </div>
  )
}

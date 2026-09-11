import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { SyntheticBadge } from '@/components/ui'
import { useAuth } from '@/store/auth'

interface NavItem {
  to: string
  label: string
}

/**
 * Shared chrome for both portals.
 *
 * RuralCare and GramSentinel are visually distinct (teal vs indigo) but share
 * the header, the disclaimer and the shell — because they are one platform,
 * not two products.
 */
export function PortalLayout({
  portal,
  subtitle,
  accent,
  nav,
}: {
  portal: string
  subtitle: string
  accent: 'care' | 'sentinel'
  nav: NavItem[]
}) {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  const bar = accent === 'care' ? 'bg-care-700' : 'bg-sentinel-700'
  const active =
    accent === 'care'
      ? 'border-care-600 text-care-700'
      : 'border-sentinel-600 text-sentinel-700'

  return (
    <div className="min-h-screen flex flex-col">
      <header className={`${bar} text-white`}>
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold tracking-tight">GramSentinel</span>
              <span className="text-white/40">/</span>
              <span className="text-sm text-white/90">{portal}</span>
            </div>
            <p className="text-xs text-white/70 truncate">{subtitle}</p>
          </div>

          <div className="ml-auto flex items-center gap-4">
            <div className="text-right hidden sm:block">
              <div className="text-sm font-medium">{user?.display_name}</div>
              <div className="text-xs text-white/70">
                {user?.role.replace(/_/g, ' ')}
                {user?.village_name ? ` · ${user.village_name}` : ''}
                {user?.district ? ` · ${user.district}` : ''}
              </div>
            </div>
            <button
              className="rounded-md border border-white/30 px-3 py-1.5 text-sm hover:bg-white/10"
              onClick={() => {
                signOut()
                navigate('/login')
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <nav className="bg-white border-b border-ink-200 sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-4 flex items-center gap-1 overflow-x-auto">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `whitespace-nowrap px-3 py-3 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  isActive
                    ? active
                    : 'border-transparent text-ink-600 hover:text-ink-800'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
          <div className="ml-auto hidden md:block py-2">
            <SyntheticBadge />
          </div>
        </div>
      </nav>

      <main className="flex-1 mx-auto w-full max-w-7xl px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-ink-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-3 text-xs text-ink-400">
          Decision-support and early-warning prototype. It does not diagnose,
          prescribe, or declare outbreaks, and it does not replace healthcare
          professionals or official public-health surveillance. All data is
          synthetic, public or anonymised — no real patient data.
        </div>
      </footer>
    </div>
  )
}

export const WORKER_NAV: NavItem[] = [
  { to: '/worker/dashboard', label: 'Dashboard' },
  { to: '/worker/assessment/new', label: 'New assessment' },
  { to: '/worker/community-report', label: 'Community report' },
  { to: '/worker/local-signals', label: 'Local signals' },
  { to: '/worker/profile', label: 'My profile' },
]

export const OFFICER_NAV: NavItem[] = [
  { to: '/officer/dashboard', label: 'Dashboard' },
  { to: '/officer/community-data', label: 'Community data' },
  { to: '/officer/community-reports', label: 'Community reports' },
  { to: '/officer/history', label: 'Alert history' },
  { to: '/officer/team', label: 'Health team' },
  { to: '/officer/profile', label: 'My profile' },
]

export const PATIENT_NAV: NavItem[] = [
  { to: '/patient/dashboard', label: 'My health' },
]

//: An administrator keeps their existing access to the officer and worker
//: portals; these are shortcuts to it, not a replacement for it.
export const ADMIN_NAV: NavItem[] = [
  { to: '/admin/dashboard', label: 'Platform overview' },
  { to: '/officer/dashboard', label: 'Officer portal' },
  { to: '/worker/dashboard', label: 'Worker portal' },
]

import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { LanguageSelector } from '@/components/LanguageSelector'
import { SyntheticBadge } from '@/components/ui'
import { useAuth } from '@/store/auth'

interface NavItem {
  to: string
  labelKey: string
}

/**
 * Shared chrome for both portals.
 *
 * RuralCare and GramSentinel are visually distinct (teal vs indigo) but share
 * the header and the shell — because they are one platform, not two products.
 */
export function PortalLayout({
  portal,
  subtitle,
  accent,
  nav,
  wide = false,
  headerExtra,
}: {
  /** Translation keys (task §29: no literal strings passed at the call
   *  site), resolved via `t()` here so every `PortalLayout` consumer stays
   *  a one-line key reference. */
  portal: string
  subtitle: string
  accent: 'care' | 'sentinel'
  nav: NavItem[]
  /** Opt-in wider shell (currently only the Simulation Lab sub-tree, whose
   *  three-column workspace is cramped at the standard `max-w-7xl` every
   *  other officer page keeps unchanged) — default `false` preserves the
   *  exact existing container width for every page that doesn't pass it. */
  wide?: boolean
  /** Optional extra header content, shown next to the account details —
   *  currently only the Worker Portal's offline/sync status indicator. */
  headerExtra?: React.ReactNode
}) {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const { t } = useTranslation()

  const bar = accent === 'care' ? 'bg-care-700' : 'bg-sentinel-700'
  const active =
    accent === 'care'
      ? 'border-care-600 text-care-700'
      : 'border-sentinel-600 text-sentinel-700'
  const containerWidth = wide ? 'max-w-[1600px]' : 'max-w-7xl'

  return (
    <div className="min-h-screen flex flex-col">
      <header className={`${bar} text-white`}>
        <div className={`mx-auto ${containerWidth} px-4 py-3 flex items-center gap-4`}>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold tracking-tight">{t('app.name')}</span>
              <span className="text-white/40">{t('header.portalSeparator')}</span>
              <span className="text-sm text-white/90">{t(portal)}</span>
            </div>
            <p className="text-xs text-white/70 truncate">{t(subtitle)}</p>
          </div>

          <div className="ml-auto flex items-center gap-3">
            <LanguageSelector tone="dark" />
            {headerExtra}
            <div className="text-right hidden sm:block">
              <div className="text-sm font-medium">{user?.display_name}</div>
              <div className="text-xs text-white/70">
                {user ? t(`role.${user.role}`, { defaultValue: user.role.replace(/_/g, ' ') }) : ''}
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
              {t('header.signOut')}
            </button>
          </div>
        </div>
      </header>

      <nav className="bg-white border-b border-ink-200 sticky top-0 z-10">
        <div className={`mx-auto ${containerWidth} px-4 flex items-center gap-1 overflow-x-auto`}>
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
              {t(item.labelKey)}
            </NavLink>
          ))}
          <div className="ml-auto hidden md:block py-2">
            <SyntheticBadge />
          </div>
        </div>
      </nav>

      <main className={`flex-1 mx-auto w-full ${containerWidth} px-4 py-6`}>
        <Outlet />
      </main>
    </div>
  )
}

export const WORKER_NAV: NavItem[] = [
  { to: '/worker/dashboard', labelKey: 'nav.dashboard' },
  { to: '/worker/assessment/new', labelKey: 'nav.newAssessment' },
  { to: '/worker/community-report', labelKey: 'nav.communityReport' },
  { to: '/worker/local-signals', labelKey: 'nav.localSignals' },
  { to: '/worker/work', labelKey: 'nav.work' },
  { to: '/worker/profile', labelKey: 'nav.profile' },
]

export const OFFICER_NAV: NavItem[] = [
  { to: '/officer/dashboard', labelKey: 'nav.dashboard' },
  { to: '/officer/community-data', labelKey: 'nav.communityData' },
  { to: '/officer/community-reports', labelKey: 'nav.communityReports' },
  { to: '/officer/history', labelKey: 'nav.alertHistory' },
  { to: '/officer/simulation', labelKey: 'nav.simulationLab' },
  { to: '/officer/team', labelKey: 'nav.healthTeam' },
  { to: '/officer/work', labelKey: 'nav.teamWorkspace' },
  { to: '/officer/operational-context', labelKey: 'nav.operationalContext' },
  { to: '/officer/profile', labelKey: 'nav.profile' },
]

//: An administrator keeps their existing access to the officer and worker
//: portals; these are shortcuts to it, not a replacement for it.
export const ADMIN_NAV: NavItem[] = [
  { to: '/admin/dashboard', labelKey: 'nav.platformOverview' },
  { to: '/officer/dashboard', labelKey: 'nav.officerPortal' },
  { to: '/worker/dashboard', labelKey: 'nav.workerPortal' },
]

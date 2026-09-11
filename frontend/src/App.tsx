import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { Loading } from '@/components/ui'
import {
  ADMIN_NAV,
  OFFICER_NAV,
  PATIENT_NAV,
  PortalLayout,
  WORKER_NAV,
} from '@/layouts/PortalLayout'
import Login from '@/pages/Login'
import AdminDashboard from '@/pages/admin/Dashboard'
import MyProfilePage from '@/pages/profile/MyProfile'
import AlertDetail from '@/pages/officer/AlertDetail'
import AlertHistory from '@/pages/officer/AlertHistory'
import CommunityDataPage from '@/pages/officer/CommunityData'
import OfficerCommunityReports from '@/pages/officer/CommunityReports'
import OfficerDashboardPage from '@/pages/officer/Dashboard'
import EvidenceView from '@/pages/officer/EvidenceView'
import OfficerTeamPage from '@/pages/officer/Team'
import PatientDashboard from '@/pages/patient/Dashboard'
import CommunityReportPage from '@/pages/worker/CommunityReport'
import WorkerDashboardPage from '@/pages/worker/Dashboard'
import LocalSignalsPage from '@/pages/worker/LocalSignals'
import NewAssessment from '@/pages/worker/NewAssessment'
import PatientDetail from '@/pages/worker/PatientDetail'
import { homeRouteFor, useAuth } from '@/store/auth'
import type { Role } from '@/types'

/**
 * Route protection is a usability measure — it keeps a worker from landing on
 * a page that would only 403. Access control itself is enforced server-side on
 * every request.
 */
function RequireRole({
  roles,
  allowAdmin = true,
  children,
}: {
  roles: Role[]
  /** The patient portal is scoped to one person's own record, so an
   *  administrator is redirected away rather than shown an empty 403. */
  allowAdmin?: boolean
  children: React.ReactNode
}) {
  const { user, status } = useAuth()

  if (status !== 'ready') return <Loading />
  if (!user) return <Navigate to="/login" replace />

  const permitted =
    roles.includes(user.role) || (allowAdmin && user.role === 'ADMIN')
  if (!permitted) return <Navigate to={homeRouteFor(user)} replace />

  return <>{children}</>
}

export default function App() {
  const { restore, status, user } = useAuth()

  useEffect(() => {
    void restore()
  }, [restore])

  if (status !== 'ready') {
    return (
      <div className="min-h-screen grid place-items-center">
        <Loading label="Starting GramSentinel…" />
      </div>
    )
  }

  return (
    <Routes>
      <Route
        path="/login"
        element={user ? <Navigate to={homeRouteFor(user)} replace /> : <Login />}
      />

      {/* RuralCare — individual layer */}
      <Route
        element={
          <RequireRole roles={['CHW_PHC_WORKER']}>
            <PortalLayout
              portal="RuralCare"
              subtitle="Individual patient support · Worker Portal"
              accent="care"
              nav={WORKER_NAV}
              hideFooterDisclaimer
            />
          </RequireRole>
        }
      >
        <Route path="/worker/dashboard" element={<WorkerDashboardPage />} />
        <Route path="/worker/assessment/new" element={<NewAssessment />} />
        <Route path="/worker/patient/:id" element={<PatientDetail />} />
        <Route
          path="/worker/community-report"
          element={<CommunityReportPage />}
        />
        <Route path="/worker/local-signals" element={<LocalSignalsPage />} />
        <Route path="/worker/profile" element={<MyProfilePage />} />
      </Route>

      {/* GramSentinel — community layer */}
      <Route
        element={
          <RequireRole roles={['HEALTH_OFFICER']}>
            <PortalLayout
              portal="Community Intelligence"
              subtitle="Community early warning · Officer Portal"
              accent="sentinel"
              nav={OFFICER_NAV}
            />
          </RequireRole>
        }
      >
        <Route path="/officer/dashboard" element={<OfficerDashboardPage />} />
        <Route path="/officer/alerts/:id" element={<AlertDetail />} />
        <Route
          path="/officer/alerts/:id/evidence"
          element={<EvidenceView />}
        />
        <Route path="/officer/community-data" element={<CommunityDataPage />} />
        <Route
          path="/officer/community-reports"
          element={<OfficerCommunityReports />}
        />
        <Route path="/officer/history" element={<AlertHistory />} />
        <Route path="/officer/team" element={<OfficerTeamPage />} />
        <Route path="/officer/profile" element={<MyProfilePage />} />
      </Route>

      {/* Administrator — platform-level view across all villages. */}
      <Route
        element={
          <RequireRole roles={['ADMIN']}>
            <PortalLayout
              portal="Administration"
              subtitle="Platform overview · Admin Portal"
              accent="sentinel"
              nav={ADMIN_NAV}
            />
          </RequireRole>
        }
      >
        <Route path="/admin/dashboard" element={<AdminDashboard />} />
      </Route>

      {/* Patient — optional, secondary module. Own records only. */}
      <Route
        element={
          <RequireRole roles={['PATIENT']} allowAdmin={false}>
            <PortalLayout
              portal="My Health"
              subtitle="Your own records · Patient Portal"
              accent="care"
              nav={PATIENT_NAV}
            />
          </RequireRole>
        }
      >
        <Route path="/patient/dashboard" element={<PatientDashboard />} />
      </Route>

      <Route path="*" element={<Navigate to={homeRouteFor(user)} replace />} />
    </Routes>
  )
}

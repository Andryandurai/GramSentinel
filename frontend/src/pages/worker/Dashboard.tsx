import { Link } from 'react-router-dom'

import { Card, Disclaimer, Empty, ErrorNote, Loading, Stat, TriagePill } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { WorkerDashboard } from '@/types'

export default function WorkerDashboardPage() {
  const { data, loading, error, reload } = useAsync<WorkerDashboard>(() =>
    api.get('/worker/dashboard/'),
  )

  if (loading) return <Loading label="Loading your dashboard…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            RuralCare — Worker Portal
          </h1>
          <p className="text-sm text-ink-600 mt-0.5">
            {data.village
              ? `${data.village.name} · ${data.village.cluster}`
              : 'No village assigned'}
          </p>
        </div>
        <Link to="/worker/assessment/new" className="btn-care ml-auto">
          New patient assessment
        </Link>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat value={data.today.assessment_count} label="Assessments today" tone="care" />
        <Stat
          value={data.today.concerning_count}
          label="Concerning today"
          tone="amber"
        />
        <Stat value={data.today.urgent_count} label="Urgent today" tone="red" />
        <Stat value={data.pending_followup_count} label="Pending follow-ups" />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Recent assessments" className="lg:col-span-2">
          {data.recent_assessments.length === 0 ? (
            <Empty>No assessments recorded yet.</Empty>
          ) : (
            <div className="overflow-x-auto -mx-5">
              <table className="w-full min-w-[560px]">
                <thead>
                  <tr>
                    <th className="table-head">Patient</th>
                    <th className="table-head">Symptoms</th>
                    <th className="table-head">Triage</th>
                    <th className="table-head">Date</th>
                    <th className="table-head">Aggregated</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_assessments.map((assessment) => (
                    <tr key={assessment.id} className="hover:bg-ink-50">
                      <td className="table-cell">
                        <Link
                          to={`/worker/patient/${assessment.patient}`}
                          className="font-medium text-care-700 hover:underline"
                        >
                          {assessment.patient_code}
                        </Link>
                        <div className="text-xs text-ink-400">
                          {assessment.patient_name}
                        </div>
                      </td>
                      <td className="table-cell text-ink-600">
                        {assessment.symptoms.join(', ').replace(/_/g, ' ')}
                        <div className="text-xs text-ink-400">
                          {assessment.duration_days} day(s)
                        </div>
                      </td>
                      <td className="table-cell">
                        <TriagePill level={assessment.triage_level} />
                        {assessment.escalation_forced && (
                          <div className="text-xs text-red-600 mt-1">
                            escalation forced
                          </div>
                        )}
                      </td>
                      <td className="table-cell text-ink-600">
                        {assessment.encounter_date}
                      </td>
                      <td className="table-cell">
                        {assessment.aggregated_at ? (
                          <span className="text-xs text-care-700">
                            counted anonymously
                          </span>
                        ) : (
                          <span className="text-xs text-ink-400">pending</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="space-y-6">
          <Card title="Pending follow-ups">
            {data.pending_followups.length === 0 ? (
              <Empty>Nothing due.</Empty>
            ) : (
              <ul className="space-y-2">
                {data.pending_followups.map((followup) => (
                  <li
                    key={followup.id}
                    className="flex items-center justify-between rounded-md border border-ink-200 px-3 py-2"
                  >
                    <div>
                      <div className="text-sm font-medium">
                        {followup.patient_code}
                      </div>
                      <div className="text-xs text-ink-400">
                        {followup.patient_name}
                      </div>
                    </div>
                    <span className="text-xs text-ink-600 font-mono">
                      {followup.due_date}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="How your work is used">
            <p className="text-sm text-ink-600 leading-relaxed">
              Each assessment you record stays inside RuralCare. Only an
              anonymised count — for example “7 fever-related encounters this
              week” — crosses into community monitoring. Patient names,
              identifiers and records never leave this portal.
            </p>
            <Disclaimer className="mt-4" />
          </Card>
        </div>
      </div>
    </div>
  )
}

import { Card, Empty, ErrorNote, Loading, TriagePill } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { PatientPortal } from '@/types'

export default function PatientDashboard() {
  const { data, loading, error, reload } = useAsync<PatientPortal>(() =>
    api.get('/patient/me/'),
  )

  if (loading) return <Loading label="Loading your health record…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          {data.patient.display_name}
        </h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {data.patient.patient_code} · {data.patient.village_name}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="My records" className="lg:col-span-2">
          {data.records.length === 0 ? (
            <Empty>No assessments recorded yet.</Empty>
          ) : (
            <ol className="space-y-3">
              {data.records.map((record) => (
                <li
                  key={record.id}
                  className="rounded-md border border-ink-200 p-4"
                >
                  <div className="flex flex-wrap items-center gap-3">
                    <TriagePill level={record.triage_level} />
                    <span className="text-sm text-ink-600">
                      {record.encounter_date}
                    </span>
                    <span className="text-xs text-ink-400">
                      {record.duration_days} day(s)
                    </span>
                  </div>

                  <p className="mt-2 text-sm text-ink-800">
                    {record.referral_recommendation}
                  </p>

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {record.symptoms.map((symptom) => (
                      <span
                        key={symptom}
                        className="pill bg-ink-100 text-ink-600 font-normal"
                      >
                        {symptom.replace(/_/g, ' ')}
                      </span>
                    ))}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <div className="space-y-6">
          <Card title="Upcoming follow-up">
            {data.followups.length === 0 ? (
              <Empty>Nothing scheduled.</Empty>
            ) : (
              <ul className="space-y-2">
                {data.followups.map((followup) => (
                  <li
                    key={followup.id}
                    className="rounded-md border border-ink-200 px-3 py-2"
                  >
                    <div className="text-sm font-medium">
                      {followup.due_date}
                    </div>
                    <div className="text-xs text-ink-400">
                      {followup.status.toLowerCase()}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="General guidance">
            <ul className="space-y-2">
              {data.guidance.map((line) => (
                <li key={line} className="flex gap-2 text-sm text-ink-600">
                  <span className="mt-1.5 h-1 w-1 rounded-full bg-ink-400 shrink-0" />
                  {line}
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-ink-400 border-t border-ink-200 pt-3">
              {data.scope_note}
            </p>
          </Card>
        </div>
      </div>

      <p className="text-xs text-ink-400 text-center">
        This system does not replace a doctor.
      </p>
    </div>
  )
}

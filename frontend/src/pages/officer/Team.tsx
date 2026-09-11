import { Avatar, Card, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { StaffDirectory, StaffProfile } from '@/types'

/**
 * The health staff assigned to this officer's area.
 *
 * Scoped server-side: an officer assigned to a village sees that village's
 * workers and officers and no others. The district-wide account keeps its
 * district-wide view, exactly as it has everywhere else in the portal.
 */
function ProfileCard({ profile }: { profile: StaffProfile }) {
  const details: Array<[string, string]> = [
    ['Employee ID', profile.staff_id],
    ['Qualification', profile.qualification],
    [
      'Experience',
      profile.experience_years === null || profile.experience_years === undefined
        ? ''
        : `${profile.experience_years} year${profile.experience_years === 1 ? '' : 's'}`,
    ],
    ['Contact', profile.phone_number],
    ['Email', profile.email],
    ['Facility', profile.facility_name ?? ''],
  ]
  const filled = details.filter(([, value]) => Boolean(value))

  return (
    <div className="rounded-md border border-ink-200 p-4">
      <div className="flex items-start gap-3">
        <Avatar
          src={profile.photo_url}
          initials={profile.initials}
          name={profile.display_name}
        />
        <div className="min-w-0">
          <div className="text-sm font-semibold text-ink-800">
            {profile.display_name}
          </div>
          <div className="text-xs text-ink-600">{profile.role_label}</div>
          <div className="text-xs text-ink-400">
            {profile.village_name ?? 'District-wide'}
            {profile.village_label ? ` · ${profile.village_label}` : ''}
          </div>
        </div>
      </div>

      {filled.length > 0 ? (
        <dl className="mt-3 space-y-1 border-t border-ink-100 pt-3 text-sm">
          {filled.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3">
              <dt className="text-xs text-ink-400">{label}</dt>
              <dd className="text-right text-ink-800">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 border-t border-ink-100 pt-3 text-xs text-ink-400">
          This colleague has not filled in their profile details yet.
        </p>
      )}
    </div>
  )
}

export default function OfficerTeamPage() {
  const { data, loading, error, reload } = useAsync<StaffDirectory>(() =>
    api.get('/auth/staff-profiles/'),
  )

  if (loading && !data) return <Loading label="Loading team profiles…" />
  if (error && !data) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Health team</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {data.scope.is_district_wide
            ? 'All villages in your district'
            : (data.scope.village_name ?? 'Your area')}
          {' · '}
          {data.counts.workers} worker{data.counts.workers === 1 ? '' : 's'} ·{' '}
          {data.counts.officers} health officer
          {data.counts.officers === 1 ? '' : 's'}
        </p>
      </div>

      {data.scope.notice && (
        <p className="rounded-md border border-ink-200 bg-white px-3 py-2 text-sm text-ink-600">
          {data.scope.notice}
        </p>
      )}

      {data.is_empty ? (
        <Card title="Health team">
          <Empty>{data.empty_message}</Empty>
        </Card>
      ) : (
        data.groups.map((group) => (
          <Card
            key={group.village_code || group.village_label}
            title={
              group.village_code
                ? `${group.village_label} — ${group.village_name}`
                : group.village_label
            }
          >
            <div className="space-y-4">
              {[
                ['CHW / PHC Workers', group.workers] as const,
                ['Health Officers', group.officers] as const,
              ].map(([heading, people]) => (
                <div key={heading}>
                  <div className="label">{heading}</div>
                  {people.length === 0 ? (
                    <p className="text-sm text-ink-400">
                      None assigned to this area.
                    </p>
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {people.map((profile) => (
                        <ProfileCard key={profile.id} profile={profile} />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        ))
      )}

      <p className="text-xs text-ink-400">
        {data.note} Profiles are maintained by each member of staff and are
        visible only within their assigned area and to the administrator.
      </p>
    </div>
  )
}

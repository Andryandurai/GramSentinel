import { Card, Stat } from '@/components/ui'
import type { VillageRealWorldProfile } from '@/types'

/**
 * The researched real-world identity of a village — population, households,
 * area, and healthcare-access context — rendered separately from, and never
 * mixed with, any synthetic health-signal figure elsewhere on the page.
 *
 * Renders nothing when `profile` is null, which is the case for every
 * village that has no researched profile (Village A included) — there is
 * no fallback, placeholder, or invented figure here.
 */
export function RealWorldCommunityProfile({
  profile,
}: {
  profile: VillageRealWorldProfile | null
}) {
  if (!profile) return null

  const location = [profile.taluk, profile.district, profile.state]
    .filter(Boolean)
    .join(' • ')

  const access: Array<[string, string]> = [
    ['ASHA / Community Health Worker', profile.healthcare_access.asha_chw],
    ['Nearby Government PHC', profile.healthcare_access.nearby_government_phc],
    ['Health Sub-Centre', profile.healthcare_access.health_sub_centre],
    ['PHC inside village', profile.healthcare_access.phc_inside_village],
    ['CHC inside village', profile.healthcare_access.chc_inside_village],
  ]

  return (
    <Card
      title="Real-world community context"
      action={
        profile.demographic_baseline_year ? (
          <span className="text-xs text-ink-400">
            Census {profile.demographic_baseline_year} baseline
          </span>
        ) : null
      }
    >
      <div>
        <div className="text-lg font-semibold tracking-tight text-ink-800">
          {profile.village_name}
        </div>
        {location && <p className="text-sm text-ink-600 mt-0.5">{location}</p>}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Stat value={profile.population ?? '—'} label="Population" />
        <Stat value={profile.households ?? '—'} label="Households" />
        <Stat value={profile.male_population ?? '—'} label="Male" />
        <Stat value={profile.female_population ?? '—'} label="Female" />
        <Stat value={profile.children_0_6 ?? '—'} label="Children 0–6" />
        <Stat
          value={profile.area_hectares ? `${profile.area_hectares} ha` : '—'}
          label="Area"
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-400">
        {profile.census_village_code && (
          <span>Census village code {profile.census_village_code}</span>
        )}
        {profile.pin_code && <span>PIN {profile.pin_code}</span>}
      </div>

      <div className="mt-4 border-t border-ink-200 pt-3">
        <div className="label">Healthcare access</div>
        <dl className="mt-1.5 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
          {access.map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between gap-3">
              <dt className="text-ink-500">{label}</dt>
              <dd
                className={
                  value === 'Not reported'
                    ? 'text-ink-400 italic text-right'
                    : 'text-ink-800 font-medium text-right'
                }
              >
                {value === 'Not reported' ? 'Not reported in available village-level research' : value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </Card>
  )
}

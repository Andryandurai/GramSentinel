import { Card } from '@/components/ui'
import type { VillageRealWorldProfile } from '@/types'

/**
 * The one place a village's Google Maps query string is built — from the
 * same researched profile fields already shown in `RealWorldCommunityProfile`
 * (village name, taluk, district, state, PIN), never a separately-stored or
 * hand-typed address. No latitude/longitude is used: none has been reliably
 * verified for this village, and guessing one is exactly what this feature
 * must not do — a name/address query lets Google's own geocoding resolve
 * the place instead.
 */
function locationQuery(profile: VillageRealWorldProfile): string {
  return [profile.village_name, profile.taluk, profile.district, profile.state, profile.pin_code]
    .filter(Boolean)
    .join(', ')
}

/**
 * Real-world geographic location — reusable for any village with a
 * researched profile, currently Manikkampatti. Renders nothing when there
 * is no profile (Village A, and any future village without one), so it
 * never needs a conditional at the call site beyond the profile lookup
 * `RealWorldCommunityProfile` already uses.
 */
export function CommunityMap({ profile }: { profile: VillageRealWorldProfile | null }) {
  if (!profile) return null

  const query = locationQuery(profile)
  const embedSrc = `https://maps.google.com/maps?q=${encodeURIComponent(query)}&z=14&output=embed`
  const openUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`

  return (
    <Card title={`${profile.village_name} — geographic location`}>
      <p className="text-sm text-ink-600">
        {[profile.village_name, profile.taluk, profile.district, profile.state]
          .filter(Boolean)
          .join(', ')}
        {profile.pin_code ? ` — ${profile.pin_code}` : ''}
      </p>

      <div className="mt-3 overflow-hidden rounded-lg border border-ink-200 shadow-sm">
        <iframe
          title={`Map showing the location of ${profile.village_name}`}
          src={embedSrc}
          className="h-[350px] w-full sm:h-[400px] lg:h-[450px]"
          style={{ border: 0 }}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-ink-400">Real-world geographical context.</p>
        <a
          href={openUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="btn-ghost py-1.5 text-xs"
          aria-label={`Open ${profile.village_name} in Google Maps (opens in a new tab)`}
        >
          Open in Google Maps ↗
        </a>
      </div>
    </Card>
  )
}
